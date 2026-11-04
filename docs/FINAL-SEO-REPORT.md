# Final SEO report

**Date:** 2026-11-04
**Site:** https://mohammedmajeedportfolio.me
**Scope:** technical SEO, structured data, Search Console readiness, Core Web
Vitals, and the documentation to run it afterwards.

Status words used throughout: **PASS**, **FAIL**, **MANUAL ACTION REQUIRED**,
**NOT TESTED**.

Supporting detail: `SEO-AUDIT.md`, `SEO-KEYWORD-STRATEGY.md`,
`GOOGLE-SEARCH-CONSOLE-SETUP.md`, `SEO-MONITORING.md`,
`SEO-CONTENT-STRATEGY.md`, and `SEO.md` for how the pipeline works.

---

## 1. Executive summary

The site was in better technical shape than most audits find. HTTPS, canonical,
sitemap, robots.txt, heading structure, image alt text and Core Web Vitals were
all already correct, and this audit found **no regression** in any of them.

Three things were genuinely wrong, and all three are fixed in this branch:

1. **No structured data at all.** Google had no machine-readable statement of
   who the site is about or which profiles are the same person. `Person`,
   `WebSite` and `ProfilePage` JSON-LD now ship.
2. **The CMS owned the SEO metadata and nothing read it.** The admin's SEO
   title, SEO description and social card fields have existed since launch,
   were exported into the snapshot, and were then ignored by the build. Editing
   them changed nothing on the live site. The build now reads them.
3. **The social card was an 848x478 background frame.** Every scraper accepted
   it; none displayed it at full size. A real 1200x630 card now exists, built
   from the same cabin poster in the site's own fonts and colours.

One problem is **not** fixed and cannot be fixed from this repository:
**`www.mohammedmajeedportfolio.me` does not work in any browser.** Its TLS
certificate does not cover the name. See section 15.

Nothing has been deployed. Nothing was published to Google. No DNS record was
touched. No analytics was added.

---

## 2. Existing SEO problems found

| # | Problem | Severity | Status |
|---|---|---|---|
| 1 | No JSON-LD structured data anywhere | High | **PASS** — fixed |
| 2 | CMS SEO title / description / social card read by nothing | High | **PASS** — fixed |
| 3 | `og:image` 848x478, below the 1200x630 both OG and Twitter want | Medium | **PASS** — fixed |
| 4 | `www` subdomain fails TLS; HSTS `includeSubDomains` removes the fallback | High | **MANUAL ACTION REQUIRED** |
| 5 | No `<meta name="robots">`, so no `max-image-preview:large` | Medium | **PASS** — fixed |
| 6 | No `og:site_name`, weakening the site-name request | Medium | **PASS** — fixed |
| 7 | `sitemap.xml` had no `<lastmod>` | Low | **PASS** — fixed |
| 8 | `robots.txt` did not exclude `/admin/` | Low | **PASS** — fixed |
| 9 | Preview deployments were crawlable and could compete with production | Medium | **PASS** — fixed |
| 10 | No `twitter:title` / `:description` / `:image` | Low | **PASS** — fixed |
| 11 | Career section renders with no body text; dates unfilled | Medium | **PARTIAL** — intro and locations filled; dates are **MANUAL ACTION REQUIRED** |
| 12 | `<noscript>` carried 51 characters for non-rendering crawlers | Low | **PASS** — now 451 |
| 13 | Deployed CSP `connect-src` names the old Render host | Low, not SEO | **MANUAL ACTION REQUIRED** — see section 16 |

---

## 3. Fixes implemented

### Structured data — PASS

One `@graph`, three cross-referenced nodes, emitted at build time so Google
sees it without executing the bundle:

- **`Person`** — name, `alternateName: "Afzal"`, portrait, `jobTitle`
  (Full Stack Developer, Python Backend Developer), description, 12
  `knowsAbout` topics, both degrees as `EducationalOrganization` with a
  `PostalAddress`, and `sameAs` for GitHub, LinkedIn and Instagram.
- **`WebSite`** — `name: "Mohammed Majeed Portfolio"`, publisher points at the
  Person.
