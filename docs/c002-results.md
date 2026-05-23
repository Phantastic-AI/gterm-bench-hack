# C002 Budgeted Repair Results

Status: implementation in progress; panel run pending.

## Candidate

`C002_budgeted_repair` keeps C001 ledger/gate/trace behavior and adds:

- robust action-JSON repair for malformed Gemini action objects;
- task-class budget profiles (`simple_file`, `code_debug`, `browser_security`, `unknown`);
- auto-finish when required outputs and fresh evidence pass the runtime gate;
- no-progress accounting for repeated passive reads/checks;
- summary-time infra classification for `/tests/test.sh` verifier-staging failures.

## Required evidence checklist

- [ ] Appzilla import check reports `candidate_id=C002_budgeted_repair`.
- [ ] Direct Gemini `gemini-3.5-flash` smoke passes.
- [ ] Canonical 10-task run under `../runs/c002-10-<timestamp>/job`.
- [ ] `scripts/summarize_job.py` output captured.
- [ ] `scripts/validate_atif.py` passes for all produced trajectories.
- [ ] `scripts/audit_no_secrets.py` passes for the run directory.
- [ ] Comparison against C000/C001 recorded.

## Comparison baselines

- C000 baseline fixed n=5: mean reward `0.2`; passed `build-pmars`.
- C001 ledger-verify n=1 diagnostic: `regex-log` reward `1.0` with ATIF + no-secret validation.
- C001 fixed n=5 diagnostic: aborted after exposing slow `break-filter-js-from-html` and malformed JSON parser weakness; used as motivation for C002.

