# Security posture

What protects this system, what was verified on 2026-10-11, and what is still
open. Written for whoever operates the site.

This document does **not** claim the project is secure. It records which
controls exist, which were observed working against the live deployment, and
which were not checked. No score, no grade, no ranking — those compress away
exactly the detail that matters.

The full audit, including the reasoning behind each control and the findings
that were investigated and dismissed, is `docs/PHASE-7-PRODUCTION-AUDIT.md`.
This file is the shorter operational view and does not repeat it.

---

## 1. What is exposed

| Surface | Host | Authentication |
|---|---|---|
| Public site | Vercel CDN, static files | none; nothing to authenticate |
| `POST /api/public/contact` | Render | none, by design — honeypot + rate limit |
| `GET /api/health`, `GET /` | Render | none |
| `/api/admin/*` | Render | session cookie + CSRF header |
| `/admin/` (the CMS bundle) | Vercel, `noindex` | the API refuses it without a session |

The public site makes exactly one runtime request — the contact form — and
never queries the database. So the blast radius of an API compromise excludes
the public site, which keeps serving from the CDN regardless.

---

## 2. Controls in place

**Authentication.** Argon2id password hashing. Sessions are opaque server-side
records in `admin_sessions`, referenced by an HttpOnly cookie — never a JWT in
`localStorage`, which would turn any XSS into account takeover. TOTP two-factor
is implemented, with hashed single-use recovery codes and replay protection via
`totp_last_counter`. Failed logins are counted per account with a lockout, and
every attempt is recorded in `login_attempts`.

**Session cookie.** `HttpOnly`, `Secure` in production, `SameSite=Lax`. The
`SameSite` choice is load-bearing and is the subject of §5.

**CSRF.** Double-submit: a readable cookie echoed in an `X-CSRF-Token` header
on every unsafe request. The cookie rides along automatically cross-site; the
header cannot be set by another origin, so requiring both proves same-origin
intent.

**CORS.** Credentialed, so no wildcard is possible. Origins are an explicit
allow-list, and the application refuses to start in production on a wildcard,
a non-HTTPS origin or a localhost origin.

**Input limits.** 256 kB for JSON, 72 MB for uploads, enforced by middleware
before a body is parsed. Contact fields are length-bounded on the server, and
control characters are stripped from free text — a classic header-injection
vector.

**Headers.** A build-time Content-Security-Policy with no `'unsafe-inline'` for
script; `frame-ancestors` and HSTS as real headers, since a meta tag cannot
carry them. The policy's `connect-src` is derived from the configured API
origin rather than written by hand, so it cannot drift away from the API the
build actually talks to.

**Startup validation.** `backend/app/core/config.py` refuses to boot in
production on an unsafe configuration: empty, wildcard, localhost or non-HTTPS
CORS origins; empty, wildcard or localhost `ALLOWED_HOSTS`;
`TRUSTED_PROXY_COUNT` of 0; unset `STORAGE_ROOT`; `DEBUG` true. A separate
always-on check rejects `SameSite=None` without `Secure`, because a browser
discards such a cookie and the session then silently never persists.

**Audit trail.** Admin mutations are recorded in `audit_logs` with the actor
and client IP. The IP is read from the *Nth-from-right* `X-Forwarded-For` entry
per `TRUSTED_PROXY_COUNT`, because proxies append — taking the leftmost entry
would record whatever the client claimed.

**Secrets.** No secret is committed. `render.yaml` declares every sensitive
variable with `sync: false`, so Render prompts for the value and git never sees
it. Anything `VITE_`-prefixed is compiled into the public bundle by
construction and therefore holds only URLs.

---

## 3. Verified against the live deployment, 2026-10-11

Observed, not inferred.

