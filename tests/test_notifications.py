from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.jobs import dispatch_notifications
from app.models import PushSubscription, Spotlight, Word
from app.services.push import build_payload
from app.services.spotlight import local_slot_instant

BRUSSELS = ZoneInfo("Europe/Brussels")

SUBSCRIPTION = {
    "endpoint": "https://web.push.apple.com/abc123",
    "keys": {"p256dh": "BPublicKeyValue", "auth": "AuthSecret"},
    "user_agent": "iPhone",
}


@pytest.fixture
def a_word(db_session: Session) -> Word:
    word = Word(
        word="Haus",
        search_key="haus",
        type="nomen",
        meaning="house",
        attrs={"artikel": "das", "plural": "Häuser"},
        example=[{"de": "Das Haus ist groß.", "meaning": "The house is big."}],
    )
    db_session.add(word)
    db_session.commit()
    db_session.refresh(word)
    return word


@pytest.fixture
def push_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "test-public-key")
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "test-private-key")


# --- auth --------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/notifications/status"),
        ("get", "/notifications/vapid-key"),
        ("post", "/notifications/subscribe"),
        ("post", "/notifications/unsubscribe"),
        ("post", "/notifications/test"),
        ("get", "/spotlight"),
    ],
)
def test_notification_endpoints_require_auth(client: TestClient, method: str, path: str) -> None:
    assert getattr(client, method)(path).status_code == 401


# --- subscriptions -----------------------------------------------------------


