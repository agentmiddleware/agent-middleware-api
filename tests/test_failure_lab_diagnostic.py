"""The diagnostic must be able to argue against the thing it is selling.

Two classes of defect are load-bearing here and neither is cosmetic.

A diagnostic that cannot print "you may not need us" is a sales page with a
progress bar on it. The PRD calls that result a feature, and a feature that is
only promised in a docstring is not implemented, so these tests drive the
branch and assert that the page it produces carries no offer.

A diagnostic that will send failure traffic wherever it is pointed is a
denial-of-service tool with a friendly name. These tests assert that both
authorizations are required, that neither substitutes for the other, and that a
credential is refused before anything parses it.

The scenario-driving tests are deliberately absent: a run boots a gateway and a
sandbox, and the comparison objects those produce are already exercised by the
scenario suite. What is tested here is the decision layer on top of them, driven
from synthetic comparisons, which is the layer that can silently start lying.
"""

from __future__ import annotations

import json
import re

import pytest
from starlette.testclient import TestClient

from failure_lab.configurations import CONFIGURATION_LABELS, Configuration
from failure_lab.diagnostic import (
    Answer,
    DiagnosticSettings,
    build_answer,
    create_app,
    headline_for,
)
from failure_lab.diagnostic import pages
from failure_lab.diagnostic.offer import OFFER
from failure_lab.diagnostic.server import MAX_SUBMISSION_BYTES, DiagnosticService
from failure_lab.report import build_comparison
from failure_lab.scenarios.base import ConfigurationResult, Counters, ScenarioResult, Verdict

ENVIRONMENT = {
    "run_id": "diagnostic-test",
    "test_definition_version": "2026.09.1",
    "gateway_version": "1.3.0",
    "gateway_commit": "0" * 40,
    "seed": "1",
    "traffic_source": "unknown",
    "reproduction_command": "python -m failure_lab run --test T03",
}


def _entry(
    configuration: Configuration,
    *,
    verdict: Verdict,
    executions: int,
    dispatches: int | None = None,
    known: int = 0,
    uncertain: int = 0,
    unresolved: int = 0,
    receipts: int | None = None,
    debits: int | None = None,
) -> ConfigurationResult:
    return ConfigurationResult(
        configuration=configuration.value,
        label=CONFIGURATION_LABELS[configuration],
        verdict=verdict,
        expectation=verdict.value,
        observation=f"{configuration.value} observed {executions} execution(s)",
        counters=Counters(
            incoming_requests=2,
            accepted_requests=2,
            downstream_requests=executions,
            downstream_executions=executions,
            gateway_dispatches=dispatches,
            gateway_debits=debits,
            gateway_refunds=0 if debits is not None else None,
            receipts=receipts,
            known_final_outcome=known,
            explicit_uncertain=uncertain,
            unresolved=unresolved,
        ),
    )


def _not_applicable(configuration: Configuration) -> ConfigurationResult:
    return ConfigurationResult(
        configuration=configuration.value,
        label=CONFIGURATION_LABELS[configuration],
        verdict=Verdict.NOT_APPLICABLE,
        expectation=Verdict.NOT_APPLICABLE.value,
        observation="a direct integration has no such component",
        counters=Counters(),
    )


def _comparison(entries: list[ConfigurationResult], *, test_id: str = "TXX"):
    result = ScenarioResult(
        test_id=test_id,
        title="Synthetic scenario",
        claim="A synthetic claim, long enough to read like a sentence.",
        definition_version="2026.09.1",
        definition_hash="f" * 64,
        started_at="2026-09-19T00:00:00Z",
        finished_at="2026-09-19T00:00:01Z",
        configurations=entries,
        limitations=["a stated limitation"],
        events=[],
        expected={entry.configuration: entry.verdict.value for entry in entries},
    )
    return build_comparison(result)


