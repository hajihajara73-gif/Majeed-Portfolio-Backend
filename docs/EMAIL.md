# Contact notification email

How a message from the public contact form reaches an inbox, what happens when
that fails, and how to set it up.

---

## 1. The shape of it

```
visitor -> contact form -> FastAPI
                             |
                    1. validate and sanitise
                    2. SAVE TO POSTGRES  <-- committed here
                    3. return 200 to the visitor
                             |
                    4. background task -> Resend -> your inbox
                    5. record the delivery status on the message
```

**Steps 2 and 4 are independent, and the order is the point.** The message is
committed before anything is emailed, and the send runs *after* the response.
A Resend outage therefore means you were not emailed — never that the
visitor's message was rejected or lost. The outcome of step 5 is stored, so a
failure is visible in the admin and can be retried.

That ordering is the single most important property of this feature. If you
change one thing here, do not change that.

---

## 2. Setting it up

### Resend

1. Create an account at <https://resend.com>.
2. **Domains → Add Domain.** Use a subdomain — `mail.your-domain.example` —
   rather than the apex. A sending subdomain keeps the DNS for mail separate
   from the DNS for the website, so a mail record can never interfere with
   the records that serve the site.
3. Add the TXT, MX and DKIM records Resend gives you at your registrar
   (Namecheap → Advanced DNS). Wait for Resend to show **Verified**.
4. **API Keys → Create API Key.** Choose **Sending access**, not full access.
   A send-only key cannot read your account, and sending is all this needs.
   Copy it once — Resend will not show it again.

### The application

In `backend/.env` — which is gitignored, and is the only place a real key
belongs:

```
RESEND_API_KEY=re_...
EMAIL_FROM=Majeed <contact@mail.your-domain.example>
ADMIN_EMAIL=you@gmail.com
ADMIN_DASHBOARD_URL=https://your-domain.example/admin
SEND_VISITOR_CONFIRMATION=false
```

On Render: **Environment → Add Environment Variable** for each, then redeploy.

`ADMIN_EMAIL` is a destination address, not a login. Admin accounts live in
the database and are managed with `python -m app.cli create-admin`.

### The migration

The delivery columns arrive in `0005_contact_email_delivery`:

```bash
cd backend && python -m alembic upgrade head
```

Purely additive — six columns and an index on `contact_messages`. Nothing
existing is rewritten. Rows that predate the feature are backfilled to
`disabled` rather than `pending`, so historical messages do not appear in the
retry queue.

**Until this runs, submitting the form returns 500**: the application writes
columns the table does not have yet.

---

## 3. Checking it works

```bash
cd backend
python scripts/send_test_email.py          # dry run — sends nothing
python scripts/send_test_email.py --send   # actually sends
```

Safe by default: without `--send` it renders the templates, prints where the
mail would go, and exits. The API key is never printed; the script shows the
first and last few characters so you can tell which key is loaded without the
value appearing in a terminal or a screenshot.

Then send a real one through the form and check three things in your inbox:

1. the subject reads `New Portfolio Message - <their subject>`;
2. the body carries the name, address, subject, message and timestamp;
3. **pressing Reply addresses the visitor**, not `contact@...`. That is the
   `Reply-To` header, and it is the feature that makes the inbox useful.

### If the send fails

The message is still saved — look in the admin, it will be there, marked
**email failed** with Resend's own reason. Common causes:

| Symptom | Cause |
|---|---|
| `domain is not verified` | DNS not finished, or the From domain differs from the verified one |
| `401` / `restricted` | key revoked, from another account, or lacking send permission |
| `CERTIFICATE_VERIFY_FAILED` | local only — a TLS-intercepting proxy or antivirus whose CA is not in Python's bundle. Does not occur on Render. |

---

## 4. Retrying

Open the message in the admin and press **Retry notification**. The admin also
shows a banner counting failed notifications.

**Pressing it twice is safe.** A retry refuses to send when a Resend id is
already recorded, so a second click reports the existing delivery instead of
putting a second copy in your inbox. The likeliest cause of a duplicate email
is an impatient second click, so that is the case guarded against.

---

## 5. Delivery states

Stored on each message as `email_delivery_status`:

