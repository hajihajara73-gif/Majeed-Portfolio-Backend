# Google Search Console — setup guide

Written for Mohammed, to follow by hand. Nothing in this guide can be
automated: Google generates a verification token unique to the account, and it
has to be copied into Namecheap by someone signed in to both.

Allow about 20 minutes, plus waiting time for DNS.

**Search Console:** https://search.google.com/search-console

---

## Before you start

- [ ] Sign in to Google with the account you want to own this property
      long-term. Moving a property later means re-verifying.
- [ ] Have the Namecheap login ready.
- [ ] Deploy the current build first. The sitemap, the structured data and the
      new social card all ship with it, and there is no reason to have Google
      crawl the old version.

**Two warnings before you touch DNS.**

1. **Do not delete or edit any existing record.** The site and the API both
   depend on records already in there. You are *adding* one TXT record and
   changing nothing else. Specifically, leave alone: the `A` or `ALIAS` record
   for the apex, the `CNAME` for `www`, the `CNAME` for `api`, and anything
   that looks like `MX`, `SPF`, `DKIM` or `DMARC` (those are email — breaking
   them stops mail arriving).
2. **Do not paste the verification token into this repository**, a commit
   message, or a public issue. It is not a password, but it is not for sharing
   either.

---

## Step 1 — Open Search Console and add a Domain property

Go to https://search.google.com/search-console and click **Add property**.

You are offered two types. Choose the left-hand one:

| Type | Choose? | Why |
|---|---|---|
| **Domain** | **Yes** | Covers every subdomain and both `http` and `https` in one property — the apex, `www`, and `api`. Verified by DNS. |
| URL prefix | No | Covers exactly one origin. You would need separate properties for `https://` and `https://www.`, which splits the data for no benefit. |

Enter the domain with **no scheme and no `www`**:

```
mohammedmajeedportfolio.me
```

Click **Continue**.

---

## Step 2 — Copy the TXT record Google gives you

Google now shows a DNS TXT record and a value that looks like this:

```
google-site-verification=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

**That value is generated for your account. It is not in this repository and
nobody can tell you what it is — copy it from the screen.**

Click **Copy**. Leave the Search Console tab open; you come back to it in
Step 5.

---

## Step 3 — Add the record in Namecheap

1. Sign in at https://www.namecheap.com.
2. **Domain List** in the left sidebar, then **Manage** next to
   `mohammedmajeedportfolio.me`.
3. Open the **Advanced DNS** tab.
4. Read the existing records once before changing anything. You should see an
   `A` or `ALIAS` record for the apex pointing at Vercel, a `CNAME` for `www`,
   and a `CNAME` for `api` pointing at Render. **Leave every one of them
   exactly as it is.**
5. Click **Add New Record** and fill in:

   | Field | Value |
   |---|---|
   | Type | `TXT Record` |
   | Host | `@` |
   | Value | the `google-site-verification=...` string from Step 2 |
   | TTL | `Automatic` |

   `@` means the domain itself. Do not type the domain name into the Host
   field — Namecheap would turn it into
   `mohammedmajeedportfolio.me.mohammedmajeedportfolio.me`.

6. Click the green tick to save the row, then **Save All Changes**.

> If a TXT record on `@` already exists for something else, **add a second
> one** rather than editing the first. A domain can hold many TXT records, and
> overwriting an existing one could break email or another service's
> verification.

---

## Step 4 — Wait for DNS to propagate

Namecheap usually publishes within a few minutes; it can take up to an hour,
occasionally longer.

Check from your machine before going back to Google:

```bash
nslookup -type=TXT mohammedmajeedportfolio.me 8.8.8.8
```

You are waiting to see your `google-site-verification=...` string in the
output. Asking `8.8.8.8` specifically matters — it is Google's own resolver,
which is roughly what Search Console will consult.

---

## Step 5 — Verify

Back in the Search Console tab, click **Verify**.

- **Success** — the property is created. Move to Step 6.
- **Failure** — almost always propagation, not a mistake. Wait 15 minutes and
  click Verify again. If it still fails after an hour, re-check Step 3: Host is
  `@`, the value is the complete string including the
  `google-site-verification=` prefix, and nothing was truncated on paste.

Google re-checks this record periodically. **Leave it in place forever** —
deleting it later un-verifies the property.

---

## Step 6 — Submit the sitemap

In the left sidebar: **Indexing**, then **Sitemaps**.

Under *Add a new sitemap*, enter just the path:

```
sitemap.xml
```

Click **Submit**.

Expected status: **Success**, with **1 discovered URL**. One is correct — the
site is a single page with hash-anchor navigation, so one URL is the honest
answer. Anything else would be invented.

If it says *Couldn't fetch*, open https://mohammedmajeedportfolio.me/sitemap.xml
in a browser first. If that loads, the error is usually Google not having
retried yet; give it a day before worrying.

---

## Step 7 — Inspect the homepage

Paste this into the search bar at the very top of Search Console:

```
https://mohammedmajeedportfolio.me/
```

Press Enter. Google reports what it currently knows.

Then click **TEST LIVE URL** (top right). This is the important one: it fetches
and renders the page right now, rather than reporting a possibly stale crawl.

When the test finishes, check three things:

1. **Availability** — "URL is available to Google".
2. **View tested page**, then the **Screenshot** tab. The rendered page should
   look like the real site. The site is React-rendered, so this is the direct
   confirmation that Googlebot can execute the JavaScript and see all eight
   sections. If the screenshot is blank, that is the single most important
   problem on the site and everything else waits.
3. **View tested page**, then the **HTML** tab. Search it (Ctrl+F) for
   `application/ld+json`. The Person, WebSite and ProfilePage block should be
   there.

---

## Step 8 — Request indexing

On the same URL Inspection screen, click **Request indexing**.

Do this **once**. Repeatedly resubmitting the same URL does not help, does not
speed anything up, and is explicitly discouraged by Google.

Then wait. Indexing a new site commonly takes **a few days to a few weeks**.
That is normal and not a sign anything is wrong.

---

## Step 9 — Also inspect these

Worth checking once each, for different reasons:

| URL | What you are checking |
|---|---|
| `https://mohammedmajeedportfolio.me/robots.txt` | Loads, and allows `/`. |
| `https://mohammedmajeedportfolio.me/sitemap.xml` | Loads and lists the apex URL. |
| `https://www.mohammedmajeedportfolio.me/` | **Expect this to fail** — see the warning below. |
| `https://mohammedmajeedportfolio.me/admin/` | Should report it is **excluded by `noindex`**. That is correct and deliberate. |

