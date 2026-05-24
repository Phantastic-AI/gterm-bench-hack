# Current state

Last updated: 2026-05-24.

## Clean framing

- Target benchmark: **Terminal-Bench v2**.
- Target model: **Gemini 3.5 Flash**.
- Harness direction: **Meta-Harness-inspired direct agent loop** with compact trace/ledger, deterministic finish gates, repair prompts, and trait-based policies.
- Flow World role: **inspiration only** for compact trace-as-code / graph-style primitives. This repo does **not** use the Flow World engine.

## Candidate truth table

| Candidate | Author/source | Status | Trust level |
| --- | --- | --- | --- |
| C000 | Codex-built baseline direct Gemini harness | Ran smoke/panel | Useful baseline |
| C001 | Codex-built ledger/verify/trace harness | Ran diagnostics; exposed Harbor verifier staging issue | Partially useful |
| C002 | Codex-built budgeted repair harness | Ran canonical 10-task panel | Historical benchmark snapshot |
| C003-C006 | Codex-authored adaptive/trait harness line | Ran n=1/n=10 experiments | Superseded by C007 |
| C007.x | Codex-authored trait/self-audit harness | Current submission-clean line; latest `55e52c7` | Best current harness |
| G003 | Gemini 3.5 Flash-generated meta-optimizer proposal | Proposal artifact only; not integrated/run | Research artifact |

## Important boundary

C007.x is **not** Gemini-meta-optimized. It is a manual Codex-authored harness candidate informed by traces and reviewer passes. G003 is the Gemini-authored meta-optimizer output; it produced a proposal only and did not edit the live harness.

## Current safe next step

Let C007.11 finish or time out, publish the score with run root evidence, and stop optimizing unless the next change is clearly generic and testable. Avoid benchmark-specific fixes.
