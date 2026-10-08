# BREAK-REPORT: launch preflight (app/services/preflight.py + router)

## Summary

Probed the launch readiness preflight (`POST /v1/launch/preflight` and
`PreflightEngine`) with adversarial inputs: blank and malformed URLs,
placeholder key variants, Stripe lookalikes, auth bypass attempts, and
verdict semantics. Local tests only, no network calls, no production use.

Counts: 6 breaks found, 6 fixed and tested, 0 fixed but failing, 3 blocked
(coverage gaps that need an owner decision, listed at the end).

Auth held up: the endpoint requires a key (401 without one), refuses unknown
keys (403), and refuses wallet-scoped tenant keys before the sweep runs
(existing tests cover this; re-verified green). The engine is stateless per
request, so no concurrency race was found. Malformed JSON types are rejected
by request validation with 422.

## Finding 1 (high): blank URLs pass critical checks

What broke: calling the engine with `base_url: ""` or
`campaign_source_url: ""` (or whitespace) returned `passed: True` on the
critical `base_url_valid`, `manifests_resolvable`, and `content_source_url`
checks. A whitespace-only `base_url` also passes through the router, because
the router only filters out the empty string.

How to reproduce: `await PreflightEngine().run({"base_url": "   "})` then
inspect the `base_url_valid` check; or POST
`/v1/launch/preflight` with `{"base_url": "   "}` and an admin key.

Root cause: `app/services/preflight.py`, `_is_placeholder_domain` used a
substring test (`if domain in url_lower`), which is False for blank input,
so blank input read as a real domain.

Fix: `_is_placeholder_domain` now parses the URL host and fails closed on
blank or unparsable values.

Test results: new tests `test_preflight_rejects_blank_base_url`,
`test_preflight_rejects_blank_campaign_source_url`, and
`test_engine_rejects_empty_string_overrides` fail on old code and pass on
new code. Full file: 28 passed.

## Finding 2 (high): placeholder key variants pass as production keys

What broke: `VALID_API_KEYS` values such as `test-key-xyz123`,
`changeme-prod`, `placeholder1`, `xxxabc`, and `my-test-key` were reported
as production keys, so a deployment still on obvious test keys could get a
clean bill of health on the key check.

How to reproduce: set `VALID_API_KEYS` to `test-key-xyz123,<real key>` and
POST `/v1/launch/preflight` with the real key; the
`api_keys_not_placeholder` check passed on old code.

Root cause: `app/services/preflight.py`, `PLACEHOLDER_PATTERNS` used
end-anchored patterns (`^changeme$`, `^placeholder$`, `^test[-_]?key$`),
so any trailing characters defeated detection, and infixed values were
never matched.

Fix: patterns now match prefixes, plus a whole-token check that flags
placeholder stems (`test`, `changeme`, `placeholder`, `todo`, `replace`,
`example`, `xxx...`) anywhere in the key. Whole-token matching keeps random
keys such as `contest-key-9f31ab` and `latest-key-44c1` passing.

Test results: new tests `test_preflight_rejects_suffixed_placeholder_keys`,
`test_preflight_rejects_infixed_placeholder_key`, and
`test_placeholder_detector_spares_real_keys` fail on old code (except the
spare-real-keys guard, which holds on both) and pass on new code. No key
material is echoed in any message (existing no-echo test still green).

## Finding 3 (medium): bare `sk_live_` prefix accepted as a live Stripe key

What broke: a `stripe_secret_key` of exactly `sk_live_` (prefix, no secret)
passed the `stripe_key_live` check.

How to reproduce: POST `/v1/launch/preflight` with
`{"stripe_secret_key": "sk_live_"}`; the check passed on old code.

Root cause: `app/services/preflight.py`, `_looks_like_live_stripe_key`
tested only the prefix.

Fix: the key must also be at least 16 characters long after stripping.

Test results: new test `test_preflight_rejects_bare_live_stripe_prefix`
fails on old code and passes on new code. The existing live-key test value
(20 chars) still passes.

## Finding 4 (medium): real domains containing placeholder letters flagged

What broke: `https://api.notexample.com` and `https://myexample.com` were
reported as placeholder domains, a false critical failure that could block
a legitimate launch.

How to reproduce: POST `/v1/launch/preflight` with
`{"base_url": "https://api.notexample.com"}`; `base_url_valid` failed on
old code.

Root cause: same function as Finding 1, `app/services/preflight.py`
`_is_placeholder_domain` matched substrings instead of hosts.

Fix: same change; the host must equal a placeholder domain or be a
subdomain of one (`api.yourdomain.com` is still flagged, verified by the
no-change guard test `test_preflight_still_flags_placeholder_subdomain`).

Test results: new test
`test_preflight_accepts_domain_containing_placeholder_letters` fails on old
code and passes on new code.

## Finding 5 (low): uppercase HTTPS scheme spuriously warned

What broke: `HTTPS://api.myrealdomain.com` failed the `base_url_https`
check even though it uses TLS.

Root cause: `app/services/preflight.py`, `_check_base_url` compared the
scheme case-sensitively.

Fix: the scheme check strips and lowercases before comparing.

Test results: new test `test_preflight_accepts_uppercase_https_scheme`
fails on old code and passes on new code.

## Finding 6 (low): report wording implied checks that never run

What broke: passing messages said "Manifests will serve at ..." and
"directory targets validated", but the engine never fetches anything; it
only validates URL shape. A GO can therefore precede a launch that fails
on unreachable manifests or directories (the pass-then-fail shape).

How to reproduce: read any passing report on old code; no message
disclosed that reachability is unchecked.

Root cause: `app/services/preflight.py`, `_check_manifest_urls` and
`_check_oracle_targets` messages.

Fix: passing messages now say URL formats were validated and reachability
was not checked. Check names are unchanged. Live reachability probing is
left as an open question below because it needs network access and owner
approval.

Test results: new test `test_preflight_states_reachability_not_checked`
fails on old code and passes on new code.

## Verification

- `pytest tests/test_preflight.py -q`: 28 passed (17 pre-existing, 11 new).
- Old-code proof: replayed every new assertion against the HEAD version of
  the helpers (via a throwaway script in /tmp, worktree untouched); all 12
  break-catching assertions fail on old code while the no-change guards
  (real keys spared, `api.yourdomain.com` still flagged) hold on both.
- `ruff check` on both changed files: clean. `ruff format`: applied
  (confined to added lines), tests re-run green.
- `mypy app/services/preflight.py`: no issues.

## Blocked / needs an owner decision (not changed)

1. Partial preflight: overrides cover only `base_url`, `stripe_secret_key`,
   and `campaign_source_url`. API keys, DEBUG, and rate limit always come
   from live settings, so a staged config cannot be dry-run without
   mutating the environment. Threading dry-run overrides through is a small
   change but widens the API and risks misleading GOs; left for Christopher.
2. Missing tool in catalog: the engine never consults the tool catalog, so
   a launch with a missing or misconfigured tool still gets GO. Adding a
   catalog check is a new capability and needs customer evidence first.
3. Sandbox flag bypass: preflight has no sandbox concept and env-backed
   checks cannot be staged per request. Same decision as above.

## Open questions

1. Should live reachability probing (fetch manifests and directory URLs)
   become an opt-in preflight mode, or stay out to keep preflight
   network-free?
2. Should any warning (DEBUG on, plain HTTP, test Stripe key) block GO
   instead of producing CONDITIONAL GO?
3. Should dry-run overrides for API keys, DEBUG, and rate limit be added
   to the request schema?
