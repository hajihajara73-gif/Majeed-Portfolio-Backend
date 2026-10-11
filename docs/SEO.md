# SEO

How the site presents itself to crawlers and link previews, how to verify it,
and what is deliberately absent. Written for whoever maintains the site.

Verified against the live deployment on 2026-10-11.

---

## 1. The shape of the problem

This is a one-page site. There is no router, no second URL, and navigation is
hash anchors — `/about` is not a route (see `CLAUDE.md`). So there is exactly
one indexable document, and SEO here means getting that one document right
rather than managing a site structure.

That makes most of the usual work unnecessary and the remainder worth doing
properly: a correct title and description, a canonical URL, Open Graph tags
that produce a real preview card, and a sitemap with one entry in it.

---

## 2. What is emitted, and from where

| Output | Source | Needs the site URL? |
|---|---|---|
| `<title>`, `<meta name="description">` | `frontend/index.html` | no |
| `og:title`, `og:description`, `og:type`, `twitter:card` | `frontend/index.html` | no |
| `theme-color`, `lang="en"`, favicon | `frontend/index.html` | no |
| `<link rel="canonical">` | `siteMetadata` plugin, `vite.config.ts` | **yes** |
| `og:url` | same | **yes** |
| `og:image` (absolute) | same | **yes** |
| `sitemap.xml` | same, `generateBundle` | **yes** |
| `robots.txt` | same | partly |
| `X-Robots-Tag: noindex` on `/admin/*` | `frontend/vercel.json` | no |

The split matters: everything in the right-hand column is unknowable at author
time, because a static build does not know what domain it will be served from.
So it is computed at build time instead of being written into a file.

### Why the site URL is not hard-coded

The repository has a standing rule against a hard-coded production domain
(`CLAUDE.md`, architecture boundaries). The sitemap is the reason it exists:
this site previously shipped a static `sitemap.xml` containing
`<loc>https://example.com/</loc>` — a submittable sitemap pointing at someone
else's domain, which is worse than having no sitemap at all.

So the rule applied throughout is the same one the content layer uses: **when a
value is unknown, emit nothing rather than something wrong.** No canonical, no
`og:url`, no sitemap, and a `robots.txt` that says in as many words why there
is no `Sitemap:` line.

### Where the site URL comes from

In order:

1. **`VITE_SITE_URL`** — an explicit value always wins. It is the only way to
   name a domain the build platform does not know about.
2. **`VERCEL_PROJECT_PRODUCTION_URL`** — Vercel sets this on every deployment:
   the project's production host, custom domain preferred, no scheme. Used only
   when `VERCEL_ENV === 'production'`.
3. **Nothing.** Canonical, `og:url`, absolute `og:image` and `sitemap.xml` are
   all omitted, and `robots.txt` explains the omission.

Step 2 is deliberate and worth understanding. It means the canonical URL comes
from the deployment itself rather than from someone remembering to fill in a
dashboard field — which is exactly the failure this document was written after
(§5). `VERCEL_URL`, the per-deployment host, is **not** used: it changes on
every build, which would make the canonical URL unstable, and a preview's
canonical should point at production anyway, which this does.

Preview deployments therefore emit no canonical and no sitemap. That is correct
— a preview must not compete with production in an index.

---

## 3. Verifying it

```bash
cd frontend && npm run build

grep -o 'rel="canonical" href="[^"]*"' dist/index.html
grep -o 'property="og:[^"]*" content="[^"]*"' dist/index.html
cat dist/robots.txt
cat dist/sitemap.xml          # absent if the site URL was unknown
```

Against the live site:

```bash
curl -s https://mohammedmajeedportfolio.me | grep -E 'canonical|og:'
curl -s https://mohammedmajeedportfolio.me/robots.txt
curl -sI https://mohammedmajeedportfolio.me/sitemap.xml   | head -1
curl -sI https://mohammedmajeedportfolio.me/admin/ | grep -i x-robots
```

Verified behaviour of the plugin, 2026-10-11, by building with no
`VITE_SITE_URL` and the Vercel variables set:

