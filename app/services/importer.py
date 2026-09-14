import csv
import io
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Word
from app.normalize import UMLAUTS, make_search_key
from app.schemas import validate_attrs

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000

TYPE_ALIASES: dict[str, set[str]] = {
    "nomen": {"nomen", "noun", "n", "n.", "substantiv", "hauptwort"},
    "verb": {"verb", "verben", "v", "v."},
    "adjektiv": {"adjektiv", "adjective", "adj", "adj."},
    "adverb": {"adverb", "adv", "adv."},
    "praeposition": {"praeposition", "preposition", "prep", "prep.", "praep", "praep."},
    "konjunktion": {"konjunktion", "conjunction", "conj", "conj."},
    "pronomen": {"pronomen", "pronoun", "pron", "pron."},
    "partikel": {"partikel", "particle", "part", "part."},
    "phrase": {"phrase", "phrases", "idiom", "redewendung", "kollokation", "chunk"},
}

FIELD_ALIASES: dict[str, set[str]] = {
    "word": {"word", "wort", "term", "front", "vokabel"},
    "meaning": {"meaning", "bedeutung", "translation", "back", "nghia"},
    "type": {"type", "art", "wortart", "pos"},
    "example": {"example", "beispiel", "satz"},
    "tags": {"tags", "tag"},
    "source": {"source", "quelle"},
    "comment": {"comment", "kommentar", "notiz", "notes"},
}


def _fold(s: str) -> str:
    s = s.strip().lower().translate(UMLAUTS)
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for header in headers:
        folded = _fold(header)
        for field, aliases in FIELD_ALIASES.items():
            if field not in mapping and folded in aliases:
                mapping[field] = header
                break
    return mapping


def normalize_type(raw: str) -> str | None:
    folded = _fold(raw)
    for canonical, aliases in TYPE_ALIASES.items():
        if folded in aliases:
            return canonical
    return None


def detect_encoding(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return enc, raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return "utf-8", raw.decode("utf-8", errors="replace")


def detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        return dialect.delimiter
    except csv.Error:
        return ","


@dataclass
class ParsedFile:
    encoding: str
    delimiter: str | None
    headers: list[str]
    rows: list[dict[str, Any]]


def parse_upload(raw: bytes) -> ParsedFile:
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"file exceeds {MAX_FILE_BYTES} bytes")

    encoding, text = detect_encoding(raw)
    stripped = text.strip()

    if stripped.startswith("["):
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise ValueError("JSON input must be an array of objects")
        if len(data) > MAX_ROWS:
            raise ValueError(f"file exceeds {MAX_ROWS} rows")
        headers = list(dict.fromkeys(k for row in data for k in row.keys()))
        return ParsedFile(encoding=encoding, delimiter=None, headers=headers, rows=data)

    sample = "\n".join(stripped.splitlines()[:2])
    delimiter = detect_delimiter(sample)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    rows = list(reader)
    if len(rows) > MAX_ROWS:
        raise ValueError(f"file exceeds {MAX_ROWS} rows")
    return ParsedFile(encoding=encoding, delimiter=delimiter, headers=headers, rows=rows)


def apply_mapping(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field, header in mapping.items():
        if not header:
            continue
        value = row.get(header)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
        if field == "tags" and isinstance(value, str):
            value = [t.strip() for t in value.replace(",", ";").split(";") if t.strip()]
        if value not in (None, "", []):
            out[field] = value
    return out


def build_preview(raw: bytes, db: Session) -> dict[str, Any]:
    parsed = parse_upload(raw)
    mapping = suggest_mapping(parsed.headers)

    row_errors: list[dict[str, Any]] = []
    seen_in_file: set[tuple[str, str]] = set()
    duplicates_in_file = 0
    duplicates_in_db = 0

    for i, raw_row in enumerate(parsed.rows, start=1):
        mapped = apply_mapping(raw_row, mapping)
        word = mapped.get("word")
        if not word:
            row_errors.append({"row": i, "reason": "missing word"})
            continue

        raw_type = mapped.get("type")
        canonical_type = normalize_type(raw_type) if raw_type else None
        if raw_type and canonical_type is None:
            row_errors.append({"row": i, "reason": f"type '{raw_type}' not recognised"})

        search_key = make_search_key(word)
        dedup_key = (search_key, canonical_type or raw_type or "")
        if dedup_key in seen_in_file:
            duplicates_in_file += 1
        else:
            seen_in_file.add(dedup_key)

        if canonical_type is not None:
            exists = db.execute(
                select(Word.id).where(
                    Word.search_key == search_key,
                    Word.type == canonical_type,
                    Word.deleted_at.is_(None),
                )
            ).first()
            if exists:
                duplicates_in_db += 1

    return {
        "encoding": parsed.encoding,
        "delimiter": parsed.delimiter,
        "total_rows": len(parsed.rows),
        "headers": parsed.headers,
        "suggested_mapping": mapping,
        "sample": [apply_mapping(r, mapping) for r in parsed.rows[:20]],
        "duplicates_in_db": duplicates_in_db,
        "duplicates_in_file": duplicates_in_file,
        "row_errors": row_errors,
    }


def commit_import(
    db: Session,
    rows: list[dict[str, Any]],
    mapping: dict[str, str],
    policy: str,
) -> dict[str, Any]:
    inserted = updated = skipped = 0
    errors: list[dict[str, Any]] = []

    for i, raw_row in enumerate(rows, start=1):
        mapped = apply_mapping(raw_row, mapping)
        word_text = mapped.get("word")
        if not word_text:
            errors.append({"row": i, "reason": "missing word"})
            continue

        raw_type = mapped.get("type")
        canonical_type = normalize_type(raw_type) if raw_type else None
        if canonical_type is None:
            reason = f"type '{raw_type}' not recognised" if raw_type else "missing type"
            errors.append({"row": i, "reason": reason})
            continue

        meaning = mapped.get("meaning")
        if not meaning:
            errors.append({"row": i, "reason": "missing meaning"})
            continue

        try:
            attrs = validate_attrs(canonical_type, {})
        except ValueError as exc:
            errors.append({"row": i, "reason": str(exc)})
            continue

        search_key = make_search_key(word_text)
        tags = mapped.get("tags") or []
        source = mapped.get("source")
        comment = mapped.get("comment")
        example = mapped.get("example")

        existing = db.execute(
            select(Word).where(
                Word.search_key == search_key,
                Word.type == canonical_type,
                Word.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

        if existing is not None:
            if policy == "skip":
                skipped += 1
                continue
            if policy == "overwrite":
                existing.meaning = meaning
                if example:
                    existing.example = example
                if tags:
                    existing.tags = tags
                if source:
                    existing.source = source
                if comment:
                    existing.comment = comment
                existing.updated_at = datetime.now(timezone.utc)
                updated += 1
                continue
            if policy == "append_meaning":
                existing.meaning = f"{existing.meaning}; {meaning}"
                existing.updated_at = datetime.now(timezone.utc)
                updated += 1
                continue

        db.add(
            Word(
                word=word_text,
                search_key=search_key,
                type=canonical_type,
                meaning=meaning,
                example=example,
                attrs=attrs,
                tags=tags,
                source=source,
                comment=comment,
            )
        )
        inserted += 1

    total = len(rows)
    if total > 0 and len(errors) / total > 0.5:
        db.rollback()
        return {"inserted": 0, "updated": 0, "skipped": 0, "errors": errors, "rolled_back": True}

    db.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "errors": errors}
