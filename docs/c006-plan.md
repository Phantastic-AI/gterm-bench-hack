# C006 Hybrid Scoring Harness

## Intent

C006 recovers the C003/C004 single-action scoring behavior while keeping the useful C005 safeguards. It follows the Oracle recommendation in `docs/oracle-c006-review.md`: broad task-class policies, deterministic finish gates, compact host-side trace memory, and no benchmark-specific task-name hacks.

## Changes

- Candidate/version: `C006_hybrid_scoring` / `0.6.0-c006-hybrid-scoring`.
- Runtime prompt: one observable action per turn; broad `transaction` actions are rejected at runtime.
- Parser hardening: `write_file_b64` decodes base64 UTF-8 into a normal `write_file` action for code/HTML/SQL/regex payloads.
- Task classes:
  - `simple_file`
  - `answer_requires_computation`
  - `build_compile_install`
  - `code_debug`
  - `browser_security`
  - `data_query`
  - `binary_reverse`
  - `unknown`
- Finish policy: deterministic gates only; semantic critic remains available for research/tests but no longer approves completion in the live finish path.
- Auto-finish: non-output tasks can finish after a fresh meaningful behavioral check, preventing post-success wandering.
- No-progress: class-specific milestone actions reset no-progress, especially build/source/dependency/build/install/smoke steps.
- Required outputs: explicit `/usr/local/bin/...` install targets can be tracked, not only `/app/...` paths.

## Non-goals

- No task-name-specific patches.
- No hidden verifier feedback in live trajectories.
- No deep multi-agent planner/critic loop inside a single benchmark run.
- No debug files written into `/app` unless the task asks for them.

## Validation

Local unit coverage in `tests/test_harness_state_machine.py` checks:

- build/install and computation class routing;
- `write_file_b64` decoding;
- class-specific meaningful-check policy;
- no-output auto-finish after a meaningful build/install smoke check;
- existing transaction parser/dispatcher remains testable as a legacy helper but is no longer the runtime default.
