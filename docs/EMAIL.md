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
