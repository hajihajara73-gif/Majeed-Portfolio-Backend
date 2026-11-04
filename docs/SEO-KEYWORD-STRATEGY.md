# Keyword strategy

Written 2026-11-04. Companion to `SEO-AUDIT.md` and `SEO-CONTENT-STRATEGY.md`.

**No search volume, keyword difficulty or competition figures appear in this
document.** Getting real numbers needs Google Keyword Planner, Ahrefs or
Semrush, none of which this project has. Every judgement below is reasoning
from the site's actual content, labelled as such. Invented metrics would be
worse than none, because they would get planned against.

The only real data will come from Search Console's Performance report, once
the property is verified and has collected impressions. At that point, replace
the guesses here with the queries Google says the site actually appears for.
See `SEO-MONITORING.md`.

---

## 1. The one thing that decides this strategy

**There is one indexable URL.**

Keyword strategy for a one-page site is not "a page per cluster". It is:

1. Win the name queries outright. They are the only ones where this site is the
   single best result on the internet, and they are the ones that matter when
   someone has a CV in front of them.
2. Be a credible, honest result for the role and technology queries, without
   pretending to compete nationally for terms owned by job boards.
3. Add pages only when there is genuinely something to say. An article about
   building the PhD admission platform earns a URL; a page targeting
   "React Developer India" does not.

Point 3 is the discipline. Creating pages to hold keywords is a doorway-page
pattern and is explicitly out of scope.

---

## 2. Clusters, by intent

### Cluster A — Name and identity (primary)

**Intent: navigational.** Someone already knows who he is — a recruiter with
his CV, an interviewer before a call, a contact after a meeting.

| Query | Where it is served |
|---|---|
| Mohammed Majeed J | `<title>`, `<h1>`, `Person.name`, meta description |
| Mohammed Majeed portfolio | `WebSite.name`, `og:site_name` |
| Mohammed Majeed developer | `<title>`, `Person.jobTitle` |
| Mohammed Majeed full stack developer | `<title>`, hero roles |
| Afzal developer | `Person.alternateName` |

**This cluster is the whole point.** It is the one place the site should
realistically expect to rank first, because the competition is other people
with similar names rather than established publishers.

What now serves it that did not before: `Person` structured data with `sameAs`
pointing at GitHub, LinkedIn and Instagram. That is the signal that ties the
site, the code and the profiles into one entity in Google's index. Without it,
Google had three unconnected accounts and a page.

**Risk, and it is real:** "Mohammed Majeed" is a common name. Expect to compete
with namesakes. The differentiators Google can actually use are the middle
initial, "Afzal", the university, and the linked profiles. All four are now in
the markup.

### Cluster B — Role (secondary)

**Intent: commercial or informational.** Someone looking for a developer, or
browsing portfolios.

| Query | Honest assessment |
|---|---|
| Full stack developer portfolio | Highly competitive; a single page will not win it nationally. Worth being relevant to, not worth optimising for. |
| Python backend developer | Now in the `<title>` and `Person.jobTitle`. The most winnable of this group, because the Skills and Projects sections genuinely evidence it. |
| FastAPI developer | Narrower, so more winnable. Genuinely evidenced: this project's own backend is FastAPI. |
| React developer | Very competitive. Relevance only. |
| AI application developer | Evidenced by Zara AI and the diabetes classifier. |

The title change (section 4) targets this cluster deliberately: it is the one
place where adding a secondary keyword costs nothing and is simply true.

### Cluster C — Academic and project

**Intent: informational, and unusually specific.**

| Query | Where it is served |
|---|---|
| MCA student Periyar University | `Person.alumniOf` with a `PostalAddress`, plus the About and Career sections |
| Periyar University PhD admission system | The project entry — a genuinely distinctive term |
| University admission management software | The project summary and highlights |
| Full stack university management project | The project description |

**This is the most promising non-name cluster**, and it is underused. The PhD
Admission Management System is a real, deployed, four-portal platform running
in production at a public university. Almost nobody else can write about that
specific system, which makes it the one topic where this site could rank for
something genuinely competitive.