| State | Meaning |
|---|---|
| `pending` | saved, not yet attempted. Also where a message sits if the process died between the commit and the send — visible, and retryable. |
| `sent` | Resend accepted it and returned an id, kept in `resend_email_id` |
| `failed` | Resend refused or was unreachable; `email_error` says why |
| `disabled` | no email configured, so nothing was attempted |

`sent` means Resend accepted the message, which is not the same as it reaching
the inbox — delivery after that is between Resend and the receiving server.

---

## 6. Security

- **The API key is backend-only.** It is read from the environment, never
  returned by the API, and never logged. Only `str(error)` is recorded from a
  failure, because an SDK exception can carry the request it was built from,
  and that includes the `Authorization` header. There is a test for this.
- **Everything the visitor typed is HTML-escaped** before it reaches the
  template. The body arrives at an unauthenticated endpoint; interpolating it
  raw into an email is the same injection bug as interpolating it into a page.
  There is a test for this too.
- **The From header is sanitised.** CR, LF and NUL are stripped, because those
  are what split one mail header into two.
- **The visitor is never the From address.** Sending as their domain fails SPF
  and DMARC and gets the mail classified as spoofing.
- **Rate limiting is unchanged** and predates this feature: 5 per hour and 20
  per day per IP, plus a honeypot field. Email is only ever sent for a message
  that got past those.
- **Contact messages are never exposed publicly.** Every read is behind the
  admin session and CSRF check; the public endpoint only writes.

---

## 7. The visitor acknowledgement

Off by default. With `SEND_VISITOR_CONFIRMATION=true` the visitor also gets a
short acknowledgement.

It is deliberately vague about timing — it says a reply will come, not when,
because that is a promise the software cannot keep. Its failure is never
recorded against the message and never changes the delivery status: it is a
courtesy, and failing to send it is not a failure to notify you.

Before switching it on, note it doubles send volume and makes the form a
potential vector for sending mail to an address somebody else typed. The rate
limit is what keeps that bounded.

---

# Part 2 — Replying from the admin

## 8. What a reply does

Open a message in the admin and the conversation opens with it: the original
enquiry, then every reply, oldest first. Outbound messages are indented and
tinted; inbound are flush and plain. The shape tells you who spoke before you
read a word.

Writing in the composer and pressing **Send reply** (or Ctrl+Enter):

```
reply text -> row written as `pending`
           -> sent via Resend from the verified domain
           -> row updated to `sent` with the Resend id, or `failed` with why
```

**The row is written before the send**, for the reason the contact form
commits before notifying: if Resend refuses, the admin must still see that a
reply was attempted and what went wrong, rather than losing the text just
typed. A failed reply is **not** an error response — it comes back `200` with
`status: failed`, the text stays in the box, and the timeline shows the
failure.

`contact_messages.replied_at` — present and unused since the table was created
— is finally populated, by the **first** reply only. It means *has been
answered*, not *answered most recently*.

## 9. Threading

Each reply sets three RFC 5322 headers, which Resend passes through verbatim:

| Header | Value |
|---|---|
| `Message-ID` | freshly minted, on the sending domain |
| `In-Reply-To` | the previous message in the thread |
| `References` | the accumulated chain, capped at 20 entries |

That is what lets Gmail and Outlook group the exchange. `References` matters
more than it looks: clients walk the whole chain to group a thread, and
dropping it is why replies sometimes appear detached.

Subjects get one `Re: ` and only one — `Re: Re: Re:` is checked for and
prevented, case-insensitively.

## 10. Where a visitor's reply goes

Controlled by `CONTACT_INBOUND_ADDRESS`, and the switch is deliberate:

| Setting | Reply-To | Effect |
|---|---|---|
| **unset** | `ADMIN_EMAIL` | replies land in your own inbox |
| **set** (today) | that address | replies return through Resend into the timeline |

One variable moves both halves, which is why there is no second switch to
forget. Setting it changes where Reply-To points *and* turns the inbound
pipeline on, so the two can never disagree.

**Do not set it until inbound is actually live.** Pointing Reply-To at an
address that is not receiving mail bounces every reply a visitor sends —
strictly worse than letting them land in your own inbox. It is live now;
Part 3 is how.

# Part 3 — Receiving a visitor's reply

Both blockers from the previous revision of this document are resolved. A
read-capable key exists, and receiving runs on a **Resend-hosted inbox
address** rather than a subdomain of your own — which means **no DNS change
was needed and none was made**. The sending domain
`mail.mohammedmajeedportfolio.me` is untouched.

