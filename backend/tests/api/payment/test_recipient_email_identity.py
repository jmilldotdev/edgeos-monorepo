"""Fulfillment links the recipient without transferring buyer/manager ownership."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.api.attendee.crud import attendees_crud
from app.api.attendee.models import Attendees
from app.api.payment.crud import payments_crud
from app.api.popup.models import Popups
from app.api.tenant.models import Tenants
from tests.api.attendee.test_list_my_tickets import _make_app_attendee
from tests.api.payment.test_deferred_attendee_fulfillment import (
    _human,
    _payment,
    _product,
    _tickets,
)


@pytest.mark.parametrize("legacy_main", [False, True])
def test_approval_links_existing_recipient_preserving_buyer_and_lineage(
    db: Session, tenant_a: Tenants, popup_tenant_a: Popups, legacy_main: bool
):
    buyer = _human(db, tenant_a, "Purchaser")
    recipient_human = _human(db, tenant_a, "Recipient")
    if legacy_main:
        _make_app_attendee(db, tenant_a, popup_tenant_a, recipient_human)
    product = _product(db, popup_tenant_a)
    payment, recipient, line = _payment(db, popup_tenant_a, buyer, product)
    recipient.email = f" {recipient_human.email.upper()} "
    db.add(recipient)
    db.commit()

    payments_crud.approve_payment(db, payment.id)
    db.refresh(recipient)
    db.refresh(line)
    attendee = db.get(Attendees, recipient.attendee_id)
    unit = _tickets(db, payment.id)[0]
    original_code = unit.check_in_code
    assert attendee.human_id == recipient_human.id
    assert attendee.managed_by_human_id == buyer.id
    assert attendee.application_id is None
    assert recipient.human_id is None  # original checkout snapshot unchanged
    assert line.attendee_id == attendee.id
    assert unit.attendee_id == attendee.id
    assert unit.payment_product_id == line.id

    payments_crud.approve_payment(db, payment.id)
    db.refresh(attendee)
    assert attendee.human_id == recipient_human.id
    assert attendee.managed_by_human_id == buyer.id
    assert _tickets(db, payment.id)[0].check_in_code == original_code
    assert len(_tickets(db, payment.id)) == 1


@pytest.mark.parametrize("conflict", ["direct", "foreign_account", "explicit"])
def test_fulfillment_does_not_reuse_or_transfer_unrelated_identity(
    db: Session,
    tenant_a: Tenants,
    tenant_b: Tenants,
    popup_tenant_a: Popups,
    conflict: str,
):
    buyer = _human(db, tenant_a, "ConflictBuyer")
    recipient_human = _human(
        db, tenant_b if conflict == "foreign_account" else tenant_a, "ConflictRecipient"
    )
    existing = None
    if conflict != "foreign_account":
        existing = Attendees(
            tenant_id=tenant_a.id,
            popup_id=popup_tenant_a.id,
            human_id=recipient_human.id,
            email=recipient_human.email,
            name="Existing unrelated recipient",
            managed_by_human_id=buyer.id if conflict == "explicit" else None,
        )
        db.add(existing)
        db.commit()
    product = _product(db, popup_tenant_a)
    payment, recipient, _ = _payment(
        db,
        popup_tenant_a,
        buyer,
        product,
        existing_attendee=existing if conflict == "explicit" else None,
    )
    recipient.email = buyer.email if conflict == "explicit" else recipient_human.email
    db.add(recipient)
    db.commit()
    payments_crud.approve_payment(db, payment.id)
    db.refresh(recipient)
    attendee = db.get(Attendees, recipient.attendee_id)
    assert attendee.human_id == (recipient_human.id if conflict == "explicit" else None)
    assert attendee.managed_by_human_id == buyer.id
    if conflict == "direct":
        assert attendee.id != existing.id
        db.refresh(existing)
        assert existing.human_id == recipient_human.id
        assert existing.managed_by_human_id is None


def test_reciprocal_purchases_can_link_each_other_without_buyer_lock_deadlock(
    db: Session, test_engine, tenant_a: Tenants, popup_tenant_a: Popups
):
    first = _human(db, tenant_a, "ReciprocalFirst")
    second = _human(db, tenant_a, "ReciprocalSecond")
    product = _product(db, popup_tenant_a)
    payments = []
    for buyer, target in [(first, second), (second, first)]:
        payment, recipient, _ = _payment(db, popup_tenant_a, buyer, product)
        recipient.email = target.email
        db.add(recipient)
        db.commit()
        payments.append((payment.id, recipient.id, buyer.id, target.id))
    barrier = Barrier(2)
    original = attendees_crud.link_pending_attendee_by_email

    def simultaneous_link(session, attendee):
        barrier.wait(timeout=15)
        return original(session, attendee)

    def approve(payment_id):
        with Session(test_engine) as session:
            payments_crud.approve_payment(session, payment_id)

    with patch.object(
        attendees_crud, "link_pending_attendee_by_email", simultaneous_link
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(approve, payment_id) for payment_id, *_ in payments]
            for future in futures:
                future.result(timeout=30)
    for payment_id, _, buyer_id, target_id in payments:
        unit = _tickets(db, payment_id)[0]
        attendee = db.get(Attendees, unit.attendee_id)
        assert attendee.human_id == target_id
        assert attendee.managed_by_human_id == buyer_id


def test_parallel_ambiguous_reconciliation_keeps_both_recipients_pending(
    db: Session, test_engine, tenant_a: Tenants, popup_tenant_a: Popups
):
    target = _human(db, tenant_a, "AmbiguousParallelTarget")
    buyers = [_human(db, tenant_a, f"AmbiguousBuyer{i}") for i in range(2)]
    product = _product(db, popup_tenant_a)
    payment_ids = []
    attendee_ids = []
    for buyer in buyers:
        attendee = Attendees(
            tenant_id=tenant_a.id,
            popup_id=popup_tenant_a.id,
            name="Ambiguous pending recipient",
            email=target.email,
            managed_by_human_id=buyer.id,
        )
        db.add(attendee)
        db.commit()
        attendee_ids.append(attendee.id)
        payment, _, _ = _payment(
            db,
            popup_tenant_a,
            buyer,
            product,
            existing_attendee=attendee,
        )
        payment_ids.append(payment.id)
    barrier = Barrier(2)
    original = attendees_crud.link_pending_attendee_by_email

    def simultaneous_link(session, attendee):
        barrier.wait(timeout=15)
        return original(session, attendee)

    def approve(payment_id):
        with Session(test_engine) as session:
            payments_crud.approve_payment(session, payment_id)

    with patch.object(
        attendees_crud, "link_pending_attendee_by_email", simultaneous_link
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(approve, payment_id) for payment_id in payment_ids]
            for future in futures:
                future.result(timeout=30)
    for payment_id, attendee_id in zip(payment_ids, attendee_ids, strict=True):
        db.expire_all()
        assert db.get(Attendees, attendee_id).human_id is None
        assert _tickets(db, payment_id)[0].attendee_id == attendee_id
