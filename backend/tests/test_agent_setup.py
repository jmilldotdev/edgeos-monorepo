"""Consumer-visible ownership, consent, context, and handoff security boundaries."""

import asyncio
import importlib
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.api.agent.desktop import native_hash
from app.api.agent.schemas import Acknowledge, Draft, SaveConsent, SaveDraft
from app.api.agent.service import (
    agent_view,
    ownership_key,
    safe_url,
    user_profile,
    verify_owner,
)


def human():
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="owner@example.com"
    )


def test_owner_requires_verified_human_not_matching_email_alone():
    owner = human()
    tenant = {
        "id": "hosted",
        "email": owner.email,
        "edgeosAttendeeId": str(uuid.uuid4()),
    }
    with pytest.raises(HTTPException) as caught:
        verify_owner(tenant, owner)
    assert caught.value.status_code == 409
    tenant["edgeosAttendeeId"] = str(owner.id)
    assert verify_owner(tenant, owner) == tenant
    other_tenant = SimpleNamespace(id=owner.id, tenant_id=uuid.uuid4())
    assert ownership_key(owner) != ownership_key(other_tenant)


def test_client_cannot_override_owner_or_cp_tenant():
    with pytest.raises(ValidationError):
        SaveDraft.model_validate(
            {"revision": 0, "draft": {}, "tenant_id": str(uuid.uuid4())}
        )
    with pytest.raises(ValidationError):
        SaveDraft.model_validate({"revision": 0, "draft": {"cp_tenant_id": "another"}})


def test_consent_choices_are_explicit_and_never_coerced():
    base = {
        "revision": 0,
        "briefVersion": "av2-consent-draft-2026-09-24",
        "research": True,
    }
    with pytest.raises(ValidationError):
        SaveConsent.model_validate(base)
    with pytest.raises(ValidationError):
        SaveConsent.model_validate({**base, "training": "false"})
    assert (
        SaveConsent.model_validate(
            {**base, "research": False, "training": False}
        ).research
        is False
    )


def test_context_preserves_selected_intentions_and_recipient_boundaries():
    draft = Draft.model_validate(
        {
            "intentions": [
                {
                    "id": "a",
                    "category": "build",
                    "text": "Build a garden",
                    "kept": True,
                },
                {
                    "id": "b",
                    "category": "meet",
                    "text": "Discarded goal",
                    "kept": False,
                },
            ],
            "offers": [{"id": "c", "title": "Seeds", "detail": "Share seeds"}],
            "answers": {"When": ["Mornings"]},
        }
    )
    context = user_profile(draft)
    assert "Build a garden" in context
    assert "Discarded goal" not in context
    assert "When: Mornings" in context
    assert "Do not allocate offers automatically" in context
    draft.profile.whatYouDo = "x" * 12000
    with pytest.raises(HTTPException) as caught:
        user_profile(draft)
    assert caught.value.status_code == 400


def test_ai_dossier_can_exceed_short_bio_limit_without_bypassing_total_context_budget():
    dossier = "I build community tools and offer practical design feedback. " * 60
    draft = Draft.model_validate({"profile": {"whatYouDo": dossier}})
    assert dossier in user_profile(draft)
    draft.sources = Draft.model_validate(
        {
            "sources": [
                {
                    "id": "more-context",
                    "method": "ai",
                    "label": "Additional background",
                    "text": "x" * 9000,
                    "words": 1,
                }
            ]
        }
    ).sources
    with pytest.raises(HTTPException) as caught:
        user_profile(draft)
    assert caught.value.status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.com",
        "https://example.com/?token=secret",
        "https://example.com/#secret",
        "http://remote.example.com",
        "javascript:alert(1)",
    ],
)
def test_credential_or_insecure_connection_urls_are_not_exposed(url):
    assert safe_url(url) is None


def test_ready_requires_actual_oauth_connection_not_just_live_tenant():
    tenant = {
        "id": "hosted",
        "status": "live",
        "connection": {
            "url": "https://gateway.example.com",
            "auth": "oauth",
            "profile": "default",
            "protocol": "hermes-jsonrpc-v1",
            "ready": False,
        },
    }
    assert agent_view(tenant)["dashboardUrl"] is None
    tenant["connection"]["ready"] = True
    assert agent_view(tenant)["status"] == "ready"
    tenant["connection"]["auth"] = "token"
    assert agent_view(tenant)["dashboardUrl"] is None