- **`ProfilePage`** — `mainEntity` and `about` point at the Person, `isPartOf`
  points at the WebSite, `dateModified` comes from the snapshot.

The facts live in `frontend/src/content/seo.ts`, under the same no-invention
rule as the rest of the content layer. Every value is checkable against the
repository, the live site, or something stated directly. There is no employer,
no job history and no metric, because none was available.

A real risk was checked and cleared: the site runs `script-src 'self'` with no
`'unsafe-inline'`. A `<script type="application/ld+json">` block is a *data*
block, not executable script, so the CSP does not apply to it. **Verified in a
real browser — console completely silent, zero CSP violations.**

### The CMS pipeline — PASS

`vite.config.ts` now reads `src/content/snapshot.json` at build time and lets a
real CMS value override the authored default for the title, the description and
the social card. An absent or unparseable snapshot stays a normal state: a
clone that has never run the CMS still builds correctly.

### Social card — PASS

`/assets/images/og-card.jpg`, 1200x630, 68 KB. Built from the existing cabin
poster, in the site's own Fraunces / Inter / JetBrains Mono and its charcoal-
and-gold tokens — all three fonts confirmed loaded at render time, so nothing
silently fell back. The approved visual identity is unchanged.

### Everything else

`meta robots` with `max-image-preview:large`; `og:site_name`; `og:locale`;
explicit `twitter:*`; `og:image:width` / `:height` / `:alt`; `<lastmod>` in the
sitemap; `Disallow: /admin/` in robots.txt; `noindex` on preview deployments;
a genuine `<noscript>` fallback; `career.introduction` and
`contacts.introduction` filled; education locations filled on all four entries.

---

## 4. Keyword strategy — PASS

Full version in `SEO-KEYWORD-STRATEGY.md`. Four clusters by intent, mapped onto
existing content.

**No search volume, difficulty or competition figures appear anywhere.** The
project has no access to Keyword Planner, Ahrefs or Semrush, and invented
numbers would be worse than none because they would get planned against. Every
judgement is labelled as reasoning from the site's actual content. Real data
arrives with Search Console's Performance report.

The honest summary: **win the name queries outright** — that is the one group
where this site can legitimately expect first position — and be a credible
result for Python, FastAPI and the university project. Do not chase
"React developer India"; that is owned by job boards and the tactics that would
move it are the ones the brief rules out.

---

## 5. Metadata configuration — PASS

| Tag | Value |
|---|---|
| `<title>` | `Mohammed Majeed J — Full Stack & Python Backend Developer` (57 chars) |
| `description` | 135 chars, leads with the name |
| `robots` | `index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1` |
| `canonical` | `https://mohammedmajeedportfolio.me/` |
| `og:site_name` | `Mohammed Majeed Portfolio` |
| `og:type` | `website` |
| `og:locale` | `en_US` |
| `og:url` | `https://mohammedmajeedportfolio.me/` |
| `og:image` | absolute, 1200x630, with `:width`, `:height`, `:alt` |
| `twitter:card` | `summary_large_image` |
| `twitter:title` / `:description` / `:image` | all set explicitly |
| `theme-color` | `#0a0e0c` |
| favicon | `/favicon.svg` |

Checked for duplicates: exactly **one** `<title>`, **one** meta description,
**one** of each `og:` property, **one** canonical. The authored defaults stay
in `index.html` so the page is correct even if the plugin never runs, and the
plugin rewrites them in place rather than appending a second copy.

`og:type` is `website`, not `profile`. `profile` is about the *object* being a
person and expects `profile:first_name` and `profile:last_name` alongside it,
which would be a second place to keep the same facts. That the page is *about*
a person is already stated precisely, in the JSON-LD, by `ProfilePage` plus
`mainEntity`.

> **The title and description are not live yet** — the published snapshot still
> carries the previous values and the CMS deliberately wins. Section 15,
> item 2.

---

## 6. Sitemap — PASS

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://mohammedmajeedportfolio.me/</loc>
    <lastmod>2026-10-24</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
