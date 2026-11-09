# Phase 2B — Resend inbound integration: final report

**Date:** 2026-11-09
**Branch:** `seo/technical-foundation`
**State:** code complete, **not committed, not pushed, not deployed**.
Migration 0007 **applied to production on 2026-11-09** (approved); see §2.

Operational detail lives in [`EMAIL.md`](EMAIL.md) Part 3. This document is
the status account: what works, what is only proven in tests, what is
blocked, and what still needs a human.

---

## 1. Classification

### ✅ Implemented and tested

Verified by automated tests. 42 cases in `backend/tests/test_inbound_email.py`,
and the whole 241-test suite passes **with every non-loopback socket blocked**
— which is the proof, not the claim, that no test sends real email.

| Feature | Pinned by |
|---|---|
| Webhook endpoint `POST /api/public/webhooks/resend` | `test_valid_signature_is_accepted` |
| svix signature verification against the **raw bytes** | `test_tampered_body_is_rejected` |
| Forged signature refused before the body is read | `test_invalid_signature_is_rejected` |
| Unsigned request refused, no hint which header was missing | `test_missing_signature_headers_are_rejected` |
| Replay protection (5-minute timestamp tolerance) | `test_stale_timestamp_is_rejected` |
| 503 rather than accepting unverifiable traffic | `test_webhook_refuses_when_unconfigured` |
| Unhandled event types acknowledged, not retried forever | `test_unsupported_event_is_acknowledged` |
| Malformed payloads answered, never a 500 | `test_malformed_payload_is_handled_safely` |
| Idempotency on Resend's email id | `test_duplicate_delivery_stores_one_row` |
| Idempotency on the RFC Message-ID | `test_duplicate_detected_by_message_id_alone` |
| Concurrent duplicate loses gracefully, not a 500 | `test_concurrent_delivery_loses_gracefully` |
| Matching via `In-Reply-To` | `test_matched_by_in_reply_to` |
| Matching via the `References` chain | `test_matched_by_references_chain` |
| Unmatched mail dropped, not attached on a guess | `test_unmatched_email_is_not_stored` |
| **Forged `From`/`Reply-To`/`Subject` cannot join a thread** | `test_forged_sender_cannot_join_a_conversation` |
| A reply resurfaces the thread; original text untouched | `test_inbound_reply_marks_the_enquiry_unread` |
| Read key used for the fetch, send key restored after | `test_fetch_uses_the_read_key_and_restores_the_send_key` |
| Filename sanitisation (traversal, both separators, dot-only) | `test_filename_sanitisation` ×9 |
| Attachment allowlist and size cap recorded with reasons | `test_attachment_rules_are_recorded_not_guessed` |
| Hostile payload bounded (subject, body, wrong types) | `test_parsing_bounds_and_sanitises_a_hostile_payload` |
| HTML-only message yields readable, tag-free text | `test_html_only_message_yields_readable_text` |
| Attachment download requires an admin session | `test_attachment_download_requires_a_session` |
| Signed URL never reaches the browser | `test_attachment_is_streamed_without_exposing_the_signed_url` |
| No cross-conversation attachment access (404, not 403) | `test_attachment_from_another_thread_is_not_reachable` |
| Oversized download abandoned **mid-stream** despite a lying `Content-Length` | `test_oversized_attachment_is_abandoned_mid_download` |
| Type allowlist re-checked at download time | `test_disallowed_attachment_type_is_refused_at_download` |
| Non-HTTPS download URL refused | `test_non_https_download_url_is_refused` |
| Signed URL redacted from failure logs | `test_download_failure_does_not_log_the_signed_url` |
| Thread API exposes metadata, never HTML or URLs | `test_thread_exposes_metadata_but_never_html_or_urls` |

### ⚠️ Implemented but not live-tested

Correct against the real API's **observed shape** — I read a genuine received
email from your inbox and built the fixtures from it — but no real visitor
reply has travelled the full path yet, because that needs the webhook
deployed.

