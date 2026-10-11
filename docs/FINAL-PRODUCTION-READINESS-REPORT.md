# Final production readiness report

**Project:** portfolio for Mohammed Majeed J
**Live site:** https://mohammedmajeedportfolio.me (Vercel)
**Live API:** https://api.mohammedmajeedportfolio.me (Render)
**Database:** Neon PostgreSQL 18.6
**Date:** 2026-10-11

Written for the project's author and any future maintainer. It records what was
tested, what the result was, and what is still open. Where evidence is missing,
it says so instead of filling the gap — an unverified claim in a readiness
report is worse than an acknowledged hole, because it stops anyone looking.

No score, no grade, no ranking.

---

## Summary

The public site is in good shape and is serving correctly: fast, accessible,
responsive, no console errors, no CSP violations, and the contact form works
end to end into the database. That was verified against the live deployment,
not locally.

Three things are not finished, and all three are configuration rather than
code:

1. **The API is running in development mode.** `/docs` and `/openapi.json` are
   public, the `Host` allow-list is inactive, and the API sends no HSTS.
2. **The admin CMS is unusable in production.** The deployed bundle targets the
   `onrender.com` host, which is cross-site from the site's own domain, so the
   `SameSite=Lax` session cookie is never sent back and every request after
   login returns 401.
3. **Two-factor authentication is not enabled**, and credentials exposed during
   earlier work have not been verified as rotated.

Items 1 and 2 are Render and Vercel dashboard changes. Item 3 is a few minutes
in the admin plus some revocations. None require code.

A fourth finding — the live site had no canonical URL, no Open Graph image and
a 404 sitemap, so shared links produced no preview card — **was fixed in this
pass and verified in production.** The site URL now resolves from the
deployment itself rather than from a dashboard field (§8.2, §D1).

Three fixes were made in code during this pass, each prompted by something
observed rather than assumed; they are in §8. Two of the three are confirmed
working on the live site, the third by construction.

---

## A — Repository and deployment audit

| Check | Result |
|---|---|
| Working tree clean at start | yes, on `master` at `629c171` |
| Backend test suite | **154 passed** |
| `ruff check app tests` | clean |
| `tsc -b` — public site | clean |
| `tsc -b` — admin | clean |
| `eslint .` | 0 errors, 6 pre-existing warnings |
| `npm run build` | succeeds |
| `npm run build:all` (what Vercel runs) | succeeds |
| Committed content export matches published snapshot | yes — `snapshot.json` unchanged by a fresh export |
| Media referenced by the snapshot | 27 of 27 present in `frontend/public/` |
| Migration head vs. database | both `0003_totp_hardening`, no drift |
| Secrets committed | none found |
| `render.yaml` correctness | all production variables declared correctly |

The 6 eslint warnings are all `react-refresh/only-export-components`, on files
that deliberately export a hook or constant beside a component. Pre-existing
and intentional.

**Finding — documentation drift.** `CLAUDE.md` listed `npm run dev`,
`typecheck`, `lint`, `build`, `build:all`, `preview` and `content:pull` as if
they ran from the repository root. There is no root `package.json` since the
monorepo split, so every one of those commands fails from the root. Fixed
(§8.4).

**Finding — `render.yaml` is not what is deployed.** The blueprint declares
`ENVIRONMENT=production`, `DEBUG=false`, `TRUSTED_PROXY_COUNT=1`,
`STORAGE_ROOT` and `SESSION_COOKIE_SAMESITE=lax` correctly — yet the live
service has none of them in effect. The service was created by hand in the
dashboard, so the blueprint was never applied. The file is right and the
deployment does not match it, which is the more dangerous failure of the two
because the file reads as reassurance.

---

## B — Security verification

Full detail in `docs/SECURITY.md`; the audit reasoning is in
`docs/PHASE-7-PRODUCTION-AUDIT.md`. Observed against the live deployment:

