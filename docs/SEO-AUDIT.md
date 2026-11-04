# SEO audit

Technical audit of the live site and of the build that will replace it.
Measured 2026-11-04 against `https://mohammedmajeedportfolio.me` and against a
local production build. Every number below was produced by a command or a real
headless Chrome run — nothing here is estimated.

Companion documents: `SEO.md` (how the metadata pipeline works),
`SEO-KEYWORD-STRATEGY.md`, `GOOGLE-SEARCH-CONSOLE-SETUP.md`,
`SEO-MONITORING.md`, `SEO-CONTENT-STRATEGY.md`, `FINAL-SEO-REPORT.md`.

---

## 1. The shape of the site

One document. No router, hash anchors for navigation, eight sections on a
single page (`home`, `about`, `skills`, `projects`, `career`, `certificates`,
`achievements`, `contacts`). That is a deliberate architecture boundary in
`CLAUDE.md`, and it decides most of what follows:

- The sitemap has **one** URL and should keep having one.
- There are no project detail pages, so there is nothing for project-level
  structured data to be the subject of.
- `/about` is not a route. Nothing should ever suggest to Google that it is.

The frontend is served by Vercel (`Server: Vercel`), the API by Render behind
`api.mohammedmajeedportfolio.me`. The public site makes exactly one runtime
request — the contact form — and never queries the database.

---

## 2. What was already right

Worth stating plainly, because it is most of the list.

| Check | Result |
|---|---|
| HTTPS, valid certificate on the apex | PASS |
| `http://` to `https://` | PASS — 308 |
| HSTS | PASS — `max-age=63072000; includeSubDomains` |
| `<link rel="canonical">` | PASS — `https://mohammedmajeedportfolio.me/` |
| `og:url`, absolute `og:image` | PASS |
| `robots.txt` | PASS — 200, correct `Sitemap:` line |
| `sitemap.xml` | PASS — 200, one `<loc>`, correct domain |
| No `example.com` or `localhost` URLs | PASS |
| No accidental `noindex` | PASS |
| Exactly one `<h1>` | PASS |
| Heading order | PASS — `H1 H2 H3 H4 ...`, no level skipped |
| Images missing `alt` | PASS — 0 of 14 |
| Outbound links | PASS — 9 of 9 return 200 |
| `/admin/` excluded from indexing | PASS — `X-Robots-Tag: noindex, nofollow` |
| Mobile overflow at 390 / 768 / 1024 / 1440 | PASS — none |
| Browser console | PASS — silent |
| LCP and CLS, production desktop | PASS — 1,140 ms and 0.0013 |

The groundwork from the October audit (`SEO.md` section 5) held up. This audit
found no regression in any of it.

---

## 3. What was wrong

### 3.1 No structured data at all — FIXED

The live page carried **zero** `application/ld+json` blocks. Google had no
machine-readable statement of who the site is about, what he does, where he
studied, or which GitHub and LinkedIn profiles belong to the same person.

`SEO.md` section 6 recorded this as a deliberate omission, and the reasoning
was sound: every field a `Person` block wants is a claim about a real person,
and the build is not entitled to invent one. **That blocker is gone** — the
facts were supplied directly — so the omission is no longer justified and has
been closed. The facts now live in `frontend/src/content/seo.ts` under the same
no-invention rule as the rest of the content layer.

Emitted now, as one `@graph` of three cross-referenced nodes:

- **`Person`** — name, `alternateName: "Afzal"`, portrait, two job titles,
  description, 12 `knowsAbout` topics, both degrees as
  `EducationalOrganization` with a `PostalAddress`, and `sameAs` for GitHub,
  LinkedIn and Instagram.
- **`WebSite`** — `name: "Mohammed Majeed Portfolio"`, publisher points at the
  Person.
- **`ProfilePage`** — `mainEntity` points at the Person, `isPartOf` points at
  the WebSite, `dateModified` comes from the published snapshot.

Validated locally: parses, three nodes, four internal `@id` references that all
resolve, no dangling pointers, required fields present on each node. Google's
own Rich Results Test is a manual step — see section 7.

**Deliberately not added.** Project-level `CreativeWork` and
`SoftwareSourceCode`: there are no project pages, so there is no page for a
project entity to be the subject of, and Google produces no rich result for
those types. Adding them would be unsupported markup for no gain, which the
brief rules out. A standalone top-level `EducationalOrganization` is absent for
a similar reason — the degrees appear nested inside `alumniOf`, which is the
correct place for them and is not a claim to own the institution's page.

### 3.2 The CMS owned the metadata and nothing read it — FIXED

The most consequential finding, because it was silent.

