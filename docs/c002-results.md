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

## Live panel snapshot — 2026-05-23 21:58 UTC

Run root on Appzilla:

```text
../runs/c002-10-20260523T213552Z/job
```

Harbor status at snapshot:

```text
completed: 8
errors: 1
running: 1
pending: 1
scored mean so far: 0.375
```

Reward `1.0` so far:

- `regex-log__Krv8zhr`
- `build-pmars__wfeotuv`
- `fix-git__FYWHCaM`

Reward `0.0` so far:

- `break-filter-js-from-html__4HPJaBx`
- `cancel-async-tasks__GqQRfgz`
- `extract-elf__Gke7sqm`
- `count-dataset-tokens__HeYhiy6`

Infra-classified:

- `filter-js-from-html__nhXMkk3`: `infra_verifier_staging_missing_tests`

Still in flight at snapshot:

- `query-optimize__iosRjrC`
- one pending task

## C002 lessons for C003

- Parser recovery worked: C001's malformed JSON/control-character abort did not recur as a harness-stopping error.
- Budgeting worked operationally: hard tasks stopped faster and produced final state artifacts.
- Auto-finish is too permissive for code-debug and browser/security tasks.
- Required-output extraction still needs stricter negative-context filtering.
- Infra classification is useful and should become a runner-side retry policy.