def _baseline_wins():
    """A run where the correct native baseline handled everything."""
    return [
        _comparison(
            [
                _entry(Configuration.DIRECT_NAIVE, verdict=Verdict.OBSERVED, executions=2),
                _entry(Configuration.DIRECT_NATIVE, verdict=Verdict.PASS, executions=1, known=2),
                _entry(
                    Configuration.GATEWAY_NATIVE,
                    verdict=Verdict.PASS,
                    executions=1,
                    dispatches=1,
                    known=2,
                    receipts=1,
                    debits=1,
                ),
            ]
        )
    ]


def _gateway_prevents():
    """A run where the baseline duplicated and the gateway did not."""
    return [
        _comparison(
            [
                _entry(Configuration.DIRECT_NAIVE, verdict=Verdict.OBSERVED, executions=3),
                _entry(Configuration.DIRECT_NATIVE, verdict=Verdict.OBSERVED, executions=2),
                _entry(
                    Configuration.GATEWAY_NATIVE,
                    verdict=Verdict.PASS,
                    executions=1,
                    dispatches=1,
                    known=2,
                    receipts=1,
                    debits=1,
                ),
            ]
        )
    ]


def _gateway_fails():
    return [
        _comparison(
            [
                _entry(Configuration.DIRECT_NAIVE, verdict=Verdict.OBSERVED, executions=2),
                _entry(Configuration.DIRECT_NATIVE, verdict=Verdict.PASS, executions=1),
                _entry(
                    Configuration.GATEWAY_NATIVE,
                    verdict=Verdict.FAIL,
                    executions=2,
                    dispatches=2,
                    receipts=2,
                    debits=2,
                ),
            ]
        )
    ]


def _no_baseline():
    return [
        _comparison(
            [
                _not_applicable(Configuration.DIRECT_NAIVE),
                _not_applicable(Configuration.DIRECT_NATIVE),
                _entry(
                    Configuration.GATEWAY_NATIVE,
                    verdict=Verdict.PASS,
                    executions=1,
                    dispatches=1,
                    known=2,
                    receipts=1,
                    debits=1,
                ),
            ]
        )
    ]


# --------------------------------------------------------------------------- #
# The answer the PRD requires to be reachable                                   #
# --------------------------------------------------------------------------- #


def test_you_may_not_need_us_is_reachable_and_says_so_plainly():
    answer = build_answer(_baseline_wins())

    assert answer.answer is Answer.YOU_MAY_NOT_NEED_US
    assert "may not need us" in answer.headline.lower()
    assert not answer.recommends_the_product
    # It must be a result, not a preamble to a pitch.
    assert "not a preamble to a recommendation" in answer.detail


def test_the_page_for_that_answer_carries_no_offer():
    """The branch exists; the rendered page must not undo it."""
    answer = build_answer(_baseline_wins())
    html = pages.render_result(answer, environment=ENVIRONMENT)

    assert "may not need us" in html.lower()
    assert OFFER.headline not in html


def test_a_prevention_result_is_the_only_one_that_carries_an_offer():
    prevented = build_answer(_gateway_prevents())
    assert prevented.answer is Answer.GATEWAY_PREVENTED_DUPLICATES
    assert prevented.recommends_the_product
    assert OFFER.headline in pages.render_result(
        prevented, environment=ENVIRONMENT
    )

    for comparisons in (_baseline_wins(), _gateway_fails(), _no_baseline()):
        answer = build_answer(comparisons)
        assert not answer.recommends_the_product, answer.answer
        assert OFFER.headline not in pages.render_result(
            answer, environment=ENVIRONMENT
        )


def test_a_failed_guarantee_outranks_a_prevention_in_the_same_run():
    """The product's own broken promise is the headline, not a footnote."""
    comparisons = _gateway_prevents() + _gateway_fails()
    assert headline_for(comparisons) is Answer.GATEWAY_DID_NOT_HOLD

    answer = build_answer(comparisons)
    html = pages.render_result(answer, environment=ENVIRONMENT)
    # And the failure block is physically above the headline block.
    assert html.index("Read this first") < html.index(answer.headline)