The admin has had **SEO title**, **SEO description** and **Social card image**
fields since it shipped. The backend models them, `published.ts` overlays them,
and `python -m app.export` writes them into `snapshot.json`. And then nothing
consumed any of the three: the title and description were hard-coded in
`index.html`, and `og:image` was a hard-coded path in `vite.config.ts`.

Editing any of those three fields in the admin, publishing, exporting and
deploying changed **nothing** on the live site. The publish, export and build
pipeline stopped one step short of the metadata it was supposed to control.

The `site-metadata` plugin now reads `snapshot.json` at build time and lets a
real CMS value override the authored default, for all three. An absent or
unparseable snapshot is still a normal state — a clone that has never run the
CMS builds correctly from the source modules alone.

### 3.3 og:image was an 848x478 background frame — FIXED

`summary_large_image` and Open Graph both want 1200x630. The old image was the
848x478 cabin poster: accepted by every scraper, shown at full size by none,
and carrying no name or title.

A proper card now exists at `/assets/images/og-card.jpg` — 1200x630, 68 KB —
built from **that same cabin poster**, in the site's own Fraunces, Inter and
JetBrains Mono, and its own charcoal-and-gold tokens. The visual identity is
unchanged; it is the existing identity at the right size with the name on it.
`og:image:width`, `og:image:height` and `og:image:alt` are emitted alongside
it, and `twitter:image` is now set explicitly rather than left to fall back.

### 3.4 Smaller gaps — all FIXED

| Gap | Fix |
|---|---|
| No `<meta name="robots">` | `index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1`. `max-image-preview:large` is what lets Google show a full-size thumbnail instead of a small one. |
| No `og:site_name` | `Mohammed Majeed Portfolio` — see section 5. |
| No `og:locale` | `en_US`. |
| No `twitter:title`, `twitter:description`, `twitter:image` | Emitted explicitly rather than relying on Open Graph fallback. |
| `sitemap.xml` had no `<lastmod>` | Now `2026-10-24`, taken from the snapshot's own publish timestamp. Omitted entirely when there is no snapshot, rather than defaulting to the build date and claiming a change that never happened. |
| `robots.txt` did not exclude `/admin/` | `Disallow: /admin/` added. It saves crawl budget; the `X-Robots-Tag: noindex` header remains the actual control. This is not a security boundary. |
| Preview deployments were crawlable | A `VERCEL_ENV=preview` build now emits `noindex, nofollow`. Previously nothing stopped a `*.vercel.app` preview competing with production in the index. |

### 3.5 Thin content — PARTLY FIXED

`SEO.md` section 7 already flagged this: *thin content is an SEO problem no
amount of metadata fixes.* Still true. Fixed where the facts were available:

- `career.introduction` was the literal string
  `TODO_REPLACE_CAREER_INTRODUCTION` — the Career section rendered with no body
  text at all. It now carries framing copy that states only what the rest of
  the content layer already evidences.
- `contacts.introduction` was likewise unfilled. It now carries functional copy
  that says how to reach him and makes no claim about what he is looking for.
- Education **locations** filled on all four entries, Salem and Vaniyambadi, in
  both `about.ts` and `career.ts`.

**Not fixed, and deliberately so:** education dates. They have never been
supplied unambiguously, so they stay `TODO_REPLACE_*`. See section 7.

---

## 4. Still broken: www does not work

**The TLS certificate does not cover `www.mohammedmajeedportfolio.me`.**

```
https://www.mohammedmajeedportfolio.me/  ->  TLS failure
    SEC_E_WRONG_PRINCIPAL - the target principal name is incorrect
```

The DNS is fine (`www` is an alias of the apex, `216.198.79.1`) and the
redirect is configured — with certificate checking disabled it returns
`307 -> https://mohammedmajeedportfolio.me/`. But no real browser disables
certificate checking, so the handshake fails before the redirect is ever read.

This is made worse by `Strict-Transport-Security: max-age=63072000;
**includeSubDomains**` on the apex. Any visitor who has loaded the apex once
has been told to use HTTPS for every subdomain, so for them `www` is a hard
failure with no fallback to plain `http://`.

Anyone who types or links `www.` gets an error page. **Manual action in the
Vercel dashboard** — see `FINAL-SEO-REPORT.md`. It cannot be fixed from this
repository.

---

## 5. Site name

The brief asks Google to show the site as **Mohammed Majeed Portfolio**. Three
signals now say so consistently, which is everything that can be done from
here:

- `WebSite.name` in the JSON-LD, with `alternateName: "Mohammed Majeed J"`
- `og:site_name`
- the `<title>`, which leads with the name

