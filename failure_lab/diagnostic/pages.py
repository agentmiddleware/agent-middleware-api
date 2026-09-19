"""HTML for the Agent Action Safety Check.

Deliberately plain. The page is the output of a measurement, and a measurement
that arrives wrapped in persuasion invites the reader to discount it. There is
no hero, no logo wall, no testimonial, no urgency, and no place to put one:
:func:`render_result` has no slot a marketing string could be threaded into,
because the sections it renders are derived from
:class:`~failure_lab.diagnostic.answer.DiagnosticAnswer`.

Three rules the templates enforce rather than merely observe:

* **No score.** Not a percentage, not a grade, not a gauge. Counts of things a
  named instrument counted, and nothing derived from them.
* **The bad news is above the fold.** A failed gateway guarantee renders in the
  first block on the page, before the headline's supporting detail and before
  anything the gateway did well in the same run.
* **A signature is never shown as proof of execution.** The verification block
  renders three separate claims with three separate statuses, and says in words
  what each one does and does not establish.
"""

from __future__ import annotations

import html
from typing import Any

from failure_lab.diagnostic.answer import Answer, DiagnosticAnswer, ScenarioRow
from failure_lab.verifier import ClaimStatus, VerificationReport

CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;font:16px/1.6 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  background:#fbfbfa;color:#16161a}
@media (prefers-color-scheme:dark){body{background:#121214;color:#e9e9ec}}
.wrap{max-width:52rem;margin:0 auto;padding:2rem 1rem 5rem}
h1{font-size:1.6rem;line-height:1.25;margin:0 0 .25rem}
h2{font-size:1.15rem;margin:2.5rem 0 .5rem;padding-top:1rem;border-top:1px solid #d9d9d6}
@media (prefers-color-scheme:dark){h2{border-color:#2f2f35}}
h3{font-size:1rem;margin:1.5rem 0 .25rem}
p{margin:.6rem 0}
.sub{color:#5b5b63;margin-top:0}
@media (prefers-color-scheme:dark){.sub{color:#a0a0aa}}
.answer{border-left:4px solid #5b5b63;padding:.75rem 0 .75rem 1rem;margin:1.5rem 0}
.answer.bad{border-color:#b0331f}
.answer.neutral{border-color:#7a6a20}
.answer.good{border-color:#1f6f45}
.answer h1{font-size:1.35rem}
.alert{border:1px solid #b0331f;background:#fff1ee;color:#5e1a0f;
  padding:.85rem 1rem;border-radius:.4rem;margin:1.5rem 0}
@media (prefers-color-scheme:dark){.alert{background:#2a1512;color:#f6cdc5}}
table{border-collapse:collapse;width:100%;margin:.75rem 0;font-size:.92rem}
th,td{text-align:left;padding:.45rem .6rem;border-bottom:1px solid #e3e3e0;vertical-align:top}
@media (prefers-color-scheme:dark){th,td{border-color:#2f2f35}}
th{font-weight:600;color:#5b5b63}
@media (prefers-color-scheme:dark){th{color:#a0a0aa}}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em}
pre{background:#f0f0ed;padding:.75rem;border-radius:.4rem;overflow-x:auto}
@media (prefers-color-scheme:dark){pre{background:#1c1c20}}
.v{font-weight:600}
.v-PASS{color:#1f6f45}.v-FAIL{color:#b0331f}.v-ERROR{color:#b0331f}
.v-OBSERVED{color:#5b5b63}.v-NOT_APPLICABLE{color:#8a8a92}.v-NOT_RUN{color:#8a8a92}
.claim{border:1px solid #d9d9d6;border-radius:.4rem;padding:.75rem 1rem;margin:.75rem 0}
@media (prefers-color-scheme:dark){.claim{border-color:#2f2f35}}
.claim .status{font-weight:600;letter-spacing:.02em}
.ESTABLISHED{color:#1f6f45}.NOT_ESTABLISHED{color:#7a6a20}.FAILED{color:#b0331f}
ul{margin:.4rem 0 .4rem 1.2rem;padding:0}
li{margin:.3rem 0}
.note{background:#f0f0ed;border-radius:.4rem;padding:.75rem 1rem;margin:1.25rem 0;
  font-size:.92rem;color:#3d3d44}
@media (prefers-color-scheme:dark){.note{background:#1c1c20;color:#c3c3cb}}
button{font:inherit;padding:.55rem 1.1rem;border-radius:.35rem;border:1px solid #16161a;
  background:#16161a;color:#fff;cursor:pointer}
@media (prefers-color-scheme:dark){button{background:#e9e9ec;color:#121214;border-color:#e9e9ec}}
textarea{width:100%;min-height:9rem;font-family:ui-monospace,monospace;font-size:.85rem;
  padding:.6rem;border-radius:.35rem;border:1px solid #c9c9c4;background:inherit;color:inherit}
label{display:block;margin:.9rem 0 .25rem;font-weight:600;font-size:.92rem}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid #d9d9d6;font-size:.86rem;color:#5b5b63}
@media (prefers-color-scheme:dark){footer{border-color:#2f2f35;color:#a0a0aa}}
"""

#: Which border colour an answer gets. Not a score -- three buckets, and the
#: one that favours the product is the same weight as the one that does not.
_ANSWER_TONE: dict[Answer, str] = {
    Answer.GATEWAY_DID_NOT_HOLD: "bad",
    Answer.GATEWAY_PREVENTED_DUPLICATES: "good",
    Answer.GATEWAY_CHANGED_EVIDENCE_ONLY: "neutral",
    Answer.YOU_MAY_NOT_NEED_US: "neutral",
    Answer.NO_COMPARISON_WAS_MADE: "neutral",
    Answer.NOTHING_ESTABLISHED: "bad",
}


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title><style>{CSS}</style></head>"
        f'<body><div class="wrap">{body}</div></body></html>\n'
    )


def _list(items: list[str]) -> str:
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>"


def render_index(
    *,
    scenarios: list[str],
    defaults: list[str],
    external_targets_enabled: bool,
) -> str:
    """The landing page: what this does, what it will not do, and a button."""
    target_line = (
        "This server was started with external targets enabled. Even so, each "
        "request must separately confirm that you are authorized to send "
        "failure traffic at the system you name. Neither authorization stands "
        "in for the other."
        if external_targets_enabled
        else "This server runs against its own sandbox only. It will not send "
        "a request to any system you name, and there is no setting in this "
        "page that changes that."
    )
    body = f"""
<h1>Agent Action Safety Check</h1>
<p class="sub">Run a real failure against an agent integration and read what the
instruments counted.</p>

<p>Your agent calls a tool. The tool executes. The response never arrives. Your
agent retries. Did the customer get refunded once, or twice?</p>

<p>This check answers that by running the failure, not by reasoning about it.
It runs the same workload three ways: a direct integration with no replay
protection, a <em>correct</em> direct integration whose downstream honours a
durable operation id, and that same correct integration with Agent Middleware
in front of it. Downstream effects are counted by the simulated tool's own
ledger, which the gateway cannot read or write.</p>

<div class="note">
<p><strong>This check can conclude that you do not need this product</strong>,
and when the measurements say so, that is what it prints. The correct baseline
is built to succeed. Constructing a weak one to make the gateway look good
would make every other number on the page worthless.</p>
<p>There is no risk score. Nothing here is graded.</p>
</div>

<h2>What it will not do</h2>
<ul>
  <li>{_e(target_line)}</li>
  <li>It never asks for an API key, a token or a private key, and it refuses a
      submission that looks like one before parsing it.</li>
  <li>It never moves real money, and nothing it does touches your systems.</li>
  <li>It does not record who you are. There is no account, and the address used
      to rate-limit a request is never written to a result or an event.</li>
</ul>

<h2>Run the check</h2>
<p>Scenarios available here: <code>{_e(", ".join(scenarios))}</code>. The
default selection is <code>{_e(", ".join(defaults))}</code>. The full
fourteen-scenario suite, including the slow ones, runs from the command line.</p>
<pre>curl -sS -X POST http://127.0.0.1:8080/check \\
  -H 'content-type: application/json' \\
  -d '{{"scenarios": {_e(str(defaults).replace("'", '"'))}}}'</pre>
<form method="post" action="/check">
  <button type="submit">Run the default check</button>
</form>

<h2>Check somebody else's receipt</h2>
<p>If you have been handed a signed receipt and want to know what it proves,
<a href="/verify">verify it here</a>. That page reports three separate claims
and will tell you plainly that a valid signature is not evidence the business
action happened.</p>

<footer>The scenarios, the instruments and this page are in the repository. Run
<code>python -m failure_lab list</code> to see every test and what it
documents.</footer>
"""
    return _page("Agent Action Safety Check", body)


def _row_html(row: ScenarioRow) -> str:
    added = (
        f"<h3>What the gateway added</h3>{_list(row.added)}" if row.added else ""
    )
    cost = f"<h3>What it cost</h3>{_list(row.cost)}" if row.cost else ""
    risks = (
        f"<h3>Still at risk</h3>{_list(row.remaining_risks)}"
        if row.remaining_risks
        else ""
    )
    flag = (
        '<p class="alert">This scenario diverged from its documented '
        "expectation. The documentation and the measurement disagree; read the "
        "measurement.</p>"
        if not row.matches_expectation
        else ""
    )
    return f"""
<h2>{_e(row.test_id)} — {_e(row.title)}</h2>
{flag}
<p><strong>Claim under test:</strong> {_e(row.claim)}</p>
<p><strong>Verdict:</strong> <span class="v v-{_e(row.verdict)}">{_e(row.verdict)}</span>
 &nbsp;<strong>Conclusion:</strong> {_e(row.conclusion_kind)}
 <span class="sub">({_e(row.conclusion_gloss)})</span></p>
<p>{_e(row.conclusion_text)}</p>
{added}{cost}{risks}
"""


def render_result(answer: DiagnosticAnswer, *, environment: dict[str, Any]) -> str:
    """The result page.

    Ordering is the argument. A failed guarantee is the first thing on the
    page; the headline's supporting detail comes after it; the offer, when
    there is one at all, is last and appears only for the single answer that
    actually points at the product.
    """
    failures = (
        '<div class="alert"><strong>Read this first.</strong>'
        f"{_list(answer.gateway_failures)}</div>"
        if answer.gateway_failures
        else ""
    )
    tone = _ANSWER_TONE[answer.answer]

    counts = answer.counts
    count_rows = "".join(
        f"<tr><td>{_e(name.replace('_', ' '))}</td><td>{_e(value)}</td></tr>"
        for name, value in sorted(counts.items())
    )

    not_tested = (
        f"<h2>What this run did not establish</h2>{_list(answer.not_tested)}"
        if answer.not_tested
        else ""
    )

    offer = ""
    if answer.recommends_the_product:
        offer = """
<h2>If you want this in front of your own tools</h2>
<p>The duplicate prevention above was measured here, in a sandbox, against a
simulated tool. It is not a prediction about your downstream. The next honest
step is to run the same scenarios against your own integration and read your
own numbers, which the command-line lab does without sending anything anywhere.</p>
"""

    meta_rows = "".join(
        f"<tr><td>{_e(name)}</td><td><code>{_e(environment.get(key, 'unknown'))}</code></td></tr>"
        for name, key in (
            ("Run id", "run_id"),
            ("Test definitions", "test_definition_version"),
            ("Gateway version", "gateway_version"),
            ("Gateway commit", "gateway_commit"),
            ("Random seed", "seed"),
            ("Traffic source", "traffic_source"),
            ("Reproduce with", "reproduction_command"),
        )
    )

    body = f"""
<h1>Agent Action Safety Check</h1>
<p class="sub">Result of one run. Every number below was counted by a named
instrument.</p>
{failures}
<div class="answer {tone}">
  <h1>{_e(answer.headline)}</h1>
  <p>{_e(answer.detail)}</p>
</div>

<h2>What ran</h2>
<table><tbody>{count_rows}</tbody></table>
<div class="note">These are counts of scenarios and of effects, not a score.
No index, grade or percentage is computed anywhere on this page, because a
single number would be easier to trust than the measurements under it and
impossible to check.
<p>The two duplicate-prevention counts are kept apart on purpose. Preventing a
duplicate that an <em>unprotected</em> integration would have caused is
something a correct downstream also does, for free. Only the count against a
correct native integration bears on whether this product adds anything.</p></div>

{not_tested}

{"".join(_row_html(row) for row in answer.rows)}

<h2>Limits of this result</h2>
{_list(answer.limitations)}

{offer}

<h2>Reproduce it</h2>
<table><tbody>{meta_rows}</tbody></table>

<footer>The machine-readable form of this page is at
<code>{_e(environment.get("run_id", ""))}.json</code> next to it. Results are
held in memory and are not a system of record.</footer>
"""
    return _page("Agent Action Safety Check — result", body)


def render_verify_form() -> str:
    body = """
<h1>Verify a receipt</h1>
<p class="sub">Three questions, answered separately, because they have
different answers.</p>

<p>Paste a portable receipt bundle. If you also have the issuer's published key
document, paste that; without it this page can tell you that the bundle is
internally consistent and nothing more.</p>

<div class="note">A valid signature establishes <strong>what the issuer
recorded</strong>. It is not evidence that the downstream business action
occurred, and it is not evidence that the issuer is who you think it is if the
key that verifies it was published by the same origin that issued it. This page
reports those as three separate claims and never collapses them into one
tick.</div>

<form method="post" action="/verify">
  <label for="bundle">Receipt bundle (JSON)</label>
  <textarea id="bundle" name="bundle" placeholder='{"receipt_id": "...", ...}'></textarea>
  <label for="keys">Issuer key document (JSON, optional)</label>
  <textarea id="keys" name="keys" placeholder='{"keys": [{"kid": "...", ...}]}'></textarea>
  <p><button type="submit">Verify</button></p>
</form>

<div class="note">Do not paste an API key, a token or a private key here.
Nothing on this page needs one, and a submission that looks like it contains
one is refused before it is parsed.</div>

<p>The same check runs offline, against a bundle on your disk, with no network
and no trust in this page:</p>
<pre>python -m failure_lab verify --bundle ./evidence</pre>
"""
    return _page("Verify a receipt", body)


def render_verification(report: VerificationReport) -> str:
    """Three claims, three statuses, three explanations. Never one verdict."""
    explanations = {
        "SIGNATURE VALID": (
            "Whether the bytes of the signed payload match the signature under "
            "the named key. This says nothing about who holds that key, and "
            "nothing about what happened downstream."
        ),
        "ISSUER TRUST ESTABLISHED": (
            "Whether the key that verified the signature reached you through a "
            "channel the issuer does not control. A key fetched from the "
            "issuer's own origin cannot establish this: an issuer that can "
            "change the receipt can change the key that validates it."
        ),
        "DOWNSTREAM EXECUTION ESTABLISHED": (
            "Whether the business action actually occurred. A receipt is the "
            "issuer's record of what it believes happened. Establishing this "
            "needs an observation from the downstream system itself, which no "
            "signature can substitute for."
        ),
    }

    blocks = []
    for claim in (report.signature, report.issuer_trust, report.downstream_execution):
        status = claim.status.value
        blocks.append(
            f'<div class="claim"><p class="status {_e(status)}">'
            f"{_e(claim.name)}: <span class=\"{_e(status)}\">{_e(status)}</span></p>"
            f"<p>{_e(claim.reason)}</p>"
            f'<p class="sub">{_e(explanations.get(claim.name, ""))}</p></div>'
        )

    disagreements = (
        '<div class="alert"><strong>The envelope disagrees with the signed '
        "payload</strong> on these fields, which means a reader trusting the "
        "envelope would be reading something nobody signed:"
        f"{_list(report.envelope_disagreements)}</div>"
        if report.envelope_disagreements
        else ""
    )
    notes = f"<h2>Notes</h2>{_list(report.notes)}" if report.notes else ""

    established = report.downstream_execution.status is ClaimStatus.ESTABLISHED
    summary = (
        "All three claims are reported above. Read them separately."
        if established
        else "A signature that checks out is not a receipt for an action that "
        "happened. Whatever the first claim says, the third one is the one "
        "that answers 'did the money move?', and it is answered from an "
        "observation of the downstream system or not at all."
    )

    body = f"""
<h1>Verification result</h1>
<p class="sub">{_e(summary)}</p>
{disagreements}
{"".join(blocks)}
{notes}
<h2>Verify it yourself</h2>
<p>This page is the issuer's own software. Running the check against a bundle
on your own disk, with an implementation that depends only on a signature
library and the standard library, is a stronger position:</p>
<pre>python -m failure_lab verify --bundle ./evidence --keys ./trust-keys.json</pre>
<footer>Key used: <code>{_e(report.key_id or "none")}</code>. The key id is read
from inside the signed payload, not from the envelope, so an envelope that names
a different key cannot redirect the check.</footer>
"""
    return _page("Verification result", body)


__all__ = [
    "CSS",
    "render_index",
    "render_result",
    "render_verification",
    "render_verify_form",
]
