"""A companion's attendee row must reach the account owning its email.

RSVP eligibility and /my/tickets read ``Attendees.human_id``, never the row's
email. A spouse row whose email named an account that already existed (or was
corrected to it later) stayed unlinked forever: signup was the only other
place a link was made.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.api.application.models import Applications
from app.api.application.schemas import ApplicationStatus
from app.api.attendee.crud import attendees_crud
from app.api.attendee.models import Attendees
from app.api.attendee.schemas import AttendeeUpdate
from app.api.attendee_category.crud import attendee_categories_crud
from app.api.auth.crud import authenticate_human
from app.api.human.models import Humans
from app.api.popup.models import Popups
from app.api.tenant.models import Tenants
from tests._flow_helpers import application_flow_id, provision_default_flow


def _popup(db: Session, tenant: Tenants) -> Popups:
    popup = Popups(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Link by email",
        slug=f"link-email-{uuid.uuid4().hex[:8]}",
    )
    db.add(popup)
    db.flush()
    provision_default_flow(db, popup, sale_type="application")
    return popup


def _human(db: Session, tenant: Tenants) -> Humans:
    human = Humans(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=f"link-{uuid.uuid4().hex[:8]}@test.com",
    )
    db.add(human)
    db.flush()
    return human


def _attendee(
    db: Session,
    tenant: Tenants,
    popup: Popups,
    holder: Humans,
    *,
    human: Humans | None,
    email: str | None,
) -> Attendees:
    """A row on ``holder``'s accepted application, linked to ``human``."""
    flow_id = application_flow_id(db, popup.id)
    category = attendee_categories_crud.get_primary_for_flow(db, flow_id)
    assert category is not None
    application = Applications(
        id=uuid.uuid4(),
        sales_flow_id=flow_id,
        tenant_id=tenant.id,
        popup_id=popup.id,
        human_id=holder.id,
        status=ApplicationStatus.ACCEPTED.value,
    )
    db.add(application)
    db.flush()
    attendee = Attendees(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        application_id=application.id,
        popup_id=popup.id,
        human_id=human.id if human else None,
        name="Row",
        email=email,
        category_id=category.id,
    )
    db.add(attendee)
    db.flush()
    return attendee


def test_email_corrected_to_existing_account_links_companion(db, tenant_a):
    popup = _popup(db, tenant_a)
    host, spouse = _human(db, tenant_a), _human(db, tenant_a)
    row = _attendee(db, tenant_a, popup, host, human=None, email=None)

    attendees_crud.update_attendee(db, row, AttendeeUpdate(email=spouse.email.upper()))

    assert row.human_id == spouse.id


def test_email_moved_off_account_unlinks_email_derived_row(db, tenant_a):
    popup = _popup(db, tenant_a)
    host, wrong = _human(db, tenant_a), _human(db, tenant_a)
    row = _attendee(db, tenant_a, popup, host, human=wrong, email=wrong.email)

    attendees_crud.update_attendee(
        db, row, AttendeeUpdate(email=f"nobody-{uuid.uuid4().hex[:6]}@test.com")
    )

    assert row.human_id is None


def test_email_edit_keeps_link_not_derived_from_email(db, tenant_a):
    """An applicant's own row filed under another address stays theirs."""
    popup = _popup(db, tenant_a)
    owner, other = _human(db, tenant_a), _human(db, tenant_a)
    row = _attendee(
        db, tenant_a, popup, owner, human=owner, email="work-alias@test.com"
    )

    attendees_crud.update_attendee(db, row, AttendeeUpdate(email=other.email))

    assert row.human_id == owner.id


def test_email_edit_to_someone_already_attending_is_rejected(db, tenant_a):
    popup = _popup(db, tenant_a)
    host, spouse = _human(db, tenant_a), _human(db, tenant_a)
    _attendee(db, tenant_a, popup, spouse, human=spouse, email=spouse.email)
    row = _attendee(db, tenant_a, popup, host, human=None, email=None)

    with pytest.raises(HTTPException) as exc:
        attendees_crud.update_attendee(db, row, AttendeeUpdate(email=spouse.email))

    assert exc.value.status_code == 409
    assert row.human_id is None
    db.rollback()


def test_link_skips_popup_the_human_already_attends(db, tenant_a):
    attended, fresh = _popup(db, tenant_a), _popup(db, tenant_a)
    host, spouse = _human(db, tenant_a), _human(db, tenant_a)
    _attendee(db, tenant_a, attended, spouse, human=spouse, email=spouse.email)
    stale = _attendee(db, tenant_a, attended, host, human=None, email=spouse.email)
    companion = _attendee(db, tenant_a, fresh, host, human=None, email=spouse.email)

    linked = attendees_crud.link_attendees_to_human(
        db, spouse.id, spouse.email, tenant_a.id
    )

    assert linked == 1
    assert stale.human_id is None
    assert companion.human_id == spouse.id


def test_existing_account_login_links_companion_row(db, tenant_a):
    """The account predates the spouse ticket, so signup never linked it."""
    popup = _popup(db, tenant_a)
    host, spouse = _human(db, tenant_a), _human(db, tenant_a)
    spouse.auth_code = "123456"
    spouse.code_expiration = datetime.now(UTC) + timedelta(minutes=10)
    row = _attendee(db, tenant_a, popup, host, human=None, email=spouse.email)
    db.commit()

    with patch("app.api.auth.crud.is_redis_available", return_value=False):
        asyncio.run(authenticate_human(db, spouse.email, tenant_a.id, "123456"))

    db.refresh(row)
    assert row.human_id == spouse.id
