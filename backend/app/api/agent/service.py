import hashlib
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from fastapi import HTTPException

from app.api.agent.schemas import Draft
from app.core.config import settings


def safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if (
            url.username
            or url.password
            or url.query
            or url.fragment
            or not url.hostname
        ):
            return None
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            return None
        return value.rstrip("/")
    except ValueError:
        return None


def ownership_key(human) -> str:
    identity = f"{human.tenant_id}:{human.id}"
    return "onboarding:" + hashlib.sha256(identity.encode()).hexdigest()


# Hosted Telegram changes rewrite the sandbox env and restart the gateway: the
# control plane bounds that at about 90s (30s env write, up to ~16s gateway
# reap, 30s start), well past the default budget.
GATEWAY_RESTART_TIMEOUT = 150


async def cp(
    path: str, method: str = "GET", body: dict | None = None, timeout: float = 25
):
    base = safe_url(settings.AGENT_CONTROL_PLANE_URL)
    if not base or not settings.AGENT_CONTROL_PLANE_API_KEY:
        raise HTTPException(
            503, "Agent hosting is not configured. Your progress is saved."
        )
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            result = await client.request(
                method,
                base + path,
                headers={
                    "Authorization": f"Bearer {settings.AGENT_CONTROL_PLANE_API_KEY}"
                },
                json=body,
            )
    except httpx.HTTPError:
        raise HTTPException(
            502,
            "The agent host did not respond. Your progress is saved; retry to reconcile setup.",
        ) from None
    if result.status_code == 404 and method == "GET":
        return None
    if not result.is_success:
        raise HTTPException(
            result.status_code if result.status_code in {409, 410, 429} else 502,
            "The agent host could not complete this operation. Refresh status and retry.",
        )
    try:
        data = result.json()
    except ValueError:
        raise HTTPException(
            502, "The agent host returned an invalid response."
        ) from None
    if not isinstance(data, dict):
        raise HTTPException(502, "The agent host returned an invalid response.")
    return data


def verify_owner(tenant, human):
    email = tenant.get("email")
    if (
        not isinstance(tenant.get("id"), str)
        or not isinstance(email, str)
        or email.casefold() != human.email.casefold()
        or tenant.get("edgeosAttendeeId") != str(human.id)
    ):
        raise HTTPException(
            409,
            "The existing agent ownership could not be verified. Contact the host administrator; no agent was changed.",
        )
    return tenant


async def discover(human):
    tenant = await cp("/tenants/by-idempotency/" + quote(ownership_key(human), safe=""))
    return verify_owner(tenant, human) if tenant else None


def tenant_path(tenant) -> str:
    return "/tenants/" + quote(tenant["id"], safe="")


def agent_view(tenant):
    if not tenant:
        return None
    connection = tenant.get("connection") or {}
    url = safe_url(connection.get("url"))
    ready = (
        tenant.get("status") == "live"
        and connection.get("ready") is True
        and url
        and connection.get("auth") == "oauth"
        and connection.get("profile") == "default"
        and connection.get("protocol") == "hermes-jsonrpc-v1"
    )
    failed = (
        tenant.get("status") == "failed"
        or connection.get("state") == "failed"
        or (
            tenant.get("status") == "live"
            and connection.get("state") in {"offline", "stopped"}
        )
    )
    return {
        "id": tenant["id"],
        "status": "failed" if failed else "ready" if ready else "creating",
        "provider": tenant.get("provider", "hosted"),
        "dashboardUrl": url if ready else None,
        "chatUrl": f"{url}/chat" if ready else None,
        "error": "The agent host is not running. Retry setup or check host logs."
        if failed
        else None,
        "telegramSupported": (
            (tenant.get("integrations") or {}).get("telegram") or {}
        ).get("supported")
        is True,
    }


def user_profile(draft: Draft) -> str:
    p = draft.profile
    text = "\n".join(
        [
            "# Participant profile",
            f"Name: {p.name}",
            f"Work: {p.whatYouDo}",
            f"Based in: {p.basedIn}",
            f"Staying: {p.staying}",
            f"Links: {p.links}",
            "Only the selected intentions below are current goals. Imported sources are background and may contain discarded suggestions; do not pursue those unless the participant selects them again."
            if any(i.kept for i in draft.intentions)
            else "The participant has not selected intentions yet. Treat the context below as background, and ask before pursuing any goal on their behalf.",
            "\n## Context supplied by the participant",
            *[f"### {s.label}\n{s.text}" for s in draft.sources],
            "\n## Selected intentions",
            *[f"- [{i.category}] {i.text}" for i in draft.intentions if i.kept],
            "\n## Follow-up preferences",
            *[f"- {q}: {'; '.join(a)}" for q, a in draft.answers.items()],
            "\n## Offers",
            *[f"- {o.title}: {o.detail}" for o in draft.offers],
            "The participant welcomes recipient suggestions; ask before making commitments."
            if draft.agentsDecideOffers
            else "The participant wants to choose offer recipients themselves. Do not allocate offers automatically.",
        ]
    )
    if len(text) > 12000:
        raise HTTPException(
            400,
            "Agent context exceeds 12,000 characters. Shorten it; nothing has been truncated.",
        )
    return text