| Feature | Why not yet proven end to end |
|---|---|
| A real `email.received` delivery from Resend | The endpoint is not deployed. Resend has nothing to call. |
| A real reply threading correctly in a visitor's client | Needs a round trip through an actual mail client. |
| A real attachment download | No inbound mail with an attachment exists yet. |
| Timeline rendering of attachments and auth warnings | Builds and typechecks clean; never rendered with real inbound data. |
| The partial unique index under genuine concurrency | The conflict path is tested by simulation; the index itself is unapplied. |

Live-verified already, worth separating from the above:

- The **read key works** — `GET /emails/receiving` and `GET /domains` both
  return 200, against three 401s for the send-only key. Tested, not assumed.
- The **response shape** — fetched a real received email and confirmed
  `headers` is a full dict, `authentication` carries SPF/DKIM/DMARC, and
  `message_id` is present top-level.

### 🚫 Blocked

**Nothing.** Both blockers in the previous revision of `EMAIL.md` are gone:

- *"The API key is send-only"* — resolved by `RESEND_READ_API_KEY`, verified
  against the live API.
- *"Receiving is not configured"* — resolved by using a **Resend-hosted inbox
  address**. This needed **no DNS change and none was made**; the sending
  domain `mail.mohammedmajeedportfolio.me` was never touched.

### 🔧 Requires manual configuration

Each of these is yours to do, and none can be done safely from here.

| # | Action | Why it is manual |
|---|---|---|
| 1 | **Apply migration 0007** | You have not approved it. See §2 — ordering matters. |
| 2 | **Register the webhook in Resend**, pointing at `https://<api-host>/api/public/webhooks/resend`, subscribed to `email.received` | Only you can reach the Resend dashboard. |
| 3 | **Confirm the three env vars are set on Render** | I have no Render API access. §4 has a probe that checks this without printing anything. |
| 4 | **Turn off Gmail→Resend forwarding** | See §5. |
| 5 | **Rotate the exposed credentials** | See §6. |

---

## 2. Migration 0007 — APPLIED

Approved and applied. Production is at `0007_inbound_attachments`.

**Restore point taken** (read-only, no writes):
`backend/storage/backups/pre-0007-20261109T092530Z.json` — 2 `email_messages`
rows, 4 `contact_messages` rows, plus the alembic version. Gitignored, so it
will not be committed.

Exact DDL, rendered offline:

```sql
BEGIN;
ALTER TABLE email_messages ADD COLUMN attachments JSONB;
ALTER TABLE email_messages ADD COLUMN auth_results JSONB;
CREATE UNIQUE INDEX uq_email_messages_inbound_resend_id
  ON email_messages (resend_email_id) WHERE direction = 'inbound';
UPDATE alembic_version SET version_num='0007_inbound_attachments'
  WHERE alembic_version.version_num = '0006_email_conversations';
COMMIT;
```

Purely additive. Two nullable columns — metadata-only in Postgres 11+, so no
table rewrite — and one partial index. No column is altered, renamed or
dropped; no other table is touched. Verified against live data that **no
existing inbound duplicates** would make the index creation fail.

### Post-application verification

Every pre-flight fact re-checked afterwards:

| Check | Result |
|---|---|
| revision advanced | `0007_inbound_attachments` |
| `attachments` / `auth_results` columns added | both present |
| partial unique index created | present, `unique=True` |
| `email_messages` rows | 2 → 2, unchanged |
| `contact_messages` rows | 4 → 4, unchanged |
| table count / names | 27 → 27, identical |
| columns added to `email_messages` | exactly 2 |
| pre-existing columns and indexes | all intact |
| ORM `SELECT` on `email_messages` | **now works** (was failing) |
| existing rows | read back with `NULL` in both new columns |

The constraint was then proven to actually enforce, inside a transaction that
was rolled back — row count 2 before and 2 after, so the database is
untouched:

- two **inbound** rows sharing a Resend id → refused with `UniqueViolation`;
- two **outbound** rows sharing a Resend id → accepted, confirming the index
  is genuinely partial and the outbound path is unaffected.

### Ordering mattered, and was respected

The model declares `attachments` and `auth_results`. Before the migration, a
direct query against production confirmed:

```
ORM SELECT FAILS: ProgrammingError | column email_messages.attachments does not exist
```

So deploying the code first would have taken the admin inbox down — the
message thread, the reply composer and the dashboard counts all depend on
that query. The migration went first. **The code is now safe to deploy.**