> ### The `www` problem — fix this before you verify
>
> `www.mohammedmajeedportfolio.me` **does not currently work in any browser.**
> DNS resolves and the redirect is configured, but the TLS certificate does not
> cover the `www` name, so the connection fails before the redirect is read.
> Because the apex sends `Strict-Transport-Security` with `includeSubDomains`,
> there is no fallback — anyone who has visited the site once is locked to
> HTTPS on `www` too.
>
> **To fix:** Vercel dashboard, your project, **Settings**, **Domains**, then
> **Add** `www.mohammedmajeedportfolio.me`. Vercel will issue a certificate
> covering it and apply the redirect to the apex. It usually takes a few
> minutes. No Namecheap change is needed — the DNS is already correct.
>
> Worth doing before Step 5, because a Domain property covers `www` and you
> would rather Google find it working.

---

## Step 10 — Monitoring

Nothing useful appears for a few days. After that, see `SEO-MONITORING.md` for
what to look at and how often.

The two reports that matter:

- **Indexing, then Pages** — is the homepage indexed, and if not, what reason
  does Google give?
- **Performance** — which queries the site appears for, how often, and at what
  position. This is the only genuine keyword data the project will ever have;
  `SEO-KEYWORD-STRATEGY.md` is guesswork until it arrives.

---

## Troubleshooting

Statuses you may see under **Indexing**, then **Pages**, and what each actually
means.

| Status | What it means | What to do |
|---|---|---|
| **Discovered — currently not indexed** | Google knows the URL but has not crawled it. Usually a queue, on a new site with no inbound links. | Wait. Get a real link from the GitHub profile README and the LinkedIn Featured section. Do not resubmit repeatedly. |
| **Crawled — currently not indexed** | Crawled, and Google chose not to index. Usually a value judgement about thin or duplicate content. | Fill the remaining `TODO_REPLACE_*` content, especially the Career dates. Consider the articles in `SEO-CONTENT-STRATEGY.md`. This is the status that would justify revisiting prerendering. |
| **Duplicate without user-selected canonical** | Google found several URLs with the same content and no canonical. | Should not happen — a canonical link is emitted on every build. Check the page really has `<link rel="canonical">`. |
| **Alternate page with proper canonical** | Google saw a URL that correctly points elsewhere. | Normal and fine. This is what `www` should report once its certificate is fixed. |
| **Blocked by robots.txt** | Something in `robots.txt` disallows the URL. | Only `/admin/` is disallowed, which is intended. If the homepage ever shows this, check the deployed `robots.txt` immediately. |
| **Page with redirect** | The URL redirects. | Expected for `http://` and for `www`. Not a problem. |
| **Server error (5xx)** | Google got an error. | Check Vercel's deployment status. The site is static, so this should be rare. |
| **Soft 404** | The page looks empty to Google. | On a React site this usually means rendering failed. Re-run Step 7 and look at the screenshot. |
| **Sitemap could not be read** | Fetch or parse failure. | Open the sitemap URL in a browser. If it loads, wait a day and recheck. |

**Mobile usability.** Measured directly on 2026-11-04 at 390, 768, 1024 and
1440 pixels: no horizontal overflow at any width, 17px body text, console
silent. If Search Console later reports a mobile problem, it will be something
new rather than something known and ignored.
