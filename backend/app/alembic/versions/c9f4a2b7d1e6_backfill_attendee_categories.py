"""Backfill attendee categories from their owning flow when one is available.

Revision ID: c9f4a2b7d1e6
Revises: a1d3f5b7c9e2
"""

import sqlalchemy as sa
from alembic import op

revision = "c9f4a2b7d1e6"
down_revision = "a1d3f5b7c9e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE attendees AS attendee
            SET category_id = category.id
            FROM attendee_categories AS category
            WHERE attendee.category_id IS NULL
              AND category.is_primary IS TRUE
              AND category.deleted_at IS NULL
              AND category.popup_id = attendee.popup_id
              AND category.sales_flow_id = COALESCE(
                  (
                      SELECT application.sales_flow_id
                      FROM applications AS application
                      WHERE application.id = attendee.application_id
                  ),
                  (
                      SELECT flow.id
                      FROM sales_flows AS flow
                      WHERE flow.popup_id = attendee.popup_id
                        AND flow.is_default IS TRUE
                      LIMIT 1
                  )
              )
            """
        )
    )
def downgrade() -> None:
    pass