That is the single strongest argument for the first article in
`SEO-CONTENT-STRATEGY.md`.

### Cluster D — Technology plus region

| Query | Honest assessment |
|---|---|
| React developer India | Dominated by job boards and agencies. A personal site will not displace them. |
| Python FastAPI developer India | Narrower, and slightly plausible. |
| Backend developer portfolio | Relevance only. |

**Recommendation: do not optimise for these.** The honest ceiling for a
one-page personal site against Naukri, Indeed and LinkedIn is low, and the
tactics that would move the needle are the ones the brief rules out. The
geographic signal that *is* legitimate — Salem and Vaniyambadi in
`Person.alumniOf.address` — is now present, and that is the right amount.

---

## 3. Mapping clusters to existing content

| Section | Serves | Current state |
|---|---|---|
| Home / hero | A, B | Strong. Name in `h1`, three roles, technology list |
| About | A, C | Strong. Biography is specific and concrete |
| Skills | B, D | Good. Six categories, genuine technologies |
| Projects | B, C | **Strongest content on the site.** Four projects with real architecture detail |
| Career | C | **Weakest.** Two education entries, dates still unfilled |
| Certificates | C | Good. 11 entries across five categories |
| Achievements | C | Good |
| Contacts | A | Fine |

### The gap worth closing

**Career is thin and it is the section that carries Cluster C.** The
introduction and the education locations are now filled, but the dates and the
two entry descriptions are still `TODO_REPLACE_*` and render as nothing.

Two fields in the admin would close it. Nothing else on this list is as cheap.

---

## 4. Title and description

Reviewed against the actual content, as the brief asked.

**Previous title** — `Mohammed Majeed J — Full Stack Developer` (40 characters).
Clean, but it spent none of its remaining budget on the second role the site
genuinely evidences.

**Suggested in the brief** — `Mohammed Majeed J. | Full Stack Developer &
Python Backend Developer` (68 characters). Right instinct; slightly over the
roughly 60 characters Google will display, so the tail risks truncation.

**Adopted** — `Mohammed Majeed J — Full Stack & Python Backend Developer`
(57 characters). Name first, because Cluster A is the priority. Both role
keywords present. Under the truncation limit. Em dash to match the house style
used across the site.

**Description adopted** (135 characters):

```
Portfolio of Mohammed Majeed J — a full stack developer building Python and
FastAPI backends, React interfaces, and applied AI projects.
```

Leads with the name, for the same reason. Names the stack the Projects and
Skills sections actually evidence. Fits inside the roughly 155 characters
Google will show.

> **These two are not live yet.** They are authored in
> `frontend/src/content/seo.ts`, but the published CMS snapshot still carries
> the previous values, and the CMS deliberately wins. Two fields in the admin
> plus a publish and a content pull. See `FINAL-SEO-REPORT.md`.

---

## 5. Rules this strategy will not break

From the brief, and worth restating because they constrain everything above:

- No keyword stuffing, and no unnatural repetition. The density on this site is
  low and should stay low.
- No pages created to hold keywords. A page needs something to say first.
- No invented search volume, difficulty or competition figures.
- No fake backlinks, purchased links or link farms. The legitimate equivalents
  are a GitHub profile README linking here, the LinkedIn Featured section, and
  an article that is worth linking to on its own.
- Nothing claimed in markup that is not true on the page.

---

## 6. What to do once there is data

Search Console Performance will, within a few weeks of verification, show the
queries the site is *actually* appearing for. Expect at least one surprise —
there usually is.

Then:

1. Replace the guesses in section 2 with real queries.
2. Look for impressions with a poor CTR. That is usually a title or description
   problem, and it is the cheapest fix in SEO.
3. Look for queries at positions 5 to 20. Those are the ones where better
   content moves the needle; position 50 rarely is.
4. Only then decide whether an article is worth writing. See
   `SEO-CONTENT-STRATEGY.md`.
