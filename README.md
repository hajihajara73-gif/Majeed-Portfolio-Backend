# Admin API

FastAPI + PostgreSQL. Phase 1: authentication, 2FA, sessions, audit log.

Architecture and the reasoning behind it: [`docs/ADMIN.md`](../../docs/ADMIN.md).

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### Database

PostgreSQL 18 is already installed locally and listening on 5432. Create a
dedicated role — **do not run the app as the `postgres` superuser**:

```sql
CREATE ROLE mj_admin LOGIN PASSWORD 'choose-a-strong-one';
CREATE DATABASE mj_portfolio OWNER mj_admin;
```

`psql` is not on PATH; it lives at
`C:\Program Files\PostgreSQL\18\bin\psql.exe`.

### Configure

```bash
cp .env.example .env
# then edit DATABASE_URL and SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(48))"   # SECRET_KEY
```

### Migrate and create the first admin

```bash
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\python.exe -m app.cli create-admin
```

### Run

```bash
.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

- Health: <http://localhost:8000/api/health>
- Docs: <http://localhost:8000/docs> (development only)

## Commands

| Command | Does |
| --- | --- |
| `python -m app.cli create-admin` | Create an admin account |
| `python -m app.cli reset-password` | Reset a password, clear lockout, sign out all sessions |
| `python -m app.cli list-admins` | List accounts and 2FA status |
| `alembic upgrade head` | Apply migrations |
| `alembic upgrade head --sql` | Render the DDL without touching a database |
| `pytest -q` | Run the test suite |
| `ruff check app tests alembic` | Lint |

## Tests

18 tests, run against in-memory SQLite — no database server needed, because
tests that need one stop being run. They assert security *properties*, not just
happy paths: account enumeration, lockout, CSRF rejection, session revocation,
and that no session is issued before the second factor succeeds.

## Deployment note

`X-Forwarded-For` is trusted when present. Behind a proxy, uvicorn must run with
`--forwarded-allow-ips` restricted to that proxy's address — otherwise a client
can forge the header and walk straight past the per-IP rate limit.
