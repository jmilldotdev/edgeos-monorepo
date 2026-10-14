"""Product QR codes in the payment confirmed email."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.attendee.models import Attendees
from app.api.email_template.schemas import EmailTemplateType
from app.api.payment.crud import payments_crud
from app.services.email.service import EmailService
from app.services.email.templates import (
    TEMPLATE_TYPE_METADATA,
    CheckInQrItem,
    PaymentConfirmedContext,
)
from app.services.payment_notifications import (
    _build_payment_checkin_qrs,
    _send_payment_confirmed_email,
)
from tests.api.payment.test_product_unit_materialization import (
    _product,
    _purchase,
    _units,
)
from tests.test_checkin_pass_dispatch import _make_human

QR_TARGET = "app.services.payment_notifications.generate_checkin_qr_url"
EMAIL_TARGET = "app.services.payment_notifications.get_email_service"


def _qr_url(code: str) -> str:
    return f"https://cdn.test/{code}.png"


def _approved(db, popup, product, *, quantity, buyer, attendee=None):
    payment, _ = _purchase(db, popup, product, quantity=quantity, attendee=attendee)
    payment.buyer_human_id = buyer.id
    db.add(payment)
    db.commit()
    payments_crud.approve_payment(db, payment.id)
    db.refresh(payment)
    return payment


def test_scannable_products_get_one_qr_per_active_unit(db, popup_tenant_a, tenant_a):
    buyer = _make_human(db, tenant_a)
    shirt = _product(db, popup_tenant_a, category="merch", requires_check_in=True)
    payment = _approved(db, popup_tenant_a, shirt, quantity=3, buyer=buyer)
    first, revoked, third = _units(db, payment)
    revoked.revoked_at = datetime.now(UTC)
    db.add(revoked)
    db.commit()

    with patch(QR_TARGET, side_effect=_qr_url):
        qrs = _build_payment_checkin_qrs(db, payment, buyer.display_name)

    assert qrs == [
        CheckInQrItem(
            attendee_name=buyer.display_name,
            product_name=shirt.name,
            check_in_code=unit.check_in_code,
            qr_url=_qr_url(unit.check_in_code),
        )
        for unit in (first, third)
    ]


def test_tickets_and_products_without_check_in_get_no_qr(db, popup_tenant_a, tenant_a):
    buyer = _make_human(db, tenant_a)
    attendee = Attendees(
        tenant_id=tenant_a.id, popup_id=popup_tenant_a.id, name="Ticket holder"
    )
    db.add(attendee)
    db.flush()
    ticket = _product(db, popup_tenant_a, category="ticket", requires_check_in=True)
    lunch = _product(db, popup_tenant_a, category="merch", requires_check_in=False)
    ticket_payment = _approved(
        db, popup_tenant_a, ticket, quantity=1, buyer=buyer, attendee=attendee
    )
    lunch_payment = _approved(db, popup_tenant_a, lunch, quantity=1, buyer=buyer)
    assert _units(db, ticket_payment)

    with patch(QR_TARGET, side_effect=_qr_url) as qr:
        assert _build_payment_checkin_qrs(db, ticket_payment, "Buyer") is None
        assert _build_payment_checkin_qrs(db, lunch_payment, "Buyer") is None
    qr.assert_not_called()


def test_a_failed_qr_upload_still_sends_the_code(db, popup_tenant_a, tenant_a):
    buyer = _make_human(db, tenant_a)
    shirt = _product(db, popup_tenant_a, category="merch", requires_check_in=True)
    payment = _approved(db, popup_tenant_a, shirt, quantity=1, buyer=buyer)
    email_service = MagicMock()
    email_service.send_payment_confirmed = AsyncMock(return_value=True)

    with (
        patch(QR_TARGET, side_effect=RuntimeError("storage down")),
        patch(EMAIL_TARGET, return_value=email_service),
    ):
        asyncio.run(_send_payment_confirmed_email(payment, db_session=db))

    context = email_service.send_payment_confirmed.await_args.kwargs["context"]
    [qr] = context.checkin_qrs
    assert qr.check_in_code == _units(db, payment)[0].check_in_code
    assert qr.qr_url is None


def test_default_template_renders_the_product_qrs():
    context = PaymentConfirmedContext(
        first_name="Ada",
        popup_name="Demo",
        payment_id="payment-1",
        amount=20,
        currency="USD",
        checkin_qrs=[
            CheckInQrItem(
                attendee_name="Ada Lovelace",
                product_name="Event T-shirt",
                check_in_code="SHIRT001",
                qr_url="https://cdn.test/SHIRT001.png",
            ),
            CheckInQrItem(
                attendee_name="Ada Lovelace",
                product_name="Event T-shirt",
                check_in_code="SHIRT002",
            ),
        ],
    )

    html = EmailService().render_template(
        "payment/confirmed.html", context.model_dump(exclude_none=True)
    )

    assert "Your QR codes" in html
    assert 'src="https://cdn.test/SHIRT001.png"' in html
    assert "SHIRT001" in html and "SHIRT002" in html
    assert html.count("<img") == 1

    without = EmailService().render_template(
        "payment/confirmed.html",
        context.model_copy(update={"checkin_qrs": None}).model_dump(exclude_none=True),
    )
    assert "Your QR" not in without


def test_payment_confirmed_metadata_exposes_the_qr_variable():
    meta = next(
        meta
        for meta in TEMPLATE_TYPE_METADATA
        if meta["type"] == EmailTemplateType.PAYMENT_CONFIRMED
    )
    assert "checkin_qrs" in {variable["name"] for variable in meta["variables"]}
