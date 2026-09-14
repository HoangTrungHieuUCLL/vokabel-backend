import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import Word

router = APIRouter(prefix="/export", tags=["export"], dependencies=[Depends(get_current_user)])

EXPORT_COLUMNS = ["word", "type", "meaning", "example", "tags", "source", "comment"]


def _row(word: Word) -> dict:
    return {
        "word": word.word,
        "type": word.type,
        "meaning": word.meaning,
        "example": word.example or "",
        "tags": ";".join(word.tags),
        "source": word.source or "",
        "comment": word.comment or "",
    }


@router.get("")
def export_words(format: Literal["csv", "json"] = Query(...), db: Session = Depends(get_db)) -> Response:
    words = list(
        db.execute(select(Word).where(Word.deleted_at.is_(None)).order_by(Word.word)).scalars()
    )

    if format == "json":
        body = json.dumps([_row(w) for w in words], ensure_ascii=False, indent=2)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=vokabel-export.json"},
        )

    if format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        for w in words:
            writer.writerow(_row(w))
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=vokabel-export.csv"},
        )

    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="format must be csv or json")
