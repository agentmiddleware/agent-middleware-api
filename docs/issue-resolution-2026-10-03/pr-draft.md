# Resolve 82 QA findings and reconcile their repairs with current main

The QA backlog contains authorization, tenant-isolation, accounting, retry/ownership, integration, proof-tooling and client defects that were repaired on unpublished local branches. This change integrates 79 fixes and three explicit retirements with current main, preserving the newer #587/#589 fixes. It also removes unsafe database stamp-head guidance and corrects a WebKit keyboard-test simulation without weakening assertions.

The inherited integration includes single-action authority and schema042. Its operational prerequisites are in `docs/schema-042-rollout.md`; local tests do not authorize or establish a deployment. Complete issue-to-fix mapping and preserved validation are in `docs/issue-resolution-2026-10-03/`.

Validation: full Python suite `4908 passed, 87 skipped, 6 warnings in 302.81s (0:05:02)`; SDK/wrapper `213 passed in 0.50s`; fresh PostgreSQL44/44; optional OpenAPI/Hypothesis2/2; browser33/33 across Chromium/Firefox/WebKit; component/arcade22, TypeScript2, design78 and calculator25. Ruff/format/mypy, generated OpenAPI/inventory/doc references and secret scans passed. Counts overlap. Independent scoped reviews found no blocking defect.

Hosted CI, deployment, live provider/payment behavior and complete human/customer/QA-charter acceptance remain unverified. Parent #499 and charters #553–556 remain open. This draft deliberately references findings rather than closing release-tracking issues on merge.

Refs: #500, #501, #502, #503, #504, #505, #506, #507, #508, #509, #510, #511, #512, #513, #514, #515, #516, #517, #518, #519, #520, #521, #522, #523, #524, #525, #526, #527, #528, #529, #530, #531, #532, #533, #534, #535, #536, #537, #538, #539, #540, #541, #542, #543, #544, #545, #546, #547, #548, #549, #550, #551, #552, #557, #558, #559, #560, #561, #562, #563, #564, #565, #566, #567, #568, #569, #570, #571, #572, #573, #574, #575, #576, #577, #578, #579, #580, #581, #582, #583, #584, #585.
