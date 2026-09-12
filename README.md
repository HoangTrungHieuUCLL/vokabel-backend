# vokabel-backend

FastAPI backend for a personal German vocabulary logger. Single user, JWT auth,
Postgres with `pg_trgm` for fuzzy search support (the actual fuzzy matching
happens client-side; the backend just stores a normalized `search_key`).

## Stack

Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, psycopg 3, Pydantic v2, uvicorn.
Tests with pytest + httpx.

## Local setup

Requires a local Postgres instance (via Homebrew, Postgres.app, or Docker).

```bash
python3.12 -m venv .venv   # 3.11/3.13 also work for local dev
source .venv/bin/activate
pip install -r requirements-dev.txt

createdb vokabel
psql -d vokabel -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

cp .env.example .env
# edit .env: set DATABASE_URL to your local Postgres, and generate a password hash:
python scripts/hash_password.py 'your-password' # paste output into APP_PASSWORD_HASH

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Note: do **not** `source .env` in a shell before running commands — the
bcrypt hash contains `$` characters that bash will try to expand as
variables. Let `pydantic-settings` load `.env` directly (it does, via
`env_file=".env"` in `app/config.py`).

### Running tests

Tests run against a real Postgres database (`vokabel_test` by default) and
apply the actual Alembic migrations, so schema drift between tests and
production is impossible.

```bash
createdb vokabel_test
pip install -r requirements-dev.txt
pytest
```

Override the test database with `TEST_DATABASE_URL` if needed.

### Docker Compose (local Postgres + API in containers)

```bash
export APP_PASSWORD_HASH=$(python scripts/hash_password.py 'your-password')
docker compose up --build
```

The API runs `alembic upgrade head` automatically on container start.

## Environment variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL, e.g. `postgresql+psycopg://user:pass@host:5432/db` |
| `JWT_SECRET` | HS256 signing key for auth tokens |
| `APP_USERNAME` | The single user's username |
| `APP_PASSWORD_HASH` | bcrypt hash from `scripts/hash_password.py` |
| `CORS_ORIGINS` | Comma-separated list of allowed origins (the frontend URL) |
| `PORT` | Port uvicorn binds to (Railway sets this automatically) |

## Deploying to Railway

1. Create a new Railway project, add a Postgres plugin.
2. Add a service from this GitHub repo.
3. Set the environment variables above. `DATABASE_URL` can reference
   Railway's Postgres plugin variable (`${{Postgres.DATABASE_URL}}`), but
   note it must use the `postgresql+psycopg://` scheme, not the plugin's
   default `postgresql://` — adjust it in the service's variable if needed.
4. Railway builds the Dockerfile and runs migrations automatically on deploy
   (the container's `CMD` runs `alembic upgrade head` before starting uvicorn).
5. Set `CORS_ORIGINS` to your deployed frontend's URL once it exists.

## API

See `app/routers/` for the full endpoint list. Everything except `/healthz`
and `/auth/login` requires `Authorization: Bearer <token>`.