## 11. How a reply gets back in

```
visitor hits Reply
      |
      v
CONTACT_INBOUND_ADDRESS  (a Resend-hosted inbox, no MX records of ours)
      |
      v
Resend fires `email.received`  -- METADATA ONLY, no body
      |
      v
POST /api/public/webhooks/resend
      |
      +-- 1. svix signature over the RAW bytes          -> 401 if it fails
      +-- 2. timestamp within 5 minutes                 -> 401 if stale
      +-- 3. already stored? (Resend id)                -> 200, no-op
      +-- 4. fetch the body with the READ key
      +-- 5. already stored? (RFC Message-ID)           -> 200, no-op
      +-- 6. match on In-Reply-To / References ONLY     -> 200, dropped if none
      |
      v
row in `email_messages` (direction='inbound', delivery_status='received')
parent contact_message marked unread again
      |
      v
admin timeline
```

## 12. Why the webhook answers 200 so often

Resend retries a delivery until it gets a 2xx. So a non-2xx is a promise to
try again, and should only be given when retrying could actually help.

| Situation | Status | Why |
|---|---|---|
| Stored successfully | 200 | Done. |
| Duplicate delivery | 200 | Expected in normal operation, not an error. |
| Event we do not handle | 200 | Retrying will never make us handle it. |
| Body could not be fetched | 200 | A missing read key will not fix itself; it is in the log. |
| No matching conversation | 200 | A decision, and the right one. See §14. |
| Malformed payload | 200 | Already-signed nonsense; retrying sends the same nonsense. |
| Bad or missing signature | 401 | Either a forgery, or a secret mismatch worth fixing. |
| Stale timestamp | 401 | Replay protection. |
| No webhook secret configured | 503 | A deployment fault. Worth retrying after it is fixed. |
| Body over 1 MB | 413 | A signed webhook is never this large. |

The one thing it will not do is return 500, because that turns a single bad
email into an indefinite retry loop.

## 13. Verification is against the raw bytes

`resend.Webhooks.verify()` signs `{svix-id}.{svix-timestamp}.{body}` with
HMAC-SHA256. The body is the **exact bytes received** — the route reads
`await request.body()` before anything parses JSON.

This is not a style preference. Parsing and re-serialising changes whitespace
and key order, so the signature would never match; and verifying a
re-serialised body would be verifying something other than what arrived.
`test_tampered_body_is_rejected` is the test that fails if anyone reorders
those two steps.

The SDK implements svix verification directly, with a five-minute tolerance
and **no `svix` dependency**.

## 14. Matching, and why an unmatched email is dropped

A reply joins a conversation **only** through `In-Reply-To` and `References`.
Those name Message-IDs that this system minted and stored, so a match is
evidence that the sender is replying to something we actually sent.

`From`, `Reply-To` and `Subject` are **never** used. All three are supplied by
the sender and trivially forged. If matching fell back to them, anyone who
guessed a visitor's address and a subject line could write into that
visitor's thread. `test_forged_sender_cannot_join_a_conversation` pins this.

The consequence is that mail replying to nothing we sent is **logged and
dropped**, not stored. Attaching it to the nearest-looking conversation is
exactly how a stranger's mail ends up in somebody else's thread.

A real consequence worth knowing: **a visitor who composes a fresh email to
the inbound address instead of pressing Reply will not appear anywhere.** It
has no threading headers, so there is nothing to match it to. This is the
intended trade and the honest one, but it does mean the inbound address is
not a general-purpose mailbox.

## 15. Attachments

Attachment **metadata** is stored — sanitised filename, declared type, byte
size, Resend's id, and whether it is inline. The **bytes are never stored**,
and no download URL is ever saved or serialised.

Downloading goes through `GET /api/admin/messages/{id}/attachments/{aid}`,
which requires an admin session and applies three checks:

1. The attachment id must belong to a message **on that conversation**.
   Without this, an authenticated caller could walk ids across threads. The
   answer for a foreign id is 404, not 403 — 403 would confirm it exists.
2. Type and size are re-checked against **Resend's** metadata at download
   time, not read from the stored row. The row records what the *sender*
   claimed, and a sender's claim should not authorise a download.
