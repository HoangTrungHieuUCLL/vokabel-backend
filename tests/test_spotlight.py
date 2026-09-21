from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Spotlight, Word
from app.services.spotlight import (
    current_spotlight,
    due_slots,
    ensure_spotlight,
    local_slot_instant,
    most_recent_past_slot,
    next_slot_instant,
    pick_word_id,
)

BRUSSELS = ZoneInfo("Europe/Brussels")
SLOTS = [time(9, 0), time(12, 0), time(15, 0), time(18, 0), time(22, 0)]


def make_words(db: Session, count: int) -> list[Word]:
    words = [
        Word(word=f"Wort{i}", search_key=f"wort{i}", type="nomen", meaning=f"meaning {i}")
        for i in range(count)
    ]
    db.add_all(words)
    db.commit()
    for w in words:
        db.refresh(w)
    return words


# --- slot arithmetic ---------------------------------------------------------


def test_slot_resolves_to_local_wall_clock_across_dst() -> None:
    """09:00 Brussels is 07:00Z in summer and 08:00Z in winter. A fixed UTC
    cron would drift by an hour; the slot must not."""
    summer = local_slot_instant(date(2026, 7, 1), time(9, 0), BRUSSELS)
    winter = local_slot_instant(date(2026, 12, 1), time(9, 0), BRUSSELS)
    assert summer.astimezone(timezone.utc).hour == 7
    assert winter.astimezone(timezone.utc).hour == 8


def test_due_slots_returns_slot_just_passed() -> None:
    now = datetime(2026, 7, 1, 10, 5, tzinfo=BRUSSELS).astimezone(timezone.utc)
    due = due_slots(now, BRUSSELS, SLOTS, catchup_minutes=90)
    assert [slot.strftime("%H:%M") for _, slot, _ in due] == ["09:00"]


def test_due_slots_ignores_future_slots() -> None:
    now = datetime(2026, 7, 1, 8, 30, tzinfo=BRUSSELS).astimezone(timezone.utc)
    assert due_slots(now, BRUSSELS, SLOTS, catchup_minutes=90) == []


def test_due_slots_drops_slots_past_the_catchup_window() -> None:
    """A slot missed for hours is dropped rather than delivered at a useless
    hour -- 09:00's word must not arrive at 14:00."""
    now = datetime(2026, 7, 1, 14, 0, tzinfo=BRUSSELS).astimezone(timezone.utc)
    assert due_slots(now, BRUSSELS, SLOTS, catchup_minutes=90) == []


def test_due_slots_catches_up_within_the_window() -> None:
    now = datetime(2026, 7, 1, 13, 20, tzinfo=BRUSSELS).astimezone(timezone.utc)
    due = due_slots(now, BRUSSELS, SLOTS, catchup_minutes=90)
    assert [slot.strftime("%H:%M") for _, slot, _ in due] == ["12:00"]


def test_due_slots_crosses_local_midnight() -> None:
    """After a delay that pushes the run past local midnight, the 22:00 slot is
    still attributed to yesterday's date rather than dropped or re-dated."""
    now = datetime(2026, 7, 2, 0, 30, tzinfo=BRUSSELS).astimezone(timezone.utc)
    due = due_slots(now, BRUSSELS, SLOTS, catchup_minutes=180)
    assert len(due) == 1
    slot_date, slot, _ = due[0]
    assert slot_date == date(2026, 7, 1)
    assert slot.strftime("%H:%M") == "22:00"


def test_hourly_dispatcher_covers_every_slot_over_a_full_day() -> None:
    """The job runs hourly on the UTC hour; every one of the five slots must be
    picked up exactly once, in both DST halves of the year."""
    for day in (date(2026, 7, 1), date(2026, 12, 1)):
        seen: list[str] = []
        start = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
        for hour in range(48):
            now = start + timedelta(hours=hour)
            for slot_date, slot, _ in due_slots(now, BRUSSELS, SLOTS, catchup_minutes=90):
                key = f"{slot_date}:{slot.strftime('%H:%M')}"
                if key not in seen:
                    seen.append(key)
        for slot in SLOTS:
            assert f"{day}:{slot.strftime('%H:%M')}" in seen


def test_most_recent_past_slot_and_next_slot() -> None:
    now = datetime(2026, 7, 1, 13, 0, tzinfo=BRUSSELS).astimezone(timezone.utc)
    slot_date, slot, _ = most_recent_past_slot(now, BRUSSELS, SLOTS)
    assert (slot_date, slot.strftime("%H:%M")) == (date(2026, 7, 1), "12:00")

    nxt = next_slot_instant(now, BRUSSELS, SLOTS)
    assert nxt.astimezone(BRUSSELS).hour == 15


def test_most_recent_past_slot_before_first_slot_of_day_looks_back() -> None:
    now = datetime(2026, 7, 2, 7, 0, tzinfo=BRUSSELS).astimezone(timezone.utc)
    slot_date, slot, _ = most_recent_past_slot(now, BRUSSELS, SLOTS)
    assert (slot_date, slot.strftime("%H:%M")) == (date(2026, 7, 1), "22:00")