```

Valid XML, UTF-8, absolute canonical URL, correct production domain. No
localhost, no `example.com`, no admin routes, no API endpoints, no auth routes,
no duplicates.

**One URL, deliberately.** The site is one document with hash-anchor
navigation; generating a fake entry per section would be inventing URLs that do
not exist. `lastmod` comes from the snapshot's own publish timestamp — the one
honest answer to "when did this change?" for a site baked in at build time —
and is omitted entirely when there is no snapshot, rather than defaulting to
the build date and claiming a change that never happened.

The dynamic generation mechanism was preserved, not replaced.

---

## 7. robots.txt — PASS

```
User-agent: *
Allow: /

# The admin is a private app. Excluded from crawling, and served
# with X-Robots-Tag: noindex. This is not an access control.
Disallow: /admin/

Sitemap: https://mohammedmajeedportfolio.me/sitemap.xml
```

Public pages allowed. No JavaScript, CSS, image or rendering resource blocked —
checked, because blocking those is the classic way to make a React site
unindexable. The `Disallow` is a crawl-budget courtesy; the real control is the
`X-Robots-Tag: noindex, nofollow` header on `/admin/`, verified live.

---

## 8. Canonical configuration — PASS

`<link rel="canonical" href="https://mohammedmajeedportfolio.me/">` on every
production build, from `VITE_SITE_URL` or Vercel's own
`VERCEL_PROJECT_PRODUCTION_URL`. No hard-coded domain anywhere — that is an
architecture boundary in `CLAUDE.md`, and it is intact.

Preview builds emit no canonical **and** now emit `noindex, nofollow`.
Previously nothing stopped a `*.vercel.app` preview being indexed alongside
production.

---

## 9. Structured data — PASS locally, MANUAL ACTION to confirm

Validated locally: parses as JSON; three nodes with correct `@type` values;
four internal `@id` references, all resolving; no dangling pointers; required
fields present on every node.

**NOT TESTED:** Google's Rich Results Test and `validator.schema.org`. Neither
has a public API, so neither could be run from here. Both are one paste each
once deployed — section 15, item 5.

---

## 10. Image optimization — PASS

- 14 images, **0 missing `alt`**, 0 with empty `alt`.
- All 14 use `loading="lazy"`.
- **The LCP element was identified rather than assumed:** `<h1>` on desktop,
  the hero `<p>` on mobile. It is **text, not an image**. So there is no LCP
  image being lazy-loaded, and the current strategy is correct.
- The hero poster is `<link rel="preload" as="image">` with a WebP `type` hint.
- Responsive `srcSet` and `sizes` on project covers and the portrait.
- Modern formats in use: WebP for the portrait, projects and certificates.
- No broken image URLs.
- The new social card is 68 KB for 1200x630 — appropriately sized.

---

## 11. Video — PASS

The approved cabin video is untouched, as required.

- Not render-blocking, and deliberately **not** preloaded — `useCanvasPolicy()`
  decides at runtime whether it plays, so it must not compete with content for
  bandwidth.
- A poster is present and preloaded; it is what paints first.
- Muted, no autoplay audio.
- CLS measured at **0.0013**, so it causes no layout shift.
- Mobile, reduced-motion and Save-Data paths all still resolve through
  `useCanvasPolicy()`, which is the single capability decision for the site.

---

## 12. Core Web Vitals — PASS on two of three, NOT TESTED on the third

Measured on production, desktop 1440x900, real network:

| Metric | Measured | Google threshold | Verdict |
|---|---|---|---|
| LCP | **1,140 ms** | 2,500 ms or less | **PASS** |
| CLS | **0.0013** | 0.1 or less | **PASS** |
| INP | **no measurement** | 200 ms or less | **NOT TESTED** |
| FCP | 1,140 ms | — | — |
| TTFB | 400 ms | — | — |
| DOM interactive | 496 ms | — | — |
| Long tasks / TBT (mobile, 4x CPU throttle) | **0 / 0 ms** | — | good sign |

**On INP, stated plainly:** an interaction run against production under a 4x
CPU throttle at 390px recorded 0 long tasks and 0 ms of total blocking time,
but captured no qualifying interaction entries, so there is **no INP number**.
INP is a field metric — it comes from CrUX and will appear in Search Console
once there is real traffic. It is reported as NOT TESTED rather than inferred
from the zero-blocking result.

---

## 13. Mobile SEO — PASS

Tested at all four required widths in a real headless Chrome:

| Width | Horizontal overflow | Body font |
|---|---|---|
| 390 px | none | 17 px |
| 768 px | none | 17 px |
| 1024 px | none | 17 px |
| 1440 px | none | 17 px |

Responsive layout intact, readable font size, navigation and forms usable,
images load, video behaviour unchanged, console silent at every width.

Google sees the same content a mobile user sees — subject to the rendering
caveat in section 17.

---

## 14. Search Console readiness — PASS, awaiting manual steps

Everything Search Console needs is in place: HTTPS, a reachable `robots.txt`
with a `Sitemap:` line, a valid `sitemap.xml` at 200, a canonical URL, and no
accidental `noindex`.

A complete step-by-step guide is in `GOOGLE-SEARCH-CONSOLE-SETUP.md`: Domain
property, DNS TXT verification through Namecheap, sitemap submission, URL
inspection, indexing requests, and a troubleshooting table covering every
common status.

**No verification token was invented. No DNS record was created or modified.**
Google generates a token unique to the account; it has to be copied from the
screen.

---

## 15. Manual actions required

In priority order. Items 1 and 2 matter most.

### 1. Fix `www` — FAIL until done

`www.mohammedmajeedportfolio.me` is unreachable in any browser. DNS resolves
and the redirect is configured, but the TLS certificate does not cover the
`www` name, so the handshake fails before the redirect is read. HSTS with
`includeSubDomains` on the apex removes any fallback.

**Fix:** Vercel dashboard, the project, **Settings**, **Domains**, **Add**
`www.mohammedmajeedportfolio.me`. Vercel issues a certificate and applies the
redirect. No Namecheap change needed — the DNS is already correct.

### 2. Publish the new title and description

Authored in `frontend/src/content/seo.ts`, but the published CMS snapshot still
carries the old values and the CMS deliberately wins — so they are **not
live**.

Admin, **Settings**:
- **SEO title:** `Mohammed Majeed J — Full Stack & Python Backend Developer`
- **SEO description:** `Portfolio of Mohammed Majeed J — a full stack developer building Python and FastAPI backends, React interfaces, and applied AI projects.`

Then **Publish**, then from `frontend/`: `npm run content:pull`, commit, push.

Everything else in this work — the JSON-LD, the social card, the robots
directive, `og:site_name`, the sitemap `lastmod` — goes live on deploy with no
CMS action at all.

### 3. Fill the Career dates

Four fields in the admin, Career. They are `TODO_REPLACE_*` and render as
nothing, which leaves the thinnest section on the site thinner than it needs to
be. Left unfilled deliberately: the dates were never supplied unambiguously,
and this repository does not guess personal data.

### 4. Confirm the LinkedIn URL

The site uses `/in/mohammed-majeed-a337842a4`; `/in/majeed74905` was mentioned
separately. LinkedIn returns HTTP 999 to automated requests, so neither could
be verified. It feeds both the visible link and `sameAs` — a wrong value there
weakens exactly the identity signal it exists to create.

### 5. Validate and submit

- Paste the deployed URL into `https://validator.schema.org` and
  `https://search.google.com/test/rich-results`.
