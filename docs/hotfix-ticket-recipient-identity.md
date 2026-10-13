# Ticket recipient identity hotfix — release runbook

## Scope

This backend-only fix resolves unambiguous pending recipient identities during
verified authentication, explicit pending email edits, payment fulfillment and
an existing-data migration. API contracts remain unchanged.

It preserves purchaser/manager permissions, application association, payment
and recipient snapshots, units, check-in codes and explicit identity links. It
does not merge attendees or delete legacy mains. An application-backed main does
not block a separate direct recipient; an existing linked direct row does.
Shared contacts, multiple pending candidates, multiple normalized accounts and
identity conflicts remain pending for explicit reconciliation.

Frontend sales-flow grouping and ambiguity guidance are outside this hotfix.

## Preflight requirements

Use `backend/scripts/preview_pending_recipient_identity.sql` with an authorized
DB connection. The preview uses a repeatable-read read-only transaction and a
final rollback. Credentials and private query results must not be included in
PRs, commits or release notes.

- Verify the current Alembic revision is the expected migration predecessor.
- Review the global scope and every proposed identity link.
- Inspect payment-owner review flags; these are review signals, not additional
  exclusions in the migration.
- Retain before-state evidence privately for approved targets and protected
  fields, units and financial lineage.
- Re-run the preview before publishing; candidate counts are not fixed and the
  migration is not restricted to one tenant or popup.

## Release gate — do not deploy during preparation

1. Review and merge the hotfix PR into `main` after required CI succeeds.
2. Repeat the read-only preview and approve its current scope.
3. Verify the exact migration chain: `c9f4a2b7d1e6` → `e8a4f1c7d2b6`,
   a data-only migration with no schema changes. Confirm a recent backup/PITR
   recovery point and retain before-state evidence privately.
4. Obtain approval for the current global impact and the release. Publishing the
   release triggers deployment; preparing/pushing a PR must not do so.
5. Create the agreed release/tag from the reviewed `main` commit. Do not reuse a
   tag or publish a draft accidentally. Choose the release version separately.
6. Use the deployment's established migration runner for `alembic upgrade head`.
   Do not run the backfill ad hoc as a second independently managed change.

## Migration behavior and monitoring

The backfill changes only `attendees.human_id` and `updated_at`. It takes an
`EXCLUSIVE` table lock to serialize claims/inserts while checking uniqueness;
ordinary reads remain available but attendee writes and row-locking reads can
wait. Monitor startup/migration logs. Do not assume simultaneous migration
runners are safe merely because the UPDATE is idempotent.

Already linked rows are not changed by another pass. Check the number of linked
attendees against the fresh preview. A changed count requires investigation,
not automatic identity transfer or deletion.

## Post-release validation

- Confirm backend health, deployed commit and Alembic head `e8a4f1c7d2b6`.
- Confirm approved targets have the expected identity; manager and application
  lineage must match the private before-state.
- Compare hashes for protected attendee fields (excluding identity/updated_at),
  units, payment products, recipient snapshots and payments.
- Confirm ambiguous/shared contacts have not received arbitrary identity links.
- Validate personal-ticket responses through authorized user sessions. The
  existing `/api/v1/applications/my/tickets` includes linked ticket holders;
  `/api/v1/attendees/my/popup/{popup_id}` exposes permitted units/QR.
- Check purchaser/manager access remains intact and personal payment history
  does not expose another purchaser's payment. Do not impersonate participants.
- The existing RSVP eligibility endpoint still requires an active ticket.
  Do not create production RSVPs solely to validate a release.
- An `Other passes` label may remain in the current frontend; flow provenance
  is separate from identity resolution.

## Rollback / incident response

Prefer a reviewed fix-forward. Downgrade intentionally does not unlink anyone:
later legitimate identity links cannot be distinguished safely from backfill
links. Reverting application code alone does not revoke repaired access, and an
older image may not recognize the new Alembic revision at startup.

Any rollback must account for that metadata with the approved migration runner.
A controlled downgrade to the previous revision changes migration metadata, not
ownership; do not perform it automatically. Never bulk-reset human IDs or
restore/delete a main. Ownership corrections need fresh state, explicit
authorization and targeted reconciliation.
