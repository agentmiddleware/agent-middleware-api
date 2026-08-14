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
- `/404.html` — branded not-found page with links back into the site
- `/.well-known/agent.json` — marketing-origin pointer to API discovery
- `/.well-known/security.txt` — vulnerability-report contact (RFC 9116)
- `/llm.txt` and `/llms.txt` — machine bootstrap prose
- `/robots.txt` and `/sitemap.xml` — search discovery

`sitemap.xml` and `.well-known/security.txt` are rendered, not copied:
`@@BUILD_DATE@@` becomes the build date's `<lastmod>`, and
`@@SECURITY_TXT_EXPIRES@@` becomes one year past the build, so a deployed
`security.txt` never serves a lapsed `Expires`. Plain-text targets take the raw
contact value; HTML and XML targets take the entity-escaped one.

## Response headers and caching

`vercel.json` sends a `Content-Security-Policy` with `script-src 'self'` and no
`'unsafe-inline'`. Two files exist only to make that possible:

- `a11y-preload.js` — applies saved accessibility preferences before first
  paint. It is loaded **synchronously** in `<head>`; do not add `defer`.
- `va-init.js` — the Vercel Web Analytics queue shim, emitted only when
  `PUBLIC_ENABLE_VERCEL_ANALYTICS=true`.

If you ever add an executable inline `<script>` to a page, the CSP will block
it and `test_pages_carry_no_inline_scripts` will fail. Put the code in a
same-origin file instead.

CSS and JS are served with `max-age=604800`, so cache busting is a **manual
query token**: every reference looks like `/styles.css?v=gateway-2`. When you
change any of those files, bump the token in `index.html`, `proof/index.html`,
`404.html`, and `build_site.py`'s `ANALYTICS_SCRIPTS`, or returning visitors
keep the old bytes for up to a week. HTML itself carries no long-lived
`Cache-Control` rule and revalidates on every request.

`trailingSlash: true` makes `/proof` redirect to `/proof/`, matching the
page's `rel="canonical"`.

The proof page reads fields from `/proof/receipt.json`; it does not hard-code a
receipt ID, amount, or verification verdict. If either proof file is absent or
does not contain the receipt's matching key, the page says the artifact is not
published and makes no validity claim. Cryptographic validity comes only from
the offline verifier.

## Analytics

Vercel Web Analytics records page views and three non-PII event names:
`booking_click`, `email_click`, and `proof_click`. Event payloads never include
the email address, booking URL, receipt fields, or link destination.

The `/_vercel/insights/script.js` loader is emitted only when
`PUBLIC_ENABLE_VERCEL_ANALYTICS=true` is set at build time; the default build
omits it. The flag accepts exactly `true` or `false` (case-insensitive) or
being unset — any other value fails the build. Vercel serves that script only for projects whose Web Analytics is
enabled in the dashboard — deploying the tag without that produces a 404 plus
a MIME-type refusal in the browser console on every page load. Enable Web
Analytics for the Vercel project first, then set the environment variable.

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
