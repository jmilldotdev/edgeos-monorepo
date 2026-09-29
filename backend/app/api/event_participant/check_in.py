"""QR check-in for events — window, capacity lock and the write itself.

The organizer shows a QR that encodes a portal URL for one event (and one
occurrence, for a recurring series). Scanning it lands the attendee on a
portal page that performs a single POST. That POST may *create* the
participation, so everything the RSVP path validates has to be validated
here too — plus a time window, which until now only existed in the UI.

Kept out of ``router.py`` so the endpoint stays a thin sequence of guards
and the transactional core can be unit-tested on its own.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlmodel import Session, select

from app.api.event_participant import crud
from app.api.event_participant.models import EventParticipants
from app.api.event_participant.schemas import ParticipantStatus

# Check-in window, relative to the *occurrence* being checked into (not the
# series master). Opens early enough for the queue that forms before the
# doors, closes late enough for the person who scans on the way out.
# Deliberately constants, not per-popup settings: no tenant has asked to
# tune them, and a column nobody changes is a migration plus a form field
# for nothing. Promote to event_settings the day one does.
CHECK_IN_OPENS_MINUTES_BEFORE = 30
CHECK_IN_CLOSES_MINUTES_AFTER = 120


def reject(status_code: int, code: str, message: str) -> HTTPException:
    """A machine-readable rejection.

    The portal maps ``code`` to a localized string; ``message`` is the
    English fallback for clients that don't know the code (and for logs).
    """
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def is_scheduled_occurrence(event, occurrence_start: datetime) -> bool:
    """Whether the series actually produces an instance at this instant.

    False for invented times and for dates removed via EXDATE.
    """
    from app.api.event.recurrence import expand, parse_rrule

    try:
        rule = parse_rrule(event.rrule)
    except ValueError:
        return False
    if rule is None:
        return False
    occ = _aware(occurrence_start)
    return bool(
        expand(
            dtstart=event.start_time,
            rule=rule,
            window_start=occ,
            window_end=occ,
            exdates=list(event.recurrence_exdates or []),
            max_occurrences=1,
            timezone=event.timezone,
        )
    )


def resolve_occurrence_window(
    event, occurrence_start: datetime | None
) -> tuple[datetime, datetime]:
    """Start/end of the instance being checked into.

    A recurring master's own ``start_time``/``end_time`` describe its first
    instance only, so for every other occurrence the end is derived by
    carrying the master's duration onto ``occurrence_start``.
    """
    start = _aware(event.start_time)
    end = _aware(event.end_time)
    if occurrence_start is None:
        return start, end
    occ = _aware(occurrence_start)
    return occ, occ + (end - start)


def ensure_check_in_window_open(
    window_start: datetime,
    window_end: datetime,
    *,
    now: datetime | None = None,
) -> None:
    """Reject a scan that is too early or too late.

    Enforced here and not only in the UI: the QR URL is shareable, so the
    window is the only thing keeping a link from being usable weeks later.
    """
    moment = now or datetime.now(UTC)
    opens_at = window_start - timedelta(minutes=CHECK_IN_OPENS_MINUTES_BEFORE)
    closes_at = window_end + timedelta(minutes=CHECK_IN_CLOSES_MINUTES_AFTER)
    if moment < opens_at:
        raise reject(
            status.HTTP_403_FORBIDDEN,
            "check_in_not_open",
            "Check-in for this event hasn't opened yet.",
        )
    if moment > closes_at:
        raise reject(
            status.HTTP_403_FORBIDDEN,
            "check_in_closed",
            "Check-in for this event is closed.",
        )


def lock_event_for_capacity(db: Session, event_id: uuid.UUID) -> None:
    """Serialize seat-taking writes for one event.

    ``SELECT ... FOR UPDATE`` on the event row is held until the surrounding
    transaction commits, so a count-then-insert on ``event_participants``
    cannot interleave with another one: two simultaneous scans (or a scan
    racing an RSVP) can no longer both take the last seat.

    ``populate_existing`` refreshes the already-identity-mapped Events row,
    so the capacity read after the lock is the committed value rather than
    whatever this session loaded before waiting.
    """
    from app.api.event.models import Events

    db.exec(  # type: ignore[call-overload]
        select(Events)
        .where(Events.id == event_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()


def ensure_rsvp_eligible(db: Session, popup_id: uuid.UUID, human_id: uuid.UUID) -> None:
    """Same gate as RSVP: an allocated ticket and no rejected application.

    Holding the QR URL is not access. Someone who could not RSVP to this
    event cannot check into it either.
    """
    access = crud.event_participants_crud.eligibility_by_human(
        db, popup_id, {human_id}
    )[human_id]
    if access.allowed:
        return
    if access.reason == "rejected":
        raise reject(
            status.HTTP_403_FORBIDDEN,
            "application_rejected",
            "Your application was not accepted, so you can't check in to events.",
        )
    raise reject(
        status.HTTP_403_FORBIDDEN,
        "ticket_required",
        "You need a purchased ticket for this popup to check in.",
    )


def perform_check_in(
    db: Session,
    event,
    human,
    occurrence_start: datetime | None,
) -> tuple[EventParticipants, bool, bool]:
    """Check ``human`` into ``event``, creating the participation if needed.

    Returns ``(participant, already_checked_in, created)``.

    Four cases, in the order the issue spells them out:

    * already ``checked_in`` — informational success, nothing is written and
      ``check_time`` keeps its original value. Re-scanning is harmless.
    * ``registered`` — flipped to ``checked_in``. No capacity check: the seat
      was already theirs, so a now-full event must not turn them away.
    * cancelled — treated as a fresh entry, subject to eligibility and
      capacity, reusing the row (the partial unique indexes allow only one).
    * missing — created directly as ``checked_in``. No RSVP required.

    Never sends the iTIP message the RSVP path sends: a direct check-in is
    not an invitation, and the event has already started by definition.
    """
    lock_event_for_capacity(db, event.id)

    existing = crud.event_participants_crud.get_by_event_and_profile(
        db, event.id, human.id, occurrence_start=occurrence_start
    )

    if existing is not None and existing.status == ParticipantStatus.CHECKED_IN:
        return existing, True, False

    now = datetime.now(UTC)

    if existing is not None and existing.status == ParticipantStatus.REGISTERED:
        existing.status = ParticipantStatus.CHECKED_IN
        existing.check_time = now
        existing.updated_at = now
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing, False, False

    # No active participation: this scan is taking a seat, so it has to pass
    # everything a fresh RSVP would.
    ensure_rsvp_eligible(db, event.popup_id, human.id)

    if occurrence_start is not None and not is_scheduled_occurrence(
        event, occurrence_start
    ):
        raise reject(
            status.HTTP_400_BAD_REQUEST,
            "occurrence_not_scheduled",
            "occurrence_start does not match a scheduled occurrence",
        )

    if event.max_participant:
        active = crud.event_participants_crud.count_active_for_event(
            db, event.id, occurrence_start=occurrence_start
        )
        if active >= event.max_participant:
            raise reject(
                status.HTTP_409_CONFLICT,
                "event_full",
                "This event is full. There are no seats left.",
            )

    if existing is not None:
        # Cancelled row — reactivate in place. ``registered_at`` is reset
        # because this is a new entry, not a resumption of the old one.
        existing.status = ParticipantStatus.CHECKED_IN
        existing.check_time = now
        existing.registered_at = now
        existing.updated_at = now
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing, False, False

    participant = EventParticipants(
        tenant_id=human.tenant_id,
        event_id=event.id,
        profile_id=human.id,
        status=ParticipantStatus.CHECKED_IN,
        occurrence_start=occurrence_start,
        check_time=now,
        registered_at=now,
    )
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant, False, True
