import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://hieuhoangtrung@localhost:5432/vokabel_test"
)
TEST_PASSWORD = "testpass123"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("APP_USERNAME", "testuser")
os.environ.setdefault("CORS_ORIGINS", "")
os.environ.setdefault("PORT", "8000")

import bcrypt  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

os.environ["APP_PASSWORD_HASH"] = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()

from app.auth import create_access_token  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()

    cfg = Config(os.path.join(BACKEND_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_ROOT, "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with engine.connect() as conn:
        # spotlights references words, so both go in one statement.
        conn.execute(text("TRUNCATE TABLE words, spotlights, push_subscriptions RESTART IDENTITY CASCADE"))
        conn.commit()


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token(os.environ["APP_USERNAME"])
    return {"Authorization": f"Bearer {token}"}