def test_subscribe_stores_the_subscription(
    client: TestClient, auth_headers: dict, db_session: Session
) -> None:
    resp = client.post("/notifications/subscribe", json=SUBSCRIPTION, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["subscribed"] is True
    assert resp.json()["subscription_count"] == 1

    stored = db_session.execute(select(PushSubscription)).scalar_one()
    assert stored.endpoint == SUBSCRIPTION["endpoint"]
    assert stored.p256dh == "BPublicKeyValue"
    assert stored.user_agent == "iPhone"


def test_resubscribing_same_endpoint_refreshes_keys_without_duplicating(
    client: TestClient, auth_headers: dict, db_session: Session
) -> None:
    """Browsers rotate an endpoint's keys; storing a second row (or keeping the
    stale keys) would break every later send."""
    client.post("/notifications/subscribe", json=SUBSCRIPTION, headers=auth_headers)
    rotated = {**SUBSCRIPTION, "keys": {"p256dh": "BRotatedKey", "auth": "RotatedAuth"}}
    resp = client.post("/notifications/subscribe", json=rotated, headers=auth_headers)

    assert resp.status_code == 201
    assert resp.json()["subscription_count"] == 1
    stored = db_session.execute(select(PushSubscription)).scalar_one()
    assert stored.p256dh == "BRotatedKey"
    assert stored.auth == "RotatedAuth"


def test_unsubscribe_removes_it(client: TestClient, auth_headers: dict, db_session: Session) -> None:
    client.post("/notifications/subscribe", json=SUBSCRIPTION, headers=auth_headers)
    resp = client.post(
        "/notifications/unsubscribe",
        json={"endpoint": SUBSCRIPTION["endpoint"]},
        headers=auth_headers,
    )
    assert resp.status_code == 204
    assert db_session.execute(select(PushSubscription)).first() is None


def test_unsubscribe_unknown_endpoint_is_not_an_error(client: TestClient, auth_headers: dict) -> None:
    resp = client.post(
        "/notifications/unsubscribe", json={"endpoint": "https://nope"}, headers=auth_headers
    )
    assert resp.status_code == 204


def test_status_reports_slots_and_timezone(client: TestClient, auth_headers: dict) -> None:
    body = client.get("/notifications/status", headers=auth_headers).json()
    assert body["slots"] == ["09:00", "12:00", "15:00", "18:00", "22:00"]
    assert body["timezone"] == "Europe/Brussels"
    assert body["subscribed"] is False
    assert body["next_slot_at"] is not None


def test_status_subscribed_flag_is_per_endpoint(client: TestClient, auth_headers: dict) -> None:
    client.post("/notifications/subscribe", json=SUBSCRIPTION, headers=auth_headers)

    mine = client.get(
        "/notifications/status", params={"endpoint": SUBSCRIPTION["endpoint"]}, headers=auth_headers
    ).json()
    other = client.get(
        "/notifications/status", params={"endpoint": "https://other-device"}, headers=auth_headers
    ).json()

    assert mine["subscribed"] is True
    assert other["subscribed"] is False
    assert other["subscription_count"] == 1


def test_vapid_key_reports_disabled_when_unset(client: TestClient, auth_headers: dict) -> None:
    body = client.get("/notifications/vapid-key", headers=auth_headers).json()
    assert body["push_enabled"] is False


def test_vapid_key_returned_when_configured(
    client: TestClient, auth_headers: dict, push_configured: None
) -> None:
    body = client.get("/notifications/vapid-key", headers=auth_headers).json()
    assert body == {"public_key": "test-public-key", "push_enabled": True}


# --- /spotlight --------------------------------------------------------------


def test_spotlight_returns_a_word(client: TestClient, auth_headers: dict, a_word: Word) -> None:
    body = client.get("/spotlight", headers=auth_headers).json()
    assert body["word"]["id"] == a_word.id
    assert body["word"]["meaning"] == "house"
    assert body["slot"] in {"09:00", "12:00", "15:00", "18:00", "22:00"}


def test_spotlight_404s_without_words(client: TestClient, auth_headers: dict) -> None:
    assert client.get("/spotlight", headers=auth_headers).status_code == 404


def test_spotlight_is_stable_across_calls(
    client: TestClient, auth_headers: dict, db_session: Session
) -> None:
    """The dashboard must not reshuffle on every refresh."""
    db_session.add_all(
        [
            Word(word=f"Wort{i}", search_key=f"wort{i}", type="nomen", meaning=f"m{i}")
            for i in range(30)
        ]
    )
    db_session.commit()

    first = client.get("/spotlight", headers=auth_headers).json()["word"]["id"]
    second = client.get("/spotlight", headers=auth_headers).json()["word"]["id"]
    assert first == second


def test_spotlight_matches_the_word_the_notification_carried(
    client: TestClient, auth_headers: dict, db_session: Session, a_word: Word
) -> None:
    body = client.get("/spotlight", headers=auth_headers).json()
    recorded = db_session.execute(select(Spotlight)).scalar_one()
    assert body["word"]["id"] == recorded.word_id


# --- payload -----------------------------------------------------------------


def test_payload_puts_the_article_in_the_title(a_word: Word) -> None:
    payload = build_payload(a_word, "09:00")
    assert payload["title"] == "das Haus"
    assert payload["body"] == "house"
    assert payload["example"] == "Das Haus ist groß."
    assert payload["url"].endswith(f"/word/{a_word.id}")


def test_payload_truncates_a_long_meaning(db_session: Session) -> None:
    word = Word(word="lang", search_key="lang", type="adjektiv", meaning="x" * 400)
    db_session.add(word)
    db_session.commit()

    payload = build_payload(word, "09:00")
    assert len(payload["body"]) <= 120
    assert payload["body"].endswith("…")


def test_payload_without_article_or_example(db_session: Session) -> None:
    word = Word(word="schnell", search_key="schnell", type="adjektiv", meaning="fast")
    db_session.add(word)
    db_session.commit()

    payload = build_payload(word, "12:00")
    assert payload["title"] == "schnell"
    assert payload["example"] is None


# --- dispatcher --------------------------------------------------------------


def test_dispatch_sends_once_then_reports_already_sent(
    db_session: Session, a_word: Word, push_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    sends: list[dict] = []
    monkeypatch.setattr(
        dispatch_notifications,
        "send_to_all",
        lambda db, payload: sends.append(payload) or {"sent": 1, "failed": 0, "removed": 0, "subscriptions": 1},
    )

    now = datetime(2026, 7, 1, 9, 10, tzinfo=BRUSSELS).astimezone(timezone.utc)
    first = dispatch_notifications.run(now)
    assert [r["status"] for r in first] == ["sent"]
    assert len(sends) == 1
    assert sends[0]["title"] == "das Haus"

    second = dispatch_notifications.run(now)
    assert [r["status"] for r in second] == ["already-sent"]
    assert len(sends) == 1


def test_dispatch_does_nothing_outside_a_slot(
    db_session: Session, a_word: Word, push_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatch_notifications, "send_to_all", lambda db, payload: pytest.fail("sent"))
    now = datetime(2026, 7, 1, 8, 0, tzinfo=BRUSSELS).astimezone(timezone.utc)
    assert dispatch_notifications.run(now) == []


def test_dispatch_without_words_reports_no_words(db_session: Session, push_configured: None) -> None:
    now = datetime(2026, 7, 1, 9, 10, tzinfo=BRUSSELS).astimezone(timezone.utc)
    assert [r["status"] for r in dispatch_notifications.run(now)] == ["no-words"]


def test_dispatch_keeps_the_pick_when_push_is_not_configured(
    db_session: Session, a_word: Word
) -> None:
    """Without VAPID keys the word is still chosen (the app shows it) and the
    slot stays unsent, so it goes out once the keys are added."""
    now = datetime(2026, 7, 1, 9, 10, tzinfo=BRUSSELS).astimezone(timezone.utc)
    assert [r["status"] for r in dispatch_notifications.run(now)] == ["push-disabled"]

    spotlight = db_session.execute(select(Spotlight)).scalar_one()
    assert spotlight.word_id == a_word.id
    assert spotlight.pushed_at is None


def test_dispatch_skips_a_word_deleted_after_selection(
    db_session: Session, a_word: Word, push_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatch_notifications, "send_to_all", lambda db, payload: pytest.fail("sent"))
    scheduled = local_slot_instant(date(2026, 7, 1), time(9, 0), BRUSSELS)
    db_session.add(
        Spotlight(slot_date=date(2026, 7, 1), slot="09:00", word_id=a_word.id, scheduled_for=scheduled)
    )
    a_word.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    now = datetime(2026, 7, 1, 9, 10, tzinfo=BRUSSELS).astimezone(timezone.utc)
    assert [r["status"] for r in dispatch_notifications.run(now)] == ["word-gone"]


def test_test_push_requires_configured_keys(
    client: TestClient, auth_headers: dict, a_word: Word
) -> None:
    assert client.post("/notifications/test", headers=auth_headers).status_code == 503


def test_test_push_409s_without_words(
    client: TestClient, auth_headers: dict, push_configured: None
) -> None:
    assert client.post("/notifications/test", headers=auth_headers).status_code == 409


# --- delivery ----------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _add_subscription(db: Session, endpoint: str) -> PushSubscription:
    sub = PushSubscription(endpoint=endpoint, p256dh="key", auth="auth")
    db.add(sub)
    db.commit()
    return sub


def test_send_to_all_drops_subscriptions_the_push_service_reports_as_gone(
    db_session: Session, push_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 410 is the only way a browser tells us permission was revoked, so that
    row must go rather than fail forever."""
    import pywebpush

    from app.services.push import send_to_all

    _add_subscription(db_session, "https://push/live")
    _add_subscription(db_session, "https://push/gone")

    def fake_webpush(subscription_info, **kwargs):
        if subscription_info["endpoint"].endswith("gone"):
            raise pywebpush.WebPushException("gone", response=_FakeResponse(410))

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)

    summary = send_to_all(db_session, {"title": "x"})
    assert summary == {"sent": 1, "failed": 0, "removed": 1, "subscriptions": 2}

    remaining = db_session.execute(select(PushSubscription)).scalars().all()
    assert [s.endpoint for s in remaining] == ["https://push/live"]
    assert remaining[0].last_success_at is not None


def test_send_to_all_keeps_a_subscription_that_failed_temporarily(
    db_session: Session, push_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pywebpush

    from app.services.push import send_to_all

    _add_subscription(db_session, "https://push/flaky")

    def fake_webpush(subscription_info, **kwargs):
        raise pywebpush.WebPushException("boom", response=_FakeResponse(500))

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)

    summary = send_to_all(db_session, {"title": "x"})
    assert summary["failed"] == 1 and summary["removed"] == 0
    assert db_session.execute(select(PushSubscription)).scalar_one().failure_count == 1


def test_send_to_all_continues_past_one_broken_subscription(
    db_session: Session, push_configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pywebpush

    from app.services.push import send_to_all

    _add_subscription(db_session, "https://push/bad")
    _add_subscription(db_session, "https://push/good")

    def fake_webpush(subscription_info, **kwargs):
        if subscription_info["endpoint"].endswith("bad"):
            raise RuntimeError("unexpected")

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)

    summary = send_to_all(db_session, {"title": "x"})
    assert summary["sent"] == 1 and summary["failed"] == 1


def test_send_to_all_raises_when_not_configured(db_session: Session) -> None:
    from app.services.push import PushNotConfigured, send_to_all

    with pytest.raises(PushNotConfigured):
        send_to_all(db_session, {"title": "x"})
