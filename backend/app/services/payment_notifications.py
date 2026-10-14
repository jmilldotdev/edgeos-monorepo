"""Payment confirmation email helpers.

Extracted from ``app/api/payment/router.py`` so the pending-payment sweeper
(and any future cross-cutting service) can import these functions at
module-load time without creating a circular dependency with the web layer.

Public API:
  - ``send_payment_confirmed_email_best_effort`` — best-effort wrapper used by
    route handlers and background jobs.  Swallows all exceptions and logs them.
  - ``_send_payment_confirmed_email`` — inner sender; exposed so callers that
    want to track email failures themselves can catch exceptions directly.

Internal helpers (module-private, prefixed with ``_``):
  - ``_build_payment_email_products``
  - ``_build_payment_email_attendees``
  - ``_build_payment_confirmed_context``
  - ``_build_payment_checkin_qrs``
"""

from __future__ import annotations

import uuid

from loguru import logger
from sqlmodel import Session, func, select

from app.api.attendee.models import AttendeeProducts
from app.api.human.models import Humans
from app.api.payment.models import Payments
from app.api.product.models import Products
from app.services.checkin_qr import generate_checkin_qr_url
from app.services.email import (
    CheckInQrItem,
    EmailAttachment,
    PaymentAttendeeItem,
    PaymentConfirmedContext,
    PaymentProductItem,
    compute_order_summary,
    get_email_service,
)


def _build_payment_email_products(payment: Payments) -> list[PaymentProductItem]:
    return [
        PaymentProductItem(
            name=pp.product_name,
            price=float(pp.product_price),
            quantity=pp.quantity,
        )
        for pp in payment.products_snapshot
    ]


def _build_payment_email_attendees(
    payment: Payments,
) -> list[PaymentAttendeeItem] | None:
    if not payment.products_snapshot:
        return None

    attendees_by_id: dict[uuid.UUID, PaymentAttendeeItem] = {}

    for product_snapshot in payment.products_snapshot:
        attendee = product_snapshot.attendee
        attendee_id = product_snapshot.attendee_id
        if attendee_id is None:
            continue

        if attendee_id not in attendees_by_id:
            attendees_by_id[attendee_id] = PaymentAttendeeItem(
                name=(attendee.name if attendee else None)
                or product_snapshot.attendee_name
                or "Attendee",
                category=(attendee.category if attendee else None) or "attendee",
                products=[],
            )

        attendees_by_id[attendee_id].products = [
            *(attendees_by_id[attendee_id].products or []),
            PaymentProductItem(
                name=product_snapshot.product_name,
                price=float(product_snapshot.product_price),
                quantity=product_snapshot.quantity,
            ),
        ]

    return list(attendees_by_id.values()) or None


def _build_payment_checkin_qrs(
    db_session: Session,
    payment: Payments,
    buyer_name: str,
) -> list[CheckInQrItem] | None:
    """QR codes for the scannable products this payment bought.

    Tickets are left out: their QR goes out with the scheduled check-in pass,
    whose timing each flow chooses. A product handed over at a desk (merch,
    parking...) is usable right away, so its QR travels with the receipt.
    """
    line_ids = [line.id for line in payment.products_snapshot]
    if not line_ids:
        return None
    line_order = {line_id: index for index, line_id in enumerate(line_ids)}
    units = db_session.exec(
        select(AttendeeProducts)
        .join(Products, AttendeeProducts.product_id == Products.id)  # type: ignore[arg-type]
        .where(
            AttendeeProducts.payment_product_id.in_(line_ids),  # type: ignore[union-attr]
            AttendeeProducts.revoked_at.is_(None),  # type: ignore[union-attr]
            Products.requires_check_in.is_(True),  # type: ignore[union-attr]
            func.lower(AttendeeProducts.product_category_snapshot) != "ticket",
        )
    ).all()
    units = sorted(
        units,
        key=lambda unit: (
            line_order[unit.payment_product_id],  # type: ignore[index]
            unit.unit_index or 0,
        ),
    )

    qrs: list[CheckInQrItem] = []
    for unit in units:
        try:
            qr_url = generate_checkin_qr_url(unit.check_in_code)
        except Exception:
            # The code alone still works at the desk; never lose the receipt
            # over an image upload.
            logger.exception(
                "Failed to host check-in QR for unit {} of payment {}",
                unit.id,
                payment.id,
            )
            qr_url = None
        qrs.append(
            CheckInQrItem(
                attendee_name=unit.attendee.name if unit.attendee else buyer_name,
                product_name=unit.product.name,
                check_in_code=unit.check_in_code,
                qr_url=qr_url,
            )
        )
    return qrs or None


