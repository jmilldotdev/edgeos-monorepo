import re
from urllib.parse import parse_qs, quote, urlsplit

from fastapi import HTTPException
from pydantic import Field

from app.api.agent.router import owned_telegram, router, setup
from app.api.agent.schemas import Confirmation
from app.api.agent.service import GATEWAY_RESTART_TIMEOUT, cp, tenant_path
from app.core.dependencies.users import CurrentHuman, SessionDep


class ConfirmOwner(Confirmation):
    owner_user_id: str = Field(pattern=r"^\d+$", max_length=30)


def telegram_link(value):
    if not isinstance(value, str):
        raise HTTPException(502, "The Telegram setup service returned an invalid link.")
    try:
        url = urlsplit(value)
        start = parse_qs(url.query).get("start", [])
        hosted_bot = (
            re.fullmatch(r"/[A-Za-z0-9_]{5,32}", url.path)
            and len(start) == 1
            and re.fullmatch(r"pair_[A-Za-z0-9_-]+", start[0])
        )
        valid = (
            not url.username
            and not url.password
            and not url.fragment
            and url.scheme == "https"
            and url.hostname == "t.me"
            and url.port in {None, 443}
            and (url.path.startswith("/newbot/") or hosted_bot)
        )
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(502, "The Telegram setup service returned an invalid link.")
    return value


def pairing_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise HTTPException(422, "Invalid Telegram setup attempt.")
    return value


def public_status(data):
    if (
        not isinstance(data, dict)
        or data.get("status") not in {"waiting", "ready", "applied"}
        or not isinstance(data.get("expires_at"), str)
    ):
        raise HTTPException(
            502, "The Telegram setup service returned an invalid status."
        )
    result = {"status": data["status"], "expires_at": data["expires_at"]}
    for key in ("bot_username", "suggested_username"):
        if isinstance(data.get(key), str) and re.fullmatch(
            r"[A-Za-z0-9_]{5,32}", data[key]
        ):
            result[key] = data[key]
    if data.get("owner_user_id") is not None:
        owner = str(data["owner_user_id"])
        if not re.fullmatch(r"\d{1,30}", owner):
            raise HTTPException(
                502, "The Telegram setup service returned an invalid owner."
            )
        result["owner_user_id"] = owner
    for key in ("deep_link", "qr_payload"):
        if data.get(key) is not None:
            result[key] = telegram_link(data[key])
    return result


async def owned_attempt(db, human, attempt, lock=False):
    pairing_id(attempt)
    owner = setup(db, human, lock)
    if owner.telegram_pairing_id != attempt:
        raise HTTPException(404, "Telegram setup attempt not found.")
    tenant, _ = await owned_telegram(human)
    return owner, tenant_path(tenant) + "/telegram/onboarding/" + quote(
        attempt, safe=""
    )


@router.post("/telegram/onboarding/start")
async def start_telegram_onboarding(db: SessionDep, human: CurrentHuman):
    owner = setup(db, human, True)
    tenant, _ = await owned_telegram(human)
    base = tenant_path(tenant) + "/telegram/onboarding"
    data = await cp(base + "/start", "POST", {})
    result = {
        "pairing_id": pairing_id(data.get("pairing_id")),
        "suggested_username": data.get("suggested_username"),
        "deep_link": telegram_link(data.get("deep_link")),
        "qr_payload": telegram_link(data.get("qr_payload")),
        "expires_at": data.get("expires_at"),
    }
    owner.telegram_pairing_id = result["pairing_id"]
    db.add(owner)
    db.commit()
    return result


@router.get("/telegram/onboarding/{attempt}")
async def get_telegram_onboarding(attempt: str, db: SessionDep, human: CurrentHuman):
    _, path = await owned_attempt(db, human, attempt)
    return public_status(await cp(path))


@router.post("/telegram/onboarding/{attempt}/apply")
async def apply_telegram_onboarding(
    attempt: str, body: ConfirmOwner, db: SessionDep, human: CurrentHuman
):
    _, path = await owned_attempt(db, human, attempt, True)
    pending = public_status(await cp(path))
    if (
        pending["status"] not in {"ready", "applied"}
        or pending.get("owner_user_id") != body.owner_user_id
    ):
        raise HTTPException(
            409,
            "The detected Telegram owner changed. Refresh and confirm the exact account again.",
        )
    data = await cp(
        path + "/apply",
        "POST",
        {"allowed_user_ids": [body.owner_user_id]},
        timeout=GATEWAY_RESTART_TIMEOUT,
    )
    if (
        data.get("ok") is not True
        or str(data.get("telegramUserId")) != body.owner_user_id
    ):
        raise HTTPException(
            502, "The host did not confirm the selected Telegram account."
        )
    return {
        "ok": True,
        "telegramUserId": body.owner_user_id,
        "bot_username": data.get("bot_username"),
    }


@router.delete("/telegram/onboarding/{attempt}")
async def cancel_telegram_onboarding(attempt: str, db: SessionDep, human: CurrentHuman):
    owner, path = await owned_attempt(db, human, attempt, True)
    await cp(path, "DELETE")
    owner.telegram_pairing_id = None
    db.add(owner)
    db.commit()
    return {"ok": True}
