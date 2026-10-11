# Backup and recovery

What is backed up, how to take a backup, how to restore it, and what is
genuinely at risk. Written for whoever has to recover this site — most likely
its author, months from now, under time pressure.

Verified on 2026-10-11. Where something was not verified, this document says so
rather than implying it was.

---

## 1. What holds state

Three stores, with very different risk profiles. Only the first is irreplaceable.

| Store | Contents | Survives a redeploy? | Backed up by |
|---|---|---|---|
| **Neon Postgres** | all CMS content, admin account, sessions, audit log, publish history, contact messages | yes | `pg_dump` (below) + Neon's own history retention |
| **Render filesystem** (`STORAGE_ROOT`) | media uploaded through the admin | **no** — free tier has no persistent disk | nothing; see §5 |
| **Git repositories** | the site itself, the committed content snapshot, every asset the public site serves | yes | GitHub remotes |

The public site is a static build from the committed snapshot. It does **not**
query the database at runtime, so losing the database does not take the site
down — it only stops content being edited and the contact form being received.
That is the single most important fact in this document.

---

## 2. Taking a backup

Requires the PostgreSQL client tools. The dumps below were taken with
`pg_dump` 18.4 against Neon's Postgres 18.6; a `pg_dump` at least as new as the
server is required, and newer is fine.

```bash
# The connection string lives in backend/.env as DATABASE_URL. SQLAlchemy's
# driver prefix is not valid for pg_dump, so strip it:
#   postgresql+psycopg://...  ->  postgresql://...

# 1. Full backup, custom format. This is the one to keep.
pg_dump --dbname="$DATABASE_URL" --no-owner --no-privileges \
        --format=custom -f "backup-$(date +%Y%m%d-%H%M).dump"

# 2. Schema only, for reading and for diffing against migrations.
pg_dump --dbname="$DATABASE_URL" --no-owner --no-privileges \
        --schema-only -f "schema-$(date +%Y%m%d).sql"
```

`--no-owner --no-privileges` matters: the Neon role (`neondb_owner`) will not
exist in whatever you restore into, and without these flags the restore emits
an error for every single object.

### Measured, 2026-10-11

| | Result |
|---|---|
| Schema-only dump | 32,153 bytes in 22.5 s |
| Full custom-format dump | 86,153 bytes in 31.9 s |
| Tables captured | 25 of 25 |
| Database size | 9,312 kB, 283 live rows |
| Migration revision recorded | `0003_totp_hardening` |

Both dumps completed without error. The elapsed times are dominated by network
latency to Neon's region, not by data volume — see §6.

### Verifying a dump before you trust it

A dump nobody has read is a guess. This decodes the whole archive, so a
truncated or corrupt file fails here rather than during a real recovery:

```bash
pg_restore --no-owner --no-privileges -f - backup-YYYYMMDD-HHMM.dump | less
```

On the 2026-10-11 archive this produced 163,936 bytes of SQL containing 25
`CREATE TABLE`, 25 `COPY` data blocks, 25 primary keys, 21 foreign keys, 15
indexes, and a clean terminator. `alembic_version` was present and held
`0003_totp_hardening`, which matches the repository's migration head — so a
restore lands at a revision the code actually expects, rather than at an
unknown one.

---

## 3. Restoring

> **Not rehearsed.** The procedure below is correct but has not been executed
> end to end. The only Postgres server available during verification required a
> password that was deliberately not requested, and restoring into the live
> Neon project to test it would risk the very data being protected. Treat §3.1
> as the outstanding task it is: a recovery plan that has never been run is a
> hypothesis.

### 3.1 Rehearse it into a Neon branch (recommended, user-side)

Neon branches are copy-on-write and cost nothing to create, which makes them
the right rehearsal target — no separate server, no risk to `main`.

1. Neon console → the project → **Branches** → **New branch** from `main`,
   named e.g. `restore-drill`.
2. Copy that branch's connection string.
3. Restore into it:
   ```bash
   pg_restore --dbname="$BRANCH_URL" --no-owner --no-privileges \
              --clean --if-exists backup-YYYYMMDD-HHMM.dump
   ```
4. Verify, rather than assume:
   ```sql
   select count(*) from pg_stat_user_tables;        -- expect 25
   select version_num from alembic_version;         -- expect the dump's revision
   select count(*) from projects, skills, achievements;
   ```
5. Point a local backend at the branch and sign in to the admin. A restore that
   satisfies SQL but not the application has not been verified.
6. Delete the branch.

Record the date of the last successful rehearsal here when one is done:

| Last restore rehearsal | Result |
|---|---|
| _never_ | — |

