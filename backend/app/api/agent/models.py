"""Private agent setup storage; accessed only through the privileged session.

Browser operations always scope both verified human and tenant. Native handoffs
use random, expiring, single-use credential hashes, never human bearer tokens.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(UTC)


class AgentSetup(SQLModel, table=True):
    __tablename__ = "agent_setups"
    __table_args__ = (UniqueConstraint("tenant_id", "human_id"),)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    human_id: uuid.UUID = Field(foreign_key="humans.id")
    revision: int = 0
    draft: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    consent: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    cp_tenant_id: str | None = None
    telegram_pairing_id: str | None = None
    context_pending: bool = False
    consent_pending: bool = False
    updated_at: datetime = Field(
        default_factory=now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class AgentConsentEvent(SQLModel, table=True):
    __tablename__ = "agent_consent_events"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    setup_id: uuid.UUID = Field(foreign_key="agent_setups.id", index=True)
    revision: int
    consent: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(
        default_factory=now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class AgentDesktopAttempt(SQLModel, table=True):
    __tablename__ = "agent_desktop_attempts"
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    setup_id: uuid.UUID = Field(foreign_key="agent_setups.id", index=True)
    cp_tenant_id: str
    gateway_url: str
    label: str
    exchange_hash: str | None = Field(default=None, unique=True)
    ack_hash: str | None = Field(default=None, unique=True)
    status: str = "pending"
    code: str | None = None
    desktop_version: str | None = None
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
