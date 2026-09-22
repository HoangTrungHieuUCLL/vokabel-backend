from datetime import datetime, time, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.jobs import dispatch_notifications
from app.models import Word
from app.services.notify_settings import (
    InvalidSlots,
    get_changed_at,
    get_slots,
    is_customised,
    parse_slots,
    set_slots,
)

BRUSSELS_UTC_OFFSET_SUMMER = 2


@pytest.fixture
def a_word(db_session: Session) -> Word:
    word = Word(word="Haus", search_key="haus", type="nomen", meaning="house", attrs={"artikel": "das"})
    db_session.add(word)
    db_session.commit()
    return word


# --- parsing -----------------------------------------------------------------


def test_parse_sorts_and_deduplicates() -> None:
    assert parse_slots(["18:00", "09:00", "18:00"]) == [time(9, 0), time(18, 0)]


def test_parse_tolerates_surrounding_whitespace() -> None:
    assert parse_slots([" 09:00 ", "12:30"]) == [time(9, 0), time(12, 30)]


@pytest.mark.parametrize("bad", ["9am", "09", "09:60", "24:00", "-1:00", "", "09:00:00"])
def test_parse_rejects_nonsense(bad: str) -> None:
    with pytest.raises(InvalidSlots):
        parse_slots([bad])


def test_parse_rejects_an_empty_list() -> None:
    with pytest.raises(InvalidSlots):
        parse_slots([])


def test_parse_rejects_more_than_the_maximum() -> None:
    with pytest.raises(InvalidSlots):
        parse_slots([f"{h:02d}:00" for h in range(13)])


# --- storage -----------------------------------------------------------------


def test_defaults_to_the_environment_until_edited(db_session: Session) -> None:
    assert is_customised(db_session) is False
    assert get_slots(db_session) == settings.notify_slots
    assert get_changed_at(db_session) is None


def test_set_then_read_round_trips(db_session: Session) -> None:
    set_slots(db_session, ["07:30", "21:15"])
    assert get_slots(db_session) == [time(7, 30), time(21, 15)]
    assert is_customised(db_session) is True


def test_setting_twice_updates_the_same_row(db_session: Session) -> None:
    # The table allows exactly one row; a second insert would violate its
    # check constraint rather than silently shadowing the first.
    set_slots(db_session, ["07:00"])
    set_slots(db_session, ["08:00", "20:00"])
    assert get_slots(db_session) == [time(8, 0), time(20, 0)]


def test_a_corrupt_stored_value_falls_back_rather_than_silencing_notifications(
    db_session: Session,
) -> None:
    set_slots(db_session, ["07:00"])
    from app.models import NotificationSettings

    row = db_session.get(NotificationSettings, 1)
    row.slots = "not-a-time"
    db_session.commit()

    assert get_slots(db_session) == settings.notify_slots


# --- endpoints ---------------------------------------------------------------


def test_settings_endpoints_require_auth(client: TestClient) -> None:
    assert client.get("/notifications/settings").status_code == 401
    assert client.put("/notifications/settings", json={"slots": ["09:00"]}).status_code == 401


def test_get_returns_the_default_before_any_edit(client: TestClient, auth_headers: dict) -> None:
    body = client.get("/notifications/settings", headers=auth_headers).json()
    assert body["slots"] == ["09:00", "12:00", "15:00", "18:00", "22:00"]
    assert body["customised"] is False
    assert body["timezone"] == "Europe/Brussels"


def test_put_saves_and_echoes_the_normalised_times(client: TestClient, auth_headers: dict) -> None:
    resp = client.put(
        "/notifications/settings", json={"slots": ["21:15", "07:30", "07:30"]}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["slots"] == ["07:30", "21:15"]
    assert resp.json()["customised"] is True

    # And it survives a fresh read.
    assert client.get("/notifications/settings", headers=auth_headers).json()["slots"] == [
        "07:30",
        "21:15",
    ]


def test_put_rejects_a_bad_time_with_a_readable_message(client: TestClient, auth_headers: dict) -> None:
    resp = client.put("/notifications/settings", json={"slots": ["25:00"]}, headers=auth_headers)
    assert resp.status_code == 422
    assert "25:00" in resp.text


def test_put_rejects_an_empty_list(client: TestClient, auth_headers: dict) -> None:
    assert (
        client.put("/notifications/settings", json={"slots": []}, headers=auth_headers).status_code
        == 422
    )


def test_status_reflects_the_chosen_times(client: TestClient, auth_headers: dict) -> None:
    client.put("/notifications/settings", json={"slots": ["06:00"]}, headers=auth_headers)
    assert client.get("/notifications/status", headers=auth_headers).json()["slots"] == ["06:00"]


# --- the dispatcher follows the chosen times ---------------------------------


def _utc(hour: int, minute: int = 0) -> datetime:
    """A UTC instant for a Brussels summer wall-clock time."""
    return datetime(2026, 7, 1, hour - BRUSSELS_UTC_OFFSET_SUMMER, minute, tzinfo=timezone.utc)


def _choose_slots(db: Session, slots: list[str], changed_at: datetime) -> None:
    """Pick the times, as of a given moment.

    set_slots stamps the real clock, so a test driving the dispatcher at a
    simulated instant has to backdate the change -- otherwise every simulated
    slot looks like it predates the edit and is skipped.
    """
    from app.models import NotificationSettings

    set_slots(db, slots)
    db.get(NotificationSettings, 1).updated_at = changed_at
    db.commit()


def test_dispatcher_uses_the_chosen_times_not_the_env_default(
    db_session: Session, a_word: Word, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "k")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "k")
    sends: list[dict] = []
    monkeypatch.setattr(
        dispatch_notifications,
        "send_to_all",
        lambda db, payload: sends.append(payload) or {"sent": 1, "failed": 0, "removed": 0, "subscriptions": 1},
    )
    _choose_slots(db_session, ["06:00"], changed_at=_utc(5, 0))

    # 09:00 is a default slot but no longer a chosen one.
    assert dispatch_notifications.run(_utc(9, 10)) == []
    # 06:00 is, and fires.
    assert [r["status"] for r in dispatch_notifications.run(_utc(6, 10))] == ["sent"]
    assert len(sends) == 1


def test_a_slot_before_the_settings_change_is_not_fired_retroactively(
    db_session: Session, a_word: Word, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adding an earlier time must not ring the phone the moment you save it."""
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "k")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(dispatch_notifications, "send_to_all", lambda db, payload: pytest.fail("sent"))

    # Saved at 14:00; the 13:00 slot is still within the catch-up window but
    # predates the change, so it is skipped rather than delivered.
    _choose_slots(db_session, ["13:00"], changed_at=_utc(14, 0))

    statuses = [r["status"] for r in dispatch_notifications.run(_utc(14, 5))]
    assert statuses == ["before-settings-change"]


def test_a_slot_after_the_settings_change_still_fires(
    db_session: Session, a_word: Word, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "k")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "k")
    monkeypatch.setattr(
        dispatch_notifications,
        "send_to_all",
        lambda db, payload: {"sent": 1, "failed": 0, "removed": 0, "subscriptions": 1},
    )

    _choose_slots(db_session, ["18:00"], changed_at=_utc(10, 0))

    assert [r["status"] for r in dispatch_notifications.run(_utc(18, 5))] == ["sent"]
