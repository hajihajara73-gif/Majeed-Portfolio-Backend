# Phase 7 — Production audit

Audit date: **2026-09-27**
Audited commit: **`27a887c`**, tagged `phase-6-complete`
Auditor: Claude Opus 5, working in the repository

> **Paths in this document are the ones that existed when it was written.** The
> repository was reorganised afterwards: `services/api` → `backend`, and
> `src` + `public` + `apps/admin` → `frontend`. This is a dated record of what
> was audited and found, so it has deliberately **not** been rewritten to match
> the new layout — a findings report edited after the fact stops being evidence.
> For current paths see `README.md` and `docs/DEPLOYMENT.md`.

Every claim below has a command or a measurement behind it. Where a scanner or a
test flagged something that turned out not to be a defect, that is recorded too,
under **False positives** — a suppressed finding is worse than a reported one.

No status here is a score. Each line is `PASS`, `FAIL` or `MANUAL`, where
`MANUAL` means the action cannot be performed safely from inside the repository.

---

## 1. Executive summary

The system was feature-complete but **not deployable**. The single hardest
finding is that the production host allow-list was hard-coded to
`["*.localhost", "localhost"]`, so the first real deployment would have rejected
every request with `400 Invalid host header` — the API would have looked broken
in a way that no amount of DNS checking explains.

Fourteen findings were fixed. Five things that looked like findings were
investigated and were not.

| | Count |
| --- | --- |
| Findings fixed | 14 |
| False positives identified and explained | 5 |
| Manual actions remaining | 10 |
| API tests | 133 passing (was 85; **+48 adversarial**) |
| axe violations | 0 (46 passes) |
| Dependency vulnerabilities | 0 npm, 0 of 48 Python packages |
| Secrets in git history | none |

**The architecture was not changed.** No technology was replaced, no module was
rewritten, the visual identity is untouched, and the public site is still static
with exactly one runtime request.

What is still blocking a launch is **configuration and content**, not code: six
environment variables, two credential rotations, a 2FA enrolment, and 33
`TODO_REPLACE_*` content fields. All are listed in §18 and §19.

---

## 2. Architecture verified

The intended flow was confirmed against the running system, not assumed.

```
Admin UI (apps/admin)  →  FastAPI (services/api)  →  Neon PostgreSQL
                                                          ↓
                                              publish snapshot (append-only)
                                                          ↓
                                    python -m app.export  →  src/content/snapshot.json
                                                          ↓
                                              static build  →  CDN
```

```
Public site  →  POST /api/public/contact  →  Neon  →  Admin Messages
```

| Check | Evidence | Status |
| --- | --- | --- |
| Public site makes no DB call | Only `connect-src` entry is the contact endpoint; 12 requests on load, all same-origin or Google Fonts | PASS |
| Content is build-time | `src/content/snapshot.json` committed; `published.ts` overlays it onto the source modules | PASS |
| Snapshot history append-only | Rollback inserts a new row; three rows in the live DB, none rewritten | PASS |
| Admin is a separate bundle | `apps/admin` has its own `node_modules`; `/admin/publish` absent from the public bundle | PASS |
| Public site builds with no snapshot | `import.meta.glob` makes the file optional | PASS |

25 tables, migrations `0001` → `0003`, single linear head, zero autogenerate
drift.

---

## 3. Security audit — findings fixed

### F-01 Production host allow-list was hard-coded to localhost

**Finding:** `TrustedHostMiddleware` was registered in production with
`allowed_hosts=["*.localhost", "localhost"]`.
**Impact:** Every production request rejected with `400 Invalid host header`.
A total outage on first deploy, presenting as a DNS or proxy fault.
**Evidence:** `app/main.py` before the change; `tests/test_security_audit.py::test_production_refuses_to_start_when_misconfigured`.
**Action:** Allow-list now comes from `ALLOWED_HOSTS`. `Settings` refuses to
start in production if it is empty, `*`, or a localhost address.
**Status:** PASS

### F-02 No production configuration validation

**Finding:** Production could start with `CORS_ORIGINS=*`, with localhost or
plain-`http` origins, or with `DEBUG=true`.
**Impact:** A wildcard is invalid for credentialed CORS and would expose the
admin API's CORS surface to any origin. `http` origins mean the session cookie
can be stripped in transit. `DEBUG=true` enables SQL echo (see F-08).
**Evidence:** 8 parametrised cases in
`test_production_refuses_to_start_when_misconfigured`, all previously accepted.
**Action:** A `model_validator` refuses to construct production `Settings` and
names every problem at once. Development is deliberately untouched —
`test_development_is_left_alone`.
**Status:** PASS

### F-03 Second factor had no rate limit and no lockout

**Finding:** `POST /api/auth/2fa` counted failures but never applied a lockout
and never checked the per-IP limit. The password stage's lockout does not apply,
because the password already succeeded.
**Impact:** A correct password bought a pending token valid for 300 seconds,
during which an unlimited number of six-digit guesses was accepted. Measured: 8
consecutive wrong codes, 8 × `401`, no lockout.
**Evidence:** `test_second_factor_brute_force_is_rate_limited` — failed before,
passes now.
**Action:** The 2FA route now applies `check_ip_rate_limit` and a dedicated
account lockout with the same exponential backoff as the password stage.
**Status:** PASS

### F-04 A used TOTP code could be replayed

**Finding:** No record of which time-step had been consumed, so a code stayed
usable for the remainder of its ±1-step window.
**Impact:** RFC 6238 §5.2 requires a verifier to reject a previously accepted
OTP. Without it, a code read off a screen share or over a shoulder is reusable
for up to ~90 seconds.
**Evidence:** `test_a_used_totp_code_cannot_be_replayed` — the same code was
accepted twice before the fix.
**Action:** New `admin_users.totp_last_counter` column (migration
`0003_totp_hardening`) plus `security.totp_counter()`, which resolves which step
a code belongs to and refuses any step at or below the last one used. The counter
is stored, never the code.
**Status:** PASS

### F-05 Re-enrolling 2FA silently broke the working authenticator

**Finding:** `POST /api/auth/2fa/setup` overwrote `totp_secret` while
`totp_enabled` stayed `true`.
**Impact:** The owner's authenticator stopped working with no warning and no
indication why; recovery codes were the only way back in. A hijacked session
could also move the second factor to the attacker's own device.
**Evidence:** `test_reenrolment_cannot_silently_break_live_2fa` — confirmed the
secret changed while 2FA remained enabled.
**Action:** New `admin_users.totp_pending_secret` stages the candidate secret;
it is promoted only once a valid code proves the authenticator works, and
re-enrolment while 2FA is on requires the current password. An abandoned
enrolment now changes nothing at all.
**Status:** PASS

### F-06 No request body size limit