| Check | Result |
|---|---|
| `/api/admin/projects`, `/dashboard`, `/messages` with no cookie | `401` each |
| `POST /api/admin/projects` with no session | `401` |
| CORS preflight from `https://evil.example.com` | `400`, no `allow-origin` |
| CORS preflight from `http://localhost:3000` | `400`, no `allow-origin` |
| CORS preflight from the site's own origin | `200`, exact origin, credentials allowed |
| 400 kB JSON body | `413 payload_too_large` |
| Site HSTS | `max-age=63072000; includeSubDomains` |
| Site CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP | all present and correct |
| CSP violations in the browser | none |
| `/admin/*` | `X-Robots-Tag: noindex, nofollow` |

### Open, in order of seriousness

**B1 — the API is not in production mode.** `/docs` 200, `/openapi.json` 200,
no HSTS. All gated on `ENVIRONMENT == "production"`, so this is configuration.
`TrustedHostMiddleware` is therefore inactive and the session cookie is not
`Secure`.

Setting `ENVIRONMENT=production` **alone will stop the service booting** — the
startup validator demands the rest. The complete set is in `docs/SECURITY.md`
§4.1. Set them together.

**B2 — two-factor authentication is off.** Verified read-only: the one admin
account has `totp_enabled = false`, no TOTP secret, and no recovery codes. The
feature is implemented and tested; it has not been switched on. One password
guards the admin, on an API whose schema is currently public.

**B3 — exposed credentials, rotation unverified.** Two GitHub tokens were
pasted into chat earlier, and the database URL and admin password were handled
in that same channel. Whether any have been revoked **cannot be verified from
here and is not claimed**. Values appear nowhere in this repository; treat them
as `[REDACTED]`. Actions listed in `docs/SECURITY.md` §4.4.

**B4 — expired sessions accumulate.** 33 of 35 `admin_sessions` rows are
expired, one revoked, nothing prunes them. Expiry is enforced on every request,
so this is unbounded growth rather than an access-control hole.
`login_attempts` behaves the same way.

**B5 — rate limiting may be ineffective.** Per-IP limiting depends on
`TRUSTED_PROXY_COUNT`. The live value is not observable from outside, and the
startup check that would have rejected `0` did not run because the service is
not in production mode. **Not verified.** Covered by B1's variable set.

---

## C — Backup and recovery

Full procedure in `docs/BACKUP-AND-RECOVERY.md`. Verified today:

| Check | Result |
|---|---|
| Full backup of the live database | succeeded — 86,153 bytes, custom format, 31.9 s |
| Schema-only backup | succeeded — 32,153 bytes, 22.5 s |
| Tables captured | 25 of 25 |
| Archive decodes completely | yes — 163,936 bytes of SQL, clean terminator |
| Constraints and indexes captured | 25 PK, 21 FK, 15 indexes |
| Migration revision in the dump | `0003_totp_hardening`, matching the repository |
| Database size | 9,312 kB, 283 live rows |

**C1 — the restore path has never been rehearsed.** The dump is known-good and
known-complete, but no restore has been executed. The only Postgres server
available required a password that was deliberately not requested, and
restoring into the live Neon project to test it would risk the data being
protected. The recommended rehearsal — restore into a throwaway Neon branch —
is documented step by step. **A recovery plan that has never been run is a
hypothesis.**

**C2 — no backup schedule exists.** Every backup taken so far, including
today's, was taken by hand. `contact_messages` is the only table holding data
that exists nowhere else; it was empty at verification, which is the only
reason this is not already urgent.

**C3 — Neon's history retention window is unrecorded.** It is the real recovery
window for recent accidents and it varies by plan. It needs looking up in the
Neon console once and writing down.

**C4 — uploaded media is not backed up, by design.** Render's free tier has no
persistent disk, so anything uploaded through the admin is destroyed on each
deploy. Survivable only because `content:pull` copies every *published* asset
into git — verified, 27 of 27 present. Unpublished uploads are one restart from
gone. Documented in `render.yaml` as an accepted trade.

---