| Check | Result |
|---|---|
| `GET /api/admin/projects` with no cookie | `401 Not authenticated` |
| `GET /api/admin/dashboard` with no cookie | `401` |
| `GET /api/admin/messages` with no cookie | `401` |
| `POST /api/admin/projects` with no session | `401` |
| CORS preflight from `https://evil.example.com` | `400`, no `allow-origin` |
| CORS preflight from `http://localhost:3000` | `400`, no `allow-origin` |
| CORS preflight from the real site origin | `200`, exact origin echoed, credentials allowed |
| 400 kB JSON body | `413 payload_too_large` |
| Site HSTS | `max-age=63072000; includeSubDomains` |
| Site `X-Frame-Options` / CSP `frame-ancestors` | `DENY` / `'none'` |
| Site `X-Content-Type-Options` | `nosniff` |
| Site `Referrer-Policy` | `strict-origin-when-cross-origin` |
| Site `Permissions-Policy` | camera, geolocation, microphone, payment, USB all `()` |
| Site `Cross-Origin-Opener-Policy` | `same-origin` |
| `/admin/*` indexing | `X-Robots-Tag: noindex, nofollow` |
| CSP violations on page load | none |
| Console errors on page load | none |
| axe-core accessibility violations | 0, 46 passes |
| Backend test suite | 154 passed |
| `ruff check app tests` | clean |

---

## 4. Open findings

### 4.1 The API is not running in production mode

Verified: `GET https://api.mohammedmajeedportfolio.me/docs` returns **200**,
`/openapi.json` returns **200**, and the API sends **no HSTS header**. All
three are gated on `settings.environment == "production"` in
`backend/app/main.py`. The code is correct; the running service is not
configured as production.

Consequences, in order of seriousness:

- **`TrustedHostMiddleware` is not active**, so the `Host` header allow-list is
  not enforced.
- **No HSTS on the API**, so a first request over plain HTTP is not upgraded by
  policy.
- **The full OpenAPI schema is public** — a map of every endpoint, parameter
  and shape. Not a vulnerability in itself; it removes the effort of finding
  the surface.
- `Secure` is not set on the session cookie, because `cookies_secure` is
  derived from the same setting.

`render.yaml` already declares all of this correctly, which means the live
service was created by hand in the Render dashboard rather than from the
blueprint, so the blueprint's values were never applied.

