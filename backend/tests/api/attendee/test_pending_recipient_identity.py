"""Recipient identity repair must preserve parties, tickets and explicit links."""

import asyncio
import importlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.api.attendee.crud import attendees_crud
from app.api.attendee.models import AttendeeProducts, Attendees
from app.api.attendee.schemas import AttendeeUpdate
from app.api.auth.crud import authenticate_human
from app.api.event_participant.crud import event_participants_crud
from app.api.tenant.models import Tenants
from tests.api.attendee.test_list_my_tickets import (
    _auth,
    _make_app_attendee,
    _make_human,
    _make_popup,
)
from tests.api.payment.test_deferred_attendee_fulfillment import _category, _product


def _pending(db, tenant, popup, human, *, manager=None, application_id=None):
    attendee = Attendees(
        tenant_id=tenant.id,
        popup_id=popup.id,
        application_id=application_id,
        email=f"  {human.email.upper()}  ",
        name="Pending recipient",
        managed_by_human_id=manager.id if manager else None,
        additional_data={"dietary_restriction": "vegan"},
    )
    db.add(attendee)
    db.commit()
    return attendee


def _verify(db, human, *, origin="portal", code="123456"):
    human.auth_code = "123456"
    human.code_expiration = datetime.now(UTC) + timedelta(minutes=5)
    human.auth_code_origin = origin
    db.add(human)
    db.commit()
    with patch("app.api.auth.crud.is_redis_available", return_value=False):
        return asyncio.run(
            authenticate_human(db, human.email, human.tenant_id, code, origin)
        )


@pytest.mark.parametrize("legacy_main", [False, True])
@pytest.mark.parametrize("origin", ["portal", "third_party"])
def test_verified_login_recovers_ticket_and_rsvp_without_changing_manager(
    db: Session, client: TestClient, tenant_a: Tenants, legacy_main: bool, origin: str
):
    popup = _make_popup(db, tenant_a, suffix="pending-login")
    holder = _make_human(db, tenant_a, suffix="holder")
    manager = _make_human(db, tenant_a, suffix="manager")
    main = None
    if legacy_main:
        _, main = _make_app_attendee(db, tenant_a, popup, holder)
    attendee = _pending(db, tenant_a, popup, holder, manager=manager)
    product = _product(db, popup)
    unit = AttendeeProducts(
        tenant_id=tenant_a.id,
        attendee_id=attendee.id,
        product_id=product.id,
        product_category_snapshot="ticket",
        check_in_code=uuid.uuid4().hex,
        requires_check_in_snapshot=True,
    )
    db.add(unit)
    db.commit()
    original_code = unit.check_in_code
    assert not event_participants_crud.eligibility_by_human(db, popup.id, {holder.id})[
        holder.id
    ].allowed

    assert _verify(db, holder, origin=origin).id == holder.id
    db.refresh(attendee)
    db.refresh(unit)
    assert attendee.human_id == holder.id
    assert attendee.managed_by_human_id == manager.id
    assert attendee.application_id is None
    assert attendee.additional_data == {"dietary_restriction": "vegan"}
    assert unit.check_in_code == original_code
    assert unit.attendee_id == attendee.id
    assert event_participants_crud.eligibility_by_human(db, popup.id, {holder.id})[
        holder.id
    ].allowed
    assert (
        attendees_crud.link_attendees_to_human(db, holder.id, holder.email, tenant_a.id)
        == 0
    )
    if main is not None:
        assert db.get(Attendees, main.id).human_id == holder.id

    response = client.get("/api/v1/applications/my/tickets", headers=_auth(holder))
    assert response.status_code == 200
    rows = response.json()
    assert any(row["id"] == str(attendee.id) and row["products"] for row in rows)
    # Resolving the recipient must not give the holder unrelated manager rights.
    other = _pending(db, tenant_a, popup, manager, manager=manager)
    assert (
        attendees_crud.get_for_human_popup(
            db,
            attendee_id=other.id,
            human_id=holder.id,
            popup_id=popup.id,
            tenant_id=tenant_a.id,
        )
        is None
    )
    assert (
        attendees_crud.get_for_human_popup(
            db,
            attendee_id=attendee.id,
            human_id=manager.id,
            popup_id=popup.id,
            tenant_id=tenant_a.id,
        )
        is not None
    )
    unit.revoked_at = datetime.now(UTC)
    db.add(unit)
    db.commit()
    eligibility = event_participants_crud.eligibility_by_human(
        db, popup.id, {holder.id}
    )[holder.id]
    assert not eligibility.allowed
    assert eligibility.reason == "no_tickets"


