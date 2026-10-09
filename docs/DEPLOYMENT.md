# Deployment — Vercel, Render, Neon

Prepared 2026-09-27, on top of the Phase 7 hardening (`cd84c75`). Everything here
was exercised locally against a simulation of the production serving model; what
could not be verified without live services is marked **MANUAL** and says why.

No domain is assumed anywhere. Every host-specific value is an environment
variable, and the applications **refuse to start or degrade honestly** when one
is missing rather than guessing.

**Start at §0 — it is the ordered runbook for this specific deployment.** The
numbered sections after it are the reference material behind each step.

---

## 0. Runbook — the actual deployment

The chosen shape, from the decisions taken on 2026-10-09:

| | Where | Host |
| --- | --- | --- |
| Public site + admin | Vercel | `DOMAIN` (apex) |
| API | Render, **free tier, no disk** | `api.DOMAIN` |
| Database | Neon | — |

Throughout, **`DOMAIN` means your `.me` domain** — substitute it everywhere it
appears. The apex layout keeps the site and the API on the same registrable
domain, which is what lets the admin session cookie stay on `SameSite=Lax`
(§9); do not split them across different domains.

Two consequences of the free tier, accepted knowingly:

- **Uploaded media does not survive a deploy.** Render's filesystem resets. The
  public site is unaffected — every asset it uses is committed in the frontend
  repository — but anything added through the admin media library afterwards is
  lost on the next deploy. Upgrading to a paid plan with a disk at `/var/data`
  and setting `STORAGE_ROOT=/var/data/storage` is the only change needed later.
- **The service sleeps when idle** and takes tens of seconds to wake. The first
  contact-form submission after a quiet period is slow; the form shows
  "Sending…" for the whole wait and then succeeds. It does not fail or lie.

### Order matters

Do these in sequence. Steps 1–3 are security actions and come before anything is
reachable; step 5 must happen before step 6, because the admin's API origin is
compiled into the bundle at build time.

---

### 1. Rotate the credentials that have been exposed

Both were pasted into a chat transcript. Treat both as compromised.

```bash
# Admin password
cd backend
python -m app.cli reset-password      # prompts; no echo; revokes every session
```

**Neon:** reset the role's password in the Neon console. You will paste the new
connection string into Render in step 4 — not into any file in git.

**GitHub:** the personal access token used to push is also in that transcript.
Revoke it at <https://github.com/settings/tokens>.

### 2. Enable two-factor authentication

```bash
cd backend
python -m app.cli enable-2fa
```

Store the ten recovery codes somewhere reachable without your phone — they are
shown exactly once. Do this before the admin is reachable from the internet.

### 3. Confirm the database is migrated

```bash
cd backend
python -m alembic current     # expect 0003_totp_hardening (head)
python -m alembic check       # expect "No new upgrade operations detected"
```

Nothing else is needed — Neon already holds the schema and content.

### 4. Create the Render service

From the **Majeed-Portfolio-Backend** repository. `render.yaml` is at its root, so
Render can read it as a Blueprint; otherwise enter these by hand:

