# CLAUDE.md

Working rules for this repository. Full specification lives in `docs/SPEC.md`.

## Purpose

Public portfolio for **Mohammed Majeed J**. One page, seven sections, deployed
as a static site.

The site is still **static**: it is built from a committed content snapshot and
makes exactly one runtime request, the contact form. There is now an admin CMS
behind it (`backend`, `frontend/admin`), but the public site **never queries
the database**. Content reaches it through a publish → export → build pipeline.
See `docs/ADMIN.md`.

## Commands

```bash
npm run dev            # dev server
npm run typecheck      # tsc -b, no emit
npm run lint           # eslint
npm run build          # tsc -b && vite build (public site only)
npm run build:all      # public site + admin into dist/ — what Vercel runs
npm run preview        # serve the production build
npm run content:pull   # export the published snapshot into src/content/
```

The API and admin have their own commands — see `docs/ADMIN.md`. The admin app
has its own `node_modules`; that isolation is deliberate.

## Architecture rules

- **Content is not design.** Every string, list and asset path lives in
  `src/content/*.ts` and is typed by `src/types/content.ts`. Components read
  content; they never contain copy. That boundary is what let the CMS take over
  the content layer without touching a single component — `src/content/index.ts`
  now serves `published.ts`, which overlays the exported snapshot onto those
  modules. The modules stay as the base, so a build with no snapshot still
  renders correctly.
- **Tokens are not values.** Every colour, size, radius, shadow and duration
  comes from `src/styles/tokens.css`. Never write a hex code, a px radius or a
  `transition: 300ms` inside a component.
- **One capability decision.** `useCanvasPolicy()` in `src/three/canvasPolicy.ts`
  decides whether video and WebGL are allowed for this visitor. Components ask
  it; they do not re-derive "is this mobile" with their own media queries.
- Path alias `@/` maps to `src/`.

## Design rules

- Natural cinematic cabin/forest: charcoal, forest green, olive, warm wood,
  gold/amber, warm-white type.
- **Never** purple/violet, cyberpunk, neon, holograms, AI particles, heavy
  gradients or glow. If it looks like a generic AI portfolio, it is wrong.
- Glass is an accent, not a default. Restrained transparency, one hairline
  border, real blur. Not every surface is glass.
- Animation must communicate hierarchy or interaction. No perpetual motion.
  Everything that animates checks `usePrefersReducedMotion()`.

## 3D rules

- Three.js/R3F only where it materially improves the experience. No giant
  always-on WebGL scene.
- DOM owns typography, navigation, content, buttons, forms and accessibility.
  WebGL owns atmosphere only.
- **The site must be complete and usable with WebGL unavailable.** Test this.

## Content rules

- **Never invent personal information** — no degrees, dates, employers,
  certificates, awards, metrics, URLs, email or phone.
- Unknown values are `TODO_REPLACE_*` strings. `resolved()` in
  `src/types/content.ts` hides them at render time, so an unfilled field shows
  nothing rather than a placeholder.
- Find outstanding work with: `grep -r "TODO_REPLACE_" src/`
- An honest empty section beats a fabricated full one.

## Testing rules

After each section, before moving on:

1. `npm run typecheck` — clean
2. `npm run lint` — clean
3. `npm run build` — succeeds
4. Load the dev server, check the browser console is silent
5. Check it at 375px wide, and with reduce-motion turned on

When the change touches `backend` or `frontend/admin`, also run, from
`backend`: `ruff check app tests` and `python -m pytest`.

Do not report a step complete without running these.

## Architecture boundaries — do not cross these

- The public site **must not fetch the database at runtime**. Content is baked
  in at build time. The contact form is the single exception and it degrades
  honestly when the API is unreachable.
- **Never fabricate a parallel schema.** If a requirement cannot be implemented
  with the existing tables, stop and report the limitation. (Example: contact
  channels stayed in source rather than gaining a table — see `docs/ADMIN.md`.)
- Do **not** add a drag-and-drop page builder.
- Publish history is **append-only**. A rollback creates a new snapshot; it
  never rewrites or deletes an old one.
- **No hard-coded production URL or domain.** The admin's API base, the site URL
  and the contact endpoint are all environment variables; production refuses to
  start rather than guess. See `docs/DEPLOYMENT.md`.
- The public site has **no router**. Navigation is hash anchors, so `/about` is
  not a route — do not add an SPA catch-all rewrite for it. The admin, at
  `/admin/`, does use path routes and has one.
- Publishing records a snapshot; it does **not** by itself change the live site.
  The site is built from the committed export — `npm run content:pull`, commit,
  push.
