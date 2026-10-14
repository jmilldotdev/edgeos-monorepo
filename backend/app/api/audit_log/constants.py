"""Stable string constants for the audit log.

Actions are namespaced as `<entity>.<verb>`. Adding a new auditable event is
just a new constant here plus a single `audit_logs_crud.record(...)` call at the
mutation site — the table and read API do not change.
"""


class AuditAction:
    """Namespaced action identifiers stored in `audit_logs.action`."""

    TICKET_SWAP = "ticket.swap"
    TICKET_ADD = "ticket.add"
    TICKET_REMOVE = "ticket.remove"
    TICKET_GRANT = "ticket.grant"

    # Manual activity note added to a human from the backoffice timeline.
    HUMAN_NOTE_ADDED = "human.note_added"

    # A human's rating (red/orange/green flag, star, …) was changed by a user.
    HUMAN_RATING_CHANGED = "human.rating_changed"

    # Coupon lifecycle changes made from the backoffice or AI copilot.
    COUPON_CREATED = "coupon.created"
    COUPON_UPDATED = "coupon.updated"

    # Credit movements on an application (grant, debit, restore).
    CREDIT_GRANTED = "credit.granted"
    CREDIT_APPLIED = "credit.applied"
    CREDIT_RESTORED = "credit.restored"

    # Portal edit-passes settlement (edit-pass swap completed).
    PASSES_EDITED = "passes.edited"

    # Sales-flow form structure changes. These entries intentionally describe
    # structure only; submitted answers and field values are never stored.
    FORM_SECTION_CREATED = "form_section.created"
    FORM_SECTION_UPDATED = "form_section.updated"
    FORM_SECTION_DELETED = "form_section.deleted"
    FORM_SECTION_DELETE_REJECTED = "form_section.delete_rejected"
    FORM_FIELD_SECTION_CHANGED = "form_field.section_changed"
    FORM_COPIED_TO_FLOW = "form.copied_to_flow"
    SALES_FLOW_DELETED = "sales_flow.deleted"
    POPUP_DELETED = "popup.deleted"


class AuditEntityType:
    """Type of the primary entity an event is grouped under."""

    ATTENDEE = "attendee"
    COUPON = "coupon"
    EVENT = "event"
    HUMAN = "human"
    PRODUCT = "product"
    FORM_SECTION = "form_section"
    FORM_FIELD = "form_field"
    BASE_FIELD_CONFIG = "base_field_config"
    SALES_FLOW = "sales_flow"
    POPUP = "popup"
