"""Picking the word behind each notification slot.

The app and the push notification must never disagree about which word is
"current", so the pick is recorded in the `spotlights` table the moment it is
made and everything else reads that row back. Selection itself is
deterministic given the candidate pool, which keeps it reproducible in tests
without storing a shuffle order.
"""

import hashlib
from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Spotlight, Word
from app.services.notify_settings import get_slots


def slot_label(slot: time) -> str:
    return slot.strftime("%H:%M")


def _score(slot_date: date_type, slot: str, word_id: int) -> str:
    # sha256, not hash() -- the built-in is salted per process, which would
    # make the same slot resolve to different words on different workers.
    return hashlib.sha256(f"{slot_date.isoformat()}:{slot}:{word_id}".encode()).hexdigest()


def local_slot_instant(slot_date: date_type, slot: time, tz: ZoneInfo) -> datetime:
    """The UTC instant a local wall-clock slot falls on, for that date's DST offset."""
    return datetime.combine(slot_date, slot, tzinfo=tz).astimezone(timezone.utc)


def due_slots(
    now: datetime,
    tz: ZoneInfo | None = None,
    slots: list[time] | None = None,
    catchup_minutes: int | None = None,
) -> list[tuple[date_type, time, datetime]]:
    """Slots whose local time has passed but is still within the catch-up window.

    Yesterday's local date is considered too: a slot late in the local evening
    can still be pending when the dispatcher next runs after local midnight.
    """
    tz = tz or settings.notify_timezone
    slots = slots if slots is not None else settings.notify_slots
    catchup = catchup_minutes if catchup_minutes is not None else settings.NOTIFY_CATCHUP_MINUTES

    local_now = now.astimezone(tz)
    due: list[tuple[date_type, time, datetime]] = []
    for day_offset in (-1, 0):
        slot_date = (local_now + timedelta(days=day_offset)).date()
        for slot in slots:
            scheduled_for = local_slot_instant(slot_date, slot, tz)
            age_minutes = (now - scheduled_for).total_seconds() / 60
            if 0 <= age_minutes <= catchup:
                due.append((slot_date, slot, scheduled_for))
    return sorted(due, key=lambda item: item[2])


def _candidate_ids(db: Session, slot_date: date_type, cooldown_days: int) -> list[int]:
    """Live word ids, preferring ones not pushed recently.

    Falls back in two steps so a small vocabulary still gets a word: first drop
    the cooldown, then allow even a word already used earlier today.
    """
    all_ids = list(
        db.execute(select(Word.id).where(Word.deleted_at.is_(None)).order_by(Word.id)).scalars()
    )
    if not all_ids:
        return []

    used_today = set(
        db.execute(select(Spotlight.word_id).where(Spotlight.slot_date == slot_date)).scalars()
    )
    recent = set(
        db.execute(
            select(Spotlight.word_id).where(Spotlight.slot_date > slot_date - timedelta(days=cooldown_days))
        ).scalars()
    )

    fresh = [i for i in all_ids if i not in recent and i not in used_today]
    if fresh:
        return fresh
    not_today = [i for i in all_ids if i not in used_today]
    return not_today or all_ids


def pick_word_id(db: Session, slot_date: date_type, slot: str, cooldown_days: int | None = None) -> int | None:
    cooldown = cooldown_days if cooldown_days is not None else settings.SPOTLIGHT_COOLDOWN_DAYS
    candidates = _candidate_ids(db, slot_date, cooldown)
    if not candidates:
        return None
    return min(candidates, key=lambda word_id: _score(slot_date, slot, word_id))


def ensure_spotlight(
    db: Session, slot_date: date_type, slot: time, scheduled_for: datetime
) -> Spotlight | None:
    """Return the slot's spotlight, creating (and committing) it if absent.

    Returns None only when there are no words at all to pick from.
    """
    label = slot_label(slot)
    existing = db.execute(
        select(Spotlight).where(Spotlight.slot_date == slot_date, Spotlight.slot == label)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    word_id = pick_word_id(db, slot_date, label)
    if word_id is None:
        return None

    spotlight = Spotlight(slot_date=slot_date, slot=label, word_id=word_id, scheduled_for=scheduled_for)
    db.add(spotlight)
    try:
        db.commit()
    except IntegrityError:
        # Another worker inserted the same slot between the select and the
        # commit; that row is just as valid as this one.
        db.rollback()
        return db.execute(
            select(Spotlight).where(Spotlight.slot_date == slot_date, Spotlight.slot == label)
        ).scalar_one_or_none()
    db.refresh(spotlight)
    return spotlight


def most_recent_past_slot(
    now: datetime, tz: ZoneInfo | None = None, slots: list[time] | None = None
) -> tuple[date_type, time, datetime]:
    """The latest slot at or before `now`, looking back across the day boundary."""
    tz = tz or settings.notify_timezone
    slots = slots if slots is not None else settings.notify_slots
    local_now = now.astimezone(tz)

    best: tuple[date_type, time, datetime] | None = None
    for day_offset in (0, -1, -2):
        slot_date = (local_now + timedelta(days=day_offset)).date()
        for slot in slots:
            scheduled_for = local_slot_instant(slot_date, slot, tz)
            if scheduled_for <= now and (best is None or scheduled_for > best[2]):
                best = (slot_date, slot, scheduled_for)
    if best is None:  # pragma: no cover - only if slots span more than two days
        slot_date = local_now.date()
        slot = slots[0]
        return slot_date, slot, local_slot_instant(slot_date, slot, tz)
    return best


def next_slot_instant(
    now: datetime, tz: ZoneInfo | None = None, slots: list[time] | None = None
) -> datetime | None:
    tz = tz or settings.notify_timezone
    slots = slots if slots is not None else settings.notify_slots
    if not slots:
        return None
    local_now = now.astimezone(tz)
    upcoming: list[datetime] = []
    for day_offset in (0, 1):
        slot_date = (local_now + timedelta(days=day_offset)).date()
        for slot in slots:
            scheduled_for = local_slot_instant(slot_date, slot, tz)
            if scheduled_for > now:
                upcoming.append(scheduled_for)
    return min(upcoming) if upcoming else None


def current_spotlight(db: Session, now: datetime | None = None) -> Spotlight | None:
    """The spotlight the app should be showing right now.

    Reads the latest already-scheduled row; if the dispatcher has not run yet
    (fresh deploy, cron not wired up) it materialises the most recent past slot
    so the dashboard is never empty.
    """
    now = now or datetime.now(timezone.utc)
    slots = get_slots(db)
    latest = db.execute(
        select(Spotlight)
        .where(Spotlight.scheduled_for <= now)
        .order_by(Spotlight.scheduled_for.desc(), Spotlight.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is not None:
        return latest

    slot_date, slot, scheduled_for = most_recent_past_slot(now, slots=slots)
    return ensure_spotlight(db, slot_date, slot, scheduled_for)