def test_invalid_otp_cannot_claim_recipient(db: Session, tenant_a: Tenants):
    popup = _make_popup(db, tenant_a, suffix="invalid-otp")
    human = _make_human(db, tenant_a, suffix="invalid-otp")
    attendee = _pending(db, tenant_a, popup, human)
    with pytest.raises(HTTPException):
        _verify(db, human, code="000000")
    db.refresh(attendee)
    assert attendee.human_id is None


def test_failed_repair_rolls_back_and_does_not_block_authentication(
    db: Session, tenant_a: Tenants
):
    popup = _make_popup(db, tenant_a, suffix="repair-failure")
    human = _make_human(db, tenant_a, suffix="repair-failure")
    attendee = _pending(db, tenant_a, popup, human)

    def fail_after_write(*_args, **_kwargs):
        attendee.human_id = human.id
        db.add(attendee)
        db.flush()
        raise RuntimeError("simulated repair failure")

    with patch.object(
        attendees_crud, "link_attendees_to_human", side_effect=fail_after_write
    ):
        assert _verify(db, human).id == human.id
    db.refresh(attendee)
    db.refresh(human)
    assert attendee.human_id is None
    assert human.auth_code is None


@pytest.mark.parametrize("operation", ["login", "migration"])
@pytest.mark.parametrize(
    "conflict", ["ambiguous", "direct", "explicit", "cross_tenant"]
)
def test_conflicts_are_not_arbitrarily_claimed(
    db: Session, tenant_a: Tenants, tenant_b: Tenants, operation: str, conflict: str
):
    popup = _make_popup(db, tenant_a, suffix=f"conflict-{conflict}")
    human = _make_human(db, tenant_a, suffix=f"conflict-{conflict}")
    other_human = _make_human(db, tenant_a, suffix="other")
    attendee = _pending(db, tenant_a, popup, human)
    expected = None
    if conflict == "ambiguous":
        _pending(db, tenant_a, popup, human)
    elif conflict == "direct":
        direct = Attendees(
            tenant_id=tenant_a.id,
            popup_id=popup.id,
            human_id=human.id,
            name="Existing direct",
        )
        db.add(direct)
    elif conflict == "explicit":
        attendee.human_id = other_human.id
        expected = other_human.id
        db.add(attendee)
    else:
        db.delete(attendee)
        db.commit()
        foreign_popup = _make_popup(db, tenant_b, suffix="foreign")
        attendee = _pending(db, tenant_b, foreign_popup, human)
    db.commit()
    if operation == "login":
        assert (
            attendees_crud.link_attendees_to_human(
                db, human.id, human.email, tenant_a.id
            )
            == 0
        )
    else:
        migration = importlib.import_module(
            "app.alembic.versions.e8a4f1c7d2b6_link_pending_attendees"
        )
        with patch.object(migration.op, "get_bind", return_value=db.connection()):
            migration.upgrade()
        db.commit()
    db.refresh(attendee)
    assert attendee.human_id == expected


