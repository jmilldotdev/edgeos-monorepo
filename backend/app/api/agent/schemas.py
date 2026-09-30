from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

BRIEF_VERSION = "av2-consent-draft-2026-09-24"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Confirmation(Input):
    confirmed: StrictBool

    @field_validator("confirmed")
    @classmethod
    def require_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation is required")
        return value


class Profile(Input):
    name: str = Field(default="", max_length=200)
    whatYouDo: str = Field(default="", max_length=12000)
    basedIn: str = Field(default="", max_length=200)
    staying: str = Field(default="", max_length=200)
    links: str = Field(default="", max_length=2000)


class Source(Input):
    id: str = Field(min_length=1, max_length=100)
    method: Literal["ai", "write", "voice"]
    label: str = Field(max_length=200)
    text: str = Field(max_length=12000)
    words: int = Field(ge=0, le=12000)


class Intention(Input):
    id: str = Field(min_length=1, max_length=100)
    category: Literal["build", "learn", "meet", "explore"]
    text: str = Field(min_length=1, max_length=2000)
    why: str = Field(default="", max_length=2000)
    kept: StrictBool
    addedByYou: StrictBool = False


class Offer(Input):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(max_length=2000)


class Draft(Input):
    profile: Profile = Field(default_factory=Profile)
    sources: list[Source] = Field(default_factory=list, max_length=20)
    intentions: list[Intention] = Field(default_factory=list, max_length=50)
    intentionsConfirmed: StrictBool = False
    answers: dict[str, list[str]] = Field(default_factory=dict, max_length=50)
    offers: list[Offer] = Field(default_factory=list, max_length=30)
    agentsDecideOffers: StrictBool = False
    questionsDone: StrictBool = False
    extractionSourceHash: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def bound_preferences(self):
        if any(
            len(k) > 200 or len(v) > 30 or any(len(s) > 1000 for s in v)
            for k, v in self.answers.items()
        ):
            raise ValueError("Follow-up preferences are too long")
        return self


class Revision(Input):
    revision: int = Field(ge=0, strict=True)


class Reset(Confirmation, Revision):
    pass


class SaveDraft(Revision):
    draft: Draft


class ExtractDraft(Input):
    draft: Draft


class IntentionSuggestion(Input):
    model_config = ConfigDict(extra="forbid", strict=True)
    category: Literal["build", "learn", "meet", "explore"]
    text: str = Field(min_length=1, max_length=2000)
    why: str = Field(max_length=2000)


class OfferSuggestion(Input):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(max_length=2000)


class ExtractionSuggestions(Input):
    model_config = ConfigDict(extra="forbid", strict=True)
    intentions: list[IntentionSuggestion] = Field(max_length=24)
    offers: list[OfferSuggestion] = Field(max_length=20)


class SaveConsent(Revision):
    research: StrictBool
    training: StrictBool
    briefVersion: Literal["av2-consent-draft-2026-09-24"]


class Attach(Input):
    action: Literal["attach"]
    token: str = Field(
        pattern=r"^\d{5,}:[A-Za-z0-9_-]{20,}$", max_length=256, repr=False
    )


class Approve(Confirmation):
    action: Literal["approve"]
    code: str = Field(min_length=1, max_length=128)
    userId: str = Field(pattern=r"^\d+$", max_length=30)


class Revoke(Confirmation):
    action: Literal["revoke"]
    userId: str = Field(pattern=r"^\d+$", max_length=30)


TelegramAction = Annotated[Attach | Approve | Revoke, Field(discriminator="action")]


class Exchange(Input):
    protocolVersion: int = Field(strict=True)
    desktopVersion: str = Field(min_length=1, max_length=100)


class Acknowledge(Input):
    status: Literal["connected", "failed", "incompatible", "cancelled"]
    code: (
        Literal[
            "connection_failed",
            "profile_missing",
            "protocol_unsupported",
            "user_cancelled",
            "chat_failed",
        ]
        | None
    ) = None
    desktopVersion: str = Field(min_length=1, max_length=100)
    profile: Literal["default"] | None = None

    @model_validator(mode="after")
    def connected_profile(self):
        if self.status == "connected" and (
            self.profile != "default" or self.code is not None
        ):
            raise ValueError("Connected requires the selected profile and no error")
        return self
