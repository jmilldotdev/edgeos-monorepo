"""Persist the current tenant-bound Telegram managed-bot setup attempt."""
import sqlalchemy as sa
from alembic import op

revision = "b7a4c9e2f180"
down_revision = "a2f6c8e1d490"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_setups", sa.Column("telegram_pairing_id", sa.String(), nullable=True))


def downgrade():
    op.drop_column("agent_setups", "telegram_pairing_id")
