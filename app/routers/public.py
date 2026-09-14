from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WORD_TYPES, Word

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/stats")
def public_stats(db: Session = Depends(get_db)) -> dict:
    """Aggregate counts only -- no word text, meanings, or examples. Safe to
    expose without auth for a portfolio dashboard to read."""
    total = db.scalar(select(func.count()).select_from(Word).where(Word.deleted_at.is_(None))) or 0
    hard = db.scalar(
        select(func.count()).select_from(Word).where(Word.deleted_at.is_(None), Word.is_hard.is_(True))
    ) or 0

    by_type_rows = db.execute(
        select(Word.type, func.count())
        .where(Word.deleted_at.is_(None))
        .group_by(Word.type)
    ).all()
    by_type_counts = dict(by_type_rows)
    by_type = {t: by_type_counts.get(t, 0) for t in WORD_TYPES}

    since = datetime.now(timezone.utc) - timedelta(days=30)
    daily_rows = db.execute(
        select(func.date(Word.created_at), func.count())
        .where(Word.created_at >= since)
        .group_by(func.date(Word.created_at))
    ).all()
    daily_counts = {d.isoformat() if isinstance(d, date) else str(d): c for d, c in daily_rows}
    added_last_30_days = [
        {"date": (date.today() - timedelta(days=i)).isoformat(), "count": daily_counts.get((date.today() - timedelta(days=i)).isoformat(), 0)}
        for i in range(29, -1, -1)
    ]

    return {
        "total_words": total,
        "hard_to_remember": hard,
        "by_type": by_type,
        "added_last_30_days": added_last_30_days,
    }