**Finding:** Neither uvicorn nor FastAPI caps body size, and field
`max_length` validators run only after the whole payload is in memory.
`upload_media` also did `await file.read()` before any size check.
**Impact:** On the one endpoint the public internet can reach, an attacker chose
how much the process allocated. Measured: a 5 MB body was fully buffered and
answered `422`.
**Evidence:** `test_a_huge_request_body_is_refused_before_it_is_buffered`.
**Action:** A `limit_request_size` middleware rejects oversized bodies with
`413` before buffering — 256 KB for JSON, 72 MB for multipart uploads. Stated
plainly in the code: `Content-Length` is attacker-supplied, so this is a cheap
first gate, and the per-endpoint validators and upload size check remain behind
it.
**Status:** PASS

### F-07 `/admin/messages` was unbounded

**Finding:** The list query had no `LIMIT`.
**Impact:** An unauthenticated endpoint feeds that table, and each row carries up
to 5,000 characters. A spam flood turns the inbox into a response that cannot be
loaded — the abuse endpoint denying service to the tool for managing abuse.
**Evidence:** `test_message_list_is_bounded` — 120 rows inserted, 120 returned.
**Action:** `limit` (default 50, max 200) and `offset`, enforced by
`Query(ge=…, le=…)` rather than by the caller's good manners.
**Status:** PASS

### F-08 SQL echo was reachable in production

**Finding:** `echo=settings.debug` on the engine.
**Impact:** SQLAlchemy echo prints statements **and bound parameters**, which in
this schema means Argon2 password hashes, session token hashes and TOTP secrets
on stdout — straight into the host's log aggregator.
**Evidence:** `app/core/db.py` before the change.
**Action:** `echo=settings.debug and settings.environment != "production"`, and
`Settings` now refuses to start in production with `DEBUG=true` (F-02). Two
independent guards, because one is a single typo from being bypassed.
**Status:** PASS

### F-09 A sitemap pointing at `example.com` shipped in the build

**Finding:** `public/sitemap.xml` contained
`<loc>https://example.com/</loc>` and was copied verbatim into `dist/`.
**Impact:** A live, submittable sitemap advertising somebody else's domain. The
file's own comment said this was worse than none — and it shipped anyway,
because a static file in `public/` cannot express "only when configured".
**Evidence:** `dist/sitemap.xml` in the pre-audit build.
**Action:** `robots.txt` and `sitemap.xml` are now generated at build time from
`VITE_SITE_URL`. With it unset, **no sitemap is emitted at all** and `robots.txt`
carries no `Sitemap:` line. Verified in both states.
**Status:** PASS

### F-10 The public site had no security headers or CSP

**Finding:** The API sent a full header set; the static site sent none.
**Impact:** No defence-in-depth against injected script, no clickjacking
protection, no HSTS, no referrer control.
**Action:** Two parts, split by what each mechanism can actually carry:

- **CSP is injected into `index.html` at build time** (`inject-csp` in
  `vite.config.ts`) so it travels with the build to any host rather than living
  in one provider's config file. `connect-src` is *derived from*
  `VITE_CONTACT_ENDPOINT`, so the policy cannot drift from the API the build
  talks to.
- **`public/_headers`** carries what a meta tag cannot express:
  `frame-ancestors`, HSTS, `Permissions-Policy`, `Referrer-Policy`,
  `X-Content-Type-Options`, `Cross-Origin-Opener-Policy`, plus immutable caching
  for hashed assets.

The policy was **tested against the running application**, not just written:

| Feature | Result |
| --- | --- |
| CSP violations | none |
| Google Fonts (Fraunces) applied | yes — 23 faces loaded |
| Cabin video | `readyState: 4` |
| WebGL bokeh scene | canvas mounted |
| Certificate PDF iframe | opens, `frame-src 'self'` |
| Failed requests | none |
| Console errors | none |

Two directives were deliberately **left out**, with reasons, rather than added
off a checklist:

- `frame-ancestors` in the meta tag — ignored there, and Chrome logs a warning
  for every attempt. It is a real header in `_headers`.
- `upgrade-insecure-requests` — every allowed source is already https or
  `'self'`, so it buys nothing, and the Projects section links to one real,
  live, plain-http university deployment that must keep working.

**Status:** PASS — with a MANUAL caveat: `_headers` is Netlify / Cloudflare Pages
syntax. On any other host those six headers are **not applied**. See §19.

### F-11 An inline event handler forced `script-src 'unsafe-inline'`

**Finding:** `index.html` loaded fonts with `media="print" onload="this.media='all'"`.
**Impact:** One inline handler would have required `'unsafe-inline'` in
`script-src`, which is most of a CSP's value gone.
**Action:** The flip moved into the bundle (`src/main.tsx`), keyed off
`id="webfonts"`. Non-blocking font loading is preserved — verified
`webfontsMedia: "all"` and Fraunces applied — and `script-src 'self'` stays
strict.
**Status:** PASS

### F-12 Open Graph image was relative; no canonical or `og:url`

**Finding:** `og:image` was `/assets/background/cabin-poster.jpg`; there was no
canonical link and no `og:url`.
**Impact:** Most social scrapers silently drop a root-relative image, so link
previews would have been blank.
**Action:** All three are injected at build time from `VITE_SITE_URL` as
absolute URLs, and omitted entirely when it is unset. `cabin-poster.jpg` was
confirmed to exist (44 KB) — the preload uses `.webp`, and the `.jpg` is there
for scrapers that do not accept WebP.
**Status:** PASS (emission verified in both states); MANUAL to set the variable.

### F-13 2FA could not be enabled at all

**Finding:** `create-admin` printed "turn it on from Settings after signing in".
There is no 2FA screen in the admin UI — `git grep` for `2fa|totp` across
`apps/admin/src` returns nothing.
**Impact:** The instruction was false, and the security control was
unreachable. This is how 2FA ends up permanently off.
**Action:** Added `python -m app.cli enable-2fa` and `disable-2fa` — operational
tooling rather than new UI, which keeps the admin surface unchanged. `enable-2fa`
mirrors the API flow exactly (stage, prove, promote, mint recovery codes);
`disable-2fa` requires the account password and destroys the recovery codes. The
misleading message is corrected.
**Status:** PASS — enrolment is now possible; performing it is MANUAL (§19).

### F-14 A 0-byte orphan file

**Finding:** `src/components/ResourcePage.tsx`, 0 bytes, imported by nothing.
The admin's own 10 KB `ResourcePage.tsx` resolves through `apps/admin`'s own
`@/` alias, so this was a stray from the admin build.
**Action:** Removed, after confirming no importer anywhere in the repository.
**Status:** PASS

### F-15 Documentation contradicted the system

