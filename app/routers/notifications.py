from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.db import get_db
from app.models import PushSubscription, Word
from app.schemas import (
    NotificationStatus,
    NotifySettingsIn,
    NotifySettingsOut,
    PushSubscriptionIn,
    PushSubscriptionRef,
    SpotlightOut,
    VapidKeyOut,
)
from app.services.notify_settings import MAX_SLOTS, InvalidSlots, get_slots, is_customised, set_slots
from app.services.push import PushNotConfigured, build_payload, send_to_all
from app.services.spotlight import current_spotlight, next_slot_instant, slot_label

router = APIRouter(
    prefix="/notifications", tags=["notifications"], dependencies=[Depends(get_current_user)]
)


@router.get("/vapid-key", response_model=VapidKeyOut)
def vapid_key() -> VapidKeyOut:
    """The frontend fetches the key instead of baking it into the bundle, so
    rotating the pair needs no frontend redeploy."""
    return VapidKeyOut(public_key=settings.VAPID_PUBLIC_KEY, push_enabled=settings.push_enabled)


@router.get("/status", response_model=NotificationStatus)
def notification_status(endpoint: str | None = None, db: Session = Depends(get_db)) -> NotificationStatus:
    total = db.scalar(select(func.count()).select_from(PushSubscription)) or 0
    subscribed = False
    if endpoint:
        subscribed = (
            db.execute(
                select(PushSubscription.id).where(PushSubscription.endpoint == endpoint)
            ).scalar_one_or_none()
            is not None
        )
    return NotificationStatus(
        push_enabled=settings.push_enabled,
        subscribed=subscribed,
        subscription_count=total,
        slots=[slot_label(s) for s in get_slots(db)],
        timezone=settings.NOTIFY_TIMEZONE,
        next_slot_at=next_slot_instant(datetime.now(timezone.utc), slots=get_slots(db)),
    )


@router.post("/subscribe", status_code=status.HTTP_201_CREATED, response_model=NotificationStatus)
def subscribe(body: PushSubscriptionIn, db: Session = Depends(get_db)) -> NotificationStatus:
    existing = db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    ).scalar_one_or_none()

    if existing is None:
        db.add(
            PushSubscription(
                endpoint=body.endpoint,
                p256dh=body.keys.p256dh,
                auth=body.keys.auth,
                user_agent=body.user_agent,
            )
        )
    else:
        # Browsers rotate the keys of an existing endpoint; re-subscribing has
        # to refresh them or every later send fails to decrypt.
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
        existing.user_agent = body.user_agent
        existing.failure_count = 0
    db.commit()

    return notification_status(endpoint=body.endpoint, db=db)


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(body: PushSubscriptionRef, db: Session = Depends(get_db)) -> None:
    existing = db.execute(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    ).scalar_one_or_none()
    if existing is not None:
        db.delete(existing)
        db.commit()


def _settings_payload(db: Session) -> NotifySettingsOut:
    return NotifySettingsOut(
        slots=[slot_label(s) for s in get_slots(db)],
        timezone=settings.NOTIFY_TIMEZONE,
        customised=is_customised(db),
        max_slots=MAX_SLOTS,
    )


@router.get("/settings", response_model=NotifySettingsOut)
def read_settings(db: Session = Depends(get_db)) -> NotifySettingsOut:
    return _settings_payload(db)


@router.put("/settings", response_model=NotifySettingsOut)
def write_settings(body: NotifySettingsIn, db: Session = Depends(get_db)) -> NotifySettingsOut:
    try:
        set_slots(db, body.slots)
    except InvalidSlots as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    return _settings_payload(db)


@router.post("/test")
def send_test(db: Session = Depends(get_db)) -> dict:
    """Push the current spotlight word immediately, so a phone can be checked
    without waiting for the next slot."""
    spotlight = current_spotlight(db)
    if spotlight is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No words yet — add one first."
        )
    word = db.get(Word, spotlight.word_id)
    if word is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Spotlight word is missing.")

    payload = build_payload(word, spotlight.slot)
    payload["tag"] = "vokabel-test"
    try:
        return send_to_all(db, payload)
    except PushNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None


spotlight_router = APIRouter(
    prefix="/spotlight", tags=["spotlight"], dependencies=[Depends(get_current_user)]
)


@spotlight_router.get("", response_model=SpotlightOut)
def get_spotlight(db: Session = Depends(get_db)) -> SpotlightOut:
    """The word currently in the spotlight — the same one the last notification
    carried, so the dashboard and the phone never disagree."""
    now = datetime.now(timezone.utc)
    spotlight = current_spotlight(db, now)
    if spotlight is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No words yet")
    word = db.get(Word, spotlight.word_id)
    if word is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spotlight word is missing")

    return SpotlightOut(
        slot=spotlight.slot,
        slot_date=spotlight.slot_date,
        scheduled_for=spotlight.scheduled_for,
        next_slot_at=next_slot_instant(now, slots=get_slots(db)),
        word=word,
    )
