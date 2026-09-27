# Mohammed Majeed J — Interactive 3D Portfolio

Specification for the public site. Working rules for day-to-day edits are in
`CLAUDE.md`; this document holds the decisions and the reasoning behind them.

---

## 1. Scope

A single-page public portfolio, seven sections, deployed static.

**In scope:** Home, About, Skills, Projects, Career, Achievements, Contacts.
Cinematic video background, subtle 3D accents, design-token system, typed
content layer, responsive behaviour, accessibility, SEO.

**Why the CMS came second.** The CMS is a months-long build and the visitor
never sees it. Content changes a handful of times a year, which a typed file
handles fine. So the portfolio was specified and built first, and the CMS
followed as its own project.

**It now exists** — `backend/` (FastAPI + PostgreSQL, auth, 2FA, media
library, contact-form backend) and `frontend/admin/` — and `docs/ADMIN.md` is its
specification. What has *not* changed is this document's subject: the public
site is still static, still built from a committed content snapshot, and still
makes exactly one runtime request. The CMS reaches it through
publish → export → build, never at request time.

`docs/PHASE-7-PRODUCTION-AUDIT.md` records the production-readiness audit of
the whole system.

---

## 2. Visual direction

Natural cinematic cabin/forest. Dark, warm, material, human.

**Palette:** charcoal and near-black ground, warm off-white ink, forest and
olive green, aged gold and wood brown.

**Never:** purple/violet, cyberpunk, neon, holograms, artificial particles,
heavy gradients, excessive glow, generic SaaS-dashboard styling.

No pure `#000` or `#FFF` anywhere — natural materials are never absolute.

### Contrast

All four ink tones pass WCAG AA on `--color-bg` (`#0a0e0c`):

| Token | Hex | Ratio | Use |
| --- | --- | --- | --- |
| `--color-ink` | `#f4f0e8` | ~16.9:1 | Body and headings |
| `--color-ink-secondary` | `#c6c0b2` | ~10.5:1 | Supporting copy |
| `--color-muted` | `#8e887b` | ~5.6:1 | Metadata, captions |
| `--color-faint` | `#6b665c` | ~3.4:1 | **Decorative only — never text** |
| `--color-gold` | `#d9a855` | ~9.6:1 | Accent, safe for text |
| `--color-forest-bright` | `#4e9070` | ~5.2:1 | Accent, safe for text |

---

## 3. Background video

### The asset

`public/assets/background/cabin-background.mp4` — 848×478, 7s, 24fps, H.264
High L3.0, no audio, faststart. ~876 KB.

Two candidate clips were supplied. Both were WhatsApp-delivered, both 848×478,
8s, 24fps, ~850 kbps — technically identical. The choice was made on content:

| | Clip A | Clip B (**chosen**) |
| --- | --- | --- |
| Grade | Cool, neutral, overcast | Golden hour, warm amber |
| Text-band median luminance | 0.155 | **0.114** (darker, better for type) |
| Blown-out pixels in band | 0% | 0.09% |
| Palette match to tokens | Poor — cool/grey | **Strong — wood, gold, amber** |
| Loop seam after processing | 2.24× | **1.99× (seamless)** |

Clip B was chosen because its grade *is* the design palette. Clip A would have
fought the gold and wood accents on every surface. Clip A is kept as
`cabin-background-alt.mp4`.

### Processing applied

1. **Audio track stripped** — 128 kbps of waste in a muted background.
2. **Made loopable.** Measured, the last-to-first frame jump was **33× larger**
   than a typical frame step: an obvious cut. Fixed by dropping the first second
   and cross-fading the tail back into it. Verified after: **2.0×**, i.e.
   indistinguishable from the clip's own motion. Command in
   `public/assets/background/README.md`.
3. **`+faststart`** so playback can begin before the file finishes downloading.

### Known limitation

**848×478 is not the original.** WhatsApp re-encoded a 1280×720 export down to
44% of its pixel area. On a 1080p viewport that is a 2.3× upscale and it will
look soft. Getting the original out of WhatsApp — sent as a *document*, not a
video — is the single highest-value fix available. See the background README.

### Scrim, derived by measurement

Every frame was sampled and the luminance of the band where type sits was
measured against `--color-ink`. Bare ink over the unscrimmed sun scores
**1.14:1** — invisible.

Black scrim alpha required for 7:1, per vertical third of the text band:

| Zone | Median luminance | p99 | Scrim needed |
| --- | --- | --- | --- |
| Left third | 0.066 | 0.554 | **0.55** |
| Centre third | 0.195 | 0.947 | 0.64 |
| Right third | 0.065 | 0.949 | 0.64 |

The sun blows out centre-right. The left column is the only zone with real
contrast headroom, so:

- **Hero copy is left-aligned.** This is a measurement-driven layout decision,
  not a stylistic one.
- Scrim is two layers: a light flat base (`--overlay-video-base: 0.32`) plus
  extra density banded over the left column (`--overlay-video-text: 0.42`),
  compositing to ~0.61 there — above the 0.55 requirement — while the sun keeps
  its punch on the right.