### 3.2 Recovering the live database

Two routes. Prefer the first.

**Neon's own history** — for recent accidents (a bad bulk edit, a wrong
delete), Neon can branch from a point in time without any dump at all. Console
→ **Branches** → **New branch** → *from a timestamp*. This is the fastest route
and it loses nothing between the incident and the backup.

Its reach is limited by the project's **history retention** setting, which
varies by plan. Look it up in the Neon console under project settings and write
it down — it is the real recovery window, and it is shorter than most people
assume:

| Neon history retention | _check the console and record it_ |
|---|---|

**From a dump** — for anything older than the retention window, or if the
project itself is lost. Create a fresh Neon project, restore as in §3.1 step 3,
then update `DATABASE_URL` on Render.

### 3.3 After any database recovery

The restore is not the end of it:

1. `alembic current` — confirm the revision matches the application's head. If
   the dump predates a migration, run `alembic upgrade head`.
2. **Every admin session is in the restored data.** If the recovery is because
   of a suspected compromise, revoke them: `delete from admin_sessions;` and
   change the admin password.
3. Re-export and redeploy the public site if content changed:
   `cd frontend && npm run content:pull`, commit, push.

---

## 4. Contact messages

The only data in this system that arrives from the outside world and exists
nowhere else. A lost CMS record can be retyped from the committed snapshot; a
lost enquiry is simply gone.

At the time of verification `contact_messages` was empty, so nothing was at
risk. Once the form starts receiving real enquiries, this table is the reason
to take backups on a schedule rather than before deploys.

There is no email notification: a message sits in the database until someone
opens the admin. That is a deliberate scope decision, not an oversight, but it
means the recovery value of this table grows the longer nobody looks at it.

---

## 5. Media uploads are not backed up

Render's free tier has no persistent disk. `STORAGE_ROOT` points at a directory
inside the ephemeral checkout, so **everything uploaded through the admin media
library is destroyed on every deploy and every restart.**

This is an accepted trade, recorded in `render.yaml`, not a defect. It is
survivable only because of how the publish pipeline works:

- `npm run content:pull` copies every file the published snapshot references
  into `frontend/public/` and commits it. At verification: *27 of 27 referenced
  files in place*.
- So every asset the public site actually serves lives in git, on the CDN, and
  in every clone.

What is lost is any upload that was never published — and the originals of
anything uploaded but since replaced. If that matters, the fix is a paid plan
with a disk mounted at `/var/data` and `STORAGE_ROOT=/var/data/storage`;
`render.yaml` documents the change.

Until then: **export after publishing, not later.** An upload that has not been
through `content:pull` and a commit is one restart from gone.

---

## 6. What recovery actually costs

Honest numbers, measured from the verification environment (India) against
Neon's `us-east-2` region:

| | Measured |
|---|---|
| Median query round trip | 338 ms |
| Cold connection | 3.2 s |
| Full backup | ~32 s |

The latency is geographic, and it is why the admin feels slow. Moving the Neon
project closer to its users would improve both the admin and the duration of
every backup and restore. That is a deliberate, user-side decision and has not
been performed — a region move is not reversible in place and is not something
to do on someone's behalf.

**Recovery objectives, stated plainly rather than aspirationally:**

- *How much data could be lost?* Everything since the last dump — or since the
  edge of Neon's history retention, whichever is more recent. With no scheduled
  backups, "the last dump" currently means "whenever someone last remembered".
- *How long would recovery take?* Unknown. The restore path has never been
  rehearsed (§3.1). The dump itself takes about 30 seconds; the rest is
  guesswork until somebody runs the drill.
- *Is the public site affected?* No. It is static, on a CDN, built from a
  committed snapshot. It keeps serving throughout.

---

## 7. Before any migration or risky change

From `docs/DEPLOYMENT.md`: migrations are deliberately **not** run
automatically on deploy. The order is backup first, then migrate:

```bash
pg_dump --dbname="$DATABASE_URL" --no-owner --no-privileges \
        --format=custom -f "pre-migration-$(date +%Y%m%d-%H%M).dump"
alembic upgrade head
```

Skipping the dump to save a step is how a bad deploy becomes an unrecoverable
one.

---

## 8. Outstanding

Honest list of what is not done. None of these can be completed from the
repository; all are console or scheduling decisions.

- [ ] Run the restore rehearsal in §3.1 and record the date.
- [ ] Look up Neon's history retention for this project and write it into §3.2.
- [ ] Decide on a backup schedule. Nothing automated exists today — every
      backup so far has been taken by hand.
- [ ] Decide whether unpublished media matters enough to justify a paid plan
      with a disk (§5).
