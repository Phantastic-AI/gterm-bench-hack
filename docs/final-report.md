# Final Report: Gemini 3.5 Flash Terminal-Bench Harness Hack

## One-line result

We built a Harbor-compatible direct Gemini 3.5 Flash Terminal-Bench harness and iterated it from a baseline solver into a trace-aware, budgeted, self-checking agent loop with reproducible trace-code artifacts.

## Claim

The strongest result is not a single high benchmark score. The result is a working mini Meta-Harness loop:

1. keep the base model fixed (`gemini-3.5-flash`),
2. vary only the harness,
3. run a fixed Terminal-Bench panel,
4. record dehydrated traces as code,
5. classify failures into model/harness/infra buckets,
6. use those traces to propose the next harness candidate.

This makes Gemini 3.5 Flash usable both as a task solver and as a constrained harness optimizer.

## Candidate lineage

### C000: direct API baseline

Purpose: prove Gemini 3.5 Flash can run through Harbor without relying on the Gemini CLI.

Evidence:

- Direct Gemini API smoke passed on Appzilla.
- `regex-log` n=1 passed with reward `1.0`.
- Fixed n=5 panel completed with mean reward `0.2`.
- Artifacts: `docs/c000-smoke-results.md`.

### C001: ledger + verifier gate

Purpose: add the core trace-aware harness primitives.

Features:

- persisted C001 system prompt loaded every run;
- `AgentState` with rolling ledger;
- compact per-turn context under the 80k-token contract;
- action protocol: `read_file`, `write_file`, `list_files`, `shell`, `finish`, `abort`;
- runtime pre-finish gate;
- required-output path extraction;
- public/self-check freshness tracking;
- no-progress budget;
- upgraded trace events and ATIF trajectory output.

Evidence:

- C001 `regex-log` diagnostic n=1 passed with reward `1.0` under canonical diagnostic mode.
- ATIF validation and no-secret audit passed.
- C001 n=5 exposed two failure modes:
  - slow wandering on hard tasks;
  - malformed action JSON caused premature aborts.

### C002: budgeted repair

Purpose: keep C001 trace/gate guarantees while improving operational behavior.

Features added:

- robust action-JSON extraction and control-character/newline repair;
- task-class budgets: `simple_file`, `code_debug`, `browser_security`, `unknown`;
- faster auto-finish when required outputs and fresh evidence satisfy the runtime gate;
- repeated passive-action/no-progress accounting;
- summary-time infra classification for `/tests/test.sh` verifier-staging failures.

Implementation commit: `bea1ad2`.

Current live panel:

- Run root: `../runs/c002-10-20260523T213552Z/job` on Appzilla.
- Canonical runner hygiene: fresh job folder, `--n-concurrent 1`, `--no-delete`.
- Status at 2026-05-23 21:58 UTC: 8 completed, 1 infra/error, 1 running, 1 pending.
- Scored passes so far: `3`.
- Current scored mean: `0.375` over the scored subset Harbor has aggregated.

Passed tasks so far:

- `regex-log`
- `build-pmars`
- `fix-git`

Known failed scored tasks:

- `break-filter-js-from-html`
- `cancel-async-tasks`
- `extract-elf`
- `count-dataset-tokens`

Infra-classified task:

- `filter-js-from-html`: `infra_verifier_staging_missing_tests` (`/tests/test.sh` missing). This is not charged as a model failure in our analysis.

Still in flight at the snapshot:

- `query-optimize`
- one pending task from the 10-task panel.

## What improved in C002

C002 improved harness behavior even where reward remained zero:

- `break-filter-js-from-html` no longer burned 60 steps; it auto-finished quickly with traceable evidence.
- `cancel-async-tasks` no longer died on malformed JSON parser failure; parser recovery worked.
- `build-pmars`, `regex-log`, and `fix-git` passed.
- The runner anomaly `/tests/test.sh missing` was classified as infra, not as a model mistake.

## What C002 exposed

The next bottleneck is finish-policy quality, not plumbing.

Observed failures point to these C003 targets:

1. **Do not auto-finish code-debug tasks without a behavioral public check.**
   - `cancel-async-tasks` finished because `/app/run.py` existed, but verifier failed.
2. **Tighten required-output extraction.**
   - False positives such as `/app/e.g` and helper/input files can distort the finish gate.
3. **Require stronger checks for browser/security tasks.**
   - Exploratory checks passed, but verifier-equivalent browser behavior did not.
4. **Use task-class-specific finish criteria.**
   - `simple_file`: output exists + fresh check.
   - `code_debug`: tests or targeted reproduction must pass.
   - `browser_security`: provided test script or browser-equivalent assertion must pass.
   - `binary/reverse`: conservative required-output extraction.

## Runner hygiene discovery

We found a Harbor/TBench verifier-staging anomaly:

```text
RewardFileNotFoundError + /tests/test.sh: No such file or directory
```

The agent output existed and passed the pre-finish gate. The missing file was the verifier's `/tests/test.sh`, so this signature is infra/retryable.

Canonical rule now documented in `docs/runner-hygiene.md` and task `AGENTS.md`:

- fresh run root per Harbor job;
- `--job-name job` inside the timestamped root;
- `--n-concurrent 1` for diagnostics;
- `--no-delete` while debugging verifier-staging failures;
- run `summarize_job.py`, `validate_atif.py`, and `audit_no_secrets.py` before reporting;
- never broad-prune Docker on Appzilla.

## Trace-as-code artifact shape

Every successful agent trial writes:

- `agent/pi-style-trace.jsonl`
- `agent/trajectory.json` (ATIF)
- `agent/trace-code/trace.yaml`
- `agent/trace-code/ledger.jsonl`
- `agent/trace-code/state/final_state.json`
- `agent/trace-code/replay/replay_commands.sh`
- `agent/trace-code/analysis/scorecard.yaml`

These are the compact substrate for meta-optimization.

## Recommended C003 meta-optimization prompt

```text
Candidate: C002_budgeted_repair
Panel result: 3 scored passes so far, one infra verifier-staging failure, failures with trace-code artifacts.

Wins:
- regex-log, build-pmars, fix-git passed.
- parser recovery fixed malformed JSON aborts.
- budget profiles reduced wandering.
- infra classifier detected /tests/test.sh missing.

Losses:
- break-filter-js-from-html: auto-finished wrong browser/security payload.
- cancel-async-tasks: auto-finished code-debug task without meaningful public check.
- extract-elf/count-dataset-tokens: required-output extraction false positives and budget exhaustion.

Task:
Propose exactly one C003 patch touching only finish policy and required-output extraction.
Preserve C001/C002 trace/gate artifacts and direct Gemini API path.
Optimize expected reward on the same 10-task panel.
```

## Submission narrative

This project demonstrates that a small Gemini 3.5 Flash agent can be made substantially more inspectable and optimizable by moving intelligence into the harness:

- direct model API instead of brittle CLI automation;
- runtime-enforced action protocol;
- compact rolling state instead of unbounded transcript replay;
- finish gates and public-check freshness;
- trace-code artifacts for replay and failure analysis;
- candidate-by-candidate Meta-Harness iteration.

The result is a working scaffold for self-improving Terminal-Bench harnesses, not just a one-off benchmark run.