**Finding:** `docs/SPEC.md` §1 listed "admin CMS, FastAPI, PostgreSQL,
authentication, 2FA, media library, contact-form backend" as out of scope. All
seven exist.
**Impact:** The specification actively misdirects anyone — including a future
session — reading it as current.
**Action:** §1 rewritten to record why the CMS came second and that it now
exists, while restating what has *not* changed: the public site is still static.
§9 item 5 updated to the single `VITE_SITE_URL` variable.
**Status:** PASS

---

## 4. Authentication audit

| Control | Finding | Status |
| --- | --- | --- |
| Password hashing | Argon2id, explicit parameters (t=3, m=64 MiB, p=2) so a dependency upgrade cannot silently weaken them | PASS |
| Plaintext storage | None. Only ever an Argon2 hash | PASS |
| Password logging | No application logging exists at all; nothing to leak | PASS |
| Account enumeration | Unknown email and wrong password return the identical error, and a missing account still runs a full Argon2 verification against a dummy hash so timing matches | PASS |
| Rehash on policy change | `check_needs_rehash` on successful login | PASS |
| Session cookie `HttpOnly` | Verified in the `Set-Cookie` header | PASS |
| `Secure` in production | `cookies_secure` is `environment == "production"`; asserted | PASS |
| `SameSite` | `Lax` on both cookies | PASS |
| Session expiry | Absolute, not sliding — a stolen cookie has a bounded life however actively used | PASS |
| Session invalidation | `revoked_at`, checked on every resolve | PASS |
| Logout | Revokes server-side; replaying the cookie by hand returns `401` | PASS |
| Session id in JS | Not readable — `HttpOnly`. The CSRF cookie is deliberately readable and is not a credential | PASS |
| Session id in localStorage | Never. `git grep localStorage` in `apps/admin/src`: no session use | PASS |
| Session fixation | A pre-set cookie value is never adopted; login always mints a new token | PASS |
| Token storage | Session and CSRF tokens stored SHA-256 hashed, so a DB leak yields no usable sessions | PASS |
| Login rate limiting | Per-IP window + per-account exponential backoff, capped so an attacker cannot lock an account out permanently | PASS |
| Failed attempts | Recorded with IP and user agent; committed even on the failure path, so the limit cannot be defeated by failing repeatedly | PASS |
| 2FA rate limiting | **Was missing — F-03.** Now enforced | PASS |
| TOTP replay | **Was possible — F-04.** Now refused | PASS |
| Recovery codes | Single-use, stored hashed, shown exactly once; reuse returns `401` | PASS |
| Password change | Requires the current password and revokes every other session | PASS |
| 2FA enforced when enabled | No session is issued until the second factor succeeds; the pending token can do nothing else | PASS |
| 2FA enabled in production | Not yet — `list-admins` reports `2FA OFF` | MANUAL |

---

## 5. Authorization audit

Every admin router depends on `AdminDep`, which resolves the session
server-side on every request. The admin UI hiding a control is never the
boundary.

| Test | Expected | Actual | Status |
| --- | --- | --- | --- |
| 14 admin `GET` routes unauthenticated | 401 | 401 | PASS |
| Admin writes unauthenticated | 401 | 401 | PASS |
| Authenticated write without CSRF header | 403 | 403 | PASS |
| Authenticated write with CSRF header | 2xx | 2xx | PASS |
| Rollback unauthenticated | 401/403 | 401 | PASS |
| Publish unauthenticated | 401 | 401 | PASS |
| Media file route unauthenticated | 401 | 401 | PASS |
| Private media file by id, unauthenticated | 401 | 401 | PASS |
| Unknown UUID on 4 resources | 404 | 404 | PASS |
| Malformed id (`not-a-uuid`, `%00`, `1 OR 1=1`, `../../etc/passwd`) | 400/404/422, no traceback | as expected | PASS |
| Session revoked mid-life | 401 | 401 | PASS |
| Account deactivated mid-session | 401 | 401 | PASS |

**IDOR:** the system is single-tenant — one owner account — so there is no
cross-tenant object to reach. What was tested instead is that object ids cannot
be used to reach anything *outside* the authorisation check, and that a
malformed id produces a clean rejection rather than a 500. Media ids in
particular do not expose private files: `GET /admin/media/{id}/file` is
session-gated regardless of the asset's `is_public` flag, because the public site
serves its own copies and never calls the API.

---

## 6. Upload, media and XSS audit

### Upload validation

Decided by **sniffed content plus an allow-list**, never by filename or the
client's `Content-Type`.

| Attack | Result | Status |
| --- | --- | --- |
| `fake-image.jpg` containing non-image bytes | `400 content_mismatch` — rejected, not corrected | PASS |
| Disallowed type (`.php`, `text/html`, …) | `400 type_not_allowed` | PASS |
| `../../file`, `..\file` in the filename | Reduced to a leaf name; stored under a generated `secrets.token_hex(16)` name | PASS |
| SVG | Excluded from the allow-list — it is XML that can carry `<script>` | PASS |
| Double extension (`file.php.jpg`) | Irrelevant by construction: the stored extension comes from the *verified* type, never the upload | PASS |
| Empty file | `400 empty_file` | PASS |
| Oversized | Per-kind caps (image 10 MB, video 64 MB, audio 20 MB, document 25 MB), now also gated before buffering (F-06) | PASS |
| Path containment on write | `destination.resolve().is_relative_to(root)` | PASS |

### Storage key traversal

`resolve_path` is the only thing between a stored key and the filesystem. Seven
escape attempts — `uploads/../../../../Windows/win.ini`, `uploads/../../.env`,
`assets/../../services/api/.env`, `..\..\.env`, `/etc/passwd`, `etc/passwd`,
`uploads/%2e%2e%2f.env` — all `404`. **PASS**

### Media access control

| Check | Evidence | Status |
| --- | --- | --- |
| Private media never enters a snapshot | `_asset()` returns `None` for `is_public=False`; `test_export_never_references_a_private_asset` | PASS |
| Export never copies a private file | It copies only what the snapshot references, so privacy is enforced at the source | PASS |
| In-use media cannot be deleted | `409 in_use` with the reference count | PASS |
| Deleted media leaves no orphan | Row deleted first, file unlinked only after the commit succeeds | PASS |
| Public media served publicly | As ordinary static files from `public/`, not via the API | PASS |

### XSS

`dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `document.write`, `eval`
and `new Function`: **zero occurrences** across `src` and `apps/admin/src`.

Tested end to end against the live stack — payloads submitted through the public
contact form, then rendered in the admin Messages page:

```
<script>window.__pwned=1</script>
<img src=x onerror="window.__pwned=2">
<svg/onload=window.__pwned=3>
```

| Observation | Result |
| --- | --- |
| `window.__pwned` | `null` — nothing executed |
| Injected `<script>` / `<iframe>` / `<svg onload>` in the DOM | 0 / 0 / 0 |
| `<img onerror>` attributes | 0 |
| `javascript:` hrefs | 0 |
| Payload rendered as literal text | yes — `<img src=x onerror="window.__pwned=2">` displayed verbatim |
| Dialogs triggered | none |

The third submission returned `429`, which incidentally confirmed the per-IP
rate limit against the live database. All test messages were then deleted from
the real inbox (7 removed, 0 real messages present). **PASS**

### Contact endpoint

| Test | Expected | Actual | Status |
| --- | --- | --- | --- |
| Valid submission | 200, stored | 200, stored, `is_read=false` | PASS |
| Empty / missing fields | 422, nothing stored | 422, 0 rows | PASS |
| Malformed email | 422 | 422 | PASS |
| Message under 10 chars | 422 | 422 | PASS |
| Oversized field values | 422, nothing stored | 422, 0 rows | PASS |
| 5 MB body | 413 before buffering | 413 | PASS (F-06) |
| Honeypot filled | 200, **nothing stored** | 200, 0 rows | PASS |
| 6th submission in an hour | 429 + `Retry-After` | 429, `Retry-After: 3600` | PASS |
| Blocked submission stored? | No — the limit must not ratchet itself | 0 rows | PASS |
| Control characters | Stripped; newlines and tabs kept | `\r`, `\x00`, `\x07` removed, paragraphs intact | PASS |
| Error responses | No traceback, no `sqlalchemy`, no `psycopg`, no filesystem paths | none present | PASS |
| Success claimed only after acceptance | Only a 2xx shows the success message | verified in a real browser: "Thanks — your message has been sent.", form cleared, 1,489 ms round trip | PASS |

---

## 7. Database audit

| Check | Evidence | Status |
| --- | --- | --- |
| TLS | `sslmode=require&channel_binding=require` in the connection URL | PASS |
| Parameterised queries | All access is SQLAlchemy ORM. The only `text()` uses are a static index expression (`lower(email)`) and the health check `SELECT 1` | PASS |
| SQL injection | 5 payloads (`'; DROP TABLE projects; --`, `' OR '1'='1`, `" UNION SELECT password_hash FROM admin_users --`, …) stored verbatim as text; `admin_users` row count unchanged | PASS |
| User-controlled sorting | None exists. `order_by` is supplied by the server-side resource config, so there is no field to allow-list | PASS |
| Pagination bounded | `snapshots` capped at 50; `messages` now `limit`/`offset` with a hard ceiling (F-07). Other collections are admin-authored and small (4 projects, 11 achievements, 27 media) | PASS |
| Connection handling | `pool_pre_ping=False` with `pool_recycle=280` — pre-ping cost a full round trip on every request | PASS |
| Migrations | `0001` → `0002` → `0003`, single linear head, `alembic check` reports no drift | PASS |
| Indexes / FKs / constraints | 16 indexes, 21 foreign keys, 16 CHECK constraints, verified from the backup's schema section | PASS |
| Least privilege | The application connects as `neondb_owner`. A dedicated non-owner role with only DML rights would be better; `.env.example` already tells operators not to run as superuser | MANUAL |
| Region | **`us-east-2` (Ohio)** — see §11 | MANUAL |

### Backup and restore

A real backup was taken and verified:

```
pg_dump --format=custom --no-owner --no-privileges   (PostgreSQL 18 client,
                                                      server 18.6 — versions match)
→ 82,501 bytes
→ pg_restore --list        : 25 TABLE DATA entries
→ pg_restore --schema-only : 1,154 lines, 25 CREATE TABLE, 16 indexes,
                             21 FOREIGN KEY, 16 CHECK
```

The archive is complete and readable. It was written to the session scratchpad,
**not** the repository, so it cannot be committed.

**A full restore test was not performed.** Stated plainly: it needs a throwaway
target database. The local PostgreSQL 18 server is running but requires a
password that is not available in the repository, and asking for a credential to
be pasted into a chat is not acceptable. The manual procedure is in §19.

---

## 8. Secret audit

Scanned with 14 patterns (Neon host and password prefix, PostgreSQL URLs with
credentials, private key blocks, AWS / GitHub / Slack / Google keys, JWT
literals, Netlify and Vercel hook URLs, assigned secrets and passwords, SMTP
credentials) across three surfaces: **tracked files**, **build output plus
`snapshot.json`**, and **the full git history** (`git log -p --all`).

The scan reports pattern name, file and line **number only** — never the matched
value — so the report itself cannot leak a credential.

| Surface | Result |
| --- | --- |
| Build output (`dist`, `apps/admin/dist`) and `snapshot.json` | **clean** |
| Tracked files | 8 hits, **all false positives** (below) |
| Git history | Same 8, plus one extra line from an edit to `.env.example`. **No credential was ever committed** |
| `.env` files ever added to git | Only `.env.example` and `services/api/.env.example` — both intentional templates |
| Real Neon credential (`.neon.tech`, `npg_…`) | **0 occurrences** in tracked files, 0 in history |
| Real admin credential | **0 occurrences** in tracked files, 0 in history |
| Live `.env` files | Untracked and ignored (`.gitignore:27-28`), confirmed via `git check-ignore -v` |

Verified as false positives by reading the actual context:

| Location | Value | Verdict |
| --- | --- | --- |
| `services/api/.env.example:9` | `…://mj_admin:CHANGE_ME@localhost:5432/…` | Template placeholder |
| `services/api/.env.example:13` | `SECRET_KEY=CHANGE_ME_GENERATE_A_REAL_ONE` | Template placeholder |
| `tests/conftest.py:11` | `…://test:test@localhost/test` | Test fixture, never connected to |
| `tests/conftest.py:62` | `correct-horse-battery-staple` | Test fixture |
| `tests/test_auth.py:70,71,92,109` | `whatever-long`, `definitely-not-the-password`, `wrong-password-here` | Deliberately wrong passwords in negative tests |

Secrets are environment-provided throughout: `DATABASE_URL`, `SECRET_KEY`,
`CORS_ORIGINS`, `ALLOWED_HOSTS`, `DEPLOY_HOOK_URL` in `services/api/.env`;
`VITE_CONTACT_ENDPOINT` and `VITE_SITE_URL` in the root env file. The two `VITE_`
values are **baked into the public bundle and are therefore public** — stated at
the top of `.env.example` so nobody puts a secret there.

The deploy hook is treated as a bearer credential: never returned by the API
(`GET /admin/publish/deploy` answers only `{"configured": true|false}`), and the
audit log records the hook's **host only**. `test_deploy_hook_is_fired_and_never_leaks_its_url`
asserts a token in the hook URL does not appear anywhere in the response.