def test_browser_cannot_exchange_native_credential():
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"origin", b"https://portal.example.com"),
                (b"authorization", b"Bearer " + b"a" * 43),
            ],
        }
    )
    with pytest.raises(HTTPException) as caught:
        native_hash(request)
    assert caught.value.status_code == 403


def test_connected_ack_requires_default_profile_without_error():
    with pytest.raises(ValidationError):
        Acknowledge(status="connected", desktopVersion="1")
    with pytest.raises(ValidationError):
        Acknowledge(
            status="connected",
            desktopVersion="1",
            profile="default",
            code="chat_failed",
        )


def test_telegram_rejects_changed_account_before_host_approval(monkeypatch):
    routes = importlib.import_module("app.api.agent.router")

    async def owned(_):
        return {"id": "hosted"}, {}

    async def pending(_):
        return [{"code": "123", "userId": "999"}]

    monkeypatch.setattr(routes, "owned_telegram", owned)
    monkeypatch.setattr(routes, "pending_for", pending)
    payload = b'{"action":"approve","code":"123","userId":"123456","confirmed":true}'

    async def receive():
        return {"type": "http.request", "body": payload}

    request = Request({"type": "http", "headers": []}, receive)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes.telegram_action(request, human()))
    assert caught.value.status_code == 409


def test_invalid_bot_token_is_not_echoed_in_error():
    routes = importlib.import_module("app.api.agent.router")
    secret = "do-not-echo-this-bot-secret"

    async def receive():
        return {
            "type": "http.request",
            "body": ('{"action":"attach","token":"' + secret + '"}').encode(),
        }

    request = Request({"type": "http", "headers": []}, receive)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes.telegram_action(request, human()))
    assert caught.value.status_code == 422
    assert secret not in str(caught.value.detail)


def test_qr_status_never_exposes_provider_credentials():
    from app.api.agent.telegram_onboarding import public_status

    status = public_status(
        {
            "status": "ready",
            "expires_at": "2026-09-29T12:00:00Z",
            "owner_user_id": 123,
            "bot_username": "example_bot",
            "bot_token": "private",
            "poll_token": "private",
            "deep_link": "https://t.me/NousHostedHermesBot?start=pair_123",
        }
    )
    assert status["owner_user_id"] == "123"
    assert "bot_token" not in status
    assert "poll_token" not in status


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/newbot/x",
        "https://secret@t.me/newbot/x",
        "https://t.me/ordinary_link",
        "tg://resolve?domain=arbitrary",
    ],
)
def test_qr_link_cannot_redirect_to_arbitrary_destination(url):
    from app.api.agent.telegram_onboarding import telegram_link

    with pytest.raises(HTTPException) as caught:
        telegram_link(url)
    assert caught.value.status_code == 502


@pytest.mark.parametrize(
    "current",
    [
        None,
        {"scopeResearch": False, "withdrawnAt": None},
        {"scopeResearch": True, "withdrawnAt": "2026-09-29T12:00:00Z"},
    ],
)
def test_already_effective_nonparticipation_does_not_retry_withdrawal(
    monkeypatch, current
):
    routes = importlib.import_module("app.api.agent.router")

    async def unexpected(*_args, **_kwargs):
        pytest.fail("Already-effective nonparticipation must not call withdrawal")

    monkeypatch.setattr(routes, "cp", unexpected)
    asyncio.run(
        routes.synchronize_consent(
            SimpleNamespace(consent={"research": False}),
            {"id": "hosted", "consent": current},
            human(),
        )
    )


def test_lost_withdrawal_response_clears_pending_only_after_authoritative_reconciliation(
    monkeypatch,
):
    from app.api.agent.schemas import Revision

    routes = importlib.import_module("app.api.agent.router")
    row = SimpleNamespace(
        revision=7,
        consent={"research": False},
        consent_pending=True,
        context_pending=False,
        draft={},
        telegram_pairing_id=None,
    )
    tenant = {"id": "hosted", "consent": {"scopeResearch": True, "withdrawnAt": None}}

    async def ambiguous(*_args, **_kwargs):
        tenant["consent"]["withdrawnAt"] = "2026-09-29T12:00:00Z"
        raise HTTPException(502, "Response lost after commit")

    async def discover_after_commit(_):
        return tenant

    monkeypatch.setattr(routes, "setup", lambda *args: row)
    monkeypatch.setattr(routes, "changed", lambda *args: None)
    monkeypatch.setattr(routes, "cp", ambiguous)
    monkeypatch.setattr(routes, "discover", discover_after_commit)
    result = asyncio.run(routes.sync_agent(Revision(revision=7), None, human()))
    assert result["contextPending"] is False
    assert result["consent"]["research"] is False
    assert result["hostError"] is None


