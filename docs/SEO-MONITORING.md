# Search performance monitoring

What to watch in Search Console once the property is verified, how often, and
how to tell a real problem from normal noise.

Setup is in `GOOGLE-SEARCH-CONSOLE-SETUP.md`. Do that first — none of this
exists until the property is verified.

---

## There is no data yet

Search Console reports **actual search activity**, not potential. Nothing
appears until Google has crawled the site, indexed it, and shown it to real
people who ran real searches.

A realistic timeline for a newly verified site with no inbound links:

| When | What to expect |
|---|---|
| Days 1–3 | Nothing. Possibly "Discovered — currently not indexed". |
| Days 3–14 | Homepage indexed. First impressions, almost all for the name. |
| Weeks 2–6 | Performance starts to be readable. Queries beyond the name appear. |
| Months 2–6 | Enough history to tell a trend from a wobble. |

**No metric in this document has a value yet, and none should be invented.**
If a number is needed for a CV or an application, take it from the Search
Console screen on the day, not from here.

---

## The eight metrics

Search Console's Performance report gives four, sliced four ways.

### The four metrics

| Metric | What it is | What it tells you |
|---|---|---|
| **Total clicks** | People who clicked through | The only one that is actually traffic |
| **Total impressions** | Times the site appeared in results | Reach. Rises long before clicks do |
| **Average CTR** | clicks / impressions | Whether the title and description earn the click |
| **Average position** | Mean rank across impressions | Rough, and easily skewed. Treat as a direction, not a number |

**CTR is the most actionable of the four.** Impressions with a poor CTR mean
Google is showing the site and people are choosing something else — which is
usually a title or description problem, and is the cheapest thing in SEO to
fix. Position is the least actionable: it averages across every query, so one
obscure term at position 80 drags it down while nothing real has changed.

### The four dimensions

- **Queries** — what people typed. The single most valuable tab.
- **Pages** — which URL appeared. There is one, so this tab will stay dull
  unless articles get added later.
- **Countries** — expect India first, then wherever applications are sent.
- **Devices** — mobile versus desktop. Worth checking once: if mobile
  impressions are high and mobile CTR is much lower than desktop, that is a
  real signal worth chasing.

---

## Keyword groups to track

Set each of these as a **query filter** in the Performance report. Check the
group, not individual spellings.

### Group 1 — Name queries (the ones that matter)

Filter: `Mohammed Majeed`

These are navigational. Someone already knows the name — from a CV, an
interview, a LinkedIn message.

- **Target: position 1–3, CTR above 50%.**
- This is the only group where first position is a reasonable expectation,
  because the real competition is namesakes rather than publishers.
- If position is good but CTR is poor, the title or description is the problem.
- If position is poor, check whether a namesake outranks him, and whether the
  `sameAs` profiles in the structured data are correct — see the LinkedIn note
  in `SEO-AUDIT.md`.

### Group 2 — Portfolio and brand

Filter: `portfolio`

Catches "Mohammed Majeed portfolio", "Afzal portfolio" and similar. Also the
place to watch whether Google has adopted **Mohammed Majeed Portfolio** as the
site name — it shows up in how results are labelled, not as a metric.

### Group 3 — Afzal

Filter: `Afzal`

Tests whether `Person.alternateName` is doing anything. Expect low volume.
Common name, so expect noise.

### Group 4 — Full stack developer

Filter: `full stack`

Highly competitive. **Impressions here are a success; clicks are a bonus.**
Do not judge the site by its position on this group.

### Group 5 — Python and backend

Filter: `python`, and separately `fastapi`

More winnable than Group 4, because the content genuinely evidences it and the
terms are narrower. **FastAPI is the most promising non-name term on the
site** — narrow, technical, and backed by a real FastAPI codebase.

### Group 6 — React

Filter: `react`

Very competitive. Relevance only.

### Group 7 — University and project

Filter: `periyar`, and separately `admission`

**Watch this one.** The PhD Admission Management System is genuinely
distinctive — a four-portal platform in production at a public university.
Almost nobody else can write about that specific system. If any non-name group
is going to produce meaningful traffic, it is this one.

It is also the best evidence for whether the first article in
`SEO-CONTENT-STRATEGY.md` is worth writing.

---

## A routine that is actually sustainable

Checking daily is a waste of time; search data is too noisy at this volume.

### Weekly, five minutes

- **Indexing, then Pages** — is the homepage still indexed? Any new errors?
- **Performance, last 28 days** — glance at clicks and impressions. Direction
  only.

### Monthly, twenty minutes

- **Performance, last 3 months, Queries tab.** Read the actual list. There is
  usually at least one surprise — a query nobody predicted.
- Note any query at **position 5–20**. Those are where better content changes
  something; position 50 rarely is.
- Note any query with **high impressions and low CTR**. Title or description
  work.
- **Core Web Vitals** — once there is enough traffic, this report appears with
  real field data. This is also where **INP** finally gets a number; it could
  not be measured in the lab (see `SEO-AUDIT.md` section 7).
- Update `SEO-KEYWORD-STRATEGY.md` section 2 with what is actually true,
  replacing the guesses.

### Quarterly

- Re-run the technical checks in `SEO.md` section 3 against production.
- Re-validate the structured data at `https://validator.schema.org`.
- Confirm the social card still renders, by pasting the URL into LinkedIn's
  Post Inspector.
- Check the outbound project links still return 200. Hosted demos go away;
  Render free tiers sleep and are eventually removed.

---

## Reading the data honestly

A few traps worth naming.

- **Impressions rise before clicks, by a lot.** Normal. Not a problem.
- **Average position jumps around.** It averages over every query. A single new
  long-tail term at position 90 moves it. Look at position *per query*.
- **Branded and unbranded traffic are different things.** Name queries will
  dominate and should. Do not read that as a failure to rank for anything else
  — it is the site working as intended.
- **Small numbers are noise.** At low volume, 3 clicks versus 7 clicks is not a
  trend. Wait for a quarter before concluding anything.
- **Search Console and analytics will disagree.** They measure different
  things. This project has no analytics (see `SEO-CONTENT-STRATEGY.md`), so
  the question will not arise unless one is added.

---

## When to act

| Observation | Action |
|---|---|
| Homepage not indexed after 4 weeks | Work through the troubleshooting table in `GOOGLE-SEARCH-CONSOLE-SETUP.md`. Get real inbound links from the GitHub profile README and LinkedIn Featured. |
| Name queries below position 5 | Check `sameAs` is correct, especially the LinkedIn URL. Strengthen the profile links. |
| High impressions, CTR under 2% | Rewrite the SEO title and description in the admin, publish, pull, deploy. |
| "Crawled — currently not indexed" persisting for months | Thin content. Fill the remaining `TODO_REPLACE_*` fields, then consider the articles in `SEO-CONTENT-STRATEGY.md`. This is also the point at which prerendering becomes worth reconsidering. |
| Core Web Vitals flagged in field data | Compare against the lab numbers in `SEO-AUDIT.md` section 9. Lab was comfortably inside the thresholds, so a field failure means something real changed. |
| A query at position 5–20 with real volume | The best opportunity available. Strengthen that content specifically. |
