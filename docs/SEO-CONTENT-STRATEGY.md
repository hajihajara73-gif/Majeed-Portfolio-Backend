# Content strategy

Long-term organic growth, based on work that actually exists.

**Nothing in this document has been published, and nothing will be without
approval.** These are proposals. The brief says to prepare ideas and let
Mohammed approve them, and that is what this is.

Companion to `SEO-KEYWORD-STRATEGY.md`.

---

## 1. The honest position

A one-page portfolio can win searches for its owner's name. It cannot win
"full stack developer" — that is owned by job boards, agencies and sites with
years of links.

Growing beyond name queries needs something only this site can say. There are
exactly two such assets, and both are real:

1. **The Periyar University PhD Admission Management System** — a four-portal
   platform over one MySQL database, running in production at a public
   university. Vanishingly few developers at any level have shipped something
   with real institutional users. Almost nobody else can write about *this*
   system.
2. **This portfolio's own architecture** — a static public site with an admin
   CMS behind it, where content reaches the site through publish, export and
   build rather than a runtime database query. That is an unusual and genuinely
   defensible design decision, and the repository documents the reasoning.

Everything below follows from those two.

---

## 2. Before writing anything: finish the site

Three fixes beat any article, and together they are maybe twenty minutes of
admin work. **Do these first.**

### 2.1 The SEO title and description (highest priority)

The improved title and description are written and in the repository, but the
published CMS snapshot still carries the old values and the CMS deliberately
wins. Until this is done, that work is not live.

Admin, **Settings**:

- **SEO title:** `Mohammed Majeed J — Full Stack & Python Backend Developer`
- **SEO description:** `Portfolio of Mohammed Majeed J — a full stack developer building Python and FastAPI backends, React interfaces, and applied AI projects.`

Then **Publish**, then from `frontend/`: `npm run content:pull`, commit, push.

### 2.2 Career dates

The Career section is the thinnest on the site and it carries every academic
query. The two entries have no dates, so they render as degree and institution
and nothing else.

Admin, **Career**. Fill start and end for both entries, and the two
descriptions. Four fields.

These were deliberately left as `TODO_REPLACE_*` rather than guessed — the
dates were never supplied unambiguously, and inventing them is against the
rules this repository runs on.

### 2.3 Confirm the LinkedIn URL

The site links `/in/mohammed-majeed-a337842a4`; `/in/majeed74905` was mentioned
separately. LinkedIn blocks automated requests, so neither could be verified.

Whichever is right, it needs to be right in the admin — it feeds both the
visible link and the `sameAs` in the structured data, and `sameAs` is the
signal that ties the site, GitHub and LinkedIn into one identity in Google's
index. A wrong URL there weakens exactly the connection it exists to make.

---

## 3. Proposed articles

Ordered by value. **None of these exists. Each needs approval before it is
written, and approval of the idea is not approval of a published page.**

### Article 1 — Building a PhD Admission Management System for a university

**The one worth doing.** If only one article is ever written, this is it.

- **Why:** the strongest asset on the site, and the only topic with
  essentially no competition. Nobody else can write it.
- **Serves:** "Periyar University PhD admission system", "university admission
  management software", "full stack university management project" — the
  academic cluster in `SEO-KEYWORD-STRATEGY.md`.
- **Secondary value:** this is interview material. A link beats a description.
- **From the repository, already true:** four portals over one MySQL database;
  JWT with per-module secrets; Argon2 hashing; Redis-backed rate limiting;
  versioned SQL migrations; a separate NestJS plus BullMQ service for queued
  email; generated PDFs, Excel exports and QR codes; Docker Compose behind
  Nginx.
- **Must not contain:** applicant numbers, uptime figures, performance
  statistics, or anything else not actually measured. The architecture is the
  story and it is interesting enough on its own.

### Article 2 — A static site with a CMS behind it

- **Why:** a genuinely unusual architecture, and the reasoning is already
  written down across `CLAUDE.md`, `docs/ADMIN.md` and `docs/SEO.md`. Mostly an
  editing job.
- **Serves:** technical readers, which is where developer-audience links come
  from.
- **The point:** the public site never queries the database. Content reaches it
  through publish, export and build. Why that is worth the indirection — one
  runtime request, no database on the critical path, a build that still works
  with no snapshot at all.
- **Honest hook:** the bug found in this audit. The CMS owned the SEO title,
  description and social card for months, and nothing read them. A pipeline is
  only as good as its last step, and this one stopped one short.

### Article 3 — Designing authentication for an admin CMS

- **Why:** a specific, recurring problem with a concrete answer in this
  codebase.
- **Serves:** FastAPI and Python backend queries — the most winnable
  non-name technical cluster.
- **From the repository:** why the session cookie is `SameSite=Lax`, and why
  that forces the API onto `api.<same-domain>` rather than a
  `*.onrender.com` host. That single decision is worth the article — it is the
  difference between an admin that works and one that signs in and then 401s
  on every request afterwards.

### Article 4 — Deploying React and FastAPI, and what broke

