"""Web Push delivery.

iOS only accepts web push for a site installed to the home screen (iOS 16.4+),
but the protocol itself is the standard VAPID flow, so nothing here is
Apple-specific.
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PushSubscription, Word

logger = logging.getLogger(__name__)

# Apple's push service rejects payloads noticeably smaller than the 4KB spec
# limit, and a truncated meaning is better than a dropped notification.
MAX_BODY_CHARS = 120
# If a phone is offline longer than this the word has already been superseded.
TTL_SECONDS = 3 * 60 * 60


class PushNotConfigured(RuntimeError):
    pass


def _truncate(text: str, limit: int = MAX_BODY_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_payload(word: Word, slot: str) -> dict:
    """Title carries the word (with its article, which is half of learning a
    noun); the body carries the meaning."""
    artikel = word.attrs.get("artikel") if isinstance(word.attrs, dict) else None
    title = f"{artikel} {word.word}" if artikel else word.word
    example = word.example[0]["de"] if word.example and isinstance(word.example[0], dict) else None

    base = settings.FRONTEND_URL.rstrip("/")
    return {
        "title": _truncate(title, 60),
        "body": _truncate(word.meaning),
        "example": _truncate(example, 100) if example else None,
        "url": f"{base}/word/{word.id}" if base else f"/word/{word.id}",
        "wordId": word.id,
        "slot": slot,
        # One tag for all of them: a phone that was offline shows the newest
        # word rather than a stack of stale ones.
        "tag": "vokabel-spotlight",
    }


def send_to_all(db: Session, payload: dict) -> dict:
    """Deliver to every stored subscription. Returns a per-run summary.

    Subscriptions the push service reports as gone (404/410) are deleted --
    that is the only way a browser tells us it revoked permission.
    """
    if not settings.push_enabled:
        raise PushNotConfigured("VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY are not set")

    from pywebpush import WebPushException, webpush

    subscriptions = list(db.execute(select(PushSubscription)).scalars())
    sent = 0
    failed = 0
    removed = 0
    now = datetime.now(timezone.utc)
    data = json.dumps(payload)

    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=data,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                # pywebpush mutates the claims dict (it fills in aud/exp), so
                # every call gets its own copy.
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                ttl=TTL_SECONDS,
            )
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (404, 410):
                db.delete(sub)
                removed += 1
            else:
                sub.failure_count += 1
                failed += 1
                logger.warning("push failed (%s) for %s", status, sub.endpoint[:60])
        except Exception:  # noqa: BLE001 - one bad subscription must not stop the rest
            sub.failure_count += 1
            failed += 1
            logger.exception("unexpected push error for %s", sub.endpoint[:60])
        else:
            sent += 1
            sub.failure_count = 0
            sub.last_success_at = now

    db.commit()
    return {"sent": sent, "failed": failed, "removed": removed, "subscriptions": len(subscriptions)}
