"""Send the notification for every slot that has come due.

Run it on a schedule (Railway cron, `0 * * * *`). Running it hourly rather
than at the five exact slot times keeps it correct across DST: the job asks
what the local wall clock says instead of trusting a UTC cron expression to
still line up in October.

Re-running it is safe -- a slot already marked `pushed_at` is skipped.
"""

import logging
import sys
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import Word
from app.services.notify_settings import get_changed_at, get_slots
from app.services.push import PushNotConfigured, build_payload, send_to_all
from app.services.spotlight import due_slots, ensure_spotlight, slot_label

logger = logging.getLogger(__name__)


def run(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    results: list[dict] = []

    with SessionLocal() as db:
        slots = get_slots(db)
        changed_at = get_changed_at(db)

        for slot_date, slot, scheduled_for in due_slots(now, slots=slots):
            label = slot_label(slot)

            # A slot that fell before the times were last edited is not
            # delivered. Otherwise adding an earlier time would fire it
            # immediately, so changing the schedule would itself ring the
            # phone -- surprising, and the catch-up window makes it likely.
            if changed_at is not None and scheduled_for < changed_at:
                results.append(
                    {"slot": label, "date": slot_date.isoformat(), "status": "before-settings-change"}
                )
                continue

            spotlight = ensure_spotlight(db, slot_date, slot, scheduled_for)
            if spotlight is None:
                results.append({"slot": label, "date": slot_date.isoformat(), "status": "no-words"})
                continue
            if spotlight.pushed_at is not None:
                results.append({"slot": label, "date": slot_date.isoformat(), "status": "already-sent"})
                continue

            word = db.get(Word, spotlight.word_id)
            if word is None or word.deleted_at is not None:
                # The pick was deleted between selection and delivery. Mark it
                # handled rather than retrying a word that no longer exists.
                spotlight.pushed_at = now
                db.commit()
                results.append({"slot": label, "date": slot_date.isoformat(), "status": "word-gone"})
                continue

            try:
                summary = send_to_all(db, build_payload(word, label))
            except PushNotConfigured:
                # Keep the pick (the app still shows it) but leave pushed_at
                # unset so the slot goes out once keys are configured.
                results.append({"slot": label, "date": slot_date.isoformat(), "status": "push-disabled"})
                continue

            spotlight.pushed_at = now
            db.commit()
            results.append(
                {
                    "slot": label,
                    "date": slot_date.isoformat(),
                    "status": "sent",
                    "word": word.word,
                    **summary,
                }
            )

    return results


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    results = run()
    if not results:
        logger.info("no slots due")
    for result in results:
        logger.info("slot %s %s: %s", result["date"], result["slot"], result["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