@pytest.mark.parametrize("target", ["alias", "other_account", "clear"])
@pytest.mark.parametrize("application_linked", [False, True])
def test_contact_edit_preserves_explicit_identity_and_tickets(
    db: Session,
    client: TestClient,
    tenant_a: Tenants,
    target: str,
    application_linked: bool,
):
    popup = _make_popup(db, tenant_a, suffix="contact-edit")
    human = _make_human(db, tenant_a, suffix="contact-owner")
    other_human = _make_human(db, tenant_a, suffix="contact-other")
    if application_linked:
        _, attendee = _make_app_attendee(db, tenant_a, popup, human)
        attendee.email = human.email
        db.add(attendee)
        db.commit()
    else:
        attendee = _pending(db, tenant_a, popup, human)
        attendee.human_id = human.id
        attendee.email = human.email
        db.add(attendee)
        db.commit()
    original_application = attendee.application_id
    product = _product(db, popup)
    unit = AttendeeProducts(
        tenant_id=tenant_a.id,
        attendee_id=attendee.id,
        product_id=product.id,
        product_category_snapshot="ticket",
        check_in_code=uuid.uuid4().hex,
    )
    db.add(unit)
    db.commit()
    email = {
        "alias": "alias@example.com",
        "other_account": other_human.email,
        "clear": None,
    }[target]
    response = client.patch(
        f"/api/v1/attendees/my/popup/{popup.id}/{attendee.id}",
        headers=_auth(human),
        json={"email": email},
    )
    assert response.status_code == 200
    db.refresh(attendee)
    assert attendee.human_id == human.id
    assert attendee.email == email
    assert attendee.application_id == original_application
    tickets = client.get("/api/v1/applications/my/tickets", headers=_auth(human))
    assert tickets.status_code == 200
    assert any(
        row["id"] == str(attendee.id) and row["products"] for row in tickets.json()
    )


@pytest.mark.parametrize("operation", ["login", "edit", "migration"])
def test_own_application_row_is_not_a_duplicate(
    db: Session, tenant_a: Tenants, operation: str
):
    popup = _make_popup(db, tenant_a, suffix="own-application")
    human = _make_human(db, tenant_a, suffix="own-application")
    _, attendee = _make_app_attendee(db, tenant_a, popup, human)
    attendee.category_id = _category(db, popup).id
    attendee.human_id = None
    attendee.email = human.email
    db.add(attendee)
    db.commit()
    if operation == "login":
        assert (
            attendees_crud.link_attendees_to_human(
                db, human.id, human.email, tenant_a.id
            )
            == 1
        )
    elif operation == "edit":
        attendees_crud.update_attendee(db, attendee, AttendeeUpdate(email=human.email))
    else:
        migration = importlib.import_module(
            "app.alembic.versions.e8a4f1c7d2b6_link_pending_attendees"
        )
        with patch.object(migration.op, "get_bind", return_value=db.connection()):
            migration.upgrade()
        db.commit()
    db.refresh(attendee)
    assert attendee.human_id == human.id


def test_email_edit_only_links_pending_target_not_other_popups(
    db: Session, tenant_a: Tenants
):
    human = _make_human(db, tenant_a, suffix="edit-scope")
    popup = _make_popup(db, tenant_a, suffix="edit-scope")
    other_popup = _make_popup(db, tenant_a, suffix="edit-other")
    attendee = _pending(db, tenant_a, popup, human)
    other = _pending(db, tenant_a, other_popup, human)
    attendee.email = None
    db.add(attendee)
    db.commit()
    updated = attendees_crud.update_attendee(
        db, attendee, AttendeeUpdate(email=human.email)
    )
    db.refresh(other)
    assert updated.human_id == human.id
    assert other.human_id is None


@pytest.mark.parametrize("legacy_main", [False, True])
def test_backfill_links_single_recipient_with_or_without_legacy_main(
    db: Session, tenant_a: Tenants, legacy_main: bool
):
    popup = _make_popup(db, tenant_a, suffix="backfill")
    human = _make_human(db, tenant_a, suffix="backfill")
    manager = _make_human(db, tenant_a, suffix="backfill-manager")
    if legacy_main:
        _make_app_attendee(db, tenant_a, popup, human)
    attendee = _pending(db, tenant_a, popup, human, manager=manager)
    migration = importlib.import_module(
        "app.alembic.versions.e8a4f1c7d2b6_link_pending_attendees"
    )
    with patch.object(migration.op, "get_bind", return_value=db.connection()):
        migration.upgrade()
        migration.upgrade()  # rerun is a no-op for already linked rows
    db.commit()
    db.refresh(attendee)
    assert attendee.human_id == human.id
    assert attendee.managed_by_human_id == manager.id
    assert attendee.application_id is None
    assert attendee.additional_data == {"dietary_restriction": "vegan"}