def _build_payment_confirmed_context(
    payment: Payments,
    popup_name: str,
    first_name: str,
    portal_url: str | None,
    checkin_qrs: list[CheckInQrItem] | None = None,
) -> PaymentConfirmedContext:
    products = _build_payment_email_products(payment)
    attendees = _build_payment_email_attendees(payment)

    original_amount = None
    if payment.discount_value and payment.discount_value > 0:
        original_amount = sum(
            float(pp.product_price) * pp.quantity for pp in payment.products_snapshot
        )

    return PaymentConfirmedContext(
        first_name=first_name,
        popup_name=popup_name,
        payment_id=str(payment.id),
        amount=float(payment.amount),
        currency=payment.currency,
        products=products if products else None,
        discount_value=int(payment.discount_value) if payment.discount_value else None,
        original_amount=original_amount,
        attendees=attendees,
        order_summary=compute_order_summary(payment)
        if payment.products_snapshot
        else None,
        portal_url=portal_url,
        checkin_qrs=checkin_qrs,
    )


def _resolve_payment_buyer(
    payment: Payments, db_session: Session | None = None
) -> Humans | None:
    """Resolve the buyer snapshot first, retaining legacy attendee fallback."""
    if payment.buyer_human_id is not None and db_session is not None:
        human = db_session.get(Humans, payment.buyer_human_id)
        if human is not None:
            return human
    if payment.application is not None and payment.application.human is not None:
        return payment.application.human
    if payment.products_snapshot:
        attendee = payment.products_snapshot[0].attendee
        if attendee is not None:
            return attendee.human
    return None


async def _send_payment_confirmed_email(payment, db_session=None) -> None:
    """Send payment confirmation email.

    If the popup has invoice details configured (company name, address, email),
    an invoice PDF is generated and attached to the email.

    Branches on payment.application_id:
    - application-based: resolve human via payment.application.human.
    - direct-sale: resolve human via the attendee in the first product snapshot,
      and popup via payment.popup.
    """
    payment_model: Payments = payment

    if payment_model.application_id is not None:
        # Application-based payment (existing flow)
        application = payment_model.application
        popup = application.popup if application else None
    else:
        # Direct-sale payment: no application. Human comes from the attendee
        # linked to the first product snapshot (direct-sale only ever has one
        # attendee per payment — the buyer).
        popup = payment_model.popup
    human = _resolve_payment_buyer(payment_model, db_session)

    if popup is None:
        logger.warning(
            f"Cannot send payment confirmed email: popup missing for payment {payment.id}"
        )
        return
    tenant = popup.tenant

    if not human or not human.email:
        logger.warning(
            f"Cannot send payment confirmed email: no human email for payment {payment.id}"
        )
        return

    # Generate invoice PDF attachment if popup has invoice details configured
    attachments: list[EmailAttachment] | None = None
    popup_has_invoice = (
        popup.invoice_company_name
        and popup.invoice_company_address
        and popup.invoice_company_email
    )
    if popup_has_invoice:
        try:
            from app.core.invoice import generate_invoice_pdf

            client_name = f"{human.first_name or ''} {human.last_name or ''}".strip()

            pdf_bytes = generate_invoice_pdf(
                payment=payment_model,
                client_name=client_name or "N/A",
                invoice_company_name=popup.invoice_company_name,
                invoice_company_address=popup.invoice_company_address,
                invoice_company_email=popup.invoice_company_email,
                header_image_url=popup.image_url,
            )
            attachments = [
                EmailAttachment(
                    filename=f"invoice-{payment_model.id}.pdf",
                    content=pdf_bytes,
                    mime_type="application/pdf",
                )
            ]
            logger.info(f"Invoice PDF generated for payment {payment_model.id}")
        except Exception as e:
            logger.error(
                f"Failed to generate invoice PDF for payment {payment_model.id}: {e}"
            )
            # Continue sending email without attachment

    email_service = get_email_service()

    from app.api.tenant.utils import get_portal_url

    portal_url = get_portal_url(tenant)
    session = db_session or Session.object_session(payment_model)
    context = _build_payment_confirmed_context(
        payment_model,
        popup_name=popup.name,
        first_name=human.first_name or "",
        portal_url=portal_url,
        checkin_qrs=_build_payment_checkin_qrs(
            session, payment_model, human.display_name
        )
        if session is not None
        else None,
    )

    await email_service.send_payment_confirmed(
        to=human.email,
        subject=f"Payment Confirmed for {popup.name}",
        context=context,
        from_address=tenant.sender_email,
        from_name=tenant.sender_name,
        popup_id=popup.id,
        sales_flow_id=payment.sales_flow_id,
        db_session=db_session,
        attachments=attachments,
    )
    logger.info(
        f"Payment confirmed email sent to {human.email} for payment {payment.id}"
    )


async def send_payment_confirmed_email_best_effort(payment, db_session=None) -> None:
    """Send payment confirmation email, swallowing all errors.

    Intended for use in webhook handlers and background jobs where a failed
    email must never abort payment processing.  Exceptions are logged but not
    re-raised.

    Callers that need to TRACK email failures (e.g. the sweeper) should call
    ``_send_payment_confirmed_email`` directly and wrap it in their own
    ``try/except``.
    """
    try:
        await _send_payment_confirmed_email(payment, db_session=db_session)
    except Exception:
        logger.exception(
            "Failed to send payment confirmation email payment_id={}",
            getattr(payment, "id", ""),
        )
