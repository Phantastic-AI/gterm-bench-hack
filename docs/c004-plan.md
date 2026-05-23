# C004 Behavior Repair Loop

Status: implemented locally; run evidence pending.

## Why C004 exists

C003 fixed a concrete harness regression: explicit output-file tasks such as `regex-log` must create the required artifact before finish. That made the `regex-log` smoke pass again.

The remaining recurring failures are not simple artifact-missing problems:

- `break-filter-js-from-html`: output exists but does not trigger the required browser/security behavior.
- `cancel-async-tasks`: basic tests pass, but cancellation semantics fail.
- `extract-elf`: expected script/artifact behavior is wrong or missing.

C004 adds a general repair loop for this class of failures.

## Harness changes

- Add behavior-repair rule to the system prompt.
- Add task policy for `code_debug`, `browser_security`, `binary_reverse`, and `data_query`: do not stop at file creation; repair failed behavior.
- Track the latest failed public/self-check digest in `AgentState`.
- After a failed public/self-check, force the next model turn to:
  1. extract the failing assertion/traceback/diff/missing behavior;
  2. patch the behavior named by the failure;
  3. rerun the focused check.
- Reject `finish` if the latest failed public/self-check has not been followed by a mutation/fresh repair.

## Boundary

C004 does **not** use hidden verifier tests. It only reacts to visible public/self-checks that the agent runs during the trial.

C004 is Codex-authored. Gemini 3.5 Flash is the task-solving model inside the harness. The Gemini-authored outer-loop proposal remains separately versioned under `candidates/G003_gemini_meta_proposal/`.

## Expected effect

C004 should help tasks where the model runs a public check, sees a failing assertion, and would otherwise finish or wander. It will not magically solve tasks where no meaningful public/self-check exists or where the model cannot infer the target behavior from visible files and task text.