def test_failed_withdrawal_stays_pending_when_host_still_grants(monkeypatch):
    routes = importlib.import_module("app.api.agent.router")
    tenant = {"id": "hosted", "consent": {"scopeResearch": True, "withdrawnAt": None}}

    async def unavailable(*_args, **_kwargs):
        raise HTTPException(502, "Host unavailable")

    async def unchanged(_):
        return tenant

    monkeypatch.setattr(routes, "cp", unavailable)
    monkeypatch.setattr(routes, "discover", unchanged)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            routes.synchronize_consent(
                SimpleNamespace(consent={"research": False}), tenant, human()
            )
        )
    assert caught.value.status_code == 502


def test_real_pending_age_contract_keeps_live_account_and_excludes_expired(monkeypatch):
    routes = importlib.import_module("app.api.agent.router")

    async def pending(*_args, **_kwargs):
        return {
            "pending": [
                {
                    "code": "12345678",
                    "platform": "telegram",
                    "userId": "123",
                    "userName": "Owner",
                    "ageMinutes": 2.5,
                },
                {
                    "code": "87654321",
                    "platform": "telegram",
                    "userId": "456",
                    "ageMinutes": 60,
                },
                {
                    "code": "11111111",
                    "platform": "discord",
                    "userId": "789",
                    "ageMinutes": 1,
                },
            ]
        }

    monkeypatch.setattr(routes, "cp", pending)
    assert asyncio.run(routes.pending_for("/tenants/hosted")) == [
        {
            "code": "12345678",
            "platform": "telegram",
            "userId": "123",
            "userName": "Owner",
            "expiresAt": None,
            "ageMinutes": 2.5,
        }
    ]


def test_competing_setup_write_returns_conflict_without_waiting(
    test_engine, db, tenant_a
):
    from sqlalchemy import text
    from sqlmodel import Session

    from app.api.agent.models import AgentSetup
    from app.api.human.models import Humans

    routes = importlib.import_module("app.api.agent.router")
    owner = Humans(
        tenant_id=tenant_a.id, email=f"agent-lock-{uuid.uuid4().hex}@example.com"
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)
    row = AgentSetup(tenant_id=tenant_a.id, human_id=owner.id)
    db.add(row)
    db.commit()
    try:
        with Session(test_engine) as first, Session(test_engine) as second:
            routes.setup(first, owner, True)
            # A regressed blocking FOR UPDATE is cancelled instead of hanging
            # this test; statement cancellation is not a lock-conflict response.
            second.exec(text("SET statement_timeout = '1s'"))
            with pytest.raises(HTTPException) as caught:
                routes.setup(second, owner, True)
            assert caught.value.status_code == 409
            first.rollback()
            assert routes.setup(second, owner, True).id == row.id
    finally:
        db.delete(row)
        db.delete(owner)
        db.commit()


