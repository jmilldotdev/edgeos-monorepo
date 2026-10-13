"""Link unambiguous pending recipients without merging attendees.

Revision ID: e8a4f1c7d2b6
Revises: c9f4a2b7d1e6

Same policy as runtime: one normalized account per tenant/email, one eligible
pending candidate per popup, and no direct-sale uniqueness conflict. Manager
contact rows are excluded; an applicant's own row needs an explicit primary
category in its application flow. A linked main does not block a recipient.
"""

import logging

import sqlalchemy as sa
from alembic import op

revision = "e8a4f1c7d2b6"
down_revision = "c9f4a2b7d1e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Reads remain available. Block concurrent inserts/claims for this short
    # backfill so the uniqueness checks cannot race application writers.
    connection.execute(sa.text("LOCK TABLE attendees IN EXCLUSIVE MODE"))
    result = connection.execute(
        sa.text(
            """
            WITH accounts AS (
                SELECT tenant_id, lower(btrim(email)) AS email,
                       (array_agg(id))[1] AS human_id
                FROM humans
                WHERE btrim(email) <> ''
                GROUP BY tenant_id, lower(btrim(email))
                HAVING count(*) = 1
            ), candidates AS (
                SELECT a.id, a.tenant_id, a.popup_id, a.application_id,
                       h.human_id,
                       count(*) OVER (
                           PARTITION BY a.tenant_id, a.popup_id, h.human_id
                       ) AS candidate_count
                FROM attendees AS a
                JOIN accounts AS h ON h.tenant_id = a.tenant_id
                                  AND h.email = lower(btrim(a.email))
                WHERE a.human_id IS NULL
                  AND (a.managed_by_human_id IS NULL
                       OR a.managed_by_human_id <> h.human_id)
                  AND (
                      NOT EXISTS (
                          SELECT 1 FROM applications AS app
                          WHERE app.id = a.application_id
                            AND app.tenant_id = a.tenant_id
                            AND app.human_id = h.human_id
                      ) OR EXISTS (
                          SELECT 1 FROM attendee_categories AS category
                          JOIN applications AS app
                            ON app.sales_flow_id = category.sales_flow_id
                          WHERE app.id = a.application_id
                            AND category.id = a.category_id
                            AND category.tenant_id = a.tenant_id
                            AND category.is_primary IS TRUE
                      )
                  )
            )
            UPDATE attendees AS a
            SET human_id = c.human_id, updated_at = now()
            FROM candidates AS c
            WHERE a.id = c.id AND a.human_id IS NULL
              AND c.candidate_count = 1
              AND (
                  c.application_id IS NOT NULL OR NOT EXISTS (
                      SELECT 1 FROM attendees AS existing
                      WHERE existing.tenant_id = c.tenant_id
                        AND existing.popup_id = c.popup_id
                        AND existing.human_id = c.human_id
                        AND existing.application_id IS NULL
                  )
              )
            """
        )
    )
    logging.getLogger(__name__).info(
        "Linked %s pending attendees", getattr(result, "rowcount", "unknown")
    )


def downgrade() -> None:
    # Deliberately irreversible: later legitimate links are indistinguishable
    # from the backfill. Never revoke identity/ticket access on downgrade.
    pass
