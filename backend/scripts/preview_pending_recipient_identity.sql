-- Preview only: same identity eligibility as e8a4f1c7d2b6.
-- Supply a database connection using your approved credential mechanism.
-- No emails, names, QR codes, financial amounts, writes, or table write locks.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '60s';
SET LOCAL lock_timeout = '3s';

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
), eligible AS (
    SELECT a.id AS attendee_id, c.tenant_id, c.popup_id,
           c.human_id AS proposed_human_id,
           a.application_id, a.managed_by_human_id,
           EXISTS (
               SELECT 1 FROM attendee_products AS unit
               JOIN payments AS payment ON payment.id = unit.payment_id
               LEFT JOIN applications AS app ON app.id = payment.application_id
               WHERE unit.attendee_id = a.id AND unit.revoked_at IS NULL
                 AND COALESCE(payment.buyer_human_id, app.human_id) = c.human_id
           ) AS payment_owner_matches_proposed_human
    FROM attendees AS a JOIN candidates AS c ON a.id = c.id
    WHERE a.human_id IS NULL AND c.candidate_count = 1
      AND (
          c.application_id IS NOT NULL OR NOT EXISTS (
              SELECT 1 FROM attendees AS existing
              WHERE existing.tenant_id = c.tenant_id
                AND existing.popup_id = c.popup_id
                AND existing.human_id = c.human_id
                AND existing.application_id IS NULL
          )
      )
)
SELECT jsonb_build_object(
    'global_counts', COALESCE((
        SELECT jsonb_agg(to_jsonb(summary)) FROM (
            SELECT tenant_id, popup_id, count(*) AS proposed_links,
                   count(*) FILTER (WHERE payment_owner_matches_proposed_human)
                       AS payment_owner_review_count
            FROM eligible GROUP BY tenant_id, popup_id
            ORDER BY tenant_id, popup_id
        ) AS summary
    ), '[]'::jsonb),
    'proposed_links', COALESCE((
        SELECT jsonb_agg(to_jsonb(eligible) ORDER BY attendee_id) FROM eligible
    ), '[]'::jsonb)
) AS preview;

ROLLBACK;