- Small screens get no video at all, so they use one flat
  `--overlay-video-flat: 0.66`.

**Rule:** bare ink lives in the left column. Anywhere else it goes on glass.

**If the video is ever replaced, these numbers must be re-measured.** They are
properties of this specific footage, not universal constants.

---

## 4. Visual tiers

`useCanvasPolicy()` returns one tier per visitor. Every expensive component asks
it rather than re-deriving device checks.

| Tier | Video | WebGL | When |
| --- | --- | --- | --- |
| `full` | yes | yes | Desktop, WebGL2 present, fine pointer, capable device |
| `reduced` | yes | no | No WebGL2, low core/memory count, or coarse pointer |
| `still` | no | no | Reduce-motion, Save-Data, slow connection, or width ≤767px |

The site is **complete and usable at `still`**. Richer tiers add atmosphere and
nothing else. Before probes resolve, the still tier renders — the first paint
never commits to work that might have to be torn down.

Phones get `still` deliberately: an 848px-wide video stretched over a tall
viewport looks worse than the poster and costs a download nobody asked for.

---

## 5. Content architecture

```
src/types/content.ts   contracts
src/content/*.ts       the actual content, one module per section
src/content/index.ts   barrel — components import from here only
```

`Todo` is a template literal type: `` `TODO_REPLACE_${string}` ``. `resolved()`
returns a value only when it is real, so unfilled fields render as nothing
instead of leaking a placeholder to a visitor.

When the CMS arrives, it replaces `src/content/*.ts` and these types become the
API response schema. Nothing else changes.

### Data integrity

Never invent degrees, dates, employers, certificates, awards, metrics, URLs,
email or phone numbers. The earlier design conversation contained invented
descriptions for all four projects; **none of it was carried into this repo.**

Confirmed: name; the roles Full Stack Developer / Python Backend Specialist /
AI Enthusiast; MCA at Periyar University; BCA at Islamiah College; the listed
technologies; four project *names*.

Everything else is `TODO_REPLACE_*`. Audit with `grep -r "TODO_REPLACE_" src/`.

---

## 6. Implementation order

| Step | | Status |
| --- | --- | --- |
| 1 | Project init | done |
| 2 | Design tokens | done |
| 3 | Content architecture | done |
| 4 | Shell + navigation | done |
| 5 | Home | done — hero, featured cards, music player, social, notes, scroll cue |
| 6 | About | done |
| 7 | Skills | done |
| 8 | Projects | done — four real projects, repository-verified stacks |
| 9 | Career | done |
| 10 | Achievements | done (renders honest empty state) |
| 11 | Contacts | done (validated form, no backend by design) |
| 12 | 3D interactions | done — see §10 |
| 13 | Responsive pass | done at 390 / 768 / 1440 |
| 14 | Asset/WebGL optimisation | video done; three lazy-chunked |
| 15 | Accessibility + SEO | done for built sections |
| 16 | Production build | passing |

---

## 9a. Projects — verification rule

Four real projects, one flagship. Every technology listed on the page was read
out of the repository, not inferred from what such a project usually uses.

| Project | Status | Verified from |
| --- | --- | --- |
| Periyar University PhD Admission Management System | Live | 6 × `package.json`, README, Prisma schema, nginx configs, SQL migrations |
| Zara AI Platform | Live | `package.json`, `services/*`, `components/*` |
| Diabetes Prediction | Live | `requirements.txt`, `src/train_model.py`, `render.yaml` |
| Online Library Management System | Local only | `includes/config.php`, PHP tree, JS assets |

**Two things were deliberately not claimed:**

- **Tailwind CSS on the PhD project.** Its README says "React + Vite +
  TailwindCSS", but `tailwindcss` appears in none of the six `package.json`
  files and there is no Tailwind config anywhere in the tree — only
  `tailwind-merge`, a class-string utility. Bootstrap 5 is what is installed,
  so Bootstrap is what the page lists. **The README overclaims; the page does
  not.**
- **A model accuracy figure for Diabetes Prediction.** `train_model.py` prints
  an accuracy at training time, but nothing in the repository records the
  value, so no number is published.

Hold any future project to the same rule: if the repository does not prove it,
it does not go on the page.

## 10. The 3D layer

Three.js does exactly one job here, and the rest of the depth is done without
it. That split is deliberate.

### WebGL — `src/three/AmbientScene.tsx`

A field of 14 large, very soft, warm discs that drift slowly and parallax with
the pointer at several z-depths. They read as **lens bokeh** thrown by the
fireplace and low sun already present in the footage.

Why this and not a big scene:

- **It is optically motivated.** Glowing sci-fi particles were explicitly ruled
  out; bokeh is what a real lens does with those light sources, so it belongs
  in this image.
- **It adds depth video cannot fake.** Parallax across several depths is the
  one thing a flat clip and a CSS gradient genuinely cannot do.
- **It holds no content.** No text, nothing interactive — so nothing is lost
  when it does not render.