Google generates site names from these signals plus its own, and **may still
choose something else**. It usually settles within a few crawls of the
homepage. There is no way to force it, and no one should claim otherwise.

---

## 6. Rendering: the one structural caveat

The page is client-rendered. Measured on the built output:

| | Text content |
|---|---|
| Raw HTML, no JavaScript — before | 51 characters |
| Raw HTML, no JavaScript — after | 451 characters |
| Rendered DOM | 9,440 characters |

Googlebot executes JavaScript and will index the rendered 9,440 characters, so
this is a caveat rather than a defect. But rendering is a second, queued pass,
and crawlers that do not render — along with some social and search previews —
see only the raw HTML.

The `<noscript>` block was 51 characters of apology. It now carries a genuine
451-character summary: real name, real roles, real education, and the three
links that work without JavaScript. It accurately reflects the rendered page,
which is what keeps it honest. Anything in there that were not also true on the
rendered page would be cloaking.

**Prerendering was considered and not done.** Making the HTML self-contained
would need a static-generation pass over the React tree. That is a real
architecture change, the brief says not to rebuild the site, and Googlebot
renders JavaScript anyway. If *Crawled — currently not indexed* persists for
months after the sitemap is submitted, revisit it. Not before.

---

## 7. What could not be verified from here

Stated rather than glossed over.

- **Google's Rich Results Test and the Schema.org validator.** Neither has a
  public API. The JSON-LD was validated locally — it parses, the types are
  correct, and all internal references resolve — but it must still be pasted
  into `https://validator.schema.org` and
  `https://search.google.com/test/rich-results` once deployed.
- **INP (Interaction to Next Paint).** Attempted against production under a 4x
  CPU throttle at 390px. The run recorded **0 long tasks and 0 ms of total
  blocking time**, which is a good sign, but it captured no qualifying
  interaction entries, so there is **no INP number**. INP is a field metric: it
  comes from CrUX and appears in Search Console once there is real traffic.
  Reported as NOT TESTED, not as a pass.
- **Indexing status.** A URL that returns 200 is not an indexed URL. Only
  Search Console can say, and the property is not verified yet.
- **Education dates.** Never supplied unambiguously, so they remain
  `TODO_REPLACE_*` rather than being approximated.
- **Which LinkedIn URL is live.** The content layer says
  `/in/mohammed-majeed-a337842a4`; Mohammed gave `/in/majeed74905` in
  conversation. LinkedIn returns HTTP 999 to automated requests, so neither
  could be checked. The content-layer value is what ships, in both the visible
  link and in `sameAs`. **Confirm it** — a wrong `sameAs` weakens exactly the
  identity connection it exists to make.

---

## 8. Configuration drift found on the way

Not SEO, but found during the audit and worth recording.

The deployed bundle posts the contact form to
`https://majeed-portfolio-backend.onrender.com/api/public/contact`, and the
deployed CSP `connect-src` names that same host. But
`frontend/.env.production` in this repository says:

```
VITE_CONTACT_ENDPOINT=https://api.mohammedmajeedportfolio.me/api/public/contact
```

The two agree with each other, so **the contact form works** — the live build
simply predates the custom API domain. Vercel's dashboard environment variables
are stale relative to the committed file. Worth reconciling at the next deploy
so the two stop disagreeing. `.env.production` is gitignored, and Vercel reads
the dashboard rather than the file.

---

## 9. Measurements

### Production, before this work (2026-11-04)

Desktop 1440x900, real network, headless Chrome:

| Metric | Value | Google "good" threshold |
|---|---|---|
| LCP | 1,140 ms | 2,500 ms or less — PASS |
| CLS | 0.0013 | 0.1 or less — PASS |
| FCP | 1,140 ms | — |
| TTFB | 400 ms | — |
| DOM interactive | 496 ms | — |
| Long tasks and TBT, mobile at 4x CPU | 0 and 0 ms | — |

### Local production build, after

Localhost figures are **not** comparable to the production network numbers
above, and are recorded only to show that nothing regressed: LCP 392 ms, CLS
0.0013, TTFB 12 ms, console silent, no horizontal overflow at 390, 768, 1024 or
1440.

**The LCP element was identified:** the `<h1>` on desktop and the hero `<p>` on
mobile. It is **text, not an image**. That matters, because all 14 images carry
`loading="lazy"` and the brief warns against lazy-loading the LCP image. There
is no LCP image to lazy-load, so the current loading strategy is correct.
Verified, not assumed.

The hero poster is already `<link rel="preload" as="image">`, and the cabin
video is deliberately not preloaded — `useCanvasPolicy()` decides at runtime
whether it plays, and it must not compete with content for bandwidth.
