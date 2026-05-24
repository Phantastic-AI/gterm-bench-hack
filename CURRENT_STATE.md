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
| C007.x | Codex-authored trait/self-audit harness | Current submission-clean line; latest `cb9587c`; runs blocked by Gemini HTTP 403 | Best current harness |
| G003 | Gemini 3.5 Flash-generated meta-optimizer proposal | Proposal artifact only; not integrated/run | Research artifact |

## Important boundary

C007.x is **not** Gemini-meta-optimized. It is a manual Codex-authored harness candidate informed by traces and reviewer passes. G003 is the Gemini-authored meta-optimizer output; it produced a proposal only and did not edit the live harness.

## Current safe next step

Stop rerunning until the Gemini key is refreshed. Publish/report C007.12 as the best reliable 10-task evidence: **2/10** (`fix-git`, `regex-log`) at `/srv/appzilla/tbench-gemini-flash/runs/c00712-10-fullverifier-20260524T054550Z`. C007.15 is blocked by HTTP 403 `PERMISSION_DENIED`, not a harness score.


## Final C007 run evidence

- Latest pushed commit: `cb9587c` (`Keep container exec hangs from wedging runs`).
- Local/Appzilla gates for `cb9587c`: `tests/test_harness_state_machine.py` 59/59, compileall, no-secret audit, import smoke; reviewer Noether PASS.
- C007.12 full-verifier best: `/srv/appzilla/tbench-gemini-flash/runs/c00712-10-fullverifier-20260524T054550Z`, score 2/10, passes `fix-git` and `regex-log`.
- C007.13: `/srv/appzilla/tbench-gemini-flash/runs/c00713-10-fullverifier-20260524T062311Z`, killed after stale Harbor/container exec behavior.
- C007.14: `/srv/appzilla/tbench-gemini-flash/runs/c00714-10-hosttimeout-20260524T063722Z`, invalid infra run because `docker compose` plugin was missing.
- C007.15: `/srv/appzilla/tbench-gemini-flash/runs/c00715-10-hosttimeout-composefix-20260524T063907Z`, Docker Compose fixed but Gemini API began returning HTTP 403 `PERMISSION_DENIED`; run killed to avoid wasting resources.