# --- word selection ----------------------------------------------------------


def test_pick_is_deterministic(db_session: Session) -> None:
    make_words(db_session, 10)
    first = pick_word_id(db_session, date(2026, 7, 1), "09:00")
    second = pick_word_id(db_session, date(2026, 7, 1), "09:00")
    assert first is not None and first == second


def test_pick_returns_none_without_words(db_session: Session) -> None:
    assert pick_word_id(db_session, date(2026, 7, 1), "09:00") is None


def test_five_slots_in_a_day_pick_five_different_words(db_session: Session) -> None:
    make_words(db_session, 20)
    picked = []
    for slot in SLOTS:
        spotlight = ensure_spotlight(
            db_session, date(2026, 7, 1), slot, local_slot_instant(date(2026, 7, 1), slot, BRUSSELS)
        )
        picked.append(spotlight.word_id)
    assert len(set(picked)) == 5


def test_pick_avoids_recently_pushed_words(db_session: Session) -> None:
    words = make_words(db_session, 4)
    # Three of the four were used yesterday; only the fourth is fresh.
    for i, slot in enumerate(["09:00", "12:00", "15:00"]):
        db_session.add(
            Spotlight(
                slot_date=date(2026, 6, 30),
                slot=slot,
                word_id=words[i].id,
                scheduled_for=datetime(2026, 6, 30, 7, 0, tzinfo=timezone.utc),
            )
        )
    db_session.commit()

    assert pick_word_id(db_session, date(2026, 7, 1), "09:00", cooldown_days=30) == words[3].id


def test_pick_falls_back_when_every_word_is_in_cooldown(db_session: Session) -> None:
    """A two-word vocabulary still gets a word rather than nothing."""
    words = make_words(db_session, 2)
    for slot_label_, word in zip(["09:00", "12:00"], words):
        db_session.add(
            Spotlight(
                slot_date=date(2026, 6, 30),
                slot=slot_label_,
                word_id=word.id,
                scheduled_for=datetime(2026, 6, 30, 7, 0, tzinfo=timezone.utc),
            )
        )
    db_session.commit()

    assert pick_word_id(db_session, date(2026, 7, 1), "09:00", cooldown_days=30) in {
        w.id for w in words
    }


def test_pick_ignores_deleted_words(db_session: Session) -> None:
    words = make_words(db_session, 3)
    for word in words[:2]:
        word.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    assert pick_word_id(db_session, date(2026, 7, 1), "09:00") == words[2].id


def test_ensure_spotlight_is_idempotent(db_session: Session) -> None:
    make_words(db_session, 10)
    scheduled = local_slot_instant(date(2026, 7, 1), time(9, 0), BRUSSELS)
    first = ensure_spotlight(db_session, date(2026, 7, 1), time(9, 0), scheduled)
    second = ensure_spotlight(db_session, date(2026, 7, 1), time(9, 0), scheduled)
    assert first.id == second.id


def test_current_spotlight_materialises_a_pick_when_none_recorded(db_session: Session) -> None:
    make_words(db_session, 5)
    spotlight = current_spotlight(db_session, datetime.now(timezone.utc))
    assert spotlight is not None
    assert spotlight.word_id is not None


def test_current_spotlight_prefers_the_latest_scheduled_row(db_session: Session) -> None:
    words = make_words(db_session, 5)
    now = datetime(2026, 7, 1, 16, 0, tzinfo=BRUSSELS).astimezone(timezone.utc)
    db_session.add_all(
        [
            Spotlight(
                slot_date=date(2026, 7, 1),
                slot="09:00",
                word_id=words[0].id,
                scheduled_for=local_slot_instant(date(2026, 7, 1), time(9, 0), BRUSSELS),
            ),
            Spotlight(
                slot_date=date(2026, 7, 1),
                slot="15:00",
                word_id=words[1].id,
                scheduled_for=local_slot_instant(date(2026, 7, 1), time(15, 0), BRUSSELS),
            ),
        ]
    )
    db_session.commit()

    assert current_spotlight(db_session, now).word_id == words[1].id


def test_current_spotlight_ignores_slots_still_in_the_future(db_session: Session) -> None:
    words = make_words(db_session, 5)
    now = datetime(2026, 7, 1, 13, 0, tzinfo=BRUSSELS).astimezone(timezone.utc)
    db_session.add_all(
        [
            Spotlight(
                slot_date=date(2026, 7, 1),
                slot="12:00",
                word_id=words[0].id,
                scheduled_for=local_slot_instant(date(2026, 7, 1), time(12, 0), BRUSSELS),
            ),
            Spotlight(
                slot_date=date(2026, 7, 1),
                slot="18:00",
                word_id=words[1].id,
                scheduled_for=local_slot_instant(date(2026, 7, 1), time(18, 0), BRUSSELS),
            ),
        ]
    )
    db_session.commit()

    assert current_spotlight(db_session, now).word_id == words[0].id