3. The bytes are counted as they arrive and the connection dropped past
   `INBOUND_ATTACHMENT_MAX_BYTES`. A `Content-Length` is the remote end's
   word, so only counting catches a response that lies.

Resend's temporary signed URL is fetched **server-side and never disclosed**.
Handing it to the browser would publish an unauthenticated link to private
mail. The response is always `Content-Disposition: attachment` with
`X-Content-Type-Options: nosniff`, so nothing from an inbound email is ever
rendered in the admin's own origin.

The type list is an **allowlist** (`ALLOWED_ATTACHMENT_TYPES`), so a type
nobody thought about is refused rather than permitted. Executables are absent
by design, not blocked by name.

A blocked attachment is still **listed in the timeline, with the reason**.
Hiding it would leave you wondering why a sender said "see attached" and
nothing was there.

## 16. SPF, DKIM, DMARC

Resend's verdicts are stored on the row and shown in the timeline **only when
something did not pass**. A green tick on every message trains people to stop
reading it; a warning that appears rarely gets read.

They are never used to decide which conversation a message joins. That is
what the threading headers are for.

## 17. Inbound HTML is stored and never served

`html_body` is kept on the row for the record. It is **not** in the thread
API's response and never reaches the browser — the timeline renders the plain
text part, escaped like any other string. A message with no plain part gets
its tags stripped to produce readable text.

One correction worth recording, because it is easy to get backwards:
`html_format` in Resend's response describes how **inline images** are encoded
*inside* the markup (`data_uri` means base64 is embedded in it). It is **not**
a statement that the body is a data URI, and the API reports `data_uri` even
for a message with no inline images at all. Treating it as "this is not
markup" silently discards every HTML body. The fetch asks for `cid` instead,
which keeps those images out of the string; the length cap is what actually
bounds the row.

## 18. The two keys

| Variable | Scope | Used for |
|---|---|---|
| `RESEND_API_KEY` | send-only | Sending notifications and replies. |
| `RESEND_READ_API_KEY` | read | Fetching inbound bodies and attachments. |

Kept separate on purpose: if the sending key leaks it still cannot read the
mailbox. `inbound_email.fetch()` swaps the read key in for the duration of a
single call and restores the sending key in a `finally`, so a failure cannot
leave the wrong key in place and a read can never widen what sending can do.
`test_fetch_uses_the_read_key_and_restores_the_send_key` asserts both halves.

## 19. Setting it up

Done already, recorded for the next time:

1. **Resend → create a second API key with full access.** A sending-only key
   gets 401 on `/emails/receiving`; this was verified rather than assumed.
2. **Resend → Inbound** gives a hosted address of the form
   `<id>@<name>.resend.app`. Using it means **no MX records and no DNS
   change** — which is why the sending domain was never at risk. A custom
   receiving subdomain is still possible later; it would need its own MX
   records and must not reuse the sending domain's.
3. **Resend → Webhooks → Add Endpoint** at
   `https://<your-api-host>/api/public/webhooks/resend`, subscribed to
   `email.received`. Copy the `whsec_` signing secret.
4. **Render → Environment**: set `CONTACT_INBOUND_ADDRESS`,
   `RESEND_READ_API_KEY` and `RESEND_WEBHOOK_SECRET`. Leave `RESEND_API_KEY`
   alone.
5. **Apply migration 0007** before deploying the code. The model declares
   `attachments` and `auth_results`; without the migration every query
   against `email_messages` fails with `UndefinedColumn`, which takes the
   admin inbox down. Order matters here.

### Checking it is configured, without printing the secret

```
curl -i -X POST https://<your-api-host>/api/public/webhooks/resend
```

- `401 invalid_signature` — the secret **is** set. The endpoint is live and
  refusing an unsigned request, which is correct.
- `503 webhook_not_configured` — the secret is **not** set.

Neither answer discloses anything. This is the check to use, rather than
reading the value back out of Render.

### One thing to clean up

The Resend inbox already contains a **Gmail forwarding confirmation**, which
means Gmail→Resend forwarding was set up at some point. It is **not needed**:
Reply-To now points at the inbound address directly, so a visitor's reply
goes to Resend without Gmail in the path. Leaving the forward on means
unrelated Gmail mail also arrives at the inbound address, where it will be
dropped for having no matching conversation — harmless, but noise in a
mailbox that should only ever hold replies. Turn it off in Gmail →
Settings → Forwarding.