| Build | canonical | sitemap.xml | robots.txt |
|---|---|---|---|
| `VERCEL_ENV=production`, production URL set | `https://mohammedmajeedportfolio.me/` | emitted, one `<loc>` | has `Sitemap:` line |
| `VERCEL_ENV=preview` | absent | absent | explains the omission |

Both as designed.

---

## 4. Live state, 2026-10-11

| Check | Result |
|---|---|
| `<title>` | `Mohammed Majeed J — Full Stack Developer` |
| `meta description` | present |
| `og:title`, `twitter:card` | present (`summary_large_image`) |
| `lang="en"`, `theme-color` | present |
| Single `<h1>` | yes, exactly one |
| Images missing `alt` | 0 |
| axe-core accessibility violations | 0 (46 passes) |
| `og:image` asset reachable | yes — 45,086 bytes, `image/jpeg` |
| `/admin/` excluded from indexing | yes — `X-Robots-Tag: noindex, nofollow` |
| HTTPS, HSTS | yes — `max-age=63072000; includeSubDomains` |
| LCP / CLS | 948 ms / 0.0011 |
| `<link rel="canonical">` | **was absent — now present** |
| `og:url`, absolute `og:image` | **were absent — now present** |
| `/sitemap.xml` | **was 404 — now 200** |
| `robots.txt` | now carries a `Sitemap:` line |

The last four were a single cause, and it is fixed. See §5.

---

## 5. The gap that was found, and closed

The deployed bundle had been built with no `VITE_SITE_URL`, so the live page
had no canonical link, no `og:url`, no absolute `og:image`, and
`/sitemap.xml` returned 404. `robots.txt` stated the reason, which is how it
was diagnosed.

The practical effect was that a link to the site posted on LinkedIn or WhatsApp
got a title and description but **no preview image**, because social scrapers
ignore a root-relative `og:image`. For a portfolio whose purpose is being
shared, that was the most visible finding of the whole audit.

**Fixed and verified in production.** The `VERCEL_PROJECT_PRODUCTION_URL`
fallback (§2) was added for precisely this. The next deploy picked it up with
no dashboard change, and the live site now serves:

```
<link rel="canonical" href="https://mohammedmajeedportfolio.me/">
<meta property="og:url" content="https://mohammedmajeedportfolio.me/">
/sitemap.xml  ->  200
robots.txt    ->  Sitemap: https://mohammedmajeedportfolio.me/sitemap.xml
```

Setting `VITE_SITE_URL` explicitly is still the clearer choice and takes
precedence, but it is no longer required for correct output.

---

## 6. Deliberately absent

Not oversights. Each is a decision.

- **JSON-LD / structured data.** A `schema.org/Person` block would be a real
  improvement and is the obvious next addition. It is not here because every
  field it wants — job title, education, employer, credentials — is subject to
  this repository's hard rule against inventing personal information, and the
  CMS does not yet carry those fields in a form safe to publish as structured
  claims. Adding it means deciding what is true, which is the author's call,
  not the build's.
- **Per-section URLs and meta.** There is one document; hash anchors are not
  separate pages and should not pretend to be.
- **`sitemap.xml` with multiple entries.** One page, one entry.
- **Analytics.** None. No third-party script runs on the site, which is also
  why the Content-Security-Policy can stay as tight as it is.
- **`hreflang`.** Single language.
- **Submitting to Search Console.** User-side, and worth doing once
  `/sitemap.xml` returns 200.

---

## 7. Outstanding

- [x] Canonical link, `og:url`, absolute `og:image` and `sitemap.xml` now
      served — verified live after deploy (§5).
- [ ] Paste the live URL into a link-preview debugger (LinkedIn Post Inspector,
      or any Open Graph checker) and confirm the image renders. The tag and the
      asset are both verified; what a given scraper does with them is not.
- [ ] Submit the sitemap to Google Search Console, once it returns 200.
- [ ] Content, not configuration: the **career section is nearly empty** on the
      live site — 157 characters, no dates — and there is **no résumé link**
      (`TODO_REPLACE_RESUME_PATH` is unfilled). Both are editable in the admin.
      Thin content is an SEO problem no amount of metadata fixes.
