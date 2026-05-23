# C000 Smoke Results

Date: 2026-05-23 UTC.

Runner: Appzilla `/srv/appzilla/tbench-gemini-flash/repo`.

Agent: `gterm_agent.harbor_agent:GeminiDirectAgent`.

Model: `google/gemini-3.5-flash` via direct Gemini API.

## Verification before runs

```bash
python -m compileall -q gterm_agent scripts
python scripts/check_agent_import.py
python scripts/check_gemini_direct.py --model gemini-3.5-flash
python scripts/audit_no_secrets.py .
```

Evidence:

- agent import succeeded with `supports_atif=True`.
- direct Gemini smoke returned JSON `{ "ok": true }`.
- repo no-secret audit passed.

## n=1 green run

Job:

```text
../runs/c000-n1/c000-n1-regex-log-20260523T195320Z
```

Task:

```text
terminal-bench/regex-log
```

Result:

```text
trials: 1
exceptions: 0
mean reward: 1.000
reward: 1/1
runtime: 1m47s
```

Artifact evidence:

```text
regex-log__HNRoyz6/result.json
regex-log__HNRoyz6/verifier/reward.txt               # 1
regex-log__HNRoyz6/agent/pi-style-trace.jsonl         # 12 events
regex-log__HNRoyz6/agent/trajectory.json              # ATIF validated
regex-log__HNRoyz6/agent/trace-code/trace.yaml
regex-log__HNRoyz6/agent/trace-code/ledger.jsonl
regex-log__HNRoyz6/agent/trace-code/replay/replay_commands.sh
```

Post-run checks:

- no-secret audit passed on the run directory.
- ATIF trajectory validated with Harbor's `Trajectory` model.

## n=5 diagnostic run

Job:

```text
../runs/c000-n5/c000-n5-20260523T195545Z
```

Tasks:

```text
terminal-bench/break-filter-js-from-html
terminal-bench/build-pmars
terminal-bench/cancel-async-tasks
terminal-bench/query-optimize
terminal-bench/regex-log
```

Result:

```text
trials: 5
exceptions: 0
mean reward: 0.200
reward: 1/5
runtime: 7m01s
```

Per-task results:

```text
break-filter-js-from-html__wgxm9jM  reward 0  agent abort
build-pmars__L5sDYvK                reward 1  agent finish
cancel-async-tasks__csRUSMu         reward 0  agent finish
query-optimize__YFBHv4N             reward 0  agent finish
regex-log__gDqqrWM                  reward 0  agent finish
```

Artifact evidence:

- every n=5 trial produced `result.json`.
- every n=5 trial produced `agent/pi-style-trace.jsonl`.
- every n=5 trial produced `agent/trajectory.json`.
- every n=5 trial produced `agent/trace-code/trace.yaml`.
- every n=5 ATIF trajectory validated with Harbor's `Trajectory` model.
- no-secret audit passed on the n=5 run directory.

## First diagnostic conclusions

C000 is viable plumbing:

- Harbor custom agent import works.
- Direct Gemini API works under Harbor.
- Appzilla Docker/Compose bridge overlay works.
- Result artifacts, ATIF trajectories, Pi-style JSONL traces, and trace-code bundles are produced.
- No-secret audit is passing.

C000 is not yet a strong harness:

- One n=1 task passed, but the n=5 panel was only 1/5.
- The model can refuse benchmark security-style tasks (`break-filter-js-from-html`) without a benchmark-safe framing.
- The model can finish with weak verification on nontrivial tasks.
- `regex-log` passed in n=1 but failed in the n=5 retry, so variance and pre-finish checks need work.

Best next candidate:

```text
C001_ledger_verify
```

Candidate focus:

- extract exact required output paths from the task instruction;
- require a path-existence check before `finish`;
- require a public/self-check command before `finish`;
- add refusal-safe benchmark framing for controlled Terminal-Bench tasks without weakening external safety boundaries;
- summarize failure evidence from trace-code bundles into candidate scorecards.