## D — SEO readiness

Full detail in `docs/SEO.md`.

| Check | Result |
|---|---|
| `<title>`, meta description | present |
| `og:title`, `og:description`, `twitter:card` | present (`summary_large_image`) |
| `lang="en"`, `theme-color`, favicon | present |
| Exactly one `<h1>` | yes |
| Images missing `alt` | 0 |
| `og:image` asset reachable | yes — 45,086 bytes, `image/jpeg` |
| `/admin/` excluded from indexing | yes |
| HTTPS and HSTS | yes |
| No `TODO_REPLACE_` placeholder visible on the page | confirmed |
| `<link rel="canonical">` | **was absent — now present** |
| `og:url`, absolute `og:image` | **were absent — now present** |
| `/sitemap.xml` | **was 404 — now 200** |

**D1 — the live build ran without a site URL. Found, fixed, verified in
production.** One cause for all three failures: with no site URL the build
deliberately emits nothing rather than a wrong domain, and `robots.txt` said so
in as many words — which is how it was diagnosed. The consequence was that a
link to the site shared on LinkedIn or WhatsApp got a title and description but
**no preview image**, because scrapers ignore a root-relative `og:image`. For a
portfolio whose purpose is being shared, that was the most user-visible finding
in this report.

Fixed in code so it no longer depends on anyone remembering a dashboard field
(§8.2). The deploy that carried this commit picked it up with no dashboard
change, and the live site now serves a canonical link, `og:url`, an absolute
`og:image`, a `sitemap.xml` returning 200 and a `robots.txt` pointing at it.
Verified after deploy, not predicted.

**D2 — structured data (JSON-LD) is absent.** A deliberate omission, not a
gap: every field a `schema.org/Person` block wants is subject to this
repository's rule against inventing personal information. Reasoning in
`docs/SEO.md` §6.

---

## E — Frontend performance

Measured against the live site, desktop, 1440 px wide:

| Metric | Result |
|---|---|
| TTFB | 262 ms |
| First Contentful Paint | 948 ms |
| Largest Contentful Paint | 948 ms |
| Cumulative Layout Shift | 0.0011 |
| Total transfer | 1,083 kB over 13 requests |
| Breakdown | video 876 kB, fonts 134 kB, images 74 kB |

LCP under one second and CLS effectively zero. The page is dominated by one
asset — the 876 kB cabin video, 81% of the payload — and that is a considered
trade for the cinematic first impression, not an oversight. It is excluded
entirely for the visitors who should not pay for it:

| Visitor condition | 3D chunk | `<canvas>` | video |
|---|---|---|---|
| `prefers-reduced-motion: reduce` | not fetched | not mounted | not fetched |
| `Save-Data` / slow connection | not fetched | not mounted | not fetched |

Both verified live. This is `useCanvasPolicy()` doing its job: one capability
decision, asked by components rather than re-derived with their own media
queries.

The lazy 3D chunk is 882 kB raw / 235 kB gzipped and is **not** preloaded —
`modulePreload.resolveDependencies` in `vite.config.ts` filters it out, so it
is fetched only when the policy decides a canvas will mount. The build warns
that this chunk exceeds 500 kB; the warning is expected and the comment in
`vite.config.ts` explains why a hand-rolled `manualChunks` must not be
reintroduced to silence it — doing so previously forced three.js into the entry
bundle for every visitor.

No performance regressions found, and no changes made in this area.

---

## F — Functional and responsive regression

### Public site, live

| Check | Result |
|---|---|
| All seven sections render | home, about, skills, projects, career, achievements, contacts |
| `<h1>` count | 1 |
| Canvas mounts | yes |
| Hero video | `readyState 4` (fully loaded) |
| Audio element | present |
| Custom fonts loaded | yes |
| Console errors | none |
| Failed requests | none |
| CSP violations | none |
| axe-core (WCAG 2.0/2.1 A + AA + best practice) | **0 violations, 46 passes** |

### Responsive