Implementation notes: one shared `PlaneGeometry`; a small shader with a
`pow()`-shaped radial falloff (a hard falloff is what makes a bokeh disc look
like a glowing dot instead); additive blending, `depthWrite: false`; DPR capped
at 1.5 because retina detail buys nothing on a soft gradient; damped pointer
follow so it never snaps. The arrangement is seeded deterministically, so it is
the same every load and can actually be art-directed.

It mounts **only at the `full` tier** and is `React.lazy`-loaded, so three and
R3F sit in a separate ~238 kB gzip chunk that phones, reduce-motion and
Save-Data visitors never download.

### Depth without WebGL

- **`TiltCard`** — pointer-reactive perspective transform on project and
  achievement cards. Content stays in the DOM (selectable, focusable,
  screen-reader addressable) and it costs one composited transform instead of a
  render loop. Off under reduce-motion and on touch.
- **`Reveal`** — a short rise-and-fade as sections arrive, once, never
  replayed. Under reduce-motion it renders a plain element with no motion
  wrapper at all.
- **Content ground** — below the hero the page settles onto solid ground via a
  gradient, so the footage reads as environment where it should and body copy
  always has a measurable contrast basis.

### Cost, stated plainly

The bokeh is subtle by design, and 238 kB gzip is a real price for a subtle
effect — even lazily loaded and desktop-only. If it is ever judged not to earn
that, deleting `AmbientScene.tsx` and the `policy.mountWebGL` branch in
`CinematicBackground.tsx` removes it and its entire dependency chain with no
other changes.

---

## 7. Accessibility

Semantic landmarks, one `h1`, skip link, visible gold focus ring on everything
focusable, `aria-current` on the active nav item, focus moved to the target
section on nav activation, mobile menu closes on Escape and returns focus to its
toggle, `prefers-reduced-motion` honoured globally in CSS *and* per-component
for anything that owns real animation.

The background layer is `aria-hidden` and the video is `tabIndex={-1}` — it is
decoration and must never be a tab stop.

---

## 8. Performance

Measured against the production build (`npm run preview`), not the dev server.

| Tier | Transfer | FCP | 3D chunk | Video |
| --- | --- | --- | --- | --- |
| Desktop 1440 (`full`) | ~1295 kB | ~420 ms | loaded | loaded |
| Mobile 390 (`still`) | **~192 kB** | ~460 ms | not loaded | not loaded |
| Reduce-motion (`still`) | **~192 kB** | ~444 ms | not loaded | not loaded |

### The chunking trap — do not repeat this

A hand-written `manualChunks` in `vite.config.ts` forcing `@react-three/*` into
its own chunk made that chunk **React's common ancestor**, so the entry chunk
statically imported it. Every visitor — phones and reduce-motion included —
downloaded ~232 kB of three.js that never rendered. Vite also emitted a
`<link rel="modulepreload">` for it, guaranteeing the fetch.

Fixes: `manualChunks` removed entirely (automatic splitting handles the dynamic
`import()` correctly), plus `modulePreload.resolveDependencies` filters the 3D
chunk out of preload hints. Mobile transfer fell from 387 kB to 192 kB.

**Verify after any bundler change**: `dist/index.html` should contain no
`modulepreload` for the 3D chunk, and the entry chunk should have no static
import of it.

- Poster preloaded; video deliberately **not** preloaded (`preload="metadata"`,
  playback started by policy) so it never competes with content.
- Portrait served as WebP at two widths via `srcset`, lazy, `decoding="async"`.
- Video is torn down properly when the tier drops — paused, `src` removed,
  `load()` called — rather than left decoding in the background.
- WebGL probe releases its context immediately via `WEBGL_lose_context`.

---

## 9. Before launch

Everything below is blocking. **27** `TODO_REPLACE_*` remain — `projects.ts` is
now complete and contains none.

1. Biography paragraphs and developer philosophy in `about.ts`.
3. Education start/end years and locations (`about.ts`, `career.ts`).
4. Add `resume.pdf` to `public/assets/documents/` and set the path in `home.ts`.
5. Set `VITE_SITE_URL`. One variable now feeds `site.url`, the canonical link,
   `og:url`, the absolute `og:image`, `robots.txt` and `sitemap.xml` — the last
   two are generated at build time and are **omitted entirely** while it is
   unset, because a sitemap pointing at the wrong domain is worse than none.
6. Replace the placeholder audio, or delete the music player.
7. Get the 720p original of the background video out of WhatsApp (send as a
   *document*, not a video, or it is re-compressed again).
8. Confirm or delete the `availability` list in `contacts.ts` — it came from the
   design conversation, not from Mohammed.
9. Decide whether Achievements ships. If nothing real goes in it, remove it from
   the nav rather than shipping an empty section.

Done: email, phone, GitHub, LinkedIn, Instagram, portrait, institution names
(recovered from the previous portfolio at majeed-portfolio-website.netlify.app
and supplied directly).

### Deliberately not published

The old portfolio listed a full street address. It is **not** carried over —
a home address on a public site is a safety issue, not a contact detail. If a
location is wanted for recruiters, use city/district level only.
