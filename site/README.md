# Agent Middleware API design-partner site

Static, human-buyer-first marketing and proof surface for the governed MCP
trust-plane wedge. The public site is `https://www.thisisatest.tech/`; the
canonical API is `https://api.thisisatest.tech/`.

The intended buyer is a platform engineering, AI infrastructure, or security
team operating internal MCP tools. Machine discovery remains available below
the one-tool pilot funnel and through the static pointer files.

## Launch gate

The deploy build refuses to emit `dist/` until all three values are provided:

- `PUBLIC_DISPLAY_NAME`: accountable public person or entity
- `PUBLIC_CONTACT_EMAIL`: monitored email address
- `PUBLIC_BOOKING_URL`: working absolute HTTPS booking URL

The builder rejects missing, unresolved, and obviously provisional values.
These inputs must still be exercised manually before production because syntax
validation cannot prove that a mailbox is monitored or a booking calendar works.

```bash
cd site
PUBLIC_DISPLAY_NAME="..." \
PUBLIC_CONTACT_EMAIL="..." \
PUBLIC_BOOKING_URL="https://..." \
python3 build_site.py
python3 -m http.server 8765 --directory dist
```

Open `http://127.0.0.1:8765/`.

## Public surfaces

- `/` — human design-partner funnel
- `/proof/` — portable receipt, matching key snapshot, and offline command
- `/.well-known/agent.json` — marketing-origin pointer to API discovery
- `/llm.txt` and `/llms.txt` — machine bootstrap prose
- `/robots.txt` and `/sitemap.xml` — search discovery

The proof page reads fields from `/proof/receipt.json`; it does not hard-code a
receipt ID, amount, or verification verdict. If either proof file is absent or
does not contain the receipt's matching key, the page says the artifact is not
published and makes no validity claim. Cryptographic validity comes only from
the offline verifier.

## Analytics

Vercel Web Analytics records page views and three non-PII event names:
`booking_click`, `email_click`, and `proof_click`. Event payloads never include
the email address, booking URL, receipt fields, or link destination. Analytics
must be enabled for the Vercel project before deploying the script.

## Deployment

Keep `vercel.json`; this change intentionally does not migrate configuration
formats. The linked Vercel project uses `site/` as its root directory and runs
the stdlib-only `python3 build_site.py` command before serving `dist/`. The
dependency-free `package.json` gives Vercel's static builder an explicit build
entrypoint; without it, a standalone JavaScript asset can be mistaken for the
entrypoint and the contact gate can be skipped.

The apex domain and known Vercel aliases redirect to
`https://www.thisisatest.tech/`. Marketing discovery redirects target the
custom API origin. The infrastructure provider hostname remains a compatibility
origin only and must not appear on customer-facing pages.
