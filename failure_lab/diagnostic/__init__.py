"""The self-serve diagnostic surface: "Agent Action Safety Check".

Three modules, split along the line that matters for reviewing this code:

:mod:`failure_lab.diagnostic.answer`
    Decides *what the run means for the visitor* -- which of six answers, in a
    fixed precedence, derived from the same comparison objects the evidence
    bundle is built from. This is where "you may not need us" is a branch with
    a test behind it rather than a sentence somebody promises to keep in.

:mod:`failure_lab.diagnostic.pages`
    Decides *how it is said*. Plain HTML with no slot a persuasive string could
    be threaded into, and no score anywhere.

:mod:`failure_lab.diagnostic.server`
    Decides *what the surface is allowed to do*: sandbox-only by default, two
    independent authorizations before any external request, no credential
    accepted, every response redacted, every visitor rate-limited, and a
    traffic source that can never label itself a customer.

``python -m failure_lab serve`` reaches this through
:func:`failure_lab.cli.command_serve`, which looks for :func:`main` by name.
"""

from __future__ import annotations

from failure_lab.diagnostic.answer import (
    ANSWER_DETAIL,
    ANSWER_HEADLINES,
    STANDING_LIMITATIONS,
    Answer,
    DiagnosticAnswer,
    ScenarioRow,
    build_answer,
    headline_for,
)
from failure_lab.diagnostic.server import (
    DEFAULT_SCENARIOS,
    PUBLIC_SCENARIOS,
    DiagnosticService,
    DiagnosticSettings,
    SubmissionRefused,
    create_app,
    main,
    serve,
)

__all__ = [
    "ANSWER_DETAIL",
    "ANSWER_HEADLINES",
    "DEFAULT_SCENARIOS",
    "PUBLIC_SCENARIOS",
    "STANDING_LIMITATIONS",
    "Answer",
    "DiagnosticAnswer",
    "DiagnosticService",
    "DiagnosticSettings",
    "ScenarioRow",
    "SubmissionRefused",
    "build_answer",
    "create_app",
    "headline_for",
    "main",
    "serve",
]
