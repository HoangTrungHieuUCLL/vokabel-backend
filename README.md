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
| `FRONTEND_URL` | Frontend origin, used to build the link a notification opens |
| `VAPID_PUBLIC_KEY` | Web Push public key from `scripts/generate_vapid_keys.py` |
| `VAPID_PRIVATE_KEY` | Web Push private key — backend only, never shipped to the browser |
| `VAPID_SUBJECT` | `mailto:` address push services contact about your sends |
| `NOTIFY_SLOTS` | Local times a word is pushed, until they are set in the app (default `09:00,12:00,15:00,18:00,22:00`) |
| `NOTIFY_TIMEZONE` | IANA zone the slots are interpreted in (default `Europe/Brussels`) |
| `NOTIFY_CATCHUP_MINUTES` | How late a missed slot may still be delivered (default 90) |
| `SPOTLIGHT_COOLDOWN_DAYS` | Days before a pushed word can be picked again (default 30) |

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

## Daily word notifications

Words are pushed to subscribed browsers at times the user chooses in the
app's Settings, stored in `notification_settings`. Until they are set for the
first time, `NOTIFY_SLOTS` applies (09:00, 12:00, 15:00, 18:00 and 22:00 by
default), so an existing deployment keeps its behaviour without a write.

Changing the times never fires a slot retroactively: a slot that fell before
the times were last edited is skipped, so adding an earlier time does not ring
the phone the moment it is saved.

The word for each slot is written to the `spotlights` table *before* the push
is attempted, and `GET /spotlight` reads that same row — so the card in the app
and the notification on the phone can never name different words. Each slot is
one row with a `(slot_date, slot)` unique constraint, which makes re-running
the dispatcher a no-op instead of a second notification.

Selection prefers words not pushed in the last `SPOTLIGHT_COOLDOWN_DAYS` days
and never repeats a word within the same day; with a vocabulary too small for
that it falls back rather than skipping the slot.

### Setup

```bash
python scripts/generate_vapid_keys.py   # once; put the output in the environment
```

Then schedule the dispatcher:

```bash
python -m app.jobs.dispatch_notifications
```

On Railway, add a **second service** from this same repo with:

- Start command: `python -m app.jobs.dispatch_notifications`
- Cron schedule: `0 * * * *`
- The same `DATABASE_URL` and `VAPID_*` variables as the API service

Run it **hourly**, not at the five slot times. Railway's cron is UTC, so a
fixed UTC expression would drift by an hour at every DST change; running
hourly lets the job read the local wall clock itself and pick up whichever
slots have come due. A slot missed because of a redeploy is delivered by the
next run as long as it is within `NOTIFY_CATCHUP_MINUTES`.

With the VAPID keys unset the job still records each slot's word (so the app's
spotlight card works) and simply skips delivery.

### iOS

iPhones only accept web push for a site **installed to the home screen**
(Share → Add to Home Screen, iOS 16.4+). Notifications cannot be enabled from
a normal Safari tab; the frontend's Settings page explains this in place.

## API

See `app/routers/` for the full endpoint list. Everything except `/healthz`
and `/auth/login` requires `Authorization: Bearer <token>`.
