# Admin CMS — architecture

Companion to `docs/SPEC.md`, which covers the public site. This document covers
the CMS: how content reaches the public portfolio, and how the admin is secured.

---

## 1. The decision that shapes everything: build-time, not request-time

The obvious architecture is the one in the brief — the public React app fetches
its content from the API on every visit:

```
visitor → public site → API → PostgreSQL
```

**We are not doing that, and the reason is a number.** Measured on the current
static build:

| Tier | Transfer | FCP | Depends on a server |
| --- | --- | --- | --- |
| Mobile | 162 kB | ~460 ms | no |
| Desktop | 1.3 MB | ~420 ms | no |

Putting an API on the read path costs all three of those properties:

- **Cold starts.** Free and hobby tiers (Render, Railway, Fly) suspend idle
  services. A recruiter opening the link after an idle period waits **30–50 s**
  for the first byte of content, or sees an empty page while it boots. That is
  the single worst thing that could happen to this site.
- **A new single point of failure.** Today the portfolio cannot go down while
  the CDN is up. With a runtime fetch, a database hiccup blanks the page.
- **Slower first paint,** permanently: content now costs a round trip plus a
  query instead of being in the HTML already.

None of that buys anything the brief actually asks for. Re-read the goal:

> Anything that is content … should be manageable from Admin without editing
> source code.

That requires content to **leave the source tree**. It does not require the
visitor to talk to a database.

### What we do instead

```
        ┌──────────────┐        ┌──────────────┐
        │ ADMIN PANEL  │ ─────▶ │     API      │
        │   React      │        │   FastAPI    │
        └──────────────┘        └──────┬───────┘
                                       │
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
                 ┌──────────────┐            ┌──────────────┐
                 │  PostgreSQL  │            │ Object/Media │
                 └──────┬───────┘            └──────┬───────┘
                        │                           │
                        │   "Publish"  ─────────────┘
                        ▼
                 ┌──────────────────────┐
                 │  BUILD  (content     │
                 │  snapshot → JSON)    │
                 └──────────┬───────────┘
                            ▼
                 ┌──────────────────────┐
                 │  PUBLIC PORTFOLIO    │
                 │  static, on a CDN    │
                 └──────────────────────┘
```

Admin writes to PostgreSQL. Pressing **Publish** triggers a build: the API
exports a content snapshot, the public site builds against it, the CDN serves
the result.

You get exactly what you asked for — **add a 5th, 6th, 20th project without
touching frontend code** — and the public site stays static, fast and immune to
the API being down. The cost is that publishing takes about a minute instead of
being instant. For a portfolio updated a handful of times a year, that is the
right trade by a wide margin.

The public site keeps its current mobile, reduce-motion and Save-Data behaviour
untouched, because nothing about its runtime changes.

### The seam already exists

`src/content/*.ts` is already the only place content lives, and
`src/types/content.ts` already defines its shape. Phase 6 replaces the bodies of
those modules with a generated snapshot. **No component changes.** That boundary
was built for this from the first commit.

### If instant updates are ever genuinely needed

Add client-side revalidation to a single section rather than moving the whole
site onto the API: static content renders immediately, then a fetch swaps in
fresher data if any exists. The page still works when the API does not.

---

## 2. Security model

### The admin UI is never the security boundary

Every write is authorised server-side, per request, against the session. Hiding
a button changes nothing about what the endpoint accepts. The admin bundle is
treated as fully public code containing no secrets.

### Sessions, not JWTs

Opaque session tokens stored in PostgreSQL, sent as an `HttpOnly`, `Secure`,
`SameSite=Lax` cookie.

The brief asks for "logout all other sessions" and a session list. A stateless
JWT cannot do either — revoking one requires a server-side denylist, which is a
session table with extra steps and worse ergonomics. So: a session table, with
the token stored **hashed** (SHA-256), so a database leak does not hand over
live sessions.

### Passwords and 2FA

- **Argon2id** for password hashing, via `argon2-cffi`.
- **TOTP** (RFC 6238) for 2FA, with single-use recovery codes, themselves
  hashed.
- Login is two-staged: password verification issues a short-lived, single-
  purpose *pending-2FA* token that can do nothing except complete the second
  factor.

### Abuse protection

- Per-account lockout with exponential backoff after failed attempts.
- Per-IP rate limits on authentication endpoints.
- Failed attempts recorded with IP and user agent.
- Login responses are deliberately uniform: an unknown email and a wrong
  password return the same error and take comparable time, so the endpoint
  cannot be used to enumerate accounts.

### CSRF

Cookie authentication means the browser attaches credentials automatically, so
state-changing requests carry a double-submit CSRF token: a non-`HttpOnly`
cookie echoed in an `X-CSRF-Token` header and compared server-side.

### Audit log

Append-only. Every authentication event and every content mutation records
actor, action, target, IP, user agent and timestamp. No update or delete path is
exposed for it.

### Uploads

Validated by *sniffed* content, not by the filename extension or the
client-supplied `Content-Type`; size-capped per type; stored under generated
names outside the web root; served through an endpoint that enforces
public/private visibility.

---

## 3. The publish pipeline

This is the part that makes section 1 real rather than aspirational.

```
Admin  →  Postgres  →  publish snapshot  →  export  →  static build  →  CDN
```

### Publish

