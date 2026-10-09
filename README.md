# Majeed Portfolio — Backend

The admin CMS API. FastAPI + SQLAlchemy + Alembic, on **Neon PostgreSQL**.
Deploys to **Render**.

The public site and admin panel live in a separate repository:
**[Majeed-Portfolio-Frontend](https://github.com/hajihajara73-gif/Majeed-Portfolio-Frontend)**
(React + Vite, deploys to Vercel).

```
frontend repo (Vercel)                  this repo (Render)
┌──────────────────────┐                ┌──────────────────┐
│  /         public    │  contact form  │  FastAPI         │
│            site      │ ─────────────► │  /api/public/*   │
│  /admin/   admin SPA │  admin API     │  /api/admin/*    │
└──────────────────────┘ ─────────────► └────────┬─────────┘
   static, no DB access                          ▼
                                        Neon PostgreSQL (TLS)
```

The public site is built from a content snapshot this API exports, so a visitor's
page load never reaches the database. Architecture and the reasoning behind it:
[`docs/ADMIN.md`](docs/ADMIN.md).

## Setup

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"     # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # macOS / Linux
```

### Configure

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # SECRET_KEY
```

`DATABASE_URL` and `SECRET_KEY` are required; the app will not start without
them. In production it additionally refuses to start unless `CORS_ORIGINS`,
`ALLOWED_HOSTS`, `TRUSTED_PROXY_COUNT` and `STORAGE_ROOT` are set correctly —
each of those is silent at boot and only visible from a browser console, or from
an audit months later, so failing on startup is the cheapest place to catch them.

### Migrate, seed, create an admin

```bash
python -m alembic upgrade head
python -m app.seed                       # idempotent; needs FRONTEND_ROOT (below)
python -m app.cli create-admin
python -m app.cli enable-2fa             # do this before going public
```

### Run

```bash
uvicorn app.main:app --reload --port 8000
```

- Health: <http://localhost:8000/api/health>
- Docs: <http://localhost:8000/docs> — development only; disabled in production,
  because the schema is a map of the attack surface

## Commands

| Command | Does |
| --- | --- |
| `python -m pytest` | Test suite |
| `ruff check app tests` | Lint |
| `python -m alembic upgrade head` | Apply migrations |
| `python -m alembic check` | Fail if models have drifted from migrations |
| `python -m app.seed` | Seed content (idempotent) |
| `python -m app.export` | Write the published snapshot into the frontend |
| `python -m app.cli create-admin` | Create an admin account |
| `python -m app.cli reset-password` | Reset a password, clear lockout, sign out every session |
| `python -m app.cli list-admins` | List accounts and 2FA status |
| `python -m app.cli enable-2fa` / `disable-2fa` | Enrol or remove an authenticator |

## `FRONTEND_ROOT` — required for seed and export

Two operations legitimately reach into the frontend, and both are **local,
build-time** jobs the deployed service never performs:

- `python -m app.export` writes `src/content/snapshot.json` there, and copies the
  uploaded media it references into `public/`
- `python -m app.seed` reads `public/` for the assets that shipped with the site

By default they look for a `frontend/` directory **beside** this one, which is the
monorepo layout. With the two repositories cloned separately, point at it:

```bash
FRONTEND_ROOT=/path/to/Majeed-Portfolio-Frontend python -m app.export
```

## Tests

**152 tests**, run against in-memory SQLite — no database server needed, because
tests that need one stop being run. They assert security *properties* rather than
happy paths: account enumeration, lockout, CSRF rejection, session revocation,
TOTP replay, 2FA brute force, SQL-injection payloads treated as data, storage-key
traversal, stored XSS, oversized bodies, forwarded-IP spoofing, and that no
session is issued before the second factor succeeds.

```
tests/test_auth.py            authentication and sessions
tests/test_admin_api.py       CRUD, authorisation, uploads, publishing
tests/test_public_api.py      the contact endpoint and its abuse controls
tests/test_publish_export.py  rollback, deploy hook, snapshot export
tests/test_security_audit.py  the Phase 7 adversarial suite
tests/test_deployment.py      proxies, hosts, CORS, cookies, paths
```

## Render

| Setting | Value |
| --- | --- |
| Service type | Web Service |
| Runtime | Python 3.13, from `.python-version` |
| Root directory | *(repository root — leave blank)* |
| Build command | `pip install .` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'` |
| Health check | `/api/health` |
| Persistent disk | 1 GB at `/var/data`, with `STORAGE_ROOT=/var/data/storage` |

`render.yaml` declares all of this as a Blueprint and contains **no secret
values** — everything sensitive is `sync: false`, so Render asks for it and it
never enters git.

**The disk is not optional if the media library is used.** Render's filesystem is
ephemeral: without it, every deploy leaves the library full of rows whose files no
longer exist.

**`TRUSTED_PROXY_COUNT=1` is not optional either.** Every per-IP limit depends on
it. Left at 0 behind Render's proxy, all visitors share one rate-limit bucket; and
the leftmost `X-Forwarded-For` entry is attacker-supplied, so the setting is what
tells the app to read the entry the proxy appended instead.

Full procedure, environment variables, DNS and smoke tests:
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Documentation

| Document | Covers |
| --- | --- |
| `docs/ADMIN.md` | CMS architecture, security model, the publish pipeline |
| `docs/DEPLOYMENT.md` | Vercel + Render + Neon, environment variables, DNS, smoke tests, manual actions |
| `docs/PHASE-7-PRODUCTION-AUDIT.md` | Security audit findings and evidence. Its paths predate the repository split |
| `docs/SPEC.md` | The public site's specification, for context |
| `CLAUDE.md` | Working rules for this codebase |