**Status: PASS.** No git history rewrite is needed, and none was performed.

---

## 9. Git history audit

4 commits, one linear branch (`master`), no merges. `git log -p --all` scanned as
above.

| Looked for | Found |
| --- | --- |
| Passwords, API keys, DB credentials, tokens, private keys | none |
| `.env` files | only the two `.env.example` templates |
| Certificates or deployment secrets | none |

**Two credentials were exposed in conversation transcripts, not in git**: the
Neon connection string and the development admin password. Git history is clean,
so a rewrite would achieve nothing. The correct remediation is **rotation** —
§19 items 1 and 2. Neither value appears in this document.

Checkpoint tag `phase-6-complete` created at `27a887c` before any change. No
history was rewritten, no tag overwritten, no destructive git operation
performed.

---

## 10. Dependency audit

| Ecosystem | Tool | Result |
| --- | --- | --- |
| Public site npm | `npm audit` (prod and dev) | **0 vulnerabilities** |
| Admin npm | `npm audit` (prod and dev) | **0 vulnerabilities** |
| Python, 48 packages | OSV.dev advisory database | **0 advisories** |

`pip-audit` could not run: PyPI's TLS chain fails to verify in this environment
(`unable to get local issuer certificate` — the same interception that breaks
`git clone` here). Rather than skip the check, the same advisory database
`pip-audit` uses was queried directly through OSV's batch API from Node, whose
TLS store does work. 48 packages checked, 0 matches.

Available upgrades, none security-related, **none applied**:

| Package | Current | Latest | Decision |
| --- | --- | --- | --- |
| SQLAlchemy | 2.0.54 | 2.1.1 | Minor-version jump across a major series boundary. Manual decision |
| uvicorn | 0.53.0 | 0.54.0 | Safe, but no reason mid-audit |
| pydantic-core | 2.46.5 | 2.49.0 | Transitive; pinned by pydantic |
| ruff | 0.16.8 | 0.16.9 | Dev tool only |

One dependency **was** added in Phase 6 and is confirmed correct here: `httpx`
is declared as a runtime dependency because `deploy_service` imports it at module
scope. It previously arrived only transitively via `TestClient`, which would have
broken a fresh production install on import.

---

## 11. Performance audit

Measured against the production build via `npm run preview`, not the dev server.

### Public site, by visual tier

| Tier | Transfer | Requests | 3D chunk | Video | FCP | LCP | CLS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Desktop 1440 (`full`) | 1,083 kB | 12 | requested | yes | 532 ms | 532 ms | 0.0011 |
| Mobile 390 (`still`) | **134 kB** | 9 | **not requested** | no | 360 ms | 360 ms | 0.0000 |
| Reduce-motion (`still`) | **134 kB** | 9 | **not requested** | no | 300 ms | 300 ms | 0.0009 |
| `saveData: true` (`still`) | 208 kB | — | **not requested** | no | — | — | — |
| `effectiveType: 3g` (`still`) | 134 kB | — | **not requested** | no | — | — | — |
| `effectiveType: slow-2g` (`still`) | 134 kB | — | **not requested** | no | — | — | — |

Bundles: main **122.13 kB gzip**, `AmbientScene` **234.54 kB gzip**, CSS 8.42 kB.
Both unchanged from the pre-audit reference figures, confirming the
`vite.config.ts` changes cost nothing.

§25 asked whether `AmbientScene` could be loaded more efficiently. The honest
answer is that all five suggested approaches are already implemented, and this
audit verified them **on the network** rather than in the source: lazy loading
via `React.lazy`, correct automatic code splitting (no `manualChunks`),
reduce-motion, Save-Data and mobile all resolving to the `still` tier. Only the
`full` tier ever requests the chunk. There is nothing left to gain without
removing the effect, which is not on the table.

Both documented bundler invariants were re-verified after the config change:

- `dist/index.html` contains **no** `modulepreload` at all, so none for the 3D chunk.
- The entry chunk has **no static import** of the 3D chunk and no `WebGLRenderer`.

### Admin, against Neon — the real bottleneck

| Page | Time to content |
| --- | --- |
| Dashboard (first load, cold connection) | 18,754 ms |
| Publish | 16,811 ms |
| Media | 8,056 ms |
| Skills / Projects / About | 5,737 – 6,108 ms |
| Career / Achievements / Messages / Settings / Social / Home | 3,155 – 3,610 ms |

All 12 pages render real content, no page errors, no 5xx, no error banners.

Profiling separates the two possible causes:

```
SELECT 1, warm connection, ×7 : median 338 ms  (min 266, max 540)
cold connect + first query    : 3,216 ms
build_snapshot                : 27 queries →  9,434 ms
media reference_counts        : 12 queries →  3,897 ms
current_snapshot              :  1 query   →    321 ms
3 × count(*)                  :  3 queries →  1,004 ms
```

Every wall time equals **queries × ~338 ms**. That is decisive: there is **no
N+1 left to fix** — 27 queries is the correct number for assembling a full
snapshot, and `reference_counts` is already the grouped version that replaced a
324-query N+1. The remaining cost is entirely network distance.

Region confirmed as **`us-east-2`** (Ohio) from the connection host. Moving the
Neon project to `ap-south-1` (Mumbai) or `ap-southeast-1` (Singapore) should take
the per-query cost from ~338 ms to roughly 20–40 ms — around a 10× improvement,
turning the 16.8 s Publish page into well under 2 s. **This was not performed:**
Neon cannot move a project between regions, so it requires creating a new project
and re-running `alembic upgrade head` and `python -m app.seed`. Procedure in §19.

An optional code-level saving exists independently: `_counts()` in
`app/api/admin/publish.py` issues 7 separate `count(*)` queries that could be one
statement with scalar subqueries, worth ~2 s at the current latency and ~0.2 s
after a region move. **Not applied** — it is an optimisation of correct, working
code, and the region move dominates it by an order of magnitude.

This latency is also the strongest possible argument *for* the existing
architecture: the public site is completely unaffected, because it never touches
the database.

---

## 12. Accessibility audit

