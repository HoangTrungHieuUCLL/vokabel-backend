"""The times of day a word is pushed.

Stored in the database so they can be changed from the app, falling back to
the NOTIFY_SLOTS environment default until they are edited for the first
time -- so an existing deployment keeps its behaviour without a write.
"""

from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import NotificationSettings

# A generous ceiling rather than a design opinion: enough for hourly-ish
# practice, few enough that a typo cannot turn the phone into an alarm.
MAX_SLOTS = 12


class InvalidSlots(ValueError):
    pass


def parse_slots(raw: list[str]) -> list[time]:
    """Validate and normalise "HH:MM" strings into sorted, unique times."""
    if not raw:
        raise InvalidSlots("Pick at least one time.")
    if len(raw) > MAX_SLOTS:
        raise InvalidSlots(f"At most {MAX_SLOTS} times.")

    parsed: set[time] = set()
    for entry in raw:
        text = entry.strip()
        try:
            hour_str, minute_str = text.split(":")
            hour, minute = int(hour_str), int(minute_str)
        except ValueError:
            raise InvalidSlots(f"'{entry}' is not a time in HH:MM form.") from None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise InvalidSlots(f"'{entry}' is not a real time of day.")
        parsed.add(time(hour, minute))

    return sorted(parsed)


def _row(db: Session) -> NotificationSettings | None:
    return db.execute(select(NotificationSettings).where(NotificationSettings.id == 1)).scalar_one_or_none()


def get_slots(db: Session) -> list[time]:
    row = _row(db)
    if row is None:
        return settings.notify_slots
    try:
        return parse_slots(row.slots.split(","))
    except InvalidSlots:
        # Never let a bad stored value stop notifications entirely.
        return settings.notify_slots


def is_customised(db: Session) -> bool:
    return _row(db) is not None


def get_changed_at(db: Session) -> datetime | None:
    """When the times were last edited, or None while they are the default."""
    row = _row(db)
    return row.updated_at if row else None


def set_slots(db: Session, raw: list[str]) -> list[time]:
    parsed = parse_slots(raw)
    stored = ",".join(t.strftime("%H:%M") for t in parsed)

    row = _row(db)
    if row is None:
        db.add(NotificationSettings(id=1, slots=stored, updated_at=datetime.now(timezone.utc)))
    else:
        row.slots = stored
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return parsed