- Paste it into LinkedIn Post Inspector to confirm the new card renders.
- Work through `GOOGLE-SEARCH-CONSOLE-SETUP.md`.

---

## 16. Remaining blockers and known limitations

- **`www`** — section 15, item 1. The only outright FAIL.
- **Client-side rendering.** Raw HTML carries 451 characters of text; the
  rendered DOM carries 9,440. Googlebot renders JavaScript and will index the
  full content, so this is a caveat, not a defect. Prerendering was considered
  and rejected: it is a real architecture change, the brief says not to rebuild
  the site, and it is unnecessary unless "Crawled — currently not indexed"
  persists for months.
- **Indexing cannot be confirmed from here.** A URL returning 200 is not an
  indexed URL. Only Search Console can say.
- **Config drift, not SEO.** The deployed bundle posts the contact form to
  `majeed-portfolio-backend.onrender.com` and its CSP `connect-src` names that
  same host, while `.env.production` in the repository names
  `api.mohammedmajeedportfolio.me`. They agree with each other, so **the form
  works** — the live build simply predates the custom API domain. Worth
  reconciling in Vercel's dashboard at the next deploy.
- **Remaining `TODO_REPLACE_*`:** education dates, four certificate
  descriptions, the philosophy block, and three home "field notes". All render
  as nothing rather than as placeholder text, which is the designed behaviour.