### Why the unique index is in here at all

I found a real defect in my own first pass while reviewing it. The webhook
checked "have I stored this already?" and then inserted, and 0006 gave
`resend_email_id` only a *plain* index. Nothing stopped two concurrent
deliveries of the same email — precisely what Resend's retries produce — from
both passing the check and both inserting, duplicating a message in the
timeline.

The pre-check is now explicitly advisory (it saves a pointless network fetch
on the common sequential retry) and the database is the authority.
`record_inbound` catches the `IntegrityError` and returns the same "duplicate"
outcome, so losing the race is a 200, not a 500.

---

## 3. Security review

### What an attacker cannot do

**Inject into a conversation.** Matching uses `In-Reply-To` and `References`
*only*. Those name Message-IDs this system minted and stored. `From`,
`Reply-To` and `Subject` are never consulted — all three are sender-supplied
and trivially forged, and a fallback to any of them would let anyone who
guessed a visitor's address and subject line write into that visitor's thread.

**Forge a delivery.** HMAC-SHA256 over the exact bytes received, with a
five-minute tolerance. Verification happens before the body is parsed, and no
database query runs until it passes.

**Exhaust memory or disk.** Request body capped at 1 MB (behind the existing
256 KB JSON middleware). Text bodies capped at 200 KB, subjects at 255,
addresses at 254, attachment count at 20. Attachment bytes are counted as
they arrive and the connection dropped past the cap — a `Content-Length` is
the remote end's word, so only counting catches a response that lies.

**Reach an attachment they should not.** The download endpoint needs an admin
session, the attachment id must belong to a message on *that* conversation
(404 for a foreign id, since 403 would confirm it exists), and type and size
are re-checked against **Resend's** metadata rather than the stored row —
because the row records what the *sender* claimed, and a sender's claim should
not authorise a download.

**Get a usable link to private mail.** Resend's signed URL is fetched
server-side and never serialised, never returned, and now redacted from
failure logs too.

**Be executed.** Nothing in an inbound email is run, followed or treated as
an instruction. Inbound HTML is stored for the record and is **not** in the
thread API's response, so it never reaches the browser. Responses are always
`Content-Disposition: attachment` with `nosniff`.

### Key separation

| Variable | Scope | Used for |
|---|---|---|
| `RESEND_API_KEY` | send-only | notifications, replies |
| `RESEND_READ_API_KEY` | read | inbound bodies, attachments |

`fetch()` swaps the read key in for one call and restores the sending key in a
`finally`, so a failure cannot leave the wrong key in place and a read can
never widen what sending can do. `RESEND_API_KEY` was **not changed**.

### Logging

Audited every log line in the new code: ids, sizes, content types and
truncated error strings only. No keys, no secrets, no message bodies, no email
addresses. `str(error)` not `repr(error)`, because an SDK exception can carry
the request it was built from — including its `Authorization` header.

### Two things I am deliberately not claiming

**No rate limit on the webhook.** An attacker can send unlimited invalid
signatures. Each costs one HMAC and no database query, so the cheap rejection
path is the mitigation — but it is a mitigation, not a limit, and if Resend's
retry volume ever needs capping that is where to add it.

**An email composed fresh to the inbound address vanishes.** It carries no
threading headers, so there is nothing to match it to, and it is logged and
dropped. This is the intended trade for refusing to guess, but it does mean
the inbound address is not a general-purpose mailbox. Worth knowing before
you give it to anyone.

---

## 4. Checking the Render configuration without printing anything

I have no Render API access, so I could not verify the three variables
myself. After deploying, this tells you whether the webhook secret is set
without disclosing it:

```bash
curl -i -X POST https://<your-api-host>/api/public/webhooks/resend
```

- **`401 invalid_signature`** — the secret **is** set. The endpoint is live
  and refusing an unsigned request, which is correct.
- **`503 webhook_not_configured`** — the secret is **not** set.

Neither answer discloses anything. Use this rather than reading the value
back out of Render.

---

## 5. The Gmail forward should be turned off

Your Resend inbox already contains a **Gmail forwarding confirmation**, so
Gmail→Resend forwarding was set up at some point.