axe-core, tags `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `best-practice`:

```
violations: 0        passes: 46
```

| Check | Result |
| --- | --- |
| `<h1>` count | exactly 1 |
| Section landmarks | all 7: home, about, skills, projects, career, achievements, contacts |
| Focusable elements | 58, **none without an accessible name** |
| Scroll-spy `aria-current` | correct on all 7 sections |
| Horizontal overflow at 390 / 768 / 1024 / 1440 | none — `scrollWidth == clientWidth` at every width |
| Images loaded | 14/14 at every width |
| Console errors | none |
| Reduced motion | resolves to the `still` tier; no video, no WebGL |
| Certificate dialog | native `<dialog>`, so focus trapping, Escape and background inerting come from the browser |
| Contrast | Documented per token in `docs/SPEC.md` §2; `--color-faint` (3.4:1) is marked decorative-only and is not used for text |

One note on method: the site's `script-src 'self'` correctly **blocked
axe-core's own injection**, which is itself evidence the policy works. The
harness now sets `page.setBypassCSP(true)` for instrumentation only; the CSP was
verified separately with it enforced (F-10).

---

## 13. SEO and production metadata

| Item | State | Status |
| --- | --- | --- |
| `<title>` | "Mohammed Majeed J — Full Stack Developer" | PASS |
| `<meta name="description">` | Present | PASS |
| `og:type`, `og:title`, `og:description` | Present | PASS |
| `og:image` | Absolute, from `VITE_SITE_URL`; file exists (44 KB JPEG) | PASS / MANUAL |
| `og:url`, canonical | Generated from `VITE_SITE_URL`; omitted when unset | PASS / MANUAL |
| `twitter:card` | `summary_large_image` | PASS |
| Favicon | `/favicon.svg`, present in `dist` | PASS |
| `robots.txt` | Generated; `Sitemap:` line only when configured | PASS |
| `sitemap.xml` | Generated **only** when configured — was shipping `example.com` (F-09) | PASS |
| `theme-color`, `color-scheme` | Present | PASS |
| Structured data | None implemented; none claimed | n/a |
| Site URL | Unset | **MANUAL** |

---

## 14. End-to-end results

### Public site

| Flow | Result |
| --- | --- |
| All 7 sections render | PASS |
| Navigation and scroll spy | PASS — all 7 correct |
| Contact form, real browser → API → Neon → admin inbox | PASS — success message shown, form cleared, 1,489 ms |
| Honeypot | PASS — invisible, `aria-hidden`, `tabIndex -1`, unreachable by keyboard |
| Client validation | PASS — 4 field errors on an empty submit |
| Video | PASS — `readyState: 4` at the `full` tier, absent at `still` |
| Audio player | PASS — present |
| Certificate PDF dialog | PASS — opens with a same-origin iframe |
| Responsive 390 / 768 / 1024 / 1440 | PASS — no overflow |
| Reduced motion, Save-Data, slow connection | PASS — `still` tier |
| Console | PASS — no errors |
| Broken assets | PASS — none |

### Admin

| Flow | Result |
| --- | --- |
| Login | PASS |
| All 12 pages render real content | PASS — no page errors, no 5xx, no error banners |
| Optimistic locking | PASS — stale `expected_updated_at` → `409 stale_write` |
| Logout | PASS — `204`, then `/auth/me` → `401` |
| CRUD, reorder, archive/restore | PASS — covered by 133 tests |
| Upload, replace, clear, media picker | PASS — covered by tests, including attack payloads |
| Publish preview → publish → snapshot → rollback | PASS — exercised against live Postgres, not only SQLite |
| Messages pagination (`?limit=200`) | PASS |

2FA could not be exercised in the live browser flow because it is not enabled on
the production account. It is covered by tests, and enrolment is now possible via
the CLI (F-13).

---

## 15. DOTE withheld document — regression

**Policy unchanged and verified at the strongest level.** The TN DOTE
typewriting certificate is listed as a credential; its scan and PDF are not
published, because that document carries date of birth, register number, a
passport photograph, a signature and the download IP — a complete identity kit.

| Check | Result |
| --- | --- |
| Credential record present | yes — title, organisation, `credentialId` |
| `image` in snapshot | `null` |
| `document` in snapshot | `null` |
| File in `public/` | **does not exist** |
| File in `dist/` | **does not exist** |
| Any file matching `dote` or `typewrit` in `public/` or `dist/` | **none** |
| Certificates that do ship | 10 PDFs, 10 thumbnail pairs — all others |

This is the right implementation: privacy by **absence**, not by an omitted link.
There is no URL to guess, so no CDN misconfiguration can expose it. The API-side
guarantee is independent and also holds — `allow_download` gates the document,
and `is_public=False` keeps any private asset out of a snapshot, both covered by
tests.

**Status: PASS. Do not change this.**

---

## 16. Content integrity

| Search | Result |
| --- | --- |
| `TODO_REPLACE_` in built JS | 1 — the `isTodo()` guard's own prefix string. Required, not a leak |
| `TODO_REPLACE_` in `dist/index.html` | 0 — the stale comment was removed (F-12) |
| `lorem ipsum` | none |
| Probe strings (`PROBE_`, `browser-test`, `XSS Probe`, `Endpoint Check`) | none in source or build |
| Test messages in the live inbox | 7 found, all created by testing, all deleted. 0 real messages were present |
| `example.com` | Was in `sitemap.xml` — fixed (F-09) |
| Placeholder audio | **Still shipping** — see below |

**33 `TODO_REPLACE_*` fields remain.** They render as nothing rather than as a
placeholder, which is correct for a visitor but means a section can look finished
while being empty. They are content tasks, not defects, and nothing here may be
invented:

| File | Count | What is missing |
| --- | --- | --- |
| `about.ts` | 8 | Education dates and locations, philosophy block |
| `career.ts` | 9 | Entry dates, locations, descriptions |
| `achievements.ts` | 4 | Four certificate descriptions |
| `home.ts` | 4 | Résumé PDF path, three "field notes" lines |
| `site.ts` | 2 | Site URL, OG image token |
| `contacts.ts` | 1 | Contact introduction |

The music player still carries `placeholder-ambient.mp3`, titled "Ambient
placeholder" by "Temporary — replace before launch", with `isPlaceholder: true`.
That is a deliberate design decision — the player labels it on screen so a
stand-in can never be mistaken for a choice — but it should not ship to a live
portfolio. Either replace the track or remove the player.

---

## 17. Error handling, logging and observability

| Check | Result | Status |
| --- | --- | --- |
| Unhandled exception response | `500` with `{"detail":{"code":"internal_error","message":"Something went wrong."}}` — no traceback, no driver message, no filesystem path, no secret | PASS |
| Validation errors | `422`, field paths only | PASS |
| `4xx` bodies | Stable `{code, message}` shape; no internals | PASS |
| Interactive docs in production | `docs_url` and `openapi_url` set to `None` — the schema is a map of the attack surface | PASS |
| SQL echo | Gated on `DEBUG` **and** hard-disabled in production (F-08) | PASS |
| Application logging | **None exists** — so no password, token, cookie, API key, credential or TOTP secret can be logged | PASS |
| Diagnostics retained | Unhandled exceptions are still re-raised after the clean response, so uvicorn logs the traceback server-side; the append-only `audit_logs` table records every authentication event and content mutation with actor, action, target, IP and user agent | PASS |
| Audit log flooding | The public contact endpoint deliberately does **not** write to it — an unauthenticated endpoint that can append to the audit log can drown it | PASS |

Worth stating as a deliberate trade-off rather than an oversight: there is no
structured application logging. For a single-operator CMS the audit table plus
uvicorn's own logs are adequate, and the absence removes an entire class of
credential-leak bug. If request logging is ever added, it must exclude the
`Cookie` and `X-CSRF-Token` headers.

### False positive — the 500 handler

The first run of `test_unhandled_error_returns_a_clean_500` failed with the raw
`RuntimeError` reaching the client, which looked like a leak. It was not.
`TestClient` defaults to `raise_server_exceptions=True`, which re-raises the
original exception *after* the handler has produced its response, hiding what a
real peer receives. Re-tested with `raise_server_exceptions=False`, the response
is clean JSON with no traceback and no secret. **The test was wrong, not the
code**, and it was corrected rather than the finding being reported.

---

## 18. Production configuration checklist

Nothing below is guessed. Unknown values are left blank.

### API — `services/api/.env`

- [ ] `ENVIRONMENT=production`
- [ ] `DEBUG=false` — production now refuses to start if this is true
- [ ] `DATABASE_URL` — with `sslmode=require`; ideally a non-owner role
- [ ] `SECRET_KEY` — fresh, ≥32 chars, `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- [ ] `CORS_ORIGINS` — the production **site** origin(s), https only, comma separated
- [ ] `ALLOWED_HOSTS` — the production **API** hostname(s)
- [ ] `DEPLOY_HOOK_URL` — the static host's build hook (treat as a secret)
- [ ] `SESSION_LIFETIME_HOURS`, `MAX_FAILED_LOGINS` — defaults are sound

