import json
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.services.importer import build_preview, commit_import, parse_upload

router = APIRouter(prefix="/import", tags=["import"], dependencies=[Depends(get_current_user)])


@router.post("/preview")
async def import_preview(file: UploadFile, db: Session = Depends(get_db)) -> dict:
    raw = await file.read()
    try:
        return build_preview(raw, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None


@router.post("/commit")
async def import_commit(
    file: UploadFile,
    mapping: str = Form(...),
    policy: Literal["skip", "overwrite", "append_meaning"] = Form(...),
    db: Session = Depends(get_db),
) -> dict:
    raw = await file.read()
    try:
        parsed = parse_upload(raw)
        mapping_dict = json.loads(mapping)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None

    return commit_import(db, parsed.rows, mapping_dict, policy)
