"""Link unlinked attendees to the Human owning their email.

Attendee rows were only linked by email at attendee creation and at signup,
so a companion row whose email named an existing account (or was corrected
to one later) stayed with human_id NULL: its holder could not RSVP or see the
ticket. Login and email edits now link; this catches the rows already
stranded. Only unambiguous matches (exactly one Human with that email in the
tenant) are linked, and never onto a Human who already has a row at the popup.

Revision ID: d7e1a3c5f9b2
Revises: c9f4a2b7d1e6
"""

import sqlalchemy as sa
from alembic import op

revision = "d7e1a3c5f9b2"
down_revision = "c9f4a2b7d1e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            WITH matches AS (
                SELECT attendee.id AS attendee_id,
                       (array_agg(human.id))[1] AS human_id
                FROM attendees AS attendee
                JOIN humans AS human
                  ON human.tenant_id = attendee.tenant_id
                 AND lower(human.email) = lower(attendee.email)
                WHERE attendee.human_id IS NULL
                  AND attendee.email IS NOT NULL
                GROUP BY attendee.id
                HAVING count(*) = 1
            ),
            unique_per_popup AS (
                SELECT m.attendee_id, m.human_id
                FROM matches AS m
                JOIN attendees AS attendee ON attendee.id = m.attendee_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM attendees AS other
                    WHERE other.human_id = m.human_id
                      AND other.popup_id = attendee.popup_id
                )
                  AND (
                    SELECT count(*) FROM matches AS m2
                    JOIN attendees AS a2 ON a2.id = m2.attendee_id
                    WHERE m2.human_id = m.human_id
                      AND a2.popup_id = attendee.popup_id
                  ) = 1
            )
            UPDATE attendees AS attendee
            SET human_id = u.human_id
            FROM unique_per_popup AS u
            WHERE attendee.id = u.attendee_id
            """
        )
    )


def downgrade() -> None:
    # Data backfill; the links it made are indistinguishable from real ones.
    pass