def test_a_run_with_no_baseline_does_not_claim_the_baseline_would_have_coped():
    answer = build_answer(_no_baseline())

    assert answer.answer is Answer.NO_COMPARISON_WAS_MADE
    assert "No comparison was made" in answer.headline
    assert "cannot tell you whether you need it" in answer.detail
    assert any("bears on whether your own integration" in note for note in answer.not_tested)


def test_an_empty_run_establishes_nothing_rather_than_something_flattering():
    answer = build_answer([])
    assert answer.answer is Answer.NOTHING_ESTABLISHED
    assert not answer.recommends_the_product


# --------------------------------------------------------------------------- #
# No score, anywhere                                                            #
# --------------------------------------------------------------------------- #


#: A number that looks like a grade: "score: 73", "82/100", "risk: 4.5".
_SCORE_WITH_A_VALUE = re.compile(
    r"(?i)\b(?:risk|safety|readiness|trust|health)\s*(?:score|rating|grade|index)\b"
    r"\s*[:=]?\s*\d"
    r"|\b\d{1,3}\s*/\s*100\b"
)


@pytest.mark.parametrize(
    "comparisons",
    [_baseline_wins(), _gateway_prevents(), _gateway_fails(), _no_baseline()],
    ids=["baseline_wins", "gateway_prevents", "gateway_fails", "no_baseline"],
)
def test_no_result_page_manufactures_a_score(comparisons):
    answer = build_answer(comparisons)
    html = pages.render_result(answer, environment=ENVIRONMENT)

    assert not _SCORE_WITH_A_VALUE.search(html), "a score appeared on the result page"
    assert answer.as_dict()["score"] is None


def test_every_answer_has_a_headline_and_a_detail():
    for member in Answer:
        assert pages._ANSWER_TONE[member]
        from failure_lab.diagnostic.answer import ANSWER_DETAIL, ANSWER_HEADLINES

        assert ANSWER_HEADLINES[member]
        assert ANSWER_DETAIL[member]


# --------------------------------------------------------------------------- #
# What the surface refuses to do                                                #
# --------------------------------------------------------------------------- #


def _client(**kwargs) -> TestClient:
    return TestClient(create_app(DiagnosticSettings(telemetry=False, **kwargs)))


def test_the_landing_page_says_it_can_conclude_you_do_not_need_the_product():
    with _client() as client:
        body = client.get("/").text
    assert "can conclude that you do not need this product" in body
    assert "no risk score" in body.lower()
    assert "sandbox only" in body


def test_an_external_target_is_refused_when_the_server_was_not_started_for_it():
    with _client() as client:
        response = client.post(
            "/check", json={"target": "https://payments.example.com"}
        )
    assert response.status_code == 403
    assert "sandbox only" in response.json()["reason"]


def test_the_server_flag_alone_does_not_authorize_an_individual_request():
    """Two authorizations, and neither stands in for the other."""
    with _client(allow_external_targets=True) as client:
        response = client.post(
            "/check", json={"target": "https://payments.example.com"}
        )
    assert response.status_code == 403
    assert "external_target_acknowledged" in response.json()["reason"]


def test_an_acknowledged_request_alone_does_not_authorize_it_either():
    with _client(allow_external_targets=False) as client:
        response = client.post(
            "/check",
            json={
                "target": "https://payments.example.com",
                "external_target_acknowledged": True,
            },
        )
    assert response.status_code == 403


def test_an_authorized_external_target_runs_nothing_rather_than_faking_it():
    """Refusing loudly beats reporting a sandbox result under a real name."""
    with _client(allow_external_targets=True) as client:
        response = client.post(
            "/check",
            json={
                "target": "https://payments.example.com",
                "external_target_acknowledged": True,
            },
        )
    assert response.status_code == 501
    assert "nothing was sent" in response.json()["reason"]