### Public site — root `.env`

- [ ] `VITE_SITE_URL` — the site's own origin
- [ ] `VITE_CONTACT_ENDPOINT` — `https://<api host>/api/public/contact`

Both are **baked into the public bundle and are public**. Never put a secret here.

### Infrastructure

- [ ] Production frontend host
- [ ] Production API host
- [ ] DNS for both
- [ ] HTTPS certificates for both
- [ ] Security headers applied — `public/_headers` works on Netlify and
      Cloudflare Pages only; see §19 item 8
- [ ] Neon region decided (§19 item 7)
- [ ] Backup schedule and a tested restore procedure
- [ ] Secret storage — the host's environment settings, never the repository

### Accounts

- [ ] Admin password rotated (§19 item 1)
- [ ] Neon credential rotated (§19 item 2)
- [ ] 2FA enabled (§19 item 3)

### Content

- [ ] 33 `TODO_REPLACE_*` fields filled or the sections removed (§16)
- [ ] Placeholder audio replaced, or the player removed
- [ ] Résumé PDF added

---

## 19. Manual actions required

Only actions that are still outstanding after this audit, and that cannot be
performed safely from inside the repository.

**1. Rotate the admin credential.** The development password was exposed in a
conversation transcript. Treat it as compromised.
```bash
cd services/api
python -m app.cli reset-password      # prompts, no echo, revokes every session
```
Do not send the new password to anyone, including to this assistant.

**2. Rotate the Neon database credential.** The connection string was pasted into
a transcript. Reset the role's password in the Neon console and update
`services/api/.env`. Git history is clean, so no rewrite is needed.

**3. Enable 2FA.** Currently `2FA OFF` for `majeed74905@gmail.com`.
```bash
cd services/api
python -m app.cli enable-2fa
```
Store the ten recovery codes somewhere reachable without the phone; they are
shown exactly once. The secret is printed to your terminal only and is never
logged.

**4. Set `VITE_SITE_URL`** in the root env file, then rebuild. Until it is set
there is no canonical link, no `og:url`, no absolute `og:image` and no sitemap —
deliberately, because wrong values are worse than absent ones.

**5. Set `VITE_CONTACT_ENDPOINT`** to the production API URL. Until it is set the
contact form says sending is not connected rather than pretending to send.

**6. Set `CORS_ORIGINS` and `ALLOWED_HOSTS`** to the real production origins and
hostnames. The API will refuse to start in production without them, which is the
intended behaviour.

**7. Decide the Neon region.** Current: `us-east-2` (Ohio), measured at **338 ms
per query** and 3.2 s to establish a connection. `ap-south-1` (Mumbai) or
`ap-southeast-1` (Singapore) should give roughly a 10× improvement.

Neon cannot move a project between regions, so this is a migration, not a
setting:
```bash
# 1. Create a NEW Neon project in ap-south-1 (or ap-southeast-1).
# 2. Back up the current database first:
"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" --format=custom \
    --no-owner --no-privileges --file=backup.dump "<OLD_URL>"
# 3. Point services/api/.env at the new DATABASE_URL.
# 4. Recreate the schema and content (both are idempotent):
cd services/api
python -m alembic upgrade head
python -m app.seed
# 5. Verify, then delete the old project.
```
The public site is unaffected either way — it never queries the database.

**8. Apply the security headers on the chosen host.** `public/_headers` is
Netlify / Cloudflare Pages syntax and is inert elsewhere, which means those six
headers would simply be missing. For nginx:
```nginx
add_header Content-Security-Policy "frame-ancestors 'none'" always;
add_header X-Frame-Options "DENY" always;
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()" always;
add_header Cross-Origin-Opener-Policy "same-origin" always;
```
For Apache, the same set via `Header always set`. The Content-Security-Policy
that governs scripts, styles and connections is already in the built HTML and
needs no host configuration.

**9. Test a restore.** A verified backup exists but was not restored, because
that needs a throwaway target database.
```bash
# Create an empty database, then:
"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" --no-owner --no-privileges \
    --dbname="<SCRATCH_DB_URL>" backup.dump
# Then check row counts against the source. Never restore over production.
```
On Neon, the cheapest version of this is a branch of the production database:
restore into the branch, verify, delete the branch.

**10. Finish the content.** 33 `TODO_REPLACE_*` fields (§16), the placeholder
audio track, and the résumé PDF. Nothing here may be invented — if a value is
not known, the field must stay empty.

---

## 20. Final security test matrix

