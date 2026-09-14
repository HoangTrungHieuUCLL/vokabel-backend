from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import Word
from app.normalize import make_search_key
from app.schemas import BulkCreateResult, WordCreate, WordOut, WordUpdate, validate_attrs

router = APIRouter(prefix="/words", tags=["words"], dependencies=[Depends(get_current_user)])


def _get_word_or_404(db: Session, word_id: int) -> Word:
    word = db.get(Word, word_id)
    if word is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Word not found")
    return word


def _find_duplicate(db: Session, search_key: str, word_type: str, exclude_id: int | None = None) -> Word | None:
    stmt = select(Word).where(
        Word.search_key == search_key,
        Word.type == word_type,
        Word.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Word.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none()


@router.get("", response_model=list[WordOut])
def list_words(
    updated_since: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Word]:
    if updated_since is not None:
        stmt = select(Word).where(Word.updated_at >= updated_since)
    else:
        stmt = select(Word).where(Word.deleted_at.is_(None))
    return list(db.execute(stmt.order_by(Word.updated_at.desc())).scalars())


@router.post("", response_model=WordOut, status_code=status.HTTP_201_CREATED)
def create_word(body: WordCreate, db: Session = Depends(get_db)) -> Word:
    search_key = make_search_key(body.word)
    existing = _find_duplicate(db, search_key, body.type)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Duplicate word", "existing": WordOut.model_validate(existing).model_dump(mode="json")},
        )

    word = Word(
        word=body.word,
        search_key=search_key,
        type=body.type,
        meaning=body.meaning,
        example=body.example,
        attrs=body.attrs,
        tags=body.tags,
        source=body.source,
        comment=body.comment,
        is_hard=body.is_hard,
        hard_since=datetime.now(timezone.utc) if body.is_hard else None,
    )
    db.add(word)
    db.commit()
    db.refresh(word)
    return word


@router.patch("/{word_id}", response_model=WordOut)
def update_word(word_id: int, body: WordUpdate, db: Session = Depends(get_db)) -> Word:
    word = _get_word_or_404(db, word_id)
    data = body.model_dump(exclude_unset=True)

    new_type = data.get("type", word.type)
    if "attrs" in data:
        try:
            data["attrs"] = validate_attrs(new_type, data["attrs"])
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    elif "type" in data and new_type != word.type:
        try:
            data["attrs"] = validate_attrs(new_type, word.attrs)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None

    if "word" in data:
        new_search_key = make_search_key(data["word"])
        check_type = data.get("type", word.type)
        existing = _find_duplicate(db, new_search_key, check_type, exclude_id=word.id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "Duplicate word", "existing": WordOut.model_validate(existing).model_dump(mode="json")},
            )
        data["search_key"] = new_search_key

    if "is_hard" in data:
        if data["is_hard"] and not word.is_hard:
            data["hard_since"] = datetime.now(timezone.utc)
        elif not data["is_hard"] and word.is_hard:
            data["hard_since"] = None

    for key, value in data.items():
        setattr(word, key, value)
    word.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(word)
    return word


@router.delete("/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_word(word_id: int, db: Session = Depends(get_db)) -> None:
    word = _get_word_or_404(db, word_id)
    now = datetime.now(timezone.utc)
    word.deleted_at = now
    word.updated_at = now
    db.commit()


@router.post("/bulk", response_model=list[BulkCreateResult])
def bulk_create_words(bodies: list[dict], db: Session = Depends(get_db)) -> list[BulkCreateResult]:
    results: list[BulkCreateResult] = []
    for index, raw in enumerate(bodies):
        try:
            body = WordCreate.model_validate(raw)
        except ValidationError as exc:
            results.append(BulkCreateResult(index=index, status="error", error=str(exc)))
            continue

        search_key = make_search_key(body.word)
        existing = _find_duplicate(db, search_key, body.type)
        if existing is not None:
            results.append(
                BulkCreateResult(index=index, status="duplicate", word=WordOut.model_validate(existing))
            )
            continue

        word = Word(
            word=body.word,
            search_key=search_key,
            type=body.type,
            meaning=body.meaning,
            example=body.example,
            attrs=body.attrs,
            tags=body.tags,
            source=body.source,
            is_hard=body.is_hard,
            hard_since=datetime.now(timezone.utc) if body.is_hard else None,
        )
        db.add(word)
        try:
            db.commit()
        except Exception as exc:  # noqa: BLE001 - report per-row, never fail the batch
            db.rollback()
            results.append(BulkCreateResult(index=index, status="error", error=str(exc)))
            continue
        db.refresh(word)
        results.append(BulkCreateResult(index=index, status="created", word=WordOut.model_validate(word)))

    return results