**This cannot be fixed one variable at a time.** Setting `ENVIRONMENT=production`
alone will make the service *refuse to start*, by design. The following must be
set together, in one go:

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `ALLOWED_HOSTS` | the API's hostnames, comma-separated |
| `TRUSTED_PROXY_COUNT` | `1` (Render's proxy) |
| `STORAGE_ROOT` | `/opt/render/project/src/storage` |
| `SESSION_COOKIE_SAMESITE` | `lax` |
| `CORS_ORIGINS` | already set correctly — verified in §3 |

Then confirm `/docs` returns 404 and the API sends HSTS. If the service fails
to boot, the startup error names the exact problem; read it rather than
guessing.

### 4.2 Two-factor authentication is not enabled

Verified read-only against the database: the single admin account has
`totp_enabled = false` and no TOTP secret set, and `admin_recovery_codes` is
empty. The implementation exists and is tested; it has not been switched on.

The admin account is therefore protected by one password, on an API whose
schema is currently public (§4.1). Enabling 2FA in the admin's security
settings is the single highest-value action available, and it takes a minute.

Store the recovery codes somewhere other than the device holding the
authenticator. With no recovery codes and a lost device, there is no documented
account-recovery path short of editing the database directly.

### 4.3 Expired sessions are retained indefinitely

Verified: 35 rows in `admin_sessions`, of which **33 are expired** and one is
revoked. Nothing prunes them.

Not an access-control hole — expiry is checked on every request, so an expired
row grants nothing. It is unbounded growth in a table that is read on every
authenticated request, and it keeps a record of every session longer than
necessary. A periodic `delete from admin_sessions where expires_at <= now()`
is sufficient. `login_attempts` grows the same way.

### 4.4 Credentials that were exposed in conversation

During earlier work, two GitHub personal access tokens were pasted into chat,
and the database connection string and admin password were handled in a session
that is not a secure channel.

**Whether any of these have been revoked or rotated has not been verified, and
is not verifiable from here.** This document will not record them as rotated on
the strength of an assumption. The values are not reproduced anywhere in this
repository — treat them as `[REDACTED]`.

Outstanding, all user-side:

- [ ] Revoke both GitHub personal access tokens (GitHub → Settings → Developer
      settings → Personal access tokens). Revoking is free; a token believed to
      be unused is still a live credential.
- [ ] Rotate the Neon database password and update `DATABASE_URL` on Render.
- [ ] Change the admin password.
- [ ] Rotate `SECRET_KEY` on Render. This invalidates pending-2FA tokens only,
      so the cost is nil.

### 4.5 Rate limiting may be ineffective

Per-IP rate limiting on the contact form depends on `TRUSTED_PROXY_COUNT`
being set to the number of proxies in front of the application. Left at its
default of 0, every request appears to come from Render's own address and all
visitors share a single bucket — so one abuser exhausts the limit for everyone.

The live value **was not verified**: it is not observable from outside, and
because the service is not in production mode (§4.1) the startup check that
would have rejected 0 did not run. Setting it is part of §4.1's variable set.

---

## 5. SameSite=Lax, and why the admin kept returning 401

Not a vulnerability, but the single most expensive misconfiguration in this
project's history, and worth stating plainly so it is not reintroduced.

The session cookie is `SameSite=Lax`, which a browser sends only within one
registrable domain:

```
mohammedmajeedportfolio.me  ->  api.mohammedmajeedportfolio.me        same site
mohammedmajeedportfolio.me  ->  majeed-portfolio-backend.onrender.com  NOT same site
```

Build the admin against the second and the failure is thoroughly misleading:
signing in **appears to work**, because the API really does authenticate and
really does set the cookie — and then every subsequent request returns 401 and
media thumbnails come up blank. Nothing in that failure points at its cause.

The apex + `api.` subdomain layout exists specifically to avoid it. Three
safeguards now apply:

1. `frontend/.env.production` and `frontend/admin/.env.production` both carry
   the reason in a comment, at the line someone would change.
2. **The admin corrects it at runtime.** `resolveApiBase()` in
   `frontend/admin/src/lib/api.ts` compares the configured API's registrable
   domain with the admin's own; when they differ, the configured value cannot
   carry the session cookie *at all*, so the client uses
   `https://api.<its own registrable domain>` instead. A cross-site base is not
   a suboptimal choice to be reported — it is a guaranteed failure, and
   preferring an origin that can work is strictly better than using one that
   cannot.
3. The correction is never silent: the module logs a `console.warn` naming both
   origins, and `apiBaseCorrection` is exported non-null whenever it applies.

The inference in (2) is deliberately narrow — it runs only when the configured
value is already broken, never to override a working one, and never in
development. A correctly-configured build never reaches it, and its bundle and
CSP are byte-for-byte what they were before.

The admin's build-time CSP allows the corrected origin as well, but **only when
the configured one is cross-site**. Without that the correction would be
blocked by `connect-src` before it was ever attempted — the policy is derived
from `VITE_API_BASE_URL`, so it would otherwise permit exactly the origin that
cannot work and forbid the one that can.

The alternative — `SameSite=None` — is deliberately not used. It requires
`Secure`, weakens CSRF posture, and the startup validator rejects it unless
cookies are actually secure.

---

## 6. How to re-run these checks

```bash
# Backend suite and linter
cd backend && ruff check app tests && python -m pytest -q

# Live headers
curl -sI https://mohammedmajeedportfolio.me | grep -iE 'strict-transport|x-frame|content-type-options|referrer|permissions'
curl -sI https://api.mohammedmajeedportfolio.me/api/health | grep -i strict-transport

# Production mode: both should be 404 once §4.1 is done
curl -so /dev/null -w '%{http_code}\n' https://api.mohammedmajeedportfolio.me/docs
curl -so /dev/null -w '%{http_code}\n' https://api.mohammedmajeedportfolio.me/openapi.json

# Access control: expect 401
curl -so /dev/null -w '%{http_code}\n' https://api.mohammedmajeedportfolio.me/api/admin/projects

# CORS: expect no allow-origin header
curl -si -X OPTIONS https://api.mohammedmajeedportfolio.me/api/public/contact \
  -H 'Origin: https://evil.example.com' \
  -H 'Access-Control-Request-Method: POST' | grep -i allow-origin
```

---

## 7. Reporting a problem

The contact form on the site reaches the author. There is no bug bounty and no
dedicated security address. Please do not open a public GitHub issue containing
details of an exploitable flaw.
