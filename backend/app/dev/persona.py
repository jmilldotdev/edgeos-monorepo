"""Create a local participant who is onboarded to a popup but has no agent.

The persona has an accepted application, an allocated ticket, an approved
payment and RSVPs to events happening today, so the portal dashboard and
agent onboarding can be exercised from a realistic starting point. Prints a
one-click sign-in link for the portal's development-only /dev/login route.

    cd backend && uv run python -m app.dev.persona [--popup SLUG] [--email E] [--name "First Last"]

Refuses to run outside ENVIRONMENT=dev.
"""

import argparse
import random
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from sqlmodel import Session, select

import app.models  # noqa: F401  Registers every SQLModel relationship.
from app.core.config import Environment, settings
from app.core.db import _seed_applications, _seed_humans, _seed_payments, engine
from app.core.security import create_access_token

DEV_TAG = "dev-persona"
NAMES = [
    ("Ada", "Okafor"),
    ("Mira", "Sato"),
    ("Tomás", "Ferreira"),
    ("Priya", "Raman"),
    ("Jonah", "Lindqvist"),
    ("Leila", "Haddad"),
]
TODAY_EVENTS = [
    ("Morning swim at the point", time(7, 30), 60),
    ("Coworking kickoff at The Circle", time(10, 0), 90),
    ("Fireside: agents that ask first", time(18, 30), 75),
]


def local_zone() -> str:
    """IANA name of the machine's zone, so seeded times render as local."""
    target = str(Path("/etc/localtime").resolve())
    return target.split("zoneinfo/", 1)[1] if "zoneinfo/" in target else "UTC"


def main() -> None:
    if settings.ENVIRONMENT != Environment.DEV:
        sys.exit(f"Refusing to create personas in ENVIRONMENT={settings.ENVIRONMENT}.")

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tenant", default="demo", help="tenant slug (default: demo)")
    parser.add_argument(
        "--popup", help="popup slug (default: first active popup with a ticket)"
    )
    parser.add_argument("--email", help="default: dev+<timestamp>@example.com")
    parser.add_argument("--name", help='default: a random "First Last"')
    args = parser.parse_args()

    from app.api.event.models import Events
    from app.api.event.schemas import EventStatus
    from app.api.event_participant.models import EventParticipants
    from app.models import Humans, Popups, Products, Tenants

    with Session(engine) as db:
        tenant = db.exec(select(Tenants).where(Tenants.slug == args.tenant)).first()
        if not tenant:
            sys.exit(f"Tenant {args.tenant!r} not found.")

        popups = db.exec(
            select(Popups).where(
                Popups.tenant_id == tenant.id, Popups.status == "active"
            )
        ).all()
        if args.popup:
            popups = [p for p in popups if p.slug == args.popup]
        popup, ticket = None, None
        for candidate in popups:
            ticket = db.exec(
                select(Products).where(
                    Products.popup_id == candidate.id, Products.category == "ticket"
                )
            ).first()
            if ticket:
                popup = candidate
                break
        if not popup or not ticket:
            sys.exit("No active popup with a ticket product found.")

        first, _, last = (args.name or " ".join(random.choice(NAMES))).partition(" ")
        stamp = datetime.now(UTC).strftime("%m%d-%H%M%S")
        email = (args.email or f"dev+{stamp}@example.com").lower()
        if db.exec(
            select(Humans).where(Humans.email == email, Humans.tenant_id == tenant.id)
        ).first():
            sys.exit(f"{email} already exists; pass a different --email.")

        # Reuse the demo seeders so the persona matches seeded attendees exactly.
        seed = {
            "humans": [
                {"key": "me", "email": email, "first_name": first, "last_name": last}
            ],
            "applications": [
                {
                    "key": "me-app",
                    "popup_key": "p",
                    "human_key": "me",
                    "status": "accepted",
                    "attendees": [
                        {
                            "name": f"{first} {last}".strip(),
                            "category": "main",
                            "email": email,
                            "products": [{"product_slug": ticket.slug, "quantity": 1}],
                        }
                    ],
                }
            ],
            "payments": [
                {
                    "application_key": "me-app",
                    "status": "approved",
                    "amount": str(ticket.price or 0),
                    "source": "dev-persona",
                    "external_id": f"dev_{stamp}",
                    "products": [
                        {
                            "product_slug": ticket.slug,
                            "attendee_index": 0,
                            "quantity": 1,
                        }
                    ],
                }
            ],
        }
        popup_map = {"p": popup}
        product_map = {f"p:{ticket.slug}": ticket}
        humans = _seed_humans(db, seed, tenant.id)
        applications, attendees = _seed_applications(
            db, seed, popup_map, humans, {}, product_map, tenant.id
        )
        _seed_payments(
            db, seed, popup_map, applications, attendees, product_map, {}, tenant.id
        )
        human = humans["me"]

        # Today's schedule, shared by every persona created today.
        today = datetime.now().astimezone().date()
        day_start = datetime.combine(today, time.min).astimezone()
        existing = db.exec(
            select(Events).where(
                Events.popup_id == popup.id,
                Events.start_time >= day_start,
                Events.start_time < day_start + timedelta(days=1),
            )
        ).all()
        dev_events = [e for e in existing if DEV_TAG in (e.tags or [])]
        if not dev_events:
            host = (
                db.exec(
                    select(Humans).where(
                        Humans.tenant_id == tenant.id, Humans.id != human.id
                    )
                ).first()
                or human
            )
            for title, starts, minutes in TODAY_EVENTS:
                start = datetime.combine(today, starts).astimezone()
                event = Events(
                    tenant_id=tenant.id,
                    popup_id=popup.id,
                    owner_id=host.id,
                    title=title,
                    start_time=start,
                    end_time=start + timedelta(minutes=minutes),
                    timezone=local_zone(),
                    custom_location_name="The Circle",
                    tags=[DEV_TAG],
                    status=EventStatus.PUBLISHED,
                )
                db.add(event)
                dev_events.append(event)
            db.commit()
        for event in sorted(dev_events, key=lambda e: e.start_time)[1:]:
            db.add(
                EventParticipants(
                    tenant_id=tenant.id, event_id=event.id, profile_id=human.id
                )
            )
        db.commit()

        token = create_access_token(subject=human.id, token_type="human")
        summary = (
            f"Created {first} {last} <{email}>\n"
            f"  popup: {popup.name} · ticket: {ticket.name}"
            f" · RSVPs today: {len(dev_events) - 1}\n"
            "  agent setup: not started\n\n"
            f"Sign in: http://{tenant.slug}.localhost:3000/dev/login#token={token}"
        )
        print(summary)  # noqa: T201  CLI output is the product.


if __name__ == "__main__":
    main()
