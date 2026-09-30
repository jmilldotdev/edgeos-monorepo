import hashlib
import re
import secrets
from datetime import timedelta
from urllib.parse import quote, urlsplit

from fastapi import HTTPException, Request, Response
from sqlmodel import select

from app.api.agent.models import AgentDesktopAttempt, now
from app.api.agent.router import locked, router, setup
from app.api.agent.schemas import Acknowledge, Exchange
from app.api.agent.service import agent_view, cp, discover, safe_url, tenant_path
from app.core.config import settings
from app.core.dependencies.users import CurrentHuman, SessionDep


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def origin():
    value = safe_url(settings.AGENT_DESKTOP_PUBLIC_ORIGIN)
    if not value or urlsplit(value).path:
        raise HTTPException(
            503, "Configure the canonical Desktop handoff origin first."
        )
    return value


def native_hash(request):
    if "origin" in request.headers:
        raise HTTPException(403, "This endpoint accepts native Desktop handoffs only.")
    match = re.fullmatch(
        r"Bearer ([A-Za-z0-9_-]{43})", request.headers.get("authorization", "")
    )
    if not match:
        raise HTTPException(
            401, "The Desktop handoff credential is missing or invalid."
        )
    return digest(match[1])


def attempt_view(row):
    if not row:
        return None
    return {
        "id": str(row.id),
        "status": "expired"
        if row.status in {"pending", "opened"} and row.expires_at <= now()
        else row.status,
        "expiresAt": row.expires_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
        "code": row.code,
        "desktopVersion": row.desktop_version,
    }


@router.get("/desktop")
async def desktop_status(db: SessionDep, human: CurrentHuman, response: Response):
    response.headers["Cache-Control"] = "no-store"
    owner = setup(db, human)
    attempt = db.exec(
        select(AgentDesktopAttempt)
        .where(AgentDesktopAttempt.setup_id == owner.id)
        .order_by(AgentDesktopAttempt.created_at.desc())
    ).first()
    return {"attempt": attempt_view(attempt)}


@router.post("/desktop")
async def desktop_begin(db: SessionDep, human: CurrentHuman, response: Response):
    response.headers["Cache-Control"] = "no-store"
    public_origin = origin()
    owner = setup(db, human, True)
    tenant = await discover(human)
    agent = agent_view(tenant)
    if not agent or agent["status"] != "ready":
        raise HTTPException(
            409,
            "Start your agent and wait for its host to be ready before opening Desktop.",
        )
    for old in db.exec(
        select(AgentDesktopAttempt).where(
            AgentDesktopAttempt.setup_id == owner.id,
            AgentDesktopAttempt.status.in_(["pending", "opened"]),
        )
    ):
        old.status, old.code = "cancelled", "superseded"
        old.exchange_hash = old.ack_hash = None
        old.updated_at = now()
        db.add(old)
    token = secrets.token_urlsafe(32)
    attempt = AgentDesktopAttempt(
        setup_id=owner.id,
        cp_tenant_id=agent["id"],
        gateway_url=agent["dashboardUrl"],
        label=f"Agent Village — {human.email}",
        exchange_hash=digest(token),
        expires_at=now() + timedelta(minutes=5),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    handoff = f"{public_origin}{settings.API_V1_STR}/agent/desktop/exchange#{token}"
    return {
        "attempt": attempt_view(attempt),
        "deepLink": "hermes://connect?v=2&handoff=" + quote(handoff, safe=""),
    }


@router.post("/desktop/exchange")
async def desktop_exchange(
    body: Exchange, request: Request, db: SessionDep, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    public_origin = origin()
    hashed = native_hash(request)
    attempt = locked(
        db,
        select(AgentDesktopAttempt).where(
            AgentDesktopAttempt.exchange_hash == hashed,
            AgentDesktopAttempt.status == "pending",
            AgentDesktopAttempt.expires_at > now(),
        ),
    ).first()
    if not attempt:
        raise HTTPException(
            410,
            "This handoff expired or was already used. Return to your agent and retry.",
        )
    compatible = body.protocolVersion == 2
    ack_token = secrets.token_urlsafe(32)
    attempt.exchange_hash = None
    attempt.ack_hash = digest(ack_token) if compatible else None
    attempt.status = "opened" if compatible else "incompatible"
    attempt.code = None if compatible else "protocol_unsupported"
    attempt.desktop_version = body.desktopVersion
    attempt.expires_at = now() + timedelta(minutes=5)
    attempt.updated_at = now()
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    if not compatible:
        raise HTTPException(
            426, "Update Hermes Desktop to support OAuth handoff protocol 2."
        )
    try:
        connection = await cp(
            tenant_path({"id": attempt.cp_tenant_id}) + "/desktop-connection"
        )
        if (
            not connection
            or connection.get("authMode") != "oauth"
            or connection.get("profile") != "default"
            or connection.get("protocol") != "hermes-jsonrpc-v1"
            or connection.get("url") != attempt.gateway_url
        ):
            raise HTTPException(
                409, "The agent connection changed. Check host status and retry."
            )
    except HTTPException:
        attempt.status, attempt.code, attempt.ack_hash = (
            "failed",
            "connection_failed",
            None,
        )
        db.add(attempt)
        db.commit()
        raise
    return {
        "protocolVersion": 2,
        "attemptId": str(attempt.id),
        "tenantId": attempt.cp_tenant_id,
        "label": attempt.label,
        "gatewayUrl": attempt.gateway_url,
        "authMode": "oauth",
        "profile": "default",
        "ackUrl": f"{public_origin}{settings.API_V1_STR}/agent/desktop/ack",
        "ackToken": ack_token,
        "expiresAt": attempt.expires_at.isoformat(),
    }


@router.post("/desktop/ack")
async def desktop_ack(
    body: Acknowledge, request: Request, db: SessionDep, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    hashed = native_hash(request)
    attempt = locked(
        db,
        select(AgentDesktopAttempt).where(
            AgentDesktopAttempt.ack_hash == hashed,
            AgentDesktopAttempt.status == "opened",
            AgentDesktopAttempt.expires_at > now(),
        ),
    ).first()
    if not attempt:
        raise HTTPException(410, "This handoff expired or was already acknowledged.")
    attempt.status, attempt.code = body.status, body.code
    attempt.desktop_version = body.desktopVersion
    attempt.ack_hash = None
    attempt.updated_at = now()
    db.add(attempt)
    db.commit()
    return {"acknowledged": True}
