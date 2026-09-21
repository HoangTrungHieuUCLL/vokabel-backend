from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WordType = Literal[
    "nomen",
    "verb",
    "adjektiv",
    "adverb",
    "praeposition",
    "konjunktion",
    "pronomen",
    "partikel",
    "phrase",
]


def _enum(values: set[str]) -> Callable[[Any, str], str]:
    def validate(v: Any, key: str) -> str:
        if not isinstance(v, str) or v not in values:
            raise ValueError(f"'{key}' must be one of {sorted(values)}")
        return v

    return validate


def _string(v: Any, key: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"'{key}' must be a non-empty string")
    return v


def _bool(v: Any, key: str) -> bool:
    if not isinstance(v, bool):
        raise ValueError(f"'{key}' must be a boolean")
    return v


# Each type's allowlist of attrs keys. "required" keys must be present and
# non-empty; "optional" keys are validated only when present. Unknown keys
# are rejected outright so a typo'd attribute never silently vanishes.
TYPE_ATTR_SPEC: dict[str, dict[str, dict[str, Callable[[Any, str], Any]]]] = {
    "nomen": {
        "required": {"artikel": _enum({"der", "die", "das"}), "plural": _string},
        "optional": {"genitiv": _string},
    },
    "verb": {
        "required": {
            "hilfsverb": _enum({"haben", "sein"}),
            "praesens_3sg": _string,
            "praeteritum": _string,
            "partizip_ii": _string,
        },
        "optional": {"trennbar": _bool, "reflexiv": _bool, "rektion": _string},
    },
    "adjektiv": {"required": {}, "optional": {"komparativ": _string, "superlativ": _string}},
    "adverb": {"required": {}, "optional": {"position": _string}},
    "praeposition": {
        "required": {"kasus": _enum({"akk", "dat", "gen", "wechsel"})},
        "optional": {},
    },
    "konjunktion": {
        "required": {"wortstellung": _enum({"pos0", "pos1", "verb_ende"})},
        "optional": {},
    },
    "pronomen": {"required": {}, "optional": {}},
    "partikel": {"required": {}, "optional": {"register": _string}},
    "phrase": {
        "required": {},
        "optional": {"register": _enum({"formell", "informell", "neutral"})},
    },
}


def validate_attrs(word_type: str, attrs: dict[str, Any]) -> dict[str, Any]:
    spec = TYPE_ATTR_SPEC[word_type]
    allowed = {**spec["required"], **spec["optional"]}

    for key in attrs:
        if key not in allowed:
            raise ValueError(f"unknown attribute '{key}' is not allowed for type '{word_type}'")

    for key in spec["required"]:
        if attrs.get(key) in (None, ""):
            raise ValueError(f"'{key}' is required for type '{word_type}'")

    return {key: allowed[key](value, key) for key, value in attrs.items()}


class ExampleSentence(BaseModel):
    de: str = Field(min_length=1)
    meaning: str = ""


class WordBase(BaseModel):
    word: str = Field(min_length=1)
    type: WordType
    meaning: str = Field(min_length=1)
    example: list[ExampleSentence] = Field(default_factory=list)
    attrs: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    comment: str | None = None
    is_hard: bool = False


class WordCreate(WordBase):
    @model_validator(mode="after")
    def _validate_attrs(self) -> "WordCreate":
        self.attrs = validate_attrs(self.type, self.attrs)
        return self


class WordUpdate(BaseModel):
    word: str | None = Field(default=None, min_length=1)
    type: WordType | None = None
    meaning: str | None = Field(default=None, min_length=1)
    example: list[ExampleSentence] | None = None
    attrs: dict[str, Any] | None = None
    tags: list[str] | None = None
    source: str | None = None
    comment: str | None = None
    is_hard: bool | None = None


class WordOut(WordBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    search_key: str
    hard_since: datetime | None = None
    due_at: datetime | None = None
    interval_days: float
    ease: float
    reps: int
    lapses: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class BulkCreateResult(BaseModel):
    index: int
    status: Literal["created", "duplicate", "error"]
    word: WordOut | None = None
    error: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    username: str


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)


class PushSubscriptionIn(BaseModel):
    """Mirrors the browser's PushSubscription.toJSON() shape."""

    endpoint: str = Field(min_length=1)
    keys: PushSubscriptionKeys
    user_agent: str | None = None


class PushSubscriptionRef(BaseModel):
    endpoint: str = Field(min_length=1)


class NotificationStatus(BaseModel):
    push_enabled: bool
    subscribed: bool
    subscription_count: int
    slots: list[str]
    timezone: str
    next_slot_at: datetime | None = None


class VapidKeyOut(BaseModel):
    public_key: str
    push_enabled: bool


class SpotlightOut(BaseModel):
    slot: str
    slot_date: date
    scheduled_for: datetime
    next_slot_at: datetime | None = None
    word: WordOut