`POST /api/admin/publish` builds the entire public payload from the database,
validates it, and stores it in `publish_snapshots` with a SHA-256 checksum.

A failed publish is still recorded, with status `failed`. It never touches the
row that is currently `published`, so a bad attempt leaves the live site exactly
as it was — the API says so explicitly in the error, naming the checksum that is
still live.

### Export

```bash
cd backend
python -m app.export            # the live published snapshot
python -m app.export --check    # report only, write nothing
python -m app.export --from-draft   # current DB state, local preview only
```

It writes two things, and the second is the one that is easy to forget:

1. `src/content/snapshot.json` — the content.
2. **The media files it references.** Uploaded files live in
   `backend/storage/`, which the static site cannot see, so any
   `uploads/...` asset is copied into `public/uploads/...`. Without that, the
   JSON would point at images that 404 in production. Files under `assets/...`
   shipped with the site and are verified in place rather than copied.

Only assets marked public ever reach a snapshot, so a withheld file — the DOTE
certificate scan, for instance — is never referenced and therefore never
copied. Privacy is enforced at the source, not by the exporter remembering.

**`snapshot.json` is committed.** That is deliberate: the static host then needs
no database access, no Python and no secrets to build the site. Pulling content
is an explicit act by the author, reviewable as a diff.

### How the public site consumes it

`src/content/published.ts` overlays the snapshot onto the source modules in
`src/content/`. The modules are the base, not a legacy path:

- A build with no `snapshot.json` renders exactly what the modules say, so the
  repository stays buildable by anyone who has never run the CMS.
  (`import.meta.glob` is what makes the file optional — a plain import of a
  missing file fails the build.)
- The CMS cannot silently delete content. An empty string, an empty list or a
  null is read as "no opinion" and the module's value survives.

Not overlaid, because the database does not model them:

| Field | Why |
| --- | --- |
| Section eyebrows, headings, intros | Layout copy, not content records |
| The seven-item nav | A design decision, fixed by the spec |
| Project galleries | No gallery table; covers only |
| `about.philosophy` | Not modelled |
| Contact channels | `social_links` has label + href; a channel also needs a display value like `github.com/majeed74905`, which cannot be derived from an href without inventing text. Adding a parallel table for it was rejected. |

`featuredProjectSlugs` has no column either, but it is not lost: the per-project
`featured` flag is the same intent, and the overlay rebuilds the list from it.

### Deploy hook

`DEPLOY_HOOK_URL` is the static host's build hook, fired after a successful
publish or rollback.

- **A failed hook never fails the publish.** The snapshot is already committed
  and is the source of truth; a hook that times out means the site is stale, not
  that the publish was wrong. The admin says which of the two happened, because
  "published" and "live" are not the same event.
- **The hook URL is a secret.** It is a bearer credential — anyone holding it
  can trigger unlimited builds. The API never returns it; `GET
  /api/admin/publish/deploy` reports only whether one is configured, and the
  audit log records the host, never the URL.

### Rollback

`POST /api/admin/publish/snapshots/{id}/rollback` copies that snapshot's content
into a **new** published row. It does not flip the old row back.

History is only trustworthy if it is append-only: a rollback that mutated the
past would make the audit trail claim the bad publish never happened. The
restored row carries the original checksum, which is how you can verify it
restored the bytes rather than rebuilt from the current database.

The content is re-validated first. It passed once, but a media asset it points
at may have been made private or deleted since, and shipping a rollback that
404s would be worse than the failure being undone.

---

## 4. The public contact endpoint

`POST /api/public/contact` is the only endpoint the public internet may call,
and the only runtime request the public site makes. Everything else is behind an
admin session.

Because it is unauthenticated it is also the one endpoint that has to survive
being found by a bot, so the abuse controls are the point of the module:

- **Honeypot** — a hidden `website` field. A filled one returns the same success
  a real sender sees and stores nothing, so a bot learns nothing and does not
  retry with the field removed.
- **Per-IP limits** — 5/hour, 20/day, answered with `429` and `Retry-After`. The
  blocked message is not stored, so the limit cannot ratchet itself.
- **Control characters stripped** from name, subject and body; newlines and tabs
  survive because a message may have paragraphs.
- **Not written to the audit log.** That log is for admin actions; filling it
  from an unauthenticated endpoint would let anyone flood it.

The form never claims success it has not achieved: with no endpoint configured
it says sending is not connected, a network failure says so and points at the
direct channels, and only a 2xx shows the success message.

---

## 5. Phases

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Foundation, auth, 2FA, sessions, audit log, dashboard shell | done |
| 2 | Content CMS — Home, About, Skills, Projects, Career, Achievements | done |
| 3 | Media and documents | done |
| 4 | Contact messages | done |
| 5 | Site configuration | done |
| 6 | Publish pipeline → public site | done |

## 6. Layout

```
portfolio/
├── frontend/            → Vercel
│   ├── src/               public site
│   ├── public/            static assets
│   └── admin/             React admin panel (its own npm project)
├── backend/             → Render: FastAPI + PostgreSQL
└── docs/
```

The two frontends stay separate applications with separate dependency trees —
that isolation is what guarantees no admin code reaches the public bundle. They
share one Vercel deployment, the admin at `/admin/`.

See `docs/DEPLOYMENT.md` for the deployment topology and root directories.