- **Why:** failure write-ups get read and linked more than success write-ups.
- **From real history, all of it in this repository:** `X-Frame-Options: DENY`
  blocking the site's own certificate viewer; `Cache-Control: immutable`
  pinning stale *headers* and keeping two certificates broken after the fix;
  the client-side cross-site cookie failure above.

### Article 5 — Building a multi-model AI platform

- **Why:** Zara AI is real and is an AI-cluster term.
- **Lower priority:** it is less distinctive than Article 1, and the space is
  crowded.
- **From the repository:** Gemini and Groq behind one shared model manager;
  Monaco and Sandpack for the in-browser workspace; IndexedDB for offline
  persistence.

---

## 4. If articles happen, this changes

Adding an article is the first thing that would make this a multi-page site,
and it touches architecture. Worth knowing before agreeing to it:

- The public site **has no router** — that is an architecture boundary in
  `CLAUDE.md`. Articles mean either adding one, or publishing elsewhere.
- **The lower-risk option is to publish on an existing platform** — Dev.to,
  Hashnode or a GitHub repository README — and link from the portfolio. No
  architecture change, no new dependency, and those platforms bring their own
  readers. The canonical stays with the platform, which is honest.
- Articles hosted here would each need a real URL, a unique title and
  description, a canonical, and their own sitemap entry. The sitemap would stop
  being a single hard-coded entry.

**Recommendation: write Article 1 and publish it on an external platform
first.** It tests whether the writing earns attention before anyone changes the
site's architecture for it.

---

## 5. Links, the legitimate kind

No purchased links, no link farms, no fake backlinks. The brief says so and so
does common sense — the risk is a manual penalty for a site whose entire
purpose is representing a real person.

What actually works here, in order of effort:

1. **GitHub profile README** — link the portfolio from
   `github.com/majeed74905`. Highest-authority link available for free, and it
   is a profile that already exists.
2. **LinkedIn Featured section** — add the portfolio. Also puts the social card
   in front of recruiters, which is the audience that matters.
3. **Each project's repository README** — link back to the portfolio. Several
   repositories, all legitimate.
4. **Instagram bio** — already linked from the site; make it mutual.
5. **University or department pages**, if a student project is ever listed. A
   `.ac.in` link is worth more than most.
6. **An article worth linking to.** The real long game, and the reason for
   section 3.

Note the shape of that list: every item is a profile that already exists and
should link to the site anyway. None is a trick.

---

## 6. Google Analytics — a recommendation, not an installation

The brief asks for an evaluation and says not to add anything without
approval. **Nothing has been added.**

### The recommendation: do not add GA4

Three reasons, in order of weight.

1. **It would cost the site its best security property.** The
   Content-Security-Policy is currently `script-src 'self'` — no third-party
   script runs on this site at all. GA4 means allowing Google's script and
   opening `connect-src`. That is a real, permanent weakening of a policy that
   is currently about as tight as a CSP gets, and it is the reason the console
   is silent and the attack surface is nearly nil.

2. **Search Console already answers the question being asked.** For a portfolio
   the useful questions are *did someone find me, and for what search?* —
   impressions, queries, CTR, position. Search Console gives all of that, for
   free, with no script on the page. GA4 answers *what did they do once here?*,
   which on a one-page site is close to unanswerable anyway.

3. **Privacy and legal surface.** GA4 sets cookies and sends visitor data to
   Google. In several jurisdictions that needs a consent banner and a privacy
   policy. The site currently has neither and currently needs neither — adding
   analytics changes that.

### If it gets added anyway

A reasonable position, if knowing visitor counts matters more than the above:

- Prefer a **cookieless, privacy-first** option — Plausible, Umami or
  Cloudflare Web Analytics — over GA4. Cloudflare's needs no script at all on
  some setups, and none of them sets a cookie, which avoids the consent banner
  entirely.
- Load it `async` or `defer` so it never blocks rendering.
- The measurement ID is **not a secret** and must carry the `VITE_` prefix like
  every other build-time public value. Keep it out of anything the backend
  reads.
- The site must work identically when the analytics host is blocked — a
  meaningful share of developer visitors run an ad blocker, and nothing on the
  page may depend on a script that will not load for them.
- Update the CSP in `vite.config.ts` deliberately and narrowly, naming exactly
  the hosts required and nothing more.

---

## 7. What not to do

From the brief, and restated because these are the temptations that would
actually come up on a site like this:

- No keyword stuffing, and no hidden text or links.
- No doorway pages — no page created to hold a keyword rather than to say
  something.
- No cloaking. The `<noscript>` block added in this work is an accurate summary
  of the rendered page, and must stay accurate. The moment it says something
  the page does not, it becomes cloaking.
- No fake reviews, testimonials or endorsements.
- No invented metrics — no user counts, uptime figures or performance claims.
  This is the rule the whole content layer is built on, and an article is not
  an exception to it.
- No fabricated structured data. Everything in the JSON-LD is checkable against
  the site, the repository, or something Mohammed stated directly.
- No competitor impersonation, and no claiming a seniority that is not real.
  He is a postgraduate student who ships genuinely substantial work. That is a
  good story told straight, and it does not need inflating.
