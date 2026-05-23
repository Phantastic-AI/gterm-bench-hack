# Current state

Last updated: 2026-05-23.

## Clean framing

- Target benchmark: **Terminal-Bench v2**.
- Target task model: **Gemini 3.5 Flash**.
- Harness direction: **Meta-Harness-inspired candidate/evaluate/improve loop**.
- Flow World role: **inspiration only** for compact trace-as-code / graph-style primitives. This repo does **not** use the Flow World engine.

## Candidate truth table

| Candidate | Author/source | Status | Trust level |
| --- | --- | --- | --- |
| C000 | Codex-built baseline direct Gemini harness | Ran smoke/panel | Useful baseline |
| C001 | Codex-built ledger/verify/trace harness | Ran diagnostics; exposed Harbor verifier staging issue | Partially useful |
| C002 | Codex-built budgeted repair harness | Ran canonical 10-task panel | Last trustworthy benchmark snapshot |
| C003 | Codex-built adaptive-thinking candidate | n=1 regex-log smoke failed after correct simple_file classification | Not final; do not run n=10 yet |
| G003 | Gemini 3.5 Flash-generated meta-optimizer proposal | Proposal artifact only; not integrated/run | Research artifact |

## Important boundary

C003 is **not** Gemini-meta-optimized. It is a manual Codex-authored harness candidate informed by C002 traces.

G003 is the Gemini-authored meta-optimizer output. It produced a proposal only. It did not edit the live harness and did not run Terminal-Bench.

## Current safe next step

Build a tiny follow-up candidate that prevents simple-file tasks from wasting budget on interpreter discovery before writing the required output file, then rerun `terminal-bench/regex-log` n=1.

Do not run a larger panel until the n=1 smoke passes.
