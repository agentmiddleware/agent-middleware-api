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

- `/` — human design-partner funnel; the hero renders the particle-wave
  field from `/wave.js` (plain WebGL, no libraries) and pauses it once
  scrolled out of view
- `/proof/` — portable receipt, matching key snapshot, and offline command
- `/compare/` — named competitor comparison, build-vs-buy, and fit/compliance FAQ
- `/concept/` — unlisted landing-page design study (noindex, absent from the
  sitemap, never linked from the funnel): the single-fold treatment the
  homepage hero was promoted from, kept as the archived study. It shares
  `/wave.js` with the homepage; the renderer honors the a11y widget's
  reduced-motion and high-contrast preferences and degrades to a static CSS
  backdrop without JavaScript or WebGL
- `/404.html` — branded not-found page with links back into the site
- `/.well-known/agent.json` — marketing-origin pointer to API discovery
- `/.well-known/security.txt` — vulnerability-report contact (RFC 9116)
- `/llm.txt` and `/llms.txt` — machine bootstrap prose
- `/llms-full.txt` — long-form machine brief: boundary, vocabulary, non-claims
- `/fonts.css` and `/fonts/*.woff2` — self-hosted typography
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
query token**: every reference looks like `/styles.css?v=gateway-4`. When you
change any of those files (including `/wave.js`), bump the token in
`index.html`, `proof/index.html`, `compare/index.html`, `concept/index.html`,
`404.html`, and `build_site.py`'s `ANALYTICS_SCRIPTS`, or
returning visitors
keep the old bytes for up to a week. HTML itself carries no long-lived
`Cache-Control` rule and revalidates on every request. The concept page's own
stylesheet uses an independent `?v=concept-N` token: bump it when
`concept/concept.css` changes.

Explicit `/proof` → `/proof/` and `/compare` → `/compare/` redirects match
those pages' `rel="canonical"`. Every directory page needs its own entry. Do **not** replace it with the global `trailingSlash: true`
setting: on Vercel that makes every `/.well-known/*` entry in `headers` stop
matching, so `agent.json` and `security.txt` silently fall back to
`max-age=0, must-revalidate` while every other configured path keeps its
headers. Confirmed on the deployed site.

The proof page reads fields from `/proof/receipt.json`; it does not hard-code a
receipt ID, amount, or verification verdict. If either proof file is absent or
does not contain the receipt's matching key, the page says the artifact is not
published and makes no validity claim. Cryptographic validity comes only from
the offline verifier.

## Typography

Fonts are **self-hosted**, not loaded from Google. A third-party font CDN costs
two cross-origin handshakes on the critical path — `fonts.googleapis.com` for
the CSS, then `fonts.gstatic.com` for the files — and puts an outside party
between a visitor and a page whose whole pitch is that you can verify things
yourself. Serving them here also lets the CSP stay `style-src 'self';
font-src 'self'` with no external host.

`fonts/` and `fonts.css` are **generated**. To add a family or weight, edit
`FAMILIES` in `vendor_fonts.py`, then:

```bash
cd site
python3 vendor_fonts.py          # refetch and rewrite fonts/ + fonts.css
python3 vendor_fonts.py --check  # verify the committed output matches upstream
```

Only `latin` and `latin-ext` are vendored, and each face keeps upstream's
`unicode-range`, so a browser downloads only the subsets a page actually uses.
Libre Franklin and Public Sans are variable fonts: one file per subset serves
every weight, which is why their filenames carry no weight.

All three families are OFL 1.1, and `fonts/OFL.txt` carries the **full license
text**, not a link to it — plain text so the notice deploys alongside the fonts
it covers. The bare-link shortcut the OFL FAQ tolerates applies to fonts
embedded in a document or bundled inside a program; serving `/fonts/*.woff2` as
standalone files is plain redistribution, so condition 2 applies in full. The
copyright lines are verbatim from each family's upstream `OFL.txt` — including
the Reserved Font Name on IBM Plex, which the other two do not reserve.

Filenames carry a content hash, so `vercel.json` serves `/fonts/*.woff2`
`immutable` for a year and a re-vendored font can never be served stale. The
stylesheet's own cache key is generated the same way — `@@FONTS_CSS_VERSION@@`
becomes a digest of `fonts.css` at build time. It must not become a manual
token: a visitor holding a week-old `fonts.css` would request the hashed woff2
files that re-vendoring has already deleted, and get 404s until it expired. That
also means preloads cannot be hand-written: `vendor_fonts.py` emits
`fonts.manifest.json`, and `build_site.py` expands `@@FONT_PRELOADS@@` in each
page from it. Edit `PRELOAD` in `vendor_fonts.py` to change which faces are
preloaded.

Preloads cover every face in the first viewport. Public Sans and Libre Franklin
are variable, so one file each is enough; IBM Plex Mono is static, so weights
400 (nav links), 500 (section kickers) and 600 (nav brand) are three separate
files and all three are preloaded. Instrument Serif renders the homepage
hero headline, so its single 400 face is preloaded too — the manifest is
shared by every page, so subpages pay its ~21KB once rather than letting
the landing headline flash Georgia and reflow. A preload must carry `crossorigin` even
same-origin, or the browser discards it and fetches the file twice. The `404`
page preloads nothing on purpose — it is `noindex` and mostly serves scanners.

Adding a family or weight to `styles.css` without adding it to `FAMILIES` fails
`test_font_stylesheet_and_files_agree` rather than letting the browser
synthesise the weight. An interrupted vendoring run that empties `fonts/` fails
the launch gate rather than deploying a stylesheet whose every `src` 404s.

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