| Width | Horizontal overflow | Images loaded | Page errors |
|---|---|---|---|
| 390 px | none | 14/14 | 0 |
| 768 px | none | 14/14 | 0 |
| 1024 px | none | 14/14 | 0 |
| 1440 px | none | 14/14 | 0 |

### Contact form, end to end against the live API

`POST /api/public/contact` → **200**, `{"received": true}`, row written to
`contact_messages` in Neon. The full browser → API → database path is proved,
not assumed.

The test row was deleted afterwards. It was matched by a unique marker written
into its own message body, never by name, address or date, and it was the only
row in the table — so no real enquiry could have been caught by the cleanup.
`contact_messages` is empty again, as it was before.

**An earlier run of this test reported failure, and the test was wrong, not the
site.** It submitted `readiness@example.invalid`; `.invalid` is a reserved TLD
that the server's email validator correctly refuses. That produced a genuine
finding anyway — see §8.1.

### Publish and rollback

| Check | Result |
|---|---|
| Publish history | 3 snapshots, append-only |
| Rollback behaviour | created a **new** snapshot (`"Rollback to snapshot 47ead32f"`) rather than rewriting an old one — the required semantics |
| Export matches published snapshot | yes, byte-identical |
| Media referenced by the snapshot | 27 of 27 in place |

### Admin CMS

**F1 — not verifiable in production, and currently broken there.** The deployed
admin bundle (`/admin/assets/index-DJVLukTD.js`) still references
`https://majeed-portfolio-backend.onrender.com`. That is the same service as
the custom domain but a **different registrable domain**, so the `SameSite=Lax`
session cookie is never sent back: login appears to succeed and every request
after it returns 401, with blank media thumbnails.

The admin bundle contains no portfolio content, so that host string can only
have come from `VITE_API_BASE_URL`: the variable is **set, to the wrong
value**, and needs changing rather than adding.

This was then confirmed beyond doubt. Deploying this commit produced a fresh
build — `/admin/assets/index-2m4vgttT.js`, a new hash — and it **still**
references `majeed-portfolio-backend.onrender.com` and no
`api.mohammedmajeedportfolio.me`. So the value is not stale; it is the value
currently configured on Vercel. For comparison, a local build against the
intended values references `api.mohammedmajeedportfolio.me` and no
`onrender.com` host at all.

The mitigation shipped in the same build and is working: loading
`https://mohammedmajeedportfolio.me/admin/` now shows the banner from §8.3,
naming both hosts and the fix. The CMS is still unusable in production — but it
now says why, on its own login screen, instead of returning ten silent 401s.

The public site is **unaffected**: its contact POST carries no cookie, and CORS
permits both hosts, which is why the form works while the admin does not.

The admin's own functionality could not be regression-tested in production as a
consequence. It was previously verified working locally.

Mitigated in code so the failure announces itself (§8.3). The real fix is a
Vercel variable and a redeploy (§9).

---

## G — Documentation

| Document | State |
|---|---|
| `docs/SECURITY.md` | **new** — operational posture, live verification, open findings |
| `docs/SEO.md` | **new** — what is emitted and from where, how to verify, deliberate omissions |
| `docs/BACKUP-AND-RECOVERY.md` | **new** — verified backup procedure, restore procedure, honest recovery objectives |
| `docs/FINAL-PRODUCTION-READINESS-REPORT.md` | **new** — this file |
| `CLAUDE.md` | corrected: commands run from `frontend/`, not the root |
| `docs/DEPLOYMENT.md` | current; §0 runbook carries the real domains |
| `docs/PHASE-7-PRODUCTION-AUDIT.md` | unchanged; still the full security audit |
| `docs/ADMIN.md`, `docs/SPEC.md`, `README.md` | unchanged, still accurate |

---

## Content completeness

Not defects — this repository's rule is that an honest empty section beats a
fabricated full one, and `resolved()` hides unfilled fields at render time so
nothing leaks to the page (verified: no `TODO_REPLACE_` string appears anywhere
in the live DOM). But they are the gaps a visitor would notice, and every one
is editable in the admin:

