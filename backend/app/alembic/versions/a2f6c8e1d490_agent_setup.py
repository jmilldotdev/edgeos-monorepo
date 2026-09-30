"""Durable human-owned agent onboarding and one-use native Desktop handoffs.

These private tables intentionally have no tenant-role grants. The privileged
session enforces human+tenant ownership; native routes accept only random hashes.
"""
import sqlalchemy as sa
from alembic import op

revision = "a2f6c8e1d490"
down_revision = "c4e81a2d7f90"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_setups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("human_id", sa.Uuid(), sa.ForeignKey("humans.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("consent", sa.JSON(), nullable=False),
        sa.Column("cp_tenant_id", sa.String(), nullable=True),
        sa.Column("context_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consent_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "human_id"),
    )
    op.create_table(
        "agent_consent_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("setup_id", sa.Uuid(), sa.ForeignKey("agent_setups.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("consent", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_consent_events_setup_id", "agent_consent_events", ["setup_id"])
    op.create_table(
        "agent_desktop_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("setup_id", sa.Uuid(), sa.ForeignKey("agent_setups.id"), nullable=False),
        sa.Column("cp_tenant_id", sa.String(), nullable=False),
        sa.Column("gateway_url", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("exchange_hash", sa.String(), unique=True),
        sa.Column("ack_hash", sa.String(), unique=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("code", sa.String()),
        sa.Column("desktop_version", sa.String()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_desktop_attempts_setup_id", "agent_desktop_attempts", ["setup_id"])
    # Default privileges differ among installations. Explicitly deny tenant roles.
    for table in ("agent_setups", "agent_consent_events", "agent_desktop_attempts"):
        op.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC, tenant_role, tenant_viewer_role")


def downgrade():
    op.drop_table("agent_desktop_attempts")
    op.drop_table("agent_consent_events")
    op.drop_table("agent_setups")
