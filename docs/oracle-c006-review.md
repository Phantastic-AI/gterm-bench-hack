# Oracle Review: C006 General Harness Direction

Date: 2026-05-24 UTC

Local full log: `../logs/oracle-c006-general-review-20260524T013834Z.log`

## Prompt framing

We asked Oracle for a general, non-benchmark-hacky review of the Terminal-Bench v2 harness direction for `gemini-3.5-flash`, including the C003/C004/C005 evidence and the current failure modes:

- C003/C004 preserved known scoring behavior better than C005.
- C005's broad transactions and semantic critic looked more agentic but regressed from ~3/10 to 2/10 confirmed passes.
- Key failures included build no-progress aborts, critic-approved but wrong code-debug output, simple-file overgeneralization to computation tasks, parser breakage on code-heavy JSON actions, required-path extraction mistakes, and weak browser/security validation.

## Verdict

Oracle agrees: **do not submit raw C005**. Build **C006 as C003/C004 scoring behavior plus selected C005 safeguards**.

The lesson is not “add more reflection.” The useful Meta-Harness pattern is candidate/evaluate/trace/improve. The live solver should stay tight and observable.

## Recommended C006 architecture

C006 should be:

> single-action disciplined agent + runtime class gates + compact host-side ledger

Inner loop:

```text
classify task broadly
observe compact state
one model-selected action
runtime executes action
runtime updates ledger/progress/gates
repeat
finish only through objective gate
```

Keep the loop boring. Avoid a new mini-agent framework.

## Priority patch list

1. **Recover C003-style single-action loop.** Keep required-output extraction, finish rejection, compact ledger, and post-success finish discipline. Disable broad transactions and critic-approved finish.
2. **Harden action parsing.** Prefer Gemini structured/function-call outputs long-term. Add `write_file_b64` / `append_file_b64` to avoid JSON escaping failures for code/HTML/SQL.
3. **Required-path extractor + finish latch.** Missing required paths always reject finish. Once an objective gate passes, force finish instead of allowing post-success wandering.
4. **Milestone-based no-progress.** Reset progress on class-specific milestones such as source tree found, dependency identified, new build error, test failure changed, query executed, or output created. No-progress should force replan before abort.
5. **Implement high-yield class gates first.** Start with `simple_artifact`, `answer_requires_computation`, `build_compile_install`, and `code_debug`; then add `browser_security` and `data_query`; keep `binary_reverse` thin.
6. **Host-side trace artifacts.** Preserve PLAN/DEBUG/DECISION spirit in host-side logs, not extra `/app` files unless the task asks for them.

## What not to do

- Do not key policies by task name.
- Do not let a semantic critic approve completion.
- Do not let file existence alone pass computation, code-debug, browser/security, SQL, or binary tasks.
- Do not write debug files into `/app` by default.
- Do not add a deep multi-agent planner/critic loop for C006.
- Do not broaden transactions.
- Do not over-invest in binary reverse tasks under time pressure.
- Do not feed hidden verifier results into live trajectories.

## General finish gates

| Class | Finish requires | Reject finish when |
| --- | --- | --- |
| `simple_artifact` | Required path exists; content non-empty unless explicitly allowed; obvious constraints satisfied; no placeholder/dummy text. | Missing file, placeholder/TODO, unrelated default content. |
| `answer_requires_computation` | Input/data inspected; computation command/script ran; answer exists; format matches; log supports answer. | Answer written before data inspection, empty/zero without evidence, no input-referencing computation. |
| `build_compile_install` | Source/package located; build/dependency commands attempted; relevant patch if needed; build succeeds; install target exists; `which`/path check and smoke run pass. | Only package probing, binary missing, build not run, smoke not run, same compiler error repeated without a patch. |
| `code_debug` | Relevant source changed; syntax/import check passes; failing behavior reproduced if feasible; targeted test/smoke passes after fix. | File merely exists, critic-only approval, no behavioral run, unrelated changes. |
| `browser_security` | Required output exists; adversarial payload check; benign-preservation check; output inspected for dangerous scripts/events/URLs as applicable. | Generic harmless dummy HTML, no adversarial/benign checks, unsafe payload survives when it should not. |
| `data_query` | Exact required query file exists; schema/data inspected; query parsed/executed; sample rows/counts checked; performance check if requested. | Wrong filename, no execution, schema guessed, SQL-ish text only. |
| `binary_reverse` | Binary identified with `file`/`readelf`/`strings`; extraction run against binary; output schema valid; rerun from clean output succeeds. | Output includes own helper/input filenames, binary never inspected, invalid JSON. |
| `unknown_complex` | Required paths satisfied; at least one domain-relevant self-check; concrete evidence tied to instruction. | Finish based only on confidence, critic approval, or file existence. |

## Submission narrative

C006 should be presented honestly as a harness-engineering result:

> C006 is a general-purpose direct-Gemini Terminal-Bench harness optimized around tight action/observation loops, objective finish evidence, and compact trace memory. Inspired by Meta-Harness, each candidate run preserves source, score summaries, and raw execution traces for subsequent harness improvement, but the live agent never receives hidden verifier feedback. The final design deliberately avoids per-task hacks: it uses broad task-class policies such as build/compile/install, answer-by-computation, code-debug, browser-security, data-query, and simple-artifact creation. The key engineering lesson was that Gemini Flash performed better with one observable action per turn and deterministic runtime gates than with broad transactions or semantic self-approval.

Also say the negative result plainly:

> C005 added more agentic machinery — transactions, durable decision logs, and a semantic critic — but regressed. C006 keeps the useful safeguards while returning to a simpler single-action loop. More reflection was not automatically better; observable state, structured actions, and class-specific verification mattered more.