| Section | Live content | Note |
|---|---|---|
| projects | 3,976 chars | strongest section |
| achievements | 1,805 chars, 12 headings | 4 certificate descriptions still unfilled |
| about | 1,457 chars | education dates and locations unfilled |
| skills | 574 chars | — |
| home | 363 chars | **no résumé link** — `TODO_REPLACE_RESUME_PATH` |
| contacts | 264 chars | no introduction paragraph |
| **career** | **157 chars, no dates** | **thinnest section on the site** |

The career section is the one worth attention: three headings and no substance.
Thin content is an SEO and credibility problem that no amount of metadata
fixes.

---

## §8 — Changes made in this pass

Four, each prompted by something observed. All verified: both apps typecheck,
eslint has no errors, both builds succeed, and the backend suite still passes
154 tests.

### 8.1 The contact form reported a server rejection as a system failure

`frontend/src/sections/ContactsSection.tsx`

A `422` from the API rendered as *"Something went wrong sending that. Please
email instead."* — which blames the system for a field the visitor could fix,
and tells them to give up. Found because an earlier test triggered exactly that
path with a reserved-TLD address.

The client's email check is deliberately permissive (the only reliable email
validation is delivery), while the server's is stricter and rejects reserved
names like `.invalid` and `.local`. That gap was reachable and
indistinguishable from an outage.

- A `422` now reports *"That email address was not accepted. Please check it
  and try again."* and attaches the error to the email field.
- The server's length limits — name 255, email 254, subject 255, message 5000 —
  are now mirrored as `maxLength` on the inputs, so an over-long field is
  prevented in the browser rather than becoming a request the server refuses.
  With those bounded, the email address is the only remaining way a well-formed
  submission comes back rejected, which is what makes the specific message
  correct rather than a guess.

### 8.2 The canonical URL no longer depends on a dashboard field

`frontend/vite.config.ts`

The live site has no canonical link and a 404 sitemap because the build ran
without `VITE_SITE_URL` (§D1). The site URL now resolves from, in order:
`VITE_SITE_URL`; else `VERCEL_PROJECT_PRODUCTION_URL` when
`VERCEL_ENV === 'production'`; else nothing, as before.

No domain is hard-coded and none is invented — the value comes from the
deployment itself. `VERCEL_URL`, the per-deployment host, is deliberately not
used: it would make the canonical URL change on every build.

Verified by building with no `VITE_SITE_URL`:

- `VERCEL_ENV=production` → canonical, `og:url`, absolute `og:image`, a
  `sitemap.xml` with the right `<loc>`, and a `robots.txt` with a `Sitemap:`
  line.
- `VERCEL_ENV=preview` → all absent, which is correct: a preview must not
  compete with production in an index.

Then verified **in production**: the deploy carrying this commit emitted all of
it with no dashboard change, and `/sitemap.xml` returns 200.

### 8.3 The admin now names its own misconfiguration

`frontend/admin/src/lib/api.ts`, `frontend/admin/src/pages/Login.tsx`

The cross-site cookie failure (§F1) cost three rounds of diagnosis because
nothing about ten 401s points at its cause. `crossSiteApiWarning()` compares
the configured API's registrable domain against the admin's own and, on a
mismatch, shows a banner on the login screen naming both hosts and explaining
that the `SameSite=Lax` cookie will not be sent.

Verified by serving the real built bundle under a mapped hostname:

| Loaded as | API base | Banner |
|---|---|---|
| `mohammedmajeedportfolio.me` | `majeed-portfolio-backend.onrender.com` | shown |
| `api-admin.onrender.com` | `majeed-portfolio-backend.onrender.com` | silent, same site |
| `localhost` | same | silent, exempt |

Also verified on the live site after deploy: the banner appears on
`https://mohammedmajeedportfolio.me/admin/`, which is the correct behaviour for
the deployment's current state.