| Area | Test | Expected | Actual | Status |
| --- | --- | --- | --- | --- |
| Authentication | Wrong password | 401, generic | 401, `invalid_credentials` | PASS |
| Authentication | Unknown email | Same as wrong password | Identical response and timing | PASS |
| Authentication | Inactive account | Same as wrong password | Identical | PASS |
| Authentication | 5 failures | Lockout with backoff | `locked_until` set, 429 | PASS |
| Authentication | Per-IP limit | 429 + `Retry-After` | 429 | PASS |
| Authentication | 2FA brute force | Lockout | 429 after threshold | PASS (F-03) |
| Authentication | TOTP replay | Second use refused | Refused | PASS (F-04) |
| Authentication | Recovery code reuse | 401 | 401 | PASS |
| Authentication | 2FA re-enrolment | Password required, live secret untouched | 400 `password_required` | PASS (F-05) |
| Session | Fixation | Pre-set cookie ignored | New token minted | PASS |
| Session | `HttpOnly` / `SameSite` / `Secure` | Set; `Secure` in production | Verified | PASS |
| Session | Logout | Server-side revocation | Cookie replay → 401 | PASS |
| Session | Revoked / deactivated | 401 | 401 | PASS |
| Authorization | 14 admin GETs unauthenticated | 401 | 401 | PASS |
| Authorization | Admin writes unauthenticated | 401 | 401 | PASS |
| Authorization | Publish / rollback unauthenticated | 401 | 401 | PASS |
| CSRF | Write without header | 403 | 403 | PASS |
| CSRF | Write with header | 2xx | 2xx | PASS |
| Rate limiting | Contact, 6th in an hour | 429 + `Retry-After` | 429, 3600 | PASS |
| Rate limiting | Blocked submission stored | No | 0 rows | PASS |
| SQL injection | 5 payloads on a write endpoint | Treated as data | Stored verbatim, tables intact | PASS |
| XSS | 3 stored payloads rendered in admin | Inert text | `__pwned` null, 0 injected nodes | PASS |
| XSS | `dangerouslySetInnerHTML` | None | 0 occurrences | PASS |
| Upload | Non-image bytes as `image/png` | Rejected | 400 `content_mismatch` | PASS |
| Upload | Disallowed type | Rejected | 400 `type_not_allowed` | PASS |
| Upload | SVG | Not accepted | Absent from allow-list | PASS |
| Upload | Traversal in filename | Sanitised | Generated name used | PASS |
| Path traversal | 7 storage keys escaping the root | 404 | 404 | PASS |
| IDOR | Unknown UUID, 4 resources | 404 | 404 | PASS |
| IDOR | Malformed id, 4 shapes | Clean 4xx | 400/404/422, no traceback | PASS |
| Private media | File route unauthenticated | 401 | 401 | PASS |
| Private media | Private asset in snapshot | Absent | Absent | PASS |
| Private media | DOTE document and image | Withheld | `null`, and no file exists | PASS |
| Publish | Failed publish | Live snapshot untouched | Previous still served | PASS |
| Publish | `TODO_REPLACE_` in content | Blocked | Blocked | PASS |
| Rollback | Already-live snapshot | 409 | 409 `already_live` | PASS |
| Rollback | History | Append-only | New row, 3 rows kept | PASS |
| Rollback | Invalid stored snapshot | 422, nothing restored | 422 `rollback_failed` | PASS |
| Deploy hook | URL in any response | Never | Token absent | PASS |
| Deploy hook | Hook failure | Publish still succeeds | Snapshot published, reported | PASS |
| Deploy hook | No hook configured | Reported plainly | `triggered: false` + reason | PASS |
| Secrets | Build output and snapshot | Clean | Clean | PASS |
| Secrets | Git history | No credential | None | PASS |
| Secrets | `.env` ignored | Yes | Confirmed | PASS |
| CORS | Wildcard in production | Refuse to start | `ValueError` | PASS (F-02) |
| CORS | localhost or http origin in production | Refuse to start | `ValueError` | PASS (F-02) |
| Hosts | Empty or localhost `ALLOWED_HOSTS` in production | Refuse to start | `ValueError` | PASS (F-01) |
| HTTPS | `Secure` cookies in production | Forced | `cookies_secure` true | PASS |
| HTTPS | HSTS | Sent in production | Set | PASS |
| Headers | API `nosniff` / `DENY` / CSP / `Referrer-Policy` | Present | Present | PASS |
| Headers | Admin responses cacheable | `no-store` | `no-store` | PASS |
| Headers | Public site CSP | Enforced, nothing broken | 0 violations, all features work | PASS (F-10) |
| Headers | Public site `frame-ancestors`, HSTS, Permissions-Policy | Real headers needed | In `_headers`; host-dependent | MANUAL |
| Request limits | 5 MB JSON body | 413 before buffering | 413 | PASS (F-06) |
| Response limits | Message list | Bounded | limit/offset enforced | PASS (F-07) |
| Error handling | Unhandled exception | Clean JSON | No traceback, no secret | PASS |
| Logging | Secrets in logs | None | No logging exists | PASS |
| Dependencies | npm, both apps | 0 vulnerabilities | 0 | PASS |
| Dependencies | Python, 48 packages | 0 advisories | 0 | PASS |
| Accessibility | axe, 4 WCAG tag sets | 0 violations | 0 / 46 passes | PASS |
| Accessibility | Overflow at 4 widths | None | None | PASS |
| Migrations | Drift | None | "No new upgrade operations detected" | PASS |
| 2FA | Enabled on the production account | Yes | **No** | MANUAL |
| Config | `VITE_SITE_URL`, `VITE_CONTACT_ENDPOINT`, `CORS_ORIGINS`, `ALLOWED_HOSTS`, `DEPLOY_HOOK_URL` | Set | **Unset** | MANUAL |
| Credentials | Admin password, Neon credential | Rotated | **Not rotated** | MANUAL |
| Database | Region near users | Yes | `us-east-2`, 338 ms/query | MANUAL |
| Database | Restore tested | Yes | Backup verified, restore not run | MANUAL |

---

## 21. False positives

Recorded because suppressing them silently would be the wrong outcome.

| Apparent finding | Reality |
| --- | --- |
| 500 handler leaking a traceback | `TestClient` re-raises by default. A real peer gets clean JSON. The test was corrected |
| Save-Data not honoured — 3D chunk downloaded | The test set an HTTP request header; the code reads `navigator.connection.saveData`. Re-tested with the real signal: `still` tier, no 3D chunk, no video |
| 8 secret-scanner hits in tracked files | All template placeholders (`CHANGE_ME`) or deliberately wrong test passwords. Context read individually |
| `ruff format` would change 19 files | Cosmetic, pre-existing, and unrelated to this phase. `ruff check` — the project's stated gate — passes. Reformatting would have produced a large diff with no behavioural change |
| `build_snapshot` issuing 27 queries | Not an N+1. 27 is the correct number for a full snapshot, and wall time equals queries × 338 ms in every measured case. The cost is distance, not query count |

---

## 22. Final git commit

Tag created before any change:

```
phase-6-complete → 27a887c   (not overwritten, no history rewritten)
```

All Phase 7 work landed in a single commit on `master`. Reviewed before
committing: no secrets, no `.env` files, no local databases, no backup archives
(the `pg_dump` output was written to the session scratchpad, outside the
repository), no debug output, no screenshots.
