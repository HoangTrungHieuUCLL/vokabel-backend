from datetime import datetime
from datetime import date as date_type

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

WORD_TYPES = (
    "nomen",
    "verb",
    "adjektiv",
    "adverb",
    "praeposition",
    "konjunktion",
    "pronomen",
    "partikel",
    "phrase",
)


class Word(Base):
    __tablename__ = "words"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    word: Mapped[str] = mapped_column(Text, nullable=False)
    search_key: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    meaning: Mapped[str] = mapped_column(Text, nullable=False)
    # list of {"de": ..., "meaning": ...} -- multiple example sentences per word
    example: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_hard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hard_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # reserved for v2 spaced repetition; written but never read in v1
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interval_days: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    ease: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    reps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PushSubscription(Base):
    """One row per browser that accepted notifications. Single-user app, so
    there is no user column -- every subscription belongs to the one account."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Spotlight(Base):
    """The word picked for one notification slot. Written before the push is
    attempted, so the app and the notification always name the same word, and
    the (slot_date, slot) unique constraint makes a re-run of the dispatcher
    idempotent rather than a second notification."""

    __tablename__ = "spotlights"
    __table_args__ = (UniqueConstraint("slot_date", "slot", name="uq_spotlights_date_slot"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    slot_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    # "HH:MM" local wall-clock, matching a NOTIFY_SLOTS entry.
    slot: Mapped[str] = mapped_column(String(5), nullable=False)
    word_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("words.id", ondelete="CASCADE"), nullable=False
    )
    # The UTC instant the local slot resolved to, so DST shifts stay visible.
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