The registrable domain is approximated as the last two labels. Correct here and
in every common case; a multi-label public suffix would compare equal where it
should not, so it stays quiet rather than crying wolf. This does not fix the
deployment — it makes the deployment's state legible.

### 8.4 `CLAUDE.md` command paths corrected

Every npm command was listed as if run from the repository root, where there is
no `package.json` since the monorepo split. Now prefixed with `cd frontend`,
with `content:check` added and a note that those two commands need the backend
virtualenv active — without it they fail with a `ModuleNotFoundError` that
names `pyotp` and explains nothing.

---

## §9 — Outstanding, user-side

Nothing here can be done from the repository. Roughly in order of value.

### Render dashboard — one change, several variables

Set these **together**; `ENVIRONMENT=production` on its own will stop the
service booting, by design.

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `ALLOWED_HOSTS` | the API's hostnames, comma-separated |
| `TRUSTED_PROXY_COUNT` | `1` |
| `STORAGE_ROOT` | `/opt/render/project/src/storage` |
| `SESSION_COOKIE_SAMESITE` | `lax` |

Then verify, rather than assume: `/docs` should return 404 and
`/api/health` should carry an HSTS header. If the service does not start, the
startup error names the exact problem — read it.

### Vercel dashboard — fixes the admin

| Variable | Value | Type |
|---|---|---|
| `VITE_API_BASE_URL` | `https://api.mohammedmajeedportfolio.me` | Config |
| `VITE_CONTACT_ENDPOINT` | `https://api.mohammedmajeedportfolio.me/api/public/contact` | Config |
| `VITE_SITE_URL` | `https://mohammedmajeedportfolio.me` | Config |

`VITE_API_BASE_URL` already exists and holds the `onrender.com` host — **edit
it**, do not add a second one. Confirmed by a fresh build after this audit,
which still produced the `onrender.com` host (§F1).

`VITE_SITE_URL` is now optional — the fallback in §8.2 covers it, verified in
production — but setting it explicitly is clearer and takes precedence.

`Config`, never `Secret`: a `VITE_`-prefixed variable is compiled into the
public bundle, so marking it Secret would have Vercel treat it as write-only
while the value sits in a file anyone can download.

Then **redeploy** — variables do not apply to an existing build. The clearest
confirmation is that the banner on the admin login screen disappears; it is
shown there now and names both hosts. Then sign in and load Media: thumbnails
appearing means the cookie is being sent.

### Admin

- [ ] Enable two-factor authentication. Store the recovery codes somewhere
      other than the device holding the authenticator.
- [ ] Fill in the career section, and add the résumé file and link.

### Credentials — none of this is verifiable from here

- [ ] Revoke both GitHub personal access tokens.
- [ ] Rotate the Neon password; update `DATABASE_URL` on Render.
- [ ] Change the admin password.
- [ ] Rotate `SECRET_KEY` on Render.

### Operational

- [ ] Run the restore rehearsal in `docs/BACKUP-AND-RECOVERY.md` §3.1 and
      record the date. This is the largest untested assumption in the project.
- [ ] Look up Neon's history retention and write it into that document.
- [ ] Decide a backup schedule.
- [ ] Prune expired `admin_sessions` and old `login_attempts`.
- [ ] Consider moving the Neon project closer to its users. 338 ms median per
      query and a 3.2 s cold connect from India fully explain the admin's
      slowness — there is no N+1 left to find. Deliberately not performed: a
      region move is not reversible in place.

---

## What this report does not establish

- That the restore procedure works. It has never been run (§C1).
- That any exposed credential has been rotated (§B3).
- The live value of `TRUSTED_PROXY_COUNT`, so whether per-IP rate limiting is
  effective (§B5).
- That the admin CMS works in production. It does not, currently, and the cause
  is known (§F1).
- Neon's history retention window, and therefore the real recovery window for
  recent accidents (§C3).
- Anything about the project's security beyond the specific controls listed and
  the specific checks observed. This report does not call the project secure.