---

## 17. Testing results

Every check below was executed. Nothing is reported as passing that was not
run.

| Test | Result |
|---|---|
| `npm run typecheck` | **PASS** — clean, 0 errors |
| `npm run lint` | **PASS** — 0 errors (6 pre-existing `react-refresh` warnings in `admin/`, untouched by this work) |
| `npm run build` | **PASS** — succeeds, no warnings from this change |
| Production build output inspected | **PASS** |
| Browser console, built site | **PASS** — zero messages |
| CSP vs JSON-LD | **PASS** — no violation; `ld+json` is a data block |
| JSON-LD parses | **PASS** |
| JSON-LD `@id` references resolve | **PASS** — 4 of 4, none dangling |
| JSON-LD required fields | **PASS** — all three nodes |
| Duplicate title / description / og tags | **PASS** — exactly one of each |
| `sitemap.xml` valid and correct domain | **PASS** |
| `robots.txt` valid, nothing critical blocked | **PASS** |
| Canonical URL | **PASS** |
| Outbound links | **PASS** — 9 of 9 return 200 |
| Image `alt` coverage | **PASS** — 14 of 14 |
| LCP element identified | **PASS** — text, not an image |
| Heading hierarchy | **PASS** — one `h1`, no level skipped |
| Mobile, 390 / 768 / 1024 / 1440 | **PASS** — no overflow at any width |
| Core Web Vitals, production | **PASS** — LCP 1,140 ms, CLS 0.0013 |
| INP | **NOT TESTED** — field metric; see section 12 |
| Rich Results Test, schema.org validator | **NOT TESTED** — no public API |
| Google indexing status | **NOT TESTED** — property not verified |
| `www` subdomain | **FAIL** — TLS certificate does not cover it |
| Backend `ruff` / `pytest` | **NOT RUN** — no backend file was changed |
| Security regression | **PASS** — CSP unchanged and still `script-src 'self'`; no third-party script added; no new dependency |

---

## 18. Changed files

**New:**

```
frontend/src/content/seo.ts                 SEO + structured-data facts
frontend/public/assets/images/og-card.jpg   1200x630 social card
docs/SEO-AUDIT.md
docs/SEO-KEYWORD-STRATEGY.md
docs/GOOGLE-SEARCH-CONSOLE-SETUP.md
docs/SEO-MONITORING.md
docs/SEO-CONTENT-STRATEGY.md
docs/FINAL-SEO-REPORT.md                    this file
```

**Modified:**

```
frontend/vite.config.ts          snapshot reading, JSON-LD, full meta set, lastmod, robots.txt
frontend/index.html              single-owner meta block, real <noscript> fallback
frontend/src/types/content.ts    StructuredDataFacts, AlumniOrganization, SocialCard
frontend/src/content/site.ts     SEO defaults now sourced from seo.ts
frontend/src/content/about.ts    education locations
frontend/src/content/career.ts   introduction + locations
frontend/src/content/contacts.ts introduction
frontend/tsconfig.node.json      @/ path alias, so the build config can import from src
docs/SEO.md                      superseded sections updated
```

No dependency was added. No component was touched. The design system, the
content architecture, the hosting setup and the CSP are all unchanged.

---

## What is not claimed

Explicitly, because the brief asks for it:

- **No claim of a first Google ranking**, for any query.
- **No claim that the site will be indexed.** Google decides; Search Console
  reports.
- **No claim of rich results.** The structured data is valid and eligible;
  eligibility is not a guarantee.
- **No claim of traffic.**
- **No claim that Search Console ownership is verified.** It is not. The guide
  to verify it is written; the steps are manual and have not been performed.
- **No claim that Google will display "Mohammed Majeed Portfolio"** as the site
  name. Three consistent signals now request it. Google generates site names
  itself and may choose otherwise.
