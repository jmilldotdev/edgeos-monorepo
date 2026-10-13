"""Backoffice PATCH validates and persists the final schedule in one request."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.audit_log.models import AuditLog
from app.api.event.models import Events
from app.api.event.schemas import EventStatus
from app.api.event_venue.models import EventVenues
from app.api.event_venue.schemas import VenueBookingMode
from app.api.popup.models import Popups
from app.api.tenant.models import Tenants

START = datetime(2026, 10, 12, 7, tzinfo=UTC)  # 12:30 IST
NEW_START = START - timedelta(minutes=30)
RRULE = "FREQ=WEEKLY;INTERVAL=1;BYDAY=MO;COUNT=3"
RULE = {"freq": "WEEKLY", "interval": 1, "by_day": ["MO"], "count": 3}
EXDATE = "2026-10-26T07:00:00Z"


@pytest.fixture
def event(db: Session, tenant_a: Tenants) -> Events:
    popup = Popups(
        tenant_id=tenant_a.id,
        name="Atomic recurrence test",
        slug=f"atomic-recurrence-{uuid.uuid4().hex[:10]}",
    )
    db.add(popup)
    db.flush()
    venue = EventVenues(
        tenant_id=tenant_a.id,
        popup_id=popup.id,
        owner_id=uuid.uuid4(),
        title="Test venue",
        booking_mode=VenueBookingMode.FREE,
    )
    db.add(venue)
    db.flush()
    result = Events(
        tenant_id=tenant_a.id,
        popup_id=popup.id,
        owner_id=venue.owner_id,
        venue_id=venue.id,
        title="Orientation",
        start_time=START,
        end_time=START + timedelta(minutes=30),
        timezone="Asia/Kolkata",
        status=EventStatus.PUBLISHED,
        rrule=RRULE,
        recurrence_exdates=[EXDATE],
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def _conflict(db: Session, event: Events, *, next_week: bool) -> None:
    start = NEW_START + (timedelta(days=7) if next_week else timedelta())
    db.add(
        Events(
            tenant_id=event.tenant_id,
            popup_id=event.popup_id,
            owner_id=event.owner_id,
            venue_id=event.venue_id,
            title="Conflicting event",
            start_time=start,
            end_time=start + timedelta(minutes=30),
            timezone=event.timezone,
            status=EventStatus.PUBLISHED,
        )
    )
    db.commit()


def _move_payload() -> dict:
    return {
        "start_time": NEW_START.isoformat(),
        "end_time": (NEW_START + timedelta(minutes=30)).isoformat(),
    }


def _reload(db: Session, event: Events) -> Events:
    db.expire_all()
    db.refresh(event)
    return event


@pytest.mark.parametrize("recurrence", [None, {"freq": "DAILY", "count": 1}])
def test_move_uses_requested_rule_not_stored_series(
    client: TestClient,
    db: Session,
    event: Events,
    admin_token_tenant_a: str,
    recurrence: dict | None,
) -> None:
    _conflict(db, event, next_week=True)
    with patch(
        "app.api.event.router._bump_and_dispatch_itip_update", new_callable=AsyncMock
    ) as dispatch:
        response = client.patch(
            f"/api/v1/events/{event.id}",
            headers={"Authorization": f"Bearer {admin_token_tenant_a}"},
            json={**_move_payload(), "recurrence": recurrence},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start_time"] == "2026-10-12T06:30:00Z"
    expected = None if recurrence is None else "FREQ=DAILY;INTERVAL=1;COUNT=1"
    assert body["rrule"] == expected
    assert body["recurrence_exdates"] == []
    saved = _reload(db, event)
    assert saved.start_time == NEW_START
    assert saved.rrule == expected
    assert saved.recurrence_exdates == []
    dispatch.assert_awaited_once()
    assert dispatch.call_args.kwargs["before"]["rrule"] == RRULE
    assert dispatch.call_args.kwargs["before"]["recurrence_exdates"] == [EXDATE]
    audits = db.exec(select(AuditLog).where(AuditLog.entity_id == event.id)).all()
    assert len(audits) == 1
    assert audits[0].action == "event.updated"
    assert audits[0].details["changes"]["rrule"] == {"old": RRULE, "new": expected}
    assert audits[0].details["changes"]["recurrence_exdates"] == {
        "old": [EXDATE],
        "new": [],
    }


def test_omitted_recurrence_still_checks_future_conflicts(
    client: TestClient, db: Session, event: Events, admin_token_tenant_a: str
) -> None:
    _conflict(db, event, next_week=True)
    response = client.patch(
        f"/api/v1/events/{event.id}",
        headers={"Authorization": f"Bearer {admin_token_tenant_a}"},
        json=_move_payload(),
    )
    assert response.status_code == 409, response.text
    assert "Mon Oct 19 12:00 IST" in response.json()["detail"]
    saved = _reload(db, event)
    assert saved.start_time == START
    assert saved.rrule == RRULE
    assert saved.recurrence_exdates == [EXDATE]


def test_real_conflict_rejects_entire_update(
    client: TestClient, db: Session, event: Events, admin_token_tenant_a: str
) -> None:
    _conflict(db, event, next_week=False)
    with patch(
        "app.api.event.router._bump_and_dispatch_itip_update", new_callable=AsyncMock
    ) as dispatch:
        response = client.patch(
            f"/api/v1/events/{event.id}",
            headers={"Authorization": f"Bearer {admin_token_tenant_a}"},
            json={**_move_payload(), "title": "Should not save", "recurrence": None},
        )
    assert response.status_code == 409, response.text
    saved = _reload(db, event)
    assert saved.title == "Orientation"
    assert saved.start_time == START
    assert saved.rrule == RRULE
    assert saved.recurrence_exdates == [EXDATE]
    dispatch.assert_not_awaited()


@pytest.mark.parametrize("include_rule", [False, True])
def test_unchanged_rule_preserves_exdates(
    client: TestClient,
    db: Session,
    event: Events,
    admin_token_tenant_a: str,
    include_rule: bool,
) -> None:
    response = client.patch(
        f"/api/v1/events/{event.id}",
        headers={"Authorization": f"Bearer {admin_token_tenant_a}"},
        json={"title": "Renamed", **({"recurrence": RULE} if include_rule else {})},
    )
    assert response.status_code == 200, response.text
    saved = _reload(db, event)
    assert saved.rrule == RRULE
    assert saved.recurrence_exdates == [EXDATE]


def test_recurrence_only_change_checks_new_occurrences(
    client: TestClient, db: Session, event: Events, admin_token_tenant_a: str
) -> None:
    event.start_time = NEW_START
    event.end_time = NEW_START + timedelta(minutes=30)
    event.rrule = None
    event.recurrence_exdates = []
    db.add(event)
    db.commit()
    _conflict(db, event, next_week=True)
    response = client.patch(
        f"/api/v1/events/{event.id}",
        headers={"Authorization": f"Bearer {admin_token_tenant_a}"},
        json={"recurrence": RULE},
    )
    assert response.status_code == 409, response.text
    assert _reload(db, event).rrule is None


def test_detached_occurrence_cannot_become_series(
    client: TestClient, db: Session, event: Events, admin_token_tenant_a: str
) -> None:
    master = Events(
        tenant_id=event.tenant_id,
        popup_id=event.popup_id,
        owner_id=event.owner_id,
        title="Master",
        start_time=START,
        end_time=START + timedelta(minutes=30),
        rrule=RRULE,
    )
    db.add(master)
    db.flush()
    event.recurrence_master_id = master.id
    event.rrule = None
    db.add(event)
    db.commit()
    response = client.patch(
        f"/api/v1/events/{event.id}",
        headers={"Authorization": f"Bearer {admin_token_tenant_a}"},
        json={"recurrence": RULE},
    )
    assert response.status_code == 400, response.text
    assert _reload(db, event).rrule is None


@pytest.mark.parametrize("recurrence", [None, {"freq": "DAILY", "count": 2}])
def test_recurrence_only_change_persists_without_changing_time(
    client: TestClient,
    db: Session,
    event: Events,
    admin_token_tenant_a: str,
    recurrence: dict | None,
) -> None:
    response = client.patch(
        f"/api/v1/events/{event.id}",
        headers={"Authorization": f"Bearer {admin_token_tenant_a}"},
        json={"recurrence": recurrence},
    )
    assert response.status_code == 200, response.text
    expected = None if recurrence is None else "FREQ=DAILY;INTERVAL=1;COUNT=2"
    saved = _reload(db, event)
    assert saved.rrule == expected
    assert saved.recurrence_exdates == []
    assert saved.start_time == START


def test_invalid_rule_does_not_save_other_fields(
    client: TestClient, db: Session, event: Events, admin_token_tenant_a: str
) -> None:
    response = client.patch(
        f"/api/v1/events/{event.id}",
        headers={"Authorization": f"Bearer {admin_token_tenant_a}"},
        json={**_move_payload(), "recurrence": {"freq": "WEEKLY", "count": 0}},
    )
    assert response.status_code == 422, response.text
    saved = _reload(db, event)
    assert saved.start_time == START
    assert saved.rrule == RRULE
    assert saved.recurrence_exdates == [EXDATE]
