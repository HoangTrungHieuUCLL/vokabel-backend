from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.routers import auth, export, imports, words

app = FastAPI(title="Vokabel API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(words.router)
app.include_router(imports.router)
app.include_router(export.router)


@app.get("/healthz")
def healthz() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001 - health check must never raise
        db_ok = False
    return {"status": "ok" if db_ok else "error", "db": db_ok}