@pytest.mark.parametrize("operation", ["login", "edit", "migration"])
def test_normalized_account_ambiguity_is_not_claimed(
    db: Session, tenant_a: Tenants, operation: str
):
    from app.api.human.models import Humans

    popup = _make_popup(db, tenant_a, suffix="ambiguous-account")
    human = _make_human(db, tenant_a, suffix="ambiguous-account")
    duplicate = Humans(tenant_id=tenant_a.id, email=human.email.upper())
    db.add(duplicate)
    db.commit()
    attendee = _pending(db, tenant_a, popup, human)
    if operation == "login":
        assert (
            attendees_crud.link_attendees_to_human(
                db, human.id, human.email, tenant_a.id
            )
            == 0
        )
    elif operation == "edit":
        attendees_crud.update_attendee(db, attendee, AttendeeUpdate(email=human.email))
    else:
        migration = importlib.import_module(
            "app.alembic.versions.e8a4f1c7d2b6_link_pending_attendees"
        )
        with patch.object(migration.op, "get_bind", return_value=db.connection()):
            migration.upgrade()
        db.commit()
    db.refresh(attendee)
    assert attendee.human_id is None


def test_ambiguous_popup_does_not_block_unique_recipient_in_other_popup(
    db: Session, tenant_a: Tenants
):
    human = _make_human(db, tenant_a, suffix="independent-popups")
    ambiguous = _make_popup(db, tenant_a, suffix="ambiguous")
    first = _pending(db, tenant_a, ambiguous, human)
    second = _pending(db, tenant_a, ambiguous, human)
    unique_popup = _make_popup(db, tenant_a, suffix="unique")
    unique = _pending(db, tenant_a, unique_popup, human)
    assert (
        attendees_crud.link_attendees_to_human(db, human.id, human.email, tenant_a.id)
        == 1
    )
    for pending in (first, second):
        db.refresh(pending)
        assert pending.human_id is None
    db.refresh(unique)
    assert unique.human_id == human.id


@pytest.mark.parametrize("operation", ["login", "edit", "migration"])
@pytest.mark.parametrize(
    "source", ["manager_contact", "application_contact", "unknown_role"]
)
def test_buyer_contact_email_does_not_claim_companion_identity(
    db: Session, tenant_a: Tenants, operation: str, source: str
):
    from app.api.attendee_category.models import AttendeeCategories

    popup = _make_popup(db, tenant_a, suffix="buyer-contact")
    buyer = _make_human(db, tenant_a, suffix="buyer-contact")
    application, _ = _make_app_attendee(db, tenant_a, popup, buyer)
    attendee = _pending(
        db,
        tenant_a,
        popup,
        buyer,
        manager=buyer if source == "manager_contact" else None,
        application_id=application.id if source != "manager_contact" else None,
    )
    if source == "application_contact":
        category = AttendeeCategories(
            tenant_id=tenant_a.id,
            popup_id=popup.id,
            sales_flow_id=application.sales_flow_id,
            key=f"guest-{uuid.uuid4().hex[:8]}",
            is_primary=False,
        )
        db.add(category)
        db.flush()
        attendee.category_id = category.id
        db.add(attendee)
        db.commit()
    if operation == "login":
        assert _verify(db, buyer).id == buyer.id
    elif operation == "edit":
        attendees_crud.update_attendee(db, attendee, AttendeeUpdate(email=buyer.email))
    else:
        migration = importlib.import_module(
            "app.alembic.versions.e8a4f1c7d2b6_link_pending_attendees"
        )
        with patch.object(migration.op, "get_bind", return_value=db.connection()):
            migration.upgrade()
        db.commit()
    db.refresh(attendee)
    assert attendee.human_id is None