It is now **unnecessary**: Reply-To points at the inbound address directly, so
a visitor's reply reaches Resend without Gmail in the path. Leaving it on
means unrelated Gmail mail also arrives at the inbound address, where it gets
dropped for having no matching conversation — harmless, but it fills a mailbox
that should only ever hold replies, and it makes the logs harder to read.

Gmail → Settings → Forwarding and POP/IMAP → remove the forwarding address.

---

## 6. Credentials

These repositories are **public**, so the credential-rotation checklist is
deliberately **not** published here. Naming which secrets are currently
exposed and unrotated tells a reader nothing useful and an attacker
something.

It lives in the private working copy of this document, alongside the
session that produced it. If you are the maintainer and need it, it is in
the monorepo at `docs/INBOUND-EMAIL-REPORT.md` §6.

Standing rules that do belong in public: no API key, webhook secret or
database URL appears in this repository, in its history, or in
`.env.example`, which carries names and guidance only. Verified by sweep
before each publish.

## 7. Files changed

Paths are the monorepo's. In this repository the leading
`backend/` or `frontend/` segment is the repository root.

**New**

```
backend/app/api/routes/webhooks.py          the endpoint
backend/app/services/inbound_email.py       fetch, parse, sanitise, download
backend/alembic/versions/0007_*.py          migration (NOT applied)
backend/tests/test_inbound_email.py         42 cases
docs/INBOUND-EMAIL-REPORT.md                this file
```

**Modified**

```
backend/app/main.py                         register the webhook router
backend/app/core/config.py                  read key, attachment cap
backend/app/models/content.py               attachments, auth_results
backend/app/schemas/content.py              expose both; Any import
backend/app/api/admin/serialisers.py        serialise both
backend/app/api/admin/dashboard.py          attachment download endpoint
backend/app/services/conversation.py        inbound matching; IntegrityError
backend/tests/conftest.py                   force inbound vars empty
backend/.env.example                        document the new vars (no values)
frontend/admin/src/lib/api.ts               downloadFile helper
frontend/admin/src/pages/Media.tsx          attachments, auth warning, sender
docs/EMAIL.md                               Part 3; §10 brought up to date
```

### One fix in the test harness worth flagging

`.env` leaked into the suite again. Once it gained
`CONTACT_INBOUND_ADDRESS`, the existing test pinning *"Reply-To falls back to
the owner until inbound is configured"* started seeing the real inbound
address and failing — the suite was reading the machine's configuration
instead of its own. `conftest.py` now forces all three inbound variables
empty, the same way it already forced the Resend key. This is the second time
this exact failure mode has appeared; the guard now covers every mail
variable.

---

## 8. Verification actually run

| Check | Result |
|---|---|
| `ruff check app tests` | clean |
| `python -m pytest` | **241 passed** |
| Same suite, every non-loopback socket blocked | **241 passed** — no test reaches Resend |
| `alembic heads` | one head, linear history |
| `alembic upgrade ... --sql` | renders offline, reviewed above |
| `alembic current` | `0006` — 0007 unapplied, as intended |
| Secret sweep of tracked files (`re_`, `whsec_`, inbox id) | no real values |
| `.env` and the backup both gitignored | confirmed |
| admin `typecheck` / `lint` / `build` | clean (8 pre-existing react-refresh warnings, untouched files) |
| public site `typecheck` / `lint` / `build:all` | clean |
| Route registration | all four paths present in the OpenAPI schema |

---

## 9. What I need from you

1. ~~Approve migration 0007~~ — **done, applied and verified.**
2. **Commit and push** — not done. I have committed nothing; say the word.
3. **Register the webhook in Resend** once deployed, and **check the three
   Render vars** with the probe in §4.
4. **Turn off the Gmail forward** (§5) and **rotate the credentials** (§6).

One correction worth recording, since it was my own misreading: I had
`parse_received` discarding the HTML body whenever Resend reported
`html_format: data_uri`. The live API showed that flag describes how *inline
images* are encoded *inside* the markup, and that it reports `data_uri` even
for a message with no inline images at all — so that code would have thrown
away **every** HTML body. The fetch now asks for `cid` and the length cap
bounds the row instead. `test_html_body_is_kept_despite_the_data_uri_format_flag`
stops it coming back.
