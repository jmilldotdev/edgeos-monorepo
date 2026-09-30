import math
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import select

from app.api.agent.extraction import extract_suggestions
from app.api.agent.models import AgentConsentEvent, AgentSetup, now
from app.api.agent.schemas import (
    BRIEF_VERSION,
    Draft,
    ExtractDraft,
    ExtractionSuggestions,
    Reset,
    Revision,
    SaveConsent,
    SaveDraft,
    TelegramAction,
)
from app.api.agent.service import (
    agent_view,
    cp,
    discover,
    ownership_key,
    tenant_path,
    user_profile,
    verify_owner,
)
from app.core.config import settings
from app.core.dependencies.users import CurrentHuman, SessionDep


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(no_store)])


def locked(db, query):
    """Never block this async worker behind a transaction awaiting the host."""
    try:
        return db.exec(
            query.with_for_update(nowait=True).execution_options(populate_existing=True)
        )
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) != "55P03":
            raise
        db.rollback()
        raise HTTPException(
            409,
            "Another agent operation is in progress. Wait for it to finish and refresh.",
        ) from None


def setup(db, human, lock=False):
    if not human.tenant_id:
        raise HTTPException(403, "A tenant-owned human session is required.")
    query = select(AgentSetup).where(
        AgentSetup.human_id == human.id, AgentSetup.tenant_id == human.tenant_id
    )
    row = (locked(db, query) if lock else db.exec(query)).first()
    if row is None:
        row = AgentSetup(
            human_id=human.id,
            tenant_id=human.tenant_id,
            draft=Draft().model_dump(),
            consent={
                "research": False,
                "training": False,
                "briefVersion": BRIEF_VERSION,
                "acceptedAt": None,
            },
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        row = (locked(db, query) if lock else db.exec(query)).one()
    return row


def revision(row, expected):
    if row.revision != expected:
        raise HTTPException(
            409, "Your setup changed in another window. Refresh before saving."
        )


def changed(db, row):
    row.revision += 1
    row.updated_at = now()
    db.add(row)
    db.commit()
    db.refresh(row)


def view(row, tenant=None, host_error=None):
    return {
        "revision": row.revision,
        "draft": row.draft,
        "consent": row.consent,
        "agent": agent_view(tenant),
        "contextPending": row.context_pending or row.consent_pending,
        "hostError": host_error,
        "telegramPairingId": row.telegram_pairing_id,
    }


async def state(row, human):
    try:
        return view(row, await discover(human))
    except HTTPException as exc:
        return view(row, host_error=exc.detail)


@router.get("")
async def get_agent(db: SessionDep, human: CurrentHuman, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await state(setup(db, human), human)


@router.put("")
async def save_draft(body: SaveDraft, db: SessionDep, human: CurrentHuman):
    user_profile(body.draft)
    row = setup(db, human, True)
    revision(row, body.revision)
    row.draft = body.draft.model_dump()
    row.context_pending = True
    changed(db, row)
    return await state(row, human)


@router.post("/extract", response_model=ExtractionSuggestions)
async def extract_agent(body: ExtractDraft, db: SessionDep, human: CurrentHuman):
    if not human.tenant_id:
        raise HTTPException(403, "A tenant-owned human session is required.")
    row = db.exec(
        select(AgentSetup).where(
            AgentSetup.human_id == human.id, AgentSetup.tenant_id == human.tenant_id
        )
    ).first()
    if row is None or row.consent.get("research") is not True:
        raise HTTPException(
            403, "Accept research consent before extracting suggestions."
        )
    user_profile(body.draft)
    return await extract_suggestions(body.draft)


@router.put("/consent")
async def save_consent(body: SaveConsent, db: SessionDep, human: CurrentHuman):
    row = setup(db, human, True)
    revision(row, body.revision)
    row.consent = {
        "research": body.research,
        "training": body.training,
        "briefVersion": body.briefVersion,
        "acceptedAt": now().isoformat(),
    }
    row.consent_pending = True
    db.add(
        AgentConsentEvent(
            setup_id=row.id, revision=row.revision + 1, consent=row.consent
        )
    )
    changed(db, row)
    return await synchronize_saved_consent(db, row, human)


@router.post("/reset")
async def reset_agent(body: Reset, db: SessionDep, human: CurrentHuman):
    row = setup(db, human, True)
    revision(row, body.revision)
    row.draft = Draft().model_dump()
    row.consent = {
        "research": False,
        "training": False,
        "briefVersion": BRIEF_VERSION,
        "acceptedAt": None,
    }
    # Reset local answers without erasing the existing runtime's profile.
    row.context_pending = False
    row.consent_pending = True
    db.add(
        AgentConsentEvent(
            setup_id=row.id, revision=row.revision + 1, consent=row.consent
        )
    )
    changed(db, row)
    return await synchronize_saved_consent(db, row, human)


async def synchronize_saved_consent(db, row, human):
    # Serialize host consent transitions too. Reload after the durable save so a
    # newer withdrawal cannot be overwritten by an older in-flight grant.
    row = locked(db, select(AgentSetup).where(AgentSetup.id == row.id)).one()
    # Withdrawal must be attempted immediately, not deferred until a later context edit.
    try:
        tenant = await discover(human)
        if tenant:
            await synchronize_consent(row, tenant, human)
            row.consent_pending = False
            db.add(row)
            db.commit()
        return view(row, tenant)
    except HTTPException as exc:
        return view(row, host_error=exc.detail)


def consent_synchronized(desired, tenant):
    if "consent" not in tenant:
        return False
    current = tenant["consent"]
    if not desired.get("research"):
        return current is None or (
            isinstance(current, dict)
            and (
                bool(current.get("withdrawnAt"))
                or current.get("scopeResearch") is False
            )
        )
    return (
        isinstance(current, dict)
        and not current.get("withdrawnAt")
        and current.get("scopeResearch") is True
        and current.get("scopeTraining") is desired["training"]
        and current.get("briefVersion") == desired["briefVersion"]
    )


async def synchronize_consent(row, tenant, human):
    if consent_synchronized(row.consent, tenant):
        return
    path = tenant_path(tenant)
    consent = row.consent
    try:
        if consent.get("research"):
            await cp(
                path + "/consent",
                "POST",
                {
                    "consent_brief_sha": consent["briefVersion"],
                    "scope_research": True,
                    "scope_training": consent["training"],
                    "method": "onboarding_web",
                },
            )
        else:
            await cp(path + "/consent/withdraw", "POST", {"method": "onboarding_web"})
    except HTTPException:
        # A committed withdrawal/grant whose response was lost is still effective.
        latest = await discover(human)
        if latest and consent_synchronized(consent, latest):
            return
        raise


@router.post("/sync")
async def sync_agent(body: Revision, db: SessionDep, human: CurrentHuman):
    row = setup(db, human, True)
    revision(row, body.revision)
    tenant = await discover(human)
    if not tenant:
        raise HTTPException(409, "Create your agent before updating the host.")
    if row.consent_pending:
        await synchronize_consent(row, tenant, human)
        row.consent_pending = False
    if row.context_pending:
        await cp(
            tenant_path(tenant),
            "PATCH",
            {"userProfile": user_profile(Draft.model_validate(row.draft))},
        )
        row.context_pending = False
    changed(db, row)
    return await state(row, human)


@router.post("/provision")
async def provision(
    body: Revision, request: Request, db: SessionDep, human: CurrentHuman
):
    row = setup(db, human, True)
    revision(row, body.revision)
    tenant = await discover(human)
    draft = Draft.model_validate(row.draft)
    if not tenant and (
        not row.consent.get("research") or not draft.profile.whatYouDo.strip()
    ):
        raise HTTPException(
            400,
            "Record research consent and describe yourself before creating an agent.",
        )
    if not tenant:
        payload = {
            "email": human.email,
            "userProfile": user_profile(draft),
            "idempotencyKey": ownership_key(human),
            "edgeosBearerToken": request.headers["authorization"].split(" ", 1)[1],
            "edgeos_attendee_id": str(human.id),
            "consent_brief_sha": row.consent["briefVersion"],
            "scope_research": True,
            "scope_training": row.consent["training"],
        }
        if settings.AGENT_POPUP_ID:
            payload["popupId"] = settings.AGENT_POPUP_ID
        if settings.AGENT_INDEX_API_KEY:
            payload["indexApiKey"] = settings.AGENT_INDEX_API_KEY
        try:
            tenant = verify_owner(await cp("/tenants", "POST", payload), human)
        except HTTPException:
            # CP may have durably accepted a request whose response was lost.
            tenant = await discover(human)
            if not tenant:
                raise
        row.context_pending = False
        row.consent_pending = False
    elif tenant.get("status") in {"failed", "creating"}:
        tenant = verify_owner(
            await cp(
                tenant_path(tenant) + "/recover",
                "POST",
                {
                    "idempotencyKey": ownership_key(human),
                    "edgeos_attendee_id": str(human.id),
                    "edgeosBearerToken": request.headers["authorization"].split(" ", 1)[
                        1
                    ],
                    **(
                        {"indexApiKey": settings.AGENT_INDEX_API_KEY}
                        if settings.AGENT_INDEX_API_KEY
                        else {}
                    ),
                },
            ),
            human,
        )
    elif agent_view(tenant)["status"] == "failed":
        if tenant.get("provider") != "local":
            raise HTTPException(
                409,
                "The hosted runtime is unavailable. Contact the host administrator to restore it.",
            )
        await cp(tenant_path(tenant) + "/runtime/start", "POST", {})
    row.cp_tenant_id = tenant["id"]
    changed(db, row)
    return await state(row, human)


async def owned_telegram(human):
    tenant = await discover(human)
    if not tenant:
        raise HTTPException(409, "Create your agent before connecting Telegram.")
    integration = (tenant.get("integrations") or {}).get("telegram") or {}
    if integration.get("supported") is not True:
        raise HTTPException(409, "This host does not support Telegram.")
    return tenant, integration


async def pending_for(path):
    result = await cp(path + "/pairings/pending")
    if not result or not isinstance(result.get("pending"), list):
        raise HTTPException(502, "Could not read pending Telegram requests.")
    pending = []
    for item in result["pending"]:
        try:
            expires = None
            age = None
            if "expiresAt" in item:
                expires = datetime.fromisoformat(
                    item["expiresAt"].replace("Z", "+00:00")
                )
                if expires <= now():
                    continue
            else:
                # The runtime enforces expiry; age is approximate display data.
                age = item["ageMinutes"]
                if (
                    isinstance(age, bool)
                    or not isinstance(age, (int, float))
                    or not math.isfinite(age)
                    or not 0 <= age < 60
                ):
                    continue
            user_id = str(item["userId"])
            if item["platform"] == "telegram" and re.fullmatch(r"\d+", user_id):
                pending.append(
                    {
                        "code": item["code"],
                        "platform": "telegram",
                        "userId": user_id,
                        "userName": item.get("userName"),
                        "expiresAt": expires.isoformat() if expires else None,
                        "ageMinutes": age,
                    }
                )
        except (KeyError, ValueError, TypeError):
            continue
    return pending


@router.get("/telegram")
async def telegram_status(human: CurrentHuman, response: Response):
    response.headers["Cache-Control"] = "no-store"
    tenant, integration = await owned_telegram(human)
    username = tenant.get("telegramBotUsername")
    username = (
        username
        if isinstance(username, str) and re.fullmatch(r"[A-Za-z0-9_]{5,32}", username)
        else None
    )
    return {
        "supported": True,
        "attached": integration.get("attached") is True,
        "ready": integration.get("ready") is True,
        "state": integration.get("state", "unknown"),
        "botUsername": username,
        "botUrl": f"https://t.me/{username}" if username else None,
        "approvedUserIds": [
            i
            for i in tenant.get("approvedTelegramUsers", [])
            if isinstance(i, str) and re.fullmatch(r"\d+", i)
        ],
        "pending": await pending_for(tenant_path(tenant))
        if integration.get("ready")
        else [],
    }


@router.post("/telegram")
async def telegram_action(request: Request, human: CurrentHuman):
    # Parse explicitly so validation errors never echo a submitted bot credential.
    raw = await request.body()
    if len(raw) > 2048:
        raise HTTPException(413, "Telegram request is too large.")
    try:
        body = TypeAdapter(TelegramAction).validate_json(raw)
    except ValidationError:
        raise HTTPException(
            422, "Check Telegram details and explicitly confirm the account."
        ) from None
    tenant, _ = await owned_telegram(human)
    path = tenant_path(tenant)
    if body.action == "attach":
        await cp(path + "/telegram", "POST", {"telegramBotToken": body.token})
    elif body.action == "approve":
        pending = await pending_for(path)
        if not any(
            i["code"] == body.code and i["userId"] == body.userId for i in pending
        ):
            raise HTTPException(
                409,
                "This pairing request expired or changed. Refresh and confirm the account again.",
            )
        await cp(
            path + "/pairings/approve",
            "POST",
            {"code": body.code, "telegramUserId": body.userId},
        )
    else:
        await cp(path + "/pairings/revoke", "POST", {"telegramUserId": body.userId})
    return {"accepted": True}