| Setting | Value |
| --- | --- |
| Type | Web Service |
| Repository | `majeed74905/Majeed-Portfolio-Backend` |
| Branch | `main` |
| Root directory | *(leave blank — the app is at the repo root)* |
| Runtime | Python 3 |
| Build command | `pip install --upgrade pip && pip install .` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'` |
| Health check path | `/api/health` |
| Plan | Free |
| Region | Singapore *(nearest of Render's options to both you and a future `ap-south-1` Neon project)* |

Environment variables — the first five are already in `render.yaml`; the rest you
enter:

| Variable | Value |
| --- | --- |
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `TRUSTED_PROXY_COUNT` | `1` |
| `STORAGE_ROOT` | `/opt/render/project/src/storage` |
| `PYTHON_VERSION` | `3.13` |
| `SESSION_COOKIE_SAMESITE` | `lax` |
| `DATABASE_URL` | the **rotated** Neon string, including `?sslmode=require` |
| `SECRET_KEY` | a fresh value — `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `CORS_ORIGINS` | `https://DOMAIN` |
| `ALLOWED_HOSTS` | `mj-portfolio-api.onrender.com,api.DOMAIN` |
| `DEPLOY_HOOK_URL` | leave empty for now — see step 8 |

`ALLOWED_HOSTS` lists **both** the Render hostname and your custom one, so the
service keeps working before and after DNS moves. Use the real service hostname
Render assigns; it may differ from `mj-portfolio-api` if that name is taken.

**The service will refuse to start if any of this is wrong** — empty or localhost
`CORS_ORIGINS`/`ALLOWED_HOSTS`, a wildcard, plain `http`, `DEBUG=true`,
`TRUSTED_PROXY_COUNT=0`, or an unset `STORAGE_ROOT`. The logs name every problem
at once. That is deliberate: each of those is silent at boot and only visible
from a browser console weeks later.

Verify before continuing:

```bash
curl https://mj-portfolio-api.onrender.com/api/health     # {"status":"ok"}
curl -H "Host: evil.invalid" https://mj-portfolio-api.onrender.com/api/health   # 400
curl https://mj-portfolio-api.onrender.com/docs           # 404 — docs are off in production
```

### 5. Add the API's custom domain on Render

In the service's **Settings → Custom Domains**, add `api.DOMAIN`. Render shows
the CNAME target to use. Do the DNS in step 7.

### 6. Create the Vercel project

From the **Majeed-Portfolio-Frontend** repository.

| Setting | Value |
| --- | --- |
| Framework preset | Vite |
| Root directory | *(leave blank — the app is at the repo root)* |
| Build command | `npm run build:all` |
| Output directory | `dist` |
| Install command | *(default)* |

Environment variables, for **Production**. All three are compiled into the
browser bundle and are public — never put a credential in a `VITE_` variable:

| Variable | Value |
| --- | --- |
| `VITE_SITE_URL` | `https://DOMAIN` |
| `VITE_CONTACT_ENDPOINT` | `https://api.DOMAIN/api/public/contact` |
| `VITE_API_BASE_URL` | `https://api.DOMAIN` |

**Set these before the first build you intend to keep.** They are read at build
time, not at runtime: `VITE_API_BASE_URL` is baked into the admin bundle and into
its Content-Security-Policy, and `VITE_SITE_URL` decides whether a canonical
link, `og:url` and `sitemap.xml` are emitted at all. A build made without them
produces a site whose admin cannot reach the API and whose sitemap does not
exist. Redeploy after setting them.

Then **Settings → Domains**: add `DOMAIN` and `www.DOMAIN`, with `www`
redirecting to the apex.

### 7. DNS at Namecheap

**Domain List → Manage → Advanced DNS.** Remove Namecheap's default parking
records (the `CNAME` for `www` pointing at `parkingpage`, and any URL-redirect
record), then add:

| Type | Host | Value | TTL |
| --- | --- | --- | --- |
| `A` | `@` | the apex IP Vercel shows you | Automatic |
| `CNAME` | `www` | the target Vercel shows you | Automatic |
| `CNAME` | `api` | the target Render shows you | Automatic |

Take the right-hand values from each dashboard rather than from any guide —
they change, and a stale one silently fails verification.

`.me` is a normal gTLD here; nothing registry-specific applies. Propagation is
usually minutes. Both Vercel and Render issue TLS certificates automatically once
the records resolve.

Check:

```bash
nslookup DOMAIN
nslookup api.DOMAIN
curl -I https://DOMAIN            # 200, and the security headers from §10
curl https://api.DOMAIN/api/health
```

### 8. Decide on the deploy hook

Optional, and reasonable to leave unset. **It does not publish content** — see
§15. Publishing records a snapshot in the database; the live site is built from
the committed export, so the sequence that actually ships content is:

```bash
# in the admin: Preview → Publish
cd backend && FRONTEND_ROOT=/path/to/Majeed-Portfolio-Frontend python -m app.export
cd /path/to/Majeed-Portfolio-Frontend
git add -A && git commit -m "content: publish" && git push   # Vercel builds on push
```

A hook is for redeploying the *current* content — after changing a Vercel
environment variable, say. If you want one: **Vercel → Project → Settings → Git →
Deploy Hooks**, create one on `main`, and put the URL in `DEPLOY_HOOK_URL` on
Render. Treat it as a password; anyone holding it can trigger unlimited builds.

### 9. Smoke test what is live

Run the "After deployment" table in §19. The ones that catch real breakage:

```bash
curl -I https://DOMAIN | grep -i content-security-policy    # present
curl https://api.DOMAIN/api/admin/projects                  # 401
curl -H "Host: evil.invalid" https://api.DOMAIN/api/health  # 400
```

Then in a browser: the site at `https://DOMAIN` with a silent console, the
contact form end to end, `https://DOMAIN/admin/` sign-in with 2FA, and a media
thumbnail loading in the admin — that last one proves the session cookie is
crossing to `api.DOMAIN`, which is the thing the apex layout exists to make work.

### 10. Still outstanding after all this

Content, not infrastructure: 33 `TODO_REPLACE_*` fields, the placeholder audio
track, and the résumé PDF. §21 item 11. Unfilled fields render as nothing, so
sections can look finished while being empty.

---

## 1. Architecture

```
                                 INTERNET
                                     │
              ┌──────────────────────┴──────────────────────┐
              ▼                                             ▼
          VERCEL                                        RENDER
   ┌──────────────────────┐                     ┌──────────────────┐
   │  /         public    │   contact form      │  FastAPI         │
   │            site      │ ──────────────────► │  /api/public/*   │
   │  /admin/   admin SPA │   admin API calls   │  /api/admin/*    │
   └──────────────────────┘ ──────────────────► └────────┬─────────┘
        static only                                      │
        no database access                               ▼
                                              Neon PostgreSQL (TLS)
```

One Vercel project serves both bundles: the public site at `/` and the admin at
`/admin/`. They remain **separate applications** with separate dependency trees —
that isolation is what guarantees no admin code reaches the public bundle, and it
is verified on every build (§19). Serving them from one host only means one
domain, one certificate and one set of environment variables.

**The public site never queries the database.** Content is baked in at build time
from a committed snapshot. The only runtime request it makes is the contact form.

### Repository layout

```
portfolio/
├── frontend/          → Vercel      (root directory: frontend)
│   ├── src/                           the public site
│   ├── public/                        static assets
│   ├── admin/                         the admin panel, its own npm project
│   ├── vercel.json                    build config and response headers
│   └── .env.example
├── backend/           → Render       (root directory: backend)
│   ├── app/                           FastAPI application
│   ├── alembic/                       migrations
│   ├── tests/
│   ├── pyproject.toml                 the single dependency declaration
│   └── .env.example
├── render.yaml        Render Blueprint — at the ROOT, because that is where
│                      Render looks for it; it sets `rootDir: backend`
└── docs/
```

The admin is nested inside `frontend/` rather than being a third top-level
application, for one reason: Vercel takes a single root directory, and the admin
ships in the same deployment. It keeps its own `package.json`, `node_modules` and
build, so the separation that matters — dependency trees and bundles — is intact.

Two paths deliberately cross the frontend/backend boundary, and both are
**build-time only**: the export writes `frontend/src/content/snapshot.json`, and
the seed reads `frontend/public/` for the assets that shipped with the site.
Both resolve through `Settings.resolved_frontend_root`, default to the sibling
layout above, and are overridable with `FRONTEND_ROOT`. The deployed API never
uses either — on Render the frontend is not present at all, and an `assets/...`
media key simply 404s there, which is correct because the public site serves
those files itself.

---

## 2. Vercel deployment

### Project settings

| Setting | Value |
| --- | --- |
| Framework preset | Vite |
| **Root directory** | **`frontend`** |
| Install command | *(default `npm install`)* |
| Build command | `npm run build:all` |
| Output directory | `dist` (i.e. `frontend/dist`) |
| Node version | 22.x — pinned by `engines.node` in `frontend/package.json` |

Most of this is already declared in `frontend/vercel.json`, so the dashboard
should pick it up once the root directory is set. The values are listed here
because a dashboard override silently wins over the file.

The build and output paths are relative to the root directory, so they stay
`npm run build:all` and `dist` — not `frontend/...`.

### What `build:all` does

```
npm run build        → public site into dist/
npm run build:admin  → installs frontend/admin deps, builds into frontend/admin/dist/
scripts/collect-admin.mjs → copies that into dist/admin/
```

The admin is a separate npm project, so Vercel's root `npm install` does not
install its dependencies — `build:admin` does it. `npm install` rather than
`npm ci` on purpose: both lockfiles are committed so the install is
deterministic, and `npm ci` deletes `node_modules` wholesale, which fails
locally whenever a dev server holds a file open.

`collect-admin.mjs` copies rather than pointing Vite's `outDir` at the other
app's output, which would couple the two builds and make `--emptyOutDir` on
either one destructive. It removes `dist/admin` first, so a stale hashed asset
cannot survive under the immutable cache policy, and it exits non-zero if the
copy did not produce `dist/admin/index.html` — a deployment silently missing the
admin would look fine until someone tried to sign in.

### Routing — and one correction to expectations

`vercel.json` contains exactly one rewrite:

```json
{ "source": "/admin/(.*)", "destination": "/admin/index.html" }
```

**The public site needs no SPA rewrite, and must not have one.** It is a single
document with hash-anchor navigation (`#about`, `#skills`, …) and no router at
all — `git grep react-router src/` returns nothing. So `/about`, `/skills`,
`/projects` are *not* application routes and never were. A catch-all rewrite
would serve the portfolio for every nonexistent path, replacing an honest 404
with a soft 200 and inviting search engines to index unlimited duplicate URLs.
Verified locally: `/` → 200, `/about` → 404.

The admin genuinely is a router-based SPA (`BrowserRouter basename="/admin"`), so
`/admin/projects` must return the shell. Verified: `/admin/projects` and
`/admin/media` → 200 `text/html`, while `/admin/assets/index-*.js` → 200
`text/javascript`. Vercel checks the filesystem before applying rewrites, which
is what keeps hashed assets from being swallowed by the rewrite.

### Environment variables (Vercel)

All three are **compiled into the browser bundle and are therefore public**.
Never put a credential in a `VITE_` variable.

| Variable | Required | Purpose |
| --- | --- | --- |
| `VITE_SITE_URL` | for launch | The site's own origin. Feeds the canonical link, `og:url`, absolute `og:image`, `robots.txt` and `sitemap.xml`. Unset ⇒ all of those are **omitted**, because a sitemap pointing at the wrong domain is worse than none |
| `VITE_CONTACT_ENDPOINT` | for launch | `https://<api host>/api/public/contact`. Unset ⇒ the form says sending is not connected rather than pretending |
| `VITE_API_BASE_URL` | **yes** | Origin of the API, e.g. `https://<api host>`. Without it the admin issues relative `/api/...` requests that resolve against Vercel and 404 |

Set all three for **Production**. For Preview, see §22.

---

## 3. Render deployment

`render.yaml` is committed, so the service can be created from it as a Blueprint.
It contains **no secret values** — everything sensitive is `sync: false`, which
tells Render to ask for the value and keep it out of git.

| Setting | Value |
| --- | --- |
| Service type | Web Service |
| Runtime | Python (3.13, from `backend/.python-version`) |
| Root directory | `backend` |
| Build command | `pip install --upgrade pip && pip install .` |
| Start command | see below |
| Health check path | `/api/health` |
| Persistent disk | **none** — free tier. Uploaded media is ephemeral; see §4 |

### Start command

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'
```

Taken from the actual application: `app/main.py` defines `app = FastAPI(...)`, so
`app.main:app` is the entrypoint. Notes:

- **`0.0.0.0` and `$PORT`.** Render assigns the port and health-checks the one it
  assigned. Never hard-code `8000` here; local development still uses it.
- **`--proxy-headers --forwarded-allow-ips '*'`** is correct *here specifically*.
  The service is reachable only through Render's proxy, so the `X-Forwarded-*`
  headers arriving at uvicorn come from it. The application then resolves the
  client address itself according to `TRUSTED_PROXY_COUNT` (§11), taking the entry
  the proxy appended rather than the one the client sent. Quote the `*` — an
  unquoted one is glob-expanded by the shell.
- Dependencies come from `pyproject.toml`. There is deliberately no
  `requirements.txt` to drift from it.

### Environment variables (Render)

**Safe configuration** — already in `render.yaml`, no action needed:

| Variable | Value |
| --- | --- |
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `TRUSTED_PROXY_COUNT` | `1` |
| `STORAGE_ROOT` | `/var/data/storage` |
| `SESSION_COOKIE_SAMESITE` | `lax` |
| `PYTHON_VERSION` | `3.13` |

**Secret / operator-supplied** — entered in the Render dashboard, never in git:

| Variable | Notes |
| --- | --- |
| `DATABASE_URL` | Neon connection string, `sslmode=require`. **Rotate first** (§21) |
| `SECRET_KEY` | Fresh value: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `CORS_ORIGINS` | The production site origin(s). https only, comma separated |
| `ALLOWED_HOSTS` | This service's hostname(s) |
| `DEPLOY_HOOK_URL` | Optional. See §15 before setting it |

The API **refuses to start** in production if `CORS_ORIGINS` or `ALLOWED_HOSTS`
is missing, contains a wildcard, is plain http, or is a localhost address; if
`TRUSTED_PROXY_COUNT` is 0; if `STORAGE_ROOT` is unset; or if `DEBUG` is true.
Each of those is silent at boot and only visible from a browser console or an
audit months later, so failing on startup is the cheapest place to catch them.

---

## 4. Uploaded media and the ephemeral filesystem

**Render's filesystem is ephemeral.** Every deploy and every restart begins from
the build image, so anything written to the application directory is gone.

Uploads live in `backend/storage/` (56 files locally), or wherever
`STORAGE_ROOT` points.

### The free tier, which is what this deployment uses

No persistent disk is available, so `STORAGE_ROOT` is an ordinary path inside
the checkout and **uploads do not survive a deploy**. After one, the media
library keeps all of its database rows and loses the files behind them:
thumbnails 401/404 in the admin, and `python -m app.export` reports missing
media and exits non-zero.

This is a knowing trade, not an oversight, and it is survivable because of where
the site's assets actually live:

- Every asset the **public site** uses is committed in the frontend repository —
  the hero video, the poster, the portrait, the certificate PDFs. None of it is
  affected.
- The export copies referenced uploads into `frontend/public/` and those get
  committed too, so any upload that has been *published and exported* is
  permanently safe. Only uploads added and not yet exported are at risk.

`STORAGE_ROOT` is still set explicitly rather than left to default. The
application refuses to start in production without it, and that check earns its
keep here: the point is that the location is a decision somebody made, not a
default nobody noticed.

### Upgrading later

Move the service to a paid plan, restore the `disk:` block in `render.yaml`
(mount path `/var/data`, 1 GB), and set `STORAGE_ROOT=/var/data/storage`. A disk
pins the service to one instance and rules out zero-downtime deploys —
acceptable for a single-operator CMS; the alternative is object storage, which
is a larger change than this phase.

**Existing local uploads are not migrated automatically.** To carry them over,
copy `backend/storage/` into the disk once, or re-upload through the admin.

`STORAGE_ROOT` is read in exactly one place (`Settings.resolved_storage_root`).
It used to be recomputed from `__file__` in two separate modules, which worked
only while both copies agreed and made a mounted volume impossible;
`test_storage_root_has_one_definition` now asserts they are the same object.

---

## 5. Neon configuration

| Item | Value |
| --- | --- |
| Current region | **`us-east-2`** (Ohio) |
| Measured latency from the audit environment | **~338 ms per query**, 3.2 s cold connect |
| Schema | 25 tables, migrations `0001` → `0003`, single linear head, no drift |
| TLS | `sslmode=require&channel_binding=require` in the connection URL |
| Privileges | The app connects as `neondb_owner` |

**Region.** Not migrated, and not to be migrated automatically. Neon cannot move
a project between regions, so it means creating a new project. `ap-south-1`
(Mumbai) or `ap-southeast-1` (Singapore) should take per-query cost from ~338 ms
to roughly 20–40 ms. Procedure in §21 item 7.

Render's region in `render.yaml` is `singapore`, chosen to be near the eventual
database and the audience. If the Neon project stays in `us-east-2`, moving the
Render region to `ohio` would cut the API↔database leg instead — but that trades
away latency to visitors, and the database leg is the one that dominates.

**Least privilege** is worth doing and is not done: a role with `SELECT`,
`INSERT`, `UPDATE`, `DELETE` on the application tables, rather than the owner,
would limit what a compromised API can do to the schema.

---

## 6. Environment variables, all of them

| Variable | Where | Secret | Consequence if unset |
| --- | --- | --- | --- |
| `VITE_SITE_URL` | Vercel | no | No canonical, `og:url`, absolute `og:image` or sitemap |
| `VITE_CONTACT_ENDPOINT` | Vercel | no | Form says sending is not connected |
| `VITE_API_BASE_URL` | Vercel | no | **Admin cannot reach the API at all** |
| `ENVIRONMENT` | Render | no | Cookies not `Secure`, docs exposed, no HSTS |
| `DEBUG` | Render | no | — (production refuses `true`) |
| `DATABASE_URL` | Render | **yes** | Will not start |
| `SECRET_KEY` | Render | **yes** | Will not start |
| `CORS_ORIGINS` | Render | no | Production will not start |
| `ALLOWED_HOSTS` | Render | no | Production will not start |
| `TRUSTED_PROXY_COUNT` | Render | no | Production will not start; at 0 behind a proxy all visitors share one rate-limit bucket |
| `STORAGE_ROOT` | Render | no | Production will not start; uploads would be ephemeral |
| `SESSION_COOKIE_SAMESITE` | Render | no | Defaults to `lax` |
| `DEPLOY_HOOK_URL` | Render | **yes** | Publishing records the snapshot and says the site was not rebuilt |

Never put any of the `yes` column — or `DATABASE_URL`, session secrets, TOTP
secrets, admin credentials, or a deploy hook — into a `VITE_` variable. Anything
prefixed that way is compiled into the browser bundle. §19 verifies this.

---

## 7. CORS

Configured through `CORS_ORIGINS`; a wildcard is rejected outright because it is
both invalid for credentialed requests and dangerous.

Verified against a real production-mode server:

| Test | Result |
| --- | --- |
| Preflight from an allowed origin | `200`, `allow-origin` echoes it, `allow-credentials: true`, `allow-headers` includes `X-CSRF-Token` |
| Preflight from an unknown origin | `400`, **no** `Access-Control-Allow-Origin` |
| `Access-Control-Allow-Origin: *` ever returned | never |
| Credentialed cross-origin `GET /api/auth/me` from the admin | `200` |
| Credentialed cross-origin write with CSRF header | passes auth and CSRF |

---

## 8. Trusted hosts

`ALLOWED_HOSTS` drives `TrustedHostMiddleware` in production. Phase 7 found this
hard-coded to `["*.localhost", "localhost"]`, which would have rejected every
production request with `400 Invalid host header`.

Verified against a production-mode server bound to `0.0.0.0`:

| `Host` header | Result |
| --- | --- |
| The configured hostname | `200` `{"status":"ok"}` |
| `evil.invalid` | **`400 Invalid host header`** |

Start with Render's own `<service>.onrender.com` and add the custom API hostname
once DNS resolves. Both may be listed at once, which is what makes the cutover
uneventful. Do not use `*`.

---

## 9. HTTPS and cookies

Vercel and Render both terminate TLS and issue certificates, so both services are
HTTPS with no configuration.

`ENVIRONMENT=production` sets `Secure` on the session and CSRF cookies, so they
are never sent over plain HTTP. Sessions stay in an `HttpOnly` cookie and are
never moved to `localStorage`.

### `SameSite` — the one thing the domain layout decides

`SameSite=Lax` is the default and the target. It is about *site* (registrable
domain), not origin, so:

| Layout | Same site? | `Lax` works? |
| --- | --- | --- |
| `example.com` → `api.example.com` | yes | **yes** |
| `www.example.com` → `api.example.com` | yes | **yes** |
| `x.vercel.app` → `y.onrender.com` | **no** | **no** |

On the platform default domains the browser withholds the cookie: login appears
to succeed and every request afterwards is `401`, and every media thumbnail
(`<img>` to the API origin) fails too.

`SESSION_COOKIE_SAMESITE=none` is the escape hatch, and a real weakening — the
browser stops enforcing same-site entirely, leaving the double-submit CSRF token
as the only defence, and browsers increasingly block such cookies regardless.
It requires `Secure`, which the configuration enforces.

**Recommendation: use a custom domain for both services from the start and leave
this at `lax`.** Verified locally across ports (same site, different origin): the
cookie is sent, `/api/auth/me` returns `200`, and a cross-origin `<img>` to the
media endpoint loads (1200×848).

### Non-production URLs in the codebase, classified

| Occurrence | Verdict |
| --- | --- |
| `frontend/admin/vite.config.ts` → `http://localhost:8000` | Dev proxy target. Correct |
| `app/core/config.py` defaults and `LOCAL_HOSTNAMES` | Dev default and a deny-list. Correct |
| `tests/*` | Fixtures. Correct |
| `app/seed.py`, `src/content/projects.ts`, `snapshot.json` → `http://research.periyaruniversity.ac.in/...` | **A real live plain-http URL** — the PhD project's actual deployment, rendered as a link. Not mixed content (`<a href>` is not a subresource). It is also why the CSP omits `upgrade-insecure-requests` |

No hard-coded production URL exists anywhere. The admin builds API URLs from
`VITE_API_BASE_URL`; the public site builds metadata from `VITE_SITE_URL`.

---

## 10. Security headers

Split by what each mechanism can actually carry.

### Vercel — `vercel.json`

Phase 7 noted that `public/_headers` is Netlify/Cloudflare Pages syntax. **Vercel
does not read it**, so those headers would simply have been absent. They are now
in `vercel.json` and were verified in real responses:

| Header | Value |
| --- | --- |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Content-Security-Policy` | `frame-ancestors 'none'` |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | accelerometer, camera, geolocation, gyroscope, magnetometer, microphone, payment, usb all `()` |
| `Cross-Origin-Opener-Policy` | `same-origin` |
| `Cache-Control` on `/assets/*` and `/admin/assets/*` | `public, max-age=31536000, immutable` |
| `X-Robots-Tag` on `/admin/*` | `noindex, nofollow` |

`public/_headers` is kept so the same headers travel if the site is ever served
from Netlify or Cloudflare Pages, and its comment now says `vercel.json` is the
authoritative copy. **Change both together.** For nginx:

```nginx
add_header Content-Security-Policy "frame-ancestors 'none'" always;
add_header X-Frame-Options "DENY" always;
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()" always;
add_header Cross-Origin-Opener-Policy "same-origin" always;
```

### Render — application middleware

Render adds no security headers of its own; the application sends them, verified
on a production-mode server: `Strict-Transport-Security`,
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'none';
frame-ancestors 'none'` (the API returns JSON only, so that costs nothing), and
`Cache-Control: no-store` so no shared cache holds an authenticated response.

Interactive docs are off in production — `/docs` and `/openapi.json` both `404`.

---

## 11. Content-Security-Policy

Phase 7's CSP is unchanged in approach: injected into the HTML at build time so
it travels with the build to any host, with `connect-src` derived from the
configured API so the policy cannot drift from what the app talks to.

The admin now has its own, by the same mechanism — a policy per document, rather
than one host header that would have to be the union of two different policies.

| | Public site | Admin |
| --- | --- | --- |
| `script-src` | `'self'` | `'self'` |
| `style-src` | `'self' 'unsafe-inline'` + Google Fonts | `'self' 'unsafe-inline'` + Google Fonts |
| `font-src` | `'self'` + `fonts.gstatic.com` | `'self'` + `fonts.gstatic.com` |
| `img-src` | `'self' data:` | `'self' data: blob:` + API origin |
| `connect-src` | `'self'` + contact endpoint origin | `'self'` + API origin |
| `frame-src` | `'self'` (certificate PDFs) | `'self'` + API origin |
| `media-src` | `'self'` | — |
| `object-src` / `base-uri` / `form-action` | `'none'` / `'self'` / `'self'` | same |

Two findings came out of testing this rather than reading it:

- **The admin's CSP blocked its own Google Fonts stylesheet.** `style-src` and
  `font-src` were `'self'` only; the admin's typography was broken.
- **The admin had an inline `onload` handler**, the same pattern Phase 7 removed
  from the public site. `script-src 'self'` blocked it, so even once the
  stylesheet was allowed it never activated. The flip moved into
  `frontend/admin/src/main.tsx`, keyed off `id="webfonts"` — which is what lets
  `script-src` stay strict instead of needing `'unsafe-inline'`.

After both fixes, with the admin signed in and navigating: **zero CSP
violations**, `Inter` and `JetBrains Mono` both loaded, `webfonts.media === 'all'`.
Public site: **zero violations**, video `readyState 4`, WebGL canvas mounted,
certificate iframe opens, fonts applied.

`script-src` was not weakened to silence anything.

---

## 12. Contact API

`VITE_CONTACT_ENDPOINT` → `https://<api host>/api/public/contact`.

Verified end to end through the simulated Vercel output to the API and Neon:

| Test | Result |
| --- | --- |
| Valid submission, cross-origin | "Thanks — your message has been sent.", form cleared |
| Round-trip time | 1.5 s – 7.4 s (Neon distance; slower on a cold connection) |
| CORS | No violations, no preflight failures |
| Client validation on an empty form | Four field errors |
| Honeypot | Invisible, `aria-hidden`, `tabIndex -1`, unreachable by keyboard |
| Rate limit | 4th rapid submission → `429` (live, against Neon) |
| Malicious HTML | Stored verbatim, rendered as inert text in the admin |
| Admin delivery | Message appears in Messages |

The XSS check was run against the live stack in Phase 7 with `<script>`,
`<img onerror>` and `<svg onload>` payloads: nothing executed, zero injected
nodes, payloads displayed as literal text.

---

## 13. Admin authentication

Unchanged from Phase 7 and re-verified across origins: Argon2id passwords, opaque
DB-backed sessions stored hashed, absolute expiry, `HttpOnly` cookie,
double-submit CSRF, per-account lockout with exponential backoff, per-IP limits,
uniform login errors, and a full audit log.

Cross-origin specifics confirmed in this phase:

- Login through the deployed admin bundle to the API on another origin: **OK**
- `GET /api/auth/me` with credentials: **200**
- CSRF cookie readable by the admin, echoed as `X-CSRF-Token`: **works**
- An authorised `DELETE` reached authorisation and returned `404` for a
  non-existent id — i.e. it passed both session and CSRF checks

---

## 14. Two-factor authentication

**2FA is currently OFF for the production admin** (`python -m app.cli list-admins`
reports `2FA OFF`), and it must be on before the site is public.

There is no 2FA screen in the admin UI, by design — Phase 7 added CLI commands
instead of new UI:

```bash
cd backend
python -m app.cli enable-2fa      # stage a secret, prove a code, mint recovery codes
python -m app.cli disable-2fa     # requires the account password
```

`enable-2fa` prints the provisioning URI and secret **to your terminal only** —
there is no other way to get it into an authenticator app — and it is never
logged. The ten recovery codes are shown exactly once; store them somewhere
reachable without the phone.

Run it against the production database, i.e. with `backend/.env` pointing at
the rotated Neon credential.

Phase 7 hardening that this relies on: the second factor has its own rate limit
and lockout, a used TOTP step cannot be replayed, and re-enrolment stages the new
secret and requires the current password, so an abandoned enrolment cannot leave
the account without a second factor.

---

## 15. Publish workflow and the deploy hook

This is the part where the intended chain needs a correction, so it is spelled
out rather than drawn.

### What actually happens

```
Admin edits content (Render)
        ↓
Preview  →  validation  →  Publish
        ↓
Snapshot stored in Neon (append-only)
        ↓
npm run content:pull      ← exports snapshot.json AND copies referenced uploads
        ↓                   into public/
git commit && git push
        ↓
Vercel builds from the committed snapshot  →  new public site
```

### Why the export is a local step, not a Render one

`python -m app.export` writes `src/content/snapshot.json` **and copies the media
it references into `public/`**. On Render both of those land in an ephemeral
checkout and are thrown away. On a developer machine they become committed repo
content, which is exactly what the design intends: the static host needs no
database, no Python and no secrets to build.

**Consequence, stated plainly: firing the deploy hook alone does not move
content.** Vercel would rebuild from the snapshot that is currently committed. A
publish that is never exported and pushed changes the database and not the site.

The admin now says so on the Publish page, pointing at `npm run content:pull` —
an operator who does not know this presses Publish again and concludes the system
is broken.

### So what is `DEPLOY_HOOK_URL` for?

Redeploying the **current** content without a code change: after altering a
Vercel environment variable, for instance. `git push` is the trigger that ships
new content, via Vercel's git integration.

It is therefore **optional, and reasonable to leave unset.** With no hook the
admin reports "Saved, but the site was not rebuilt", which is accurate.

If it is set, the existing mechanism is compatible with Vercel. Create the hook
in **Vercel → Project → Settings → Git → Deploy Hooks**, choose the production
branch, and put the resulting URL in `DEPLOY_HOOK_URL` on Render. It looks like
`https://api.vercel.com/v1/integrations/deploy/<project>/<hash>`. Vercel ignores
the JSON body the service sends.

Treat it as a bearer credential: anyone holding it can trigger unlimited builds.
It lives only on Render, never in a `VITE_` variable, is never returned by the API
(`GET /api/admin/publish/deploy` answers only `{"configured": true|false}`), and
only its **host** reaches the audit log. A hook failure never fails the publish —
the snapshot is already the source of truth; a timeout means the site is stale,
not that the publish was wrong.

---

## 16. Rollback

```
Admin → History → Restore
        ↓
A NEW published snapshot containing the old content (same checksum)
        ↓
npm run content:pull → commit → push   (or the deploy hook, for current content)
        ↓
Vercel redeploys
```

History is append-only: a rollback never rewrites or deletes an earlier snapshot,
because a rollback that mutated the past would make the audit trail claim the bad
publish never happened. The restored row carries the original checksum, which is
how you verify it restored the bytes rather than rebuilding from the current
database. The content is re-validated first, and restoring the already-live
snapshot returns `409 already_live`.

Exercised against real PostgreSQL in Phase 7, not only SQLite.

---

## 17. Backup

```bash
# Verified working: PostgreSQL 18 client against Neon's 18.6 server.
"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" --format=custom \
    --no-owner --no-privileges --file=backup.dump "<DATABASE_URL>"

# Check the archive is readable before trusting it:
"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" --list backup.dump
```

Phase 7 produced an 82 KB archive containing 25 tables, 16 indexes, 21 foreign
keys and 16 CHECK constraints.

Write backups **outside the repository** — `.gitignore` does not cover a
`.dump` at the root, and a database archive must never be committed.

**A full restore has still not been tested**, because it needs a throwaway target
database and the local PostgreSQL server's password is not available. On Neon the
cheapest version is a branch: restore into the branch, compare row counts, delete
the branch. Never restore over production.

---

## 18. DNS

Nothing here can be done until the domain is chosen. Both layouts keep the
frontend and API **same-site**, which is what lets `SameSite=Lax` stand (§9).

### Option A — apex + api

| Record | Type | Name | Value |
| --- | --- | --- | --- |
| Site | `A` | `@` | Vercel's apex IP (given in the dashboard) |
| Site | `CNAME` | `www` | `cname.vercel-dns.com` |
| API | `CNAME` | `api` | `<service>.onrender.com` |

Then `VITE_SITE_URL=https://example.com`, `ALLOWED_HOSTS=api.example.com`,
`CORS_ORIGINS=https://example.com` (add `https://www.example.com` if `www`
resolves rather than redirecting).

### Option B — www + api

| Record | Type | Name | Value |
| --- | --- | --- | --- |
| Site | `CNAME` | `www` | `cname.vercel-dns.com` |
| Site redirect | `A` | `@` | Vercel apex IP, redirecting to `www` |
| API | `CNAME` | `api` | `<service>.onrender.com` |

Then `VITE_SITE_URL=https://www.example.com`.

Exact target values come from the Vercel and Render dashboards when the domain is
added — they are not invented here, and registrar-specific steps are not guessed.
Add the custom hostname to `ALLOWED_HOSTS` **before** cutting DNS over, keeping
the `onrender.com` entry alongside it.

---

## 19. Smoke tests

Local results are from this phase. Anything needing live services is `MANUAL`
with the command to run.

### Verified locally

| Test | Expected | Actual | Status |
| --- | --- | --- | --- |
| Backend tests | all pass | **151 passed** (+18 this phase) | PASS |
| Backend lint | clean | `ruff check` clean | PASS |
| Migration drift | none | "No new upgrade operations detected" | PASS |
| Public typecheck / lint / build | clean | clean, 0 errors | PASS |
| Admin typecheck / lint / build | clean | clean, 0 errors | PASS |
| `build:all` output layout | site + `dist/admin/` | both present | PASS |
| Frontend loads | 200, 7 sections | 7 sections, one `<h1>` | PASS |
| `/admin/` | 200 | 200 | PASS |
| `/admin/projects` (SPA rewrite) | 200 html | 200 html | PASS |
| `/admin/assets/*.js` | served as JS | `text/javascript` | PASS |
| `/about` (not a route) | 404 | 404 | PASS |
| Security headers | 7 present | all 7 | PASS |
| Asset caching | immutable | `max-age=31536000, immutable` | PASS |
| `/admin/*` noindex | present | `noindex, nofollow` | PASS |
| API health | 200 `{"status":"ok"}` | 200, no internals leaked | PASS |
| Valid `Host` | normal response | 200 | PASS |
| Invalid `Host` | 400 | **400 Invalid host header** | PASS |
| Docs in production | 404 | `/docs` and `/openapi.json` 404 | PASS |
| CORS allowed origin | credentialed preflight | 200 + `allow-credentials` | PASS |
| CORS unknown origin | no allow-origin | 400, header absent | PASS |
| Admin login (cross-origin) | 200 | OK, `/api/auth/me` 200 | PASS |
| Session cookie cross-origin | sent | sent (same-site) | PASS |
| CSRF across origins | write accepted | passed auth + CSRF | PASS |
| Cross-origin media `<img>` | loads | 1200×848 | PASS |
| Media file without a cookie | 401 | **401** | PASS |
| Admin list without a cookie | 401 | 401 | PASS |
| Publish preview (cross-origin) | 200 | 200, 0 blocking | PASS |
| Optimistic locking | 409 `stale_write` | 409 `stale_write` | PASS |
| Logout | 204 then 401 | 204 then 401 | PASS |
| Contact form (cross-origin) | success only on 2xx | success, form cleared | PASS |
| Contact rate limit | 429 | 429 | PASS |
| Malicious contact HTML | inert text | nothing executed | PASS |
| Public CSP | no violations | none; video, WebGL, fonts, iframe all work | PASS |
| Admin CSP | no violations | none, after two fixes | PASS |
| Forwarded-IP spoofing | one bucket | spoofed prefixes all resolve to the real client | PASS |
| Production misconfiguration | refuses to start | refuses, naming each problem | PASS |
| Bundle isolation | no admin code in public, no three.js in admin | both confirmed | PASS |
| Lazy-load invariants | no 3D preload, not in entry chunk | both hold | PASS |
| Secret scan of `dist/` | no secrets | 13 hits, all content/field names/shader text | PASS |
| DOTE withheld document | absent | not in repo, snapshot, or build | PASS |
| Accessibility (axe) | 0 violations | 0 / 46 passes | PASS |
| Responsive 390–1440 | no overflow | none | PASS |
| Console errors | none | none | PASS |

### After deployment — MANUAL

| Test | Command / check |
| --- | --- |
| HTTPS on both | Browser padlock; `http://` redirects |
| API health | `curl https://<api>/api/health` → `{"status":"ok"}` |
| Invalid Host | `curl -H "Host: evil.invalid" https://<api>/api/health` → 400 |
| Headers in production | `curl -I https://<site>/` → all 7 |
| Unauthenticated admin | `curl https://<api>/api/admin/projects` → 401 |
| Wrong 2FA repeatedly | rate limited / locked out |
| Replayed TOTP | rejected |
| Private media by id | 401 |
| DOTE document | not present on the public site |
| Contact spam | 429 after the limit |
| Frontend bundle | no secrets (re-run the `dist/` scan on the deployed files) |
| Mobile / reduced motion / Save-Data | `still` tier, no 3D chunk, no video |
| Publish → pull → push → deploy | new content live |
| Rollback | previous content restored |

---

## 20. Troubleshooting

| Symptom | Cause |
| --- | --- |
| Every API request `400 Invalid host header` | `ALLOWED_HOSTS` missing the hostname actually being used |
| API will not start, logs list problems | Intentional — production config validation. Fix what it names |
| Admin loads, login "succeeds", then everything 401s | Cookie withheld. Frontend and API are not same-site (§9). Use a shared parent domain, or set `SESSION_COOKIE_SAMESITE=none` |
| Admin requests 404 against the Vercel domain | `VITE_API_BASE_URL` unset at build time |
| Admin thumbnails broken, list works | Same cookie problem, on `<img>` requests |
| Admin typography looks wrong | Google Fonts blocked by CSP — check `style-src`/`font-src` |
| CORS error in the browser console | Origin not in `CORS_ORIGINS`, or http where https is required |
| Media 404s after a deploy | Expected on the free tier — no persistent disk (§4). On a paid plan, `STORAGE_ROOT` outside the mount |
| Contact form rate-limits everyone at once | `TRUSTED_PROXY_COUNT` still 0 behind Render |
| Publish succeeds, site unchanged | Expected. Export and push (§15) |
| Health check fails on first deploy | Cold Neon connection ~3.2 s. Raise the timeout |
| `/about` returns 404 | Correct. Sections are hash anchors, `/#about` |
| Admin page blank, console CSP error | A CSP source is missing; fix the policy, do not add `'unsafe-inline'` |

---

## 21. Manual actions

In order. Items 1–3 are security actions and come first.

**1. Rotate the admin password.** Exposed in a development transcript; treat as
compromised.
```bash
cd backend
python -m app.cli reset-password   # prompts, no echo, revokes every session
```
Do not send the new password to anyone, including this assistant.

**2. Rotate the Neon credential.** Also exposed in a transcript. Reset the role's
password in the Neon console. Put the new value **only** into Render's
environment settings and your local `backend/.env` — never into git. Git
history is clean, so no rewrite is needed.

**3. Enable 2FA** — §14. Must be done before the site is public.

**4. Create the Render Web Service** from `render.yaml` (Blueprint), or manually
with the settings in §3. Supply the five `sync: false` values. No disk is
attached on the free tier, so uploaded media is ephemeral (§4).

**5. Run the first migration** — §22.

**6. Create the Vercel project.** Settings in §2. Add the three `VITE_` variables
for Production, then deploy.

**7. Decide the Neon region.** Current `us-east-2`, ~338 ms/query.
```bash
# Neon cannot move a project between regions, so this is a migration.
# 1. Create a NEW Neon project in ap-south-1 (or ap-southeast-1).
# 2. Back up the current database (§17).
# 3. Point backend/.env and Render's DATABASE_URL at the new project.
# 4. Recreate schema and content — both idempotent:
cd backend
python -m alembic upgrade head
python -m app.seed
# 5. Verify, re-upload or copy media into the new disk, then delete the old project.
```
The public site is unaffected either way.

**8. Choose the domain and configure DNS** — §18. Add the hostname to
`ALLOWED_HOSTS` before cutting over.

**9. Verify HTTPS and the production headers** — §19, "After deployment".

**10. Decide on `DEPLOY_HOOK_URL`** — §15. Leaving it unset is a reasonable
choice.

**11. Finish the content.** 33 `TODO_REPLACE_*` fields, the placeholder audio
track, and the résumé PDF. Nothing here may be invented — an unknown value stays
empty.

**12. Consider a least-privilege database role** — §5.

**13. Copy existing uploads** into the Render disk, or re-upload them (§4).

---

## 22. Database migrations

Additive only so far (`0003` adds two nullable columns), and deliberately **not**
run automatically — `preDeployCommand` is left commented out in `render.yaml`,
because the safe order starts with a backup and skipping that to save a step is
how a bad deploy becomes an unrecoverable one.

```bash
# 1. Back up, and verify the archive is readable (§17).
# 2. Deploy the backend. Migrations are additive, so the running code tolerates
#    both the old and new schema.
# 3. Apply:
cd backend
python -m alembic current          # where the database is
python -m alembic upgrade head     # apply
# 4. Verify:
python -m alembic current          # should report the new head
python -m alembic check            # should report no drift
# 5. Restart / confirm the service is healthy.
# 6. Smoke test: login, a CRUD read, publish preview, contact submission.
```

Never run `DROP DATABASE`, `DROP SCHEMA` or `TRUNCATE` against production. If a
future migration is genuinely destructive, split it: deploy code that tolerates
both shapes, migrate, then remove the old path in a later release.

Rollback limitation, stated honestly: `alembic downgrade` reverses the schema, not
the data. `0003`'s downgrade drops `totp_last_counter`, which discards TOTP
replay state — a code used just before the downgrade becomes acceptable again for
the rest of its window.

---

## 23. Vercel previews

Preview deployments get their own URLs. **Do not add those to production
`CORS_ORIGINS`** — that would let any preview build, including one from an
unreviewed branch, drive the production API with real credentials.

Options, in order of preference:

1. **Leave previews without API access.** The public site still renders fully:
   content is baked in, and the contact form degrades honestly to "sending is not
   connected". This is the default and costs nothing.
2. **A second Render service** pointed at a separate Neon branch, with the preview
   origins in *its* `CORS_ORIGINS`. Full isolation; the price is another service.
3. A stable preview alias added to production `CORS_ORIGINS` — acceptable only
   for a single trusted alias, never a wildcard.

The API refuses `*` in `CORS_ORIGINS` outright, so the worst option is not
available.