@pytest.mark.parametrize(
    "body",
    [
        {"bundle": {"note": "api_key=sk-abcdefghijklmnopqrstuvwx"}},
        {"bundle": {"note": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz"}},
        {"bundle": {"pem": "-----BEGIN PRIVATE KEY-----\\nMIIB"}},
        {"bundle": {"client_secret": "hunter2hunter2hunter2"}},
    ],
    ids=["api_key", "bearer", "private_key", "client_secret"],
)
def test_a_credential_shaped_submission_is_refused_before_it_is_parsed(body):
    with _client() as client:
        response = client.post("/verify", json=body)
    assert response.status_code == 400
    assert "refused" in response.json()["error"]
    assert "credential" in response.json()["reason"] or "secret" in response.json()["reason"]


def test_an_oversized_submission_is_refused_without_being_read():
    with _client() as client:
        response = client.post(
            "/verify",
            content=json.dumps({"bundle": {"pad": "x" * (MAX_SUBMISSION_BYTES + 1024)}}),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413


def test_a_scenario_outside_the_allowlist_is_refused():
    service = DiagnosticService(DiagnosticSettings(telemetry=False))
    with pytest.raises(Exception) as excinfo:
        service.select_scenarios(["T11"])
    assert "not available on this surface" in str(excinfo.value)


def test_the_surface_never_labels_its_own_traffic_as_a_customer():
    """A visitor cannot make themselves count towards conversion."""
    from failure_lab.telemetry import TrafficSource, counts_toward_conversion

    settings = DiagnosticSettings()
    assert settings.traffic_source is TrafficSource.UNKNOWN
    assert not counts_toward_conversion(settings.traffic_source)


def test_health_reports_whether_external_targets_are_enabled():
    with _client() as client:
        body = client.get("/healthz").json()
    assert body["external_targets_enabled"] is False
    assert body["traffic_source"] == "unknown"


# --------------------------------------------------------------------------- #
# Verification: three claims, never one tick                                    #
# --------------------------------------------------------------------------- #


def test_the_verify_page_says_a_signature_is_not_proof_of_execution():
    with _client() as client:
        body = client.get("/verify").text
    assert "not evidence that the downstream business action" in body
    assert "three separate claims" in body


def test_a_verification_result_renders_three_independent_claims():
    from failure_lab.verifier import Claim, ClaimStatus, VerificationReport

    report = VerificationReport(
        signature=Claim("SIGNATURE VALID", ClaimStatus.ESTABLISHED, "signature checks out"),
        issuer_trust=Claim(
            "ISSUER TRUST ESTABLISHED",
            ClaimStatus.NOT_ESTABLISHED,
            "the key came from the issuing origin",
        ),
        downstream_execution=Claim(
            "DOWNSTREAM EXECUTION ESTABLISHED",
            ClaimStatus.NOT_ESTABLISHED,
            "no independent downstream observation was supplied",
        ),
        key_id="kid-1",
    )
    html = pages.render_verification(report)

    assert html.count("NOT_ESTABLISHED") >= 2
    assert "ESTABLISHED" in html
    # The page must spell out that a valid signature does not settle the third.
    assert "is not a receipt for an action that happened" in html
    # And each claim must carry its own explanation, not share one verdict.
    assert "says nothing about who holds that key" in html
    assert "no signature can substitute for" in html


def test_duplicate_prevention_is_reported_against_each_baseline_separately():
    """One collapsed number reads as the page arguing with itself.

    In the lost-response scenario the unprotected integration duplicates and a
    correct native one does not, so the gateway prevents a duplicate relative
    to the former and none relative to the latter. A single "duplicates
    prevented: 1" printed under the headline "you may not need us" looks like a
    contradiction, and resolving it requires knowing which baseline the number
    was measured against. So the page prints both and never their maximum.
    """
    answer = build_answer(_baseline_wins())
    counts = answer.counts

    assert counts["duplicates_prevented_vs_a_correct_native_integration"] == 0
    assert counts["duplicates_prevented_vs_an_unprotected_integration"] == 1
    assert "duplicates_prevented" not in counts, "the collapsed count came back"

    html = pages.render_result(answer, environment=ENVIRONMENT)
    assert "kept apart on purpose" in html
    # The headline and the count that could contradict it must both be present,
    # with the distinction that reconciles them.
    assert "may not need us" in html.lower()
    assert "bears on whether this product adds anything" in html


def test_the_offer_never_invents_a_price():
    """An unset price renders as unset, not as a plausible-looking number."""
    from failure_lab.diagnostic.offer import OFFER_PRICE, PRICE_NOT_PUBLISHED

    assert OFFER_PRICE is None, "a price was hardcoded into the repository"
    assert OFFER.price == PRICE_NOT_PUBLISHED

    html = pages.render_result(build_answer(_gateway_prevents()), environment=ENVIRONMENT)
    assert PRICE_NOT_PUBLISHED in html
    assert "will not invent one" in html
    # No currency amount anywhere on a page that shows an offer.
    assert not re.search(r"[$£€]\s?\d", html), "a currency amount appeared"


def test_the_offer_marks_what_a_human_has_to_size_first():
    """A trust plane that implies one-click production is lying about itself."""
    assert OFFER.needs_manual_review
    manual = [item for item in OFFER.items if item.manual_review]
    assert len(manual) >= 2

    html = pages.render_result(build_answer(_gateway_prevents()), environment=ENVIRONMENT)
    assert "technical review of your" in html
    assert "deploys anything to production by itself" in html
    for item in manual:
        assert item.title in html


def test_the_offer_has_exactly_one_definition():
    """The page must not carry a second copy of the offer text to drift from."""
    source = (pages.__file__,)
    for path in source:
        with open(path, encoding="utf-8") as handle:
            body = handle.read()
    for item in OFFER.items:
        assert item.detail not in body, (
            f"{item.title!r} is spelled out in pages.py as well as offer.py"
        )


def test_the_narration_cannot_claim_an_execution_nobody_counted():
    """The line only appears where the instrument reading does.

    The obvious way to produce the PRD's six lines is to print them on a timer
    while a run happens elsewhere. That is a screensaver, and it would keep
    saying "Downstream executed operation." on a run where nothing executed.
    """
    from failure_lab.diagnostic.steps import EXECUTED, translate_all

    without_evidence = [
        {
            "sequence": 1,
            "at": "2026-09-19T00:00:00Z",
            "scenario": "T03",
            "configuration": Configuration.DIRECT_NAIVE.value,
            "step": "attempt.first",
            "message": "first attempt timed out",
            "data": {"status": "timeout", "client_visible_state": "no_information"},
        }
    ]
    with_evidence = [
        {
            **without_evidence[0],
            "data": {
                **without_evidence[0]["data"],
                "executions_so_far": 1,
                "downstream_requests_so_far": 1,
            },
        }
    ]

    assert not any(step.text.startswith(EXECUTED) for step in translate_all(without_evidence))
    assert any(step.text.startswith(EXECUTED) for step in translate_all(with_evidence))


def test_an_unknown_step_is_printed_rather_than_dropped():
    """A new scenario step must degrade to a plain line, not a silent gap."""
    from failure_lab.diagnostic.steps import translate_all

    steps = translate_all(
        [
            {
                "sequence": 1,
                "at": "2026-09-19T00:00:00Z",
                "scenario": "T99",
                "configuration": Configuration.GATEWAY_NATIVE.value,
                "step": "some.step.invented.later",
                "message": "a step this module has never heard of",
                "data": {},
            }
        ]
    )
    assert len(steps) == 1
    assert "never heard of" in steps[0].text or "never heard of" in steps[0].detail
    assert steps[0].source_step == "some.step.invented.later"
