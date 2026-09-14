from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, Float, Integer, String, Text, func
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
