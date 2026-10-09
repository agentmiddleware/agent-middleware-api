import pathlib

R = pathlib.Path(".")
edits = {
    "gateway/WEDGE.md": [
        (
            "# Wedge: Replay-safe MCP permits and exactly-once debits",
            "# Wedge: Replay-safe MCP permits and at-most-once debits",
        ),
        (
            "> Exactly-once gateway authorization, debit, and receipt finalization for\n> metered MCP calls.",
            "> At most one gateway dispatch and at most one debit per accepted idempotency\n> key, with one finalized signed receipt, for metered MCP calls.",
        ),
        (
            '**What "exactly-once" means here, precisely.** It is the distributed-systems\nterm of art for the *deduplication* guarantee',
            '**Why this project does not say "exactly-once".** The guarantee is\n*deduplication* at the gateway',
        ),
        (
            "differentiating primitive is exactly-once economic authorization at the\ngateway boundary",
            "differentiating primitive is at-most-once economic authorization per accepted\nidempotency key at the gateway boundary",
        ),
        (
            "A remote tool's own side effect is exactly\nonce only when that tool also honors the forwarded idempotency key.",
            "This is not exactly-once: a remote tool's own side effect is deduplicated\nonly when that tool also honors the forwarded idempotency key.",
        ),
    ],
    "gateway/DESIGN_PARTNER_GUIDE.md": [
        (
            '- "Exactly-once gateway authorization, debit, and receipt finalization for\n  metered MCP calls."',
            '- "At most one gateway dispatch and at most one debit per accepted idempotency\n  key; a same-key retry returns the original receipt."',
        ),
        (
            "and that a final valid call still charges exactly once.",
            "and that a final valid call is charged once (one debit for its key).",
        ),
        (
            "- Claiming an arbitrary remote tool's side effect is exactly once when that",
            '- Claiming "exactly-once", or that an arbitrary remote tool\'s side effect happens once when that',
        ),
    ],
    "TRUST_MODEL.md": [
        (
            "## Exactly-Once Debit, Bound To The Idempotency Record",
            "## At-Most-Once Debit, Bound To The Idempotency Record",
        )
    ],
    "SECURITY_LIMITATIONS.md": [
        (
            "- Gateway exactly-once behavior does not make a remote side effect exactly\n  once unless",
            "- The gateway's at-most-once dispatch and debit per key does not make a\n  remote side effect happen only once unless",
        )
    ],
    "gateway/docs/failure-semantics.md": [
        ("## Exactly-once refunds", "## Refunds are written at most once"),
        (
            "That retry is exactly-once under concurrency:",
            "That retry cannot double-refund under concurrency:",
        ),
        ("budget release is exactly-once,", "budget release happens at most once,"),
    ],
    "gateway/docs/PROOF_MATRIX.md": [
        (
            "| Exactly-once against a **real durable side effect**",
            "| One write per key against a **real durable side effect**",
        ),
        (
            "- **Exactly-once is gateway-scoped.** A remote tool's side effect is exactly\n  once only if",
            "- **Deduplication is gateway-scoped; this is not exactly-once.** A remote\n  tool's side effect is deduplicated only if",
        ),
    ],
    "gateway/docs/security-review-kit.md": [
        (
            "- Gateway exactly-once does not make the upstream side effect exactly-once\n  unless",
            "- Gateway deduplication (at most one dispatch and debit per key) does not make\n  the upstream side effect happen once unless",
        )
    ],
    "gateway/docs/owasp-agentic-top10-mapping.md": [
        (
            "- Gap: exactly-once at the gateway does not make the remote side effect\n  exactly-once unless",
            "- Gap: at-most-once dispatch at the gateway does not make the remote side\n  effect happen once unless",
        )
    ],
    "gateway/docs/PROOF_SURFACES.md": [
        ("exactly-once MCP permit wedge.", "replay-safe MCP permit wedge.")
    ],
    "gateway/docs/invariant-attack-report.md": [
        (
            "exactly-once receipts/refunds/dispatch",
            "single receipts/refunds/dispatch per key",
        )
    ],
    "gateway/DEMO_SCRIPT.md": [
        (
            "This call charges it exactly once, and",
            "This call charges it once for this key, and",
        )
    ],
    "gateway/docs/README.md": [
        (
            "A remote side effect is exactly once only if",
            "This is not exactly-once: a remote side effect is deduplicated only if",
        )
    ],
    "gateway/docs/failure-lab-suite.md": [
        ("effect is exactly once only if", "effect is deduplicated only if")
    ],
    "gateway/docs/partner-first-tool-runbook.md": [
        ("side effect is exactly once only if", "side effect is deduplicated only if")
    ],
}
for f, pairs in edits.items():
    p = R / f
    s = p.read_text()
    for a, b in pairs:
        if a not in s:
            print("MISS", f, a[:60])
            continue
        s = s.replace(a, b)
    p.write_text(s)