@pytest.fixture
def reset_setup(db, tenant_a, tenant_b):
    from datetime import timedelta

    from sqlmodel import select

    from app.api.agent.models import (
        AgentConsentEvent,
        AgentDesktopAttempt,
        AgentSetup,
        now,
    )
    from app.api.human.models import Humans

    owners = [
        Humans(
            tenant_id=tenant.id,
            email=f"agent-reset-{uuid.uuid4().hex}@example.com",
        )
        for tenant in (tenant_a, tenant_b)
    ]
    for owner in owners:
        db.add(owner)
    db.commit()
    rows = [
        AgentSetup(
            tenant_id=owner.tenant_id,
            human_id=owner.id,
            revision=4,
            draft=Draft(
                profile={"name": "Alice", "whatYouDo": "Build gardens"},
                answers={"When": ["Morning"]},
                questionsDone=True,
            ).model_dump(),
            consent={
                "research": True,
                "training": True,
                "briefVersion": "previous-brief",
                "acceptedAt": now().isoformat(),
            },
            context_pending=True,
            cp_tenant_id=f"hosted-{owner.id}",
            telegram_pairing_id=f"pair-{owner.id}",
        )
        for owner in owners
    ]
    for row in rows:
        db.add(row)
    db.commit()
    original_event = AgentConsentEvent(
        setup_id=rows[0].id, revision=4, consent=rows[0].consent
    )
    attempt = AgentDesktopAttempt(
        setup_id=rows[0].id,
        cp_tenant_id=rows[0].cp_tenant_id,
        gateway_url="https://gateway.example.com",
        label="Existing agent",
        exchange_hash="reset-test-" + uuid.uuid4().hex,
        expires_at=now() + timedelta(minutes=10),
    )
    db.add(original_event)
    db.add(attempt)
    db.commit()
    try:
        yield owners, rows, original_event, attempt
    finally:
        db.rollback()
        for model in (AgentDesktopAttempt, AgentConsentEvent):
            for record in db.exec(
                select(model).where(model.setup_id.in_([row.id for row in rows]))
            ).all():
                db.delete(record)
        db.commit()
        for row in rows:
            db.delete(row)
        db.commit()
        for owner in owners:
            db.delete(owner)
        db.commit()


def test_reset_clears_answers_and_withdraws_without_erasing_runtime_or_connections(
    monkeypatch, db, reset_setup
):
    from sqlmodel import select

    from app.api.agent.models import AgentConsentEvent
    from app.api.agent.schemas import BRIEF_VERSION, Reset, Revision

    routes = importlib.import_module("app.api.agent.router")
    owners, rows, original_event, attempt = reset_setup
    owner, row = owners[0], rows[0]
    identity = ownership_key(owner)
    tenant = {
        "id": row.cp_tenant_id,
        "status": "live",
        "userProfile": "Existing runtime context",
        "telegram": {"ownerUserId": "123"},
        "consent": {"scopeResearch": True, "scopeTraining": True},
    }

    async def discover(_):
        return tenant

    async def withdraw(path, method, _payload):
        assert (path, method) == (
            f"/tenants/{row.cp_tenant_id}/consent/withdraw",
            "POST",
        )
        tenant["consent"] = {"scopeResearch": False, "scopeTraining": False}

    monkeypatch.setattr(routes, "discover", discover)
    monkeypatch.setattr(routes, "cp", withdraw)
    result = asyncio.run(
        routes.reset_agent(Reset(revision=4, confirmed=True), db, owner)
    )
    assert result["revision"] == 5
    assert result["draft"] == Draft().model_dump()
    assert result["consent"] == {
        "research": False,
        "training": False,
        "briefVersion": BRIEF_VERSION,
        "acceptedAt": None,
    }
    assert result["agent"]["id"] == tenant["id"]
    assert result["contextPending"] is False
    assert result["hostError"] is None
    # A later sync must not replace the retained profile with the cleared draft.
    asyncio.run(routes.sync_agent(Revision(revision=5), db, owner))
    assert tenant["userProfile"] == "Existing runtime context"
    assert tenant["telegram"] == {"ownerUserId": "123"}
    assert ownership_key(owner) == identity
    db.refresh(row)
    db.refresh(attempt)
    assert row.cp_tenant_id == tenant["id"]
    assert result["telegramPairingId"] == row.telegram_pairing_id
    assert attempt.status == "pending"
    assert attempt.exchange_hash is not None
    events = db.exec(
        select(AgentConsentEvent)
        .where(AgentConsentEvent.setup_id == row.id)
        .order_by(AgentConsentEvent.revision)
    ).all()
    assert [(event.revision, event.consent["research"]) for event in events] == [
        (4, True),
        (5, False),
    ]
    assert events[0].id == original_event.id
    db.refresh(rows[1])
    assert rows[1].revision == 4
    assert rows[1].draft["profile"]["name"] == "Alice"
    assert rows[1].consent["research"] is True


