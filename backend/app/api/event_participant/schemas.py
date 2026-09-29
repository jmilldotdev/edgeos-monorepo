import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Text
from sqlmodel import DateTime, Field, SQLModel


class ParticipantStatus(str, Enum):
    REGISTERED = "registered"
    CHECKED_IN = "checked_in"
    CANCELLED = "cancelled"


class ParticipantRole(str, Enum):
    HOST = "host"
    SPEAKER = "speaker"
    ATTENDEE = "attendee"


class EventParticipantBase(SQLModel):
    """Base participant schema."""

    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    event_id: uuid.UUID = Field(foreign_key="events.id", index=True)
    profile_id: uuid.UUID = Field(index=True)
    status: ParticipantStatus = Field(default=ParticipantStatus.REGISTERED)
    role: ParticipantRole = Field(default=ParticipantRole.ATTENDEE)
    # Set when the registration targets a single occurrence of a recurring
    # event. NULL for one-off events (the row applies to the event itself).
    occurrence_start: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    check_time: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    message: str | None = Field(default=None, sa_type=Text())
    registered_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_type=DateTime(timezone=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_type=DateTime(timezone=True),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_type=DateTime(timezone=True),
    )


class EventParticipantPublic(EventParticipantBase):
    """Participant schema for API responses."""

    id: uuid.UUID
    # Resolved from the participant's event so administrative clients and the
    # AI broker can show the actual gathering affected by an ID-based action.
    popup_id: uuid.UUID | None = None
    # Joined from Humans. Populated by router helpers when listing participants
    # so clients can render a real name instead of a UUID; None when the
    # referenced human is missing (deleted / cross-tenant link).
    first_name: str | None = None
    last_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class EventParticipantCreate(BaseModel):
    """Participant schema for creation (admin adding participant)."""

    event_id: uuid.UUID
    profile_id: uuid.UUID
    role: ParticipantRole = ParticipantRole.ATTENDEE
    message: str | None = None
    occurrence_start: datetime | None = None


class EventParticipantUpdate(BaseModel):
    """Participant schema for updates."""

    status: ParticipantStatus | None = None
    role: ParticipantRole | None = None
    message: str | None = None


class RegisterRequest(BaseModel):
    """Request body for self-registration."""

    role: ParticipantRole = ParticipantRole.ATTENDEE
    message: str | None = None
    # Set when registering for a single occurrence of a recurring event.
    occurrence_start: datetime | None = None


class EventCheckInEvent(BaseModel):
    """Everything the QR success screen renders, resolved server-side.

    Lets the portal paint the result from the check-in response alone: the
    landing page performs one POST and no follow-up GET, so a scan is a
    single round trip even on a phone on venue wifi.
    """

    id: uuid.UUID
    title: str
    # Already resolved through the portal's own fallback chain:
    # event cover -> venue image -> the popup's placeholder -> None.
    cover_url: str | None = None
    host_display_name: str | None = None
    start_time: datetime
    end_time: datetime
    timezone: str
    venue_title: str | None = None
    # Echoed back so the "view event" link points at the occurrence that was
    # checked into, not at the series master.
    occurrence_start: datetime | None = None
    popup_slug: str


class EventCheckInResult(BaseModel):
    """Outcome of a QR check-in."""

    participant: EventParticipantPublic
    # True when the scan found an existing checked-in row. The screen shows
    # success either way; this only changes the wording.
    already_checked_in: bool = False
    # True when the participation did not exist and was created by this scan
    # (i.e. check-in without a prior RSVP).
    created: bool = False
    event: EventCheckInEvent


class AttendeeEmailsResponse(BaseModel):
    """Active RSVPers' emails for an event, for its managers (portal).

    Returned only to the event's owner/host/collaborators so they can
    contact everyone who RSVPed. Emails are deduplicated and ordered by
    registration order.
    """

    emails: list[str]
    count: int


class RsvpEligibility(BaseModel):
    allowed: bool
    reason: Literal["rejected", "no_tickets"] | None = None
