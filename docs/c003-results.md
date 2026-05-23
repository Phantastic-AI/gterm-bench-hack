# C003 Adaptive Thinking Results

Status: **n=1 smoke failed; do not run n=10 yet.**

## What changed from C002

C003 is still one general harness, not per-task tuning. It adds automatic policy inside the harness:

- Gemini 3 `thinkingLevel` support.
- `medium` thinking for simple file-output tasks.
- `high` thinking for code/debug, SQL/data query, browser/security, binary/reverse, and unknown tasks.
- escalation to `high` after parse repair, finish-gate rejection, no-progress, or failure signatures.
- stricter finish policy: non-simple tasks need meaningful behavioral public checks, not just an existing output file.
- new task classes: `data_query`, `binary_reverse`.
- tighter required-output filtering for false positives like `e.g.`.

## 2026-05-23 regex-log smoke

Run:

```text
/srv/appzilla/tbench-gemini-flash/runs/c003-n1-20260523T222848Z/job
```

Result:

```text
Trials: 1
Exceptions: 0
Mean reward: 0.000
Trial: regex-log__Cbfq5Fk
Reward: 0
Agent status: abort
Stop reason: no-progress loop detected after 3 passive/repeated actions
ATIF validation: passed
Secret audit: passed
```

Classifier preflight was correct after the patch:

```text
CLASSIFIER simple_file 18 simple file-output task should finish after output plus fresh check
```

Final harness state confirmed:

```text
task_class: simple_file
required output: /app/regex.txt
exists: false
shell_calls: 4
model_calls: 3
```

Verifier failure was real benchmark failure, not Harbor test staging failure:

```text
AssertionError: Regex file /app/regex.txt does not exist
```

## Root cause

C003 classified the task correctly after the fix, but Gemini spent the simple task budget probing unavailable Python interpreters instead of writing `/app/regex.txt`. The no-progress guard then aborted before any mutation.

This means C003's adaptive-thinking policy is not enough by itself. The immediate issue is a simple-file action policy problem: for simple output tasks, the harness should bias the first model action toward writing the requested output file using available POSIX shell primitives, not exploratory interpreter checks.

## Decision

Do **not** run the 10-task C003 panel from this state. It would waste time and tokens.

Next candidate should be a small C003 follow-up or C004/C004-equivalent that adds a simple-file fast path / stronger system instruction for required-output tasks, then reruns this exact n=1 smoke.