@pytest.mark.parametrize("failure", ["discover", "withdraw", "lost_response"])
def test_reset_persists_withdrawal_and_retries_without_blank_profile(
    monkeypatch, db, reset_setup, failure
):
    from app.api.agent.schemas import Reset, Revision

    routes = importlib.import_module("app.api.agent.router")
    owners, rows, _, _ = reset_setup
    row = rows[0]
    tenant = {"id": row.cp_tenant_id, "consent": {"scopeResearch": True}}
    available = False

    async def discover(_):
        if not available and failure == "discover":
            raise HTTPException(502, "Host unavailable")
        return tenant

    async def withdraw(path, method, _payload):
        assert path.endswith("/consent/withdraw")
        assert method == "POST"
        if available or failure == "lost_response":
            tenant["consent"] = {"scopeResearch": False}
        if not available:
            raise HTTPException(502, "Host unavailable")

    monkeypatch.setattr(routes, "discover", discover)
    monkeypatch.setattr(routes, "cp", withdraw)
    result = asyncio.run(
        routes.reset_agent(Reset(revision=4, confirmed=True), db, owners[0])
    )
    reconciled = failure == "lost_response"
    assert result["contextPending"] is (not reconciled)
    assert result["hostError"] == (None if reconciled else "Host unavailable")
    db.refresh(row)
    assert row.revision == 5
    assert row.draft == Draft().model_dump()
    assert row.consent["acceptedAt"] is None
    assert row.context_pending is False
    assert row.consent_pending is (not reconciled)
    available = True
    retried = asyncio.run(routes.sync_agent(Revision(revision=5), db, owners[0]))
    assert retried["contextPending"] is False
    assert tenant["consent"]["scopeResearch"] is False


def test_reset_stale_revision_does_not_change_answers_or_consent(
    monkeypatch, db, reset_setup
):
    from app.api.agent.schemas import Reset

    routes = importlib.import_module("app.api.agent.router")
    owners, rows, _, _ = reset_setup

    async def unexpected(_):
        pytest.fail("Stale reset must not contact the host")

    monkeypatch.setattr(routes, "discover", unexpected)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            routes.reset_agent(Reset(revision=3, confirmed=True), db, owners[0])
        )
    assert caught.value.status_code == 409
    db.rollback()
    db.refresh(rows[0])
    assert rows[0].revision == 4
    assert rows[0].draft["profile"]["name"] == "Alice"
    assert rows[0].consent["research"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"revision": 4},
        {"revision": 4, "confirmed": False},
        {"revision": 4, "confirmed": "true"},
        {"revision": 4, "confirmed": 1},
        {"revision": "4", "confirmed": True},
        {"revision": 4, "confirmed": True, "human_id": "another"},
        {"revision": 4, "confirmed": True, "tenant_id": "another"},
    ],
)
def test_reset_rejects_implicit_confirmation_and_owner_overrides(payload):
    from app.api.agent.schemas import Reset

    with pytest.raises(ValidationError):
        Reset.model_validate(payload)


def test_reset_without_runtime_keeps_registration_and_can_restart(
    monkeypatch, db, reset_setup
):
    from app.api.agent.schemas import Reset, SaveDraft
    from app.api.human.models import Humans

    routes = importlib.import_module("app.api.agent.router")
    owners, rows, _, _ = reset_setup
    row = rows[0]
    row.cp_tenant_id = None
    db.add(row)
    db.commit()

    async def absent(_):
        return None

    async def unexpected(*_args):
        pytest.fail("Reset without a runtime must not provision or delete anything")

    monkeypatch.setattr(routes, "discover", absent)
    monkeypatch.setattr(routes, "cp", unexpected)
    result = asyncio.run(
        routes.reset_agent(Reset(revision=4, confirmed=True), db, owners[0])
    )
    assert result["agent"] is None
    assert result["draft"]["answers"] == {}
    assert result["consent"]["acceptedAt"] is None
    assert db.get(Humans, owners[0].id).tenant_id == owners[0].tenant_id
    restarted = asyncio.run(
        routes.save_draft(
            SaveDraft(
                revision=result["revision"],
                draft=Draft(profile={"name": "New answer"}),
            ),
            db,
            owners[0],
        )
    )
    assert restarted["draft"]["profile"]["name"] == "New answer"
    assert restarted["revision"] == result["revision"] + 1


def test_reset_requires_tenant_owned_human(db):
    from app.api.agent.schemas import Reset

    routes = importlib.import_module("app.api.agent.router")
    owner = human()
    owner.tenant_id = None
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes.reset_agent(Reset(revision=0, confirmed=True), db, owner))
    assert caught.value.status_code == 403
