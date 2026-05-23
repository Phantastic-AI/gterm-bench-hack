# Oracle Master Plan

Source: browser-mode Oracle (`@steipete/oracle@0.13.0`) on Discovery Two, model `gpt-5.5-pro`, remote Chrome `127.0.0.1:9223`.

Date: 2026-05-23 UTC.

Status: advisory. Treat this as a planning artifact; verify every Harbor/Gemini/leaderboard command against installed tooling before official runs.


# Master plan for `Phantastic-AI/gterm-bench-hack`

## 1. Verdict

Build a **custom Harbor external agent** that calls the **Gemini API directly** and executes shell actions through Harbor’s `BaseEnvironment`, with a repo-native trace layer that emits both Harbor-compatible `trajectory.json` and your own dehydrated “trace-as-code” artifacts. This is the right architecture because Harbor is the official Terminal-Bench 2.0 harness, supports custom agents without modifying Harbor source, and its external-agent interface lets the API key stay on the Appzilla host instead of being injected into benchmark containers. Gemini 3.5 Flash’s direct API model ID is `gemini-3.5-flash`, and Google describes it as optimized for agentic/coding/long-horizon tasks, so the core bet should be: **Gemini model capability + disciplined terminal harness + analyzable failures**, not `gemini-cli`, not Flow World runtime. ([Harbor][1])

---

## 2. Phase plan

### Phase 0 — Repo skeleton and docs

Create the public repo as a **submission/runbook/research repo**, not a pile of scripts.

Recommended tree:

```text
gterm-bench-hack/
  README.md
  docs/
    ARCHITECTURE.md
    APPZILLA_RUNBOOK.md
    HARBOR_NOTES.md
    GEMINI_DIRECT_AGENT.md
    TRACE_AS_CODE.md
    META_HARNESS_PLAN.md
    SUBMISSION_NOTES.md
  gterm_agent/
    __init__.py
    harbor_agent.py
    gemini_client.py
    shell_protocol.py
    prompt_templates.py
    trace_writer.py
    redaction.py
    verifier_notes.py
  configs/
    tb2-smoke-1.job.yaml
    tb2-smoke-5.job.yaml
    tb2-full-local.job.yaml
  scripts/
    check_gemini_direct.py
    check_agent_import.py
    materialize_tb2_subset.py
    summarize_job.py
    audit_no_secrets.py
    audit_leaderboard_validity.py
  traces/
    .gitkeep
  candidates/
    C000_baseline/
    C001_env_bootstrap/
  runs/
    .gitkeep
  .gitignore
  pyproject.toml
```

Hard rule: `runs/`, `.env`, `secrets.env`, raw provider responses, and private full replay histories are ignored by default. Public artifacts should be redacted summaries plus selected trace-as-code bundles.

### Phase 1 — Custom direct agent

Implement `gterm_agent.harbor_agent:GeminiDirectAgent` as a Harbor **external** agent. Harbor documents custom external agents as `BaseAgent` implementations with `setup()` and `run(instruction, environment, context)`; they interact with the container via the environment interface. ([Harbor][2])

Command shape:

```bash
set -a
source /opt/appzilla/secrets.env
set +a

uv sync
uv run python scripts/check_gemini_direct.py --model gemini-3.5-flash
uv run python scripts/check_agent_import.py
```

Then:

```bash
harbor run \
  -d terminal-bench/terminal-bench-2 \
  --agent-import-path gterm_agent.harbor_agent:GeminiDirectAgent \
  -m google/gemini-3.5-flash \
  --jobs-dir runs/smoke-import
```

Treat `-m` as run metadata unless Harbor requires it for job config; the custom agent should read `GEMINI_API_KEY` from host env and call Google directly.

### Phase 2 — n=1 smoke

Run a single medium/easy task, sequentially, with conservative budgets. Do not optimize yet.

Success criteria:

```text
agent imports
Gemini API call succeeds
at least one shell action executes through Harbor
agent exits cleanly
Harbor verifier runs
trial has result.json
trial has agent/trajectory.json
trial has trace-as-code bundle
no API key appears anywhere under runs/
```

### Phase 3 — n=5 run

Run five intentionally diverse but not insane tasks. Start sequentially: `n_concurrent_trials: 1`. This gives clean failure reading and avoids Appzilla/Docker/API confounding.

Use a local subset job created by `scripts/materialize_tb2_subset.py` rather than depending on undocumented task-filter flags.

Suggested smoke panel:

```text
regex-log                 string parsing / simple file output
cancel-async-tasks        Python async / cleanup semantics
query-optimize            SQL optimization / correctness preservation
build-pmars               build/package/debug flow
break-filter-js-from-html security-style adversarial artifact, controlled benchmark only
```

These tasks are present in the Terminal-Bench 2.0 task list and cover parsing, Python, SQL, compilation, and adversarial/security-flavored reasoning without immediately jumping to extreme QEMU/video/model-training tasks. ([Terminal-Bench][3])

Command shape:

```bash
uv run python scripts/materialize_tb2_subset.py \
  --dataset terminal-bench/terminal-bench-2 \
  --tasks regex-log,cancel-async-tasks,query-optimize,build-pmars,break-filter-js-from-html \
  --out .cache/tb2-smoke-5

harbor run \
  -p .cache/tb2-smoke-5 \
  --agent-import-path gterm_agent.harbor_agent:GeminiDirectAgent \
  -m google/gemini-3.5-flash \
  --jobs-dir runs/tb2-smoke-5 \
  --n-concurrent 1
```

If `--n-concurrent` is not accepted by the installed Harbor CLI, use the equivalent job config field; Harbor’s docs show local benchmark jobs, job directories, and result structures, but the exact installed CLI flags should be verified on Appzilla via `harbor run --help`. ([Harbor][4])

### Phase 4 — Meta-harness iteration

Freeze the n=5 panel. Create candidate harness versions under `candidates/C###`. Each candidate may change prompts, observation truncation, bootstrap context, self-verification policy, command timeout policy, and critic gates. It may not hardcode task IDs, task-specific file names beyond what the task instruction gives at runtime, or known solutions.

Loop:

```text
propose candidate harness
run fixed n=5 panel
write scorecard.yaml
write failure_digest.md
audit no leakage / no task-specific cheating
promote only if better pass rate or equal pass rate with materially better cost/time/reliability
```

Meta-Harness’s core lesson is directly applicable: optimize the harness code around a fixed model using source, scores, and execution traces as filesystem-visible search material, while auditing for benchmark-specific overfitting/leakage. ([arXiv][5])

### Phase 5 — Full bench / submission packaging

Only after the n=5 loop stabilizes:

```text
run full Terminal-Bench 2.0 locally
run with official timeout/resource defaults
do not use timeout/resource overrides
collect full job directory
validate result.json and trajectory artifacts
prepare metadata.yaml
audit no Terminal-Bench website/GitHub access during agent run
```

Important: the public Terminal-Bench 2.0 Hugging Face leaderboard page currently says submissions are closed while a new process is being prepared, and its stated validation rules include no timeout/resource overrides, valid trial results/artifacts, minimum five trials per task, and no access to Terminal-Bench website/GitHub by agents. Treat hackathon packaging and official leaderboard packaging as separate until that process reopens. ([Hugging Face][6])

---

## 3. Minimal custom agent architecture

### `GeminiDirectAgent`

Use Harbor external-agent mode.

Responsibilities:

```text
setup(environment)
  - no package installs unless required
  - initialize trace writer
  - optionally collect safe environment bootstrap via environment.exec

run(instruction, environment, context)
  - create initial prompt from task instruction + bootstrap snapshot
  - loop until finish/abort/timeout
  - ask Gemini for next action
  - validate action
  - execute shell command through environment
  - append observation
  - update ledger
  - periodically self-verify
  - finish so Harbor verifier can run
  - populate context metrics and trajectory
```

### Gemini API client

Use direct `generateContent` against `gemini-3.5-flash`.

Configuration:

```text
model: gemini-3.5-flash
default sampling params
thinking_level: high, if supported by installed SDK/API path
max output: bounded, not 65k by default
full conversation history preserved inside the run
```

Google’s Gemini 3.x docs recommend default sampling parameters and note that Gemini 3.5 Flash can use prior reasoning context when full unmodified history is preserved by the SDK/API history path. ([Google AI for Developers][7])

### Shell action protocol

Prefer native function/tool calling if the SDK is stable; otherwise strict JSON.

Minimum action schema:

```json
{
  "action": "shell",
  "command": "pytest -q",
  "cwd": "/app",
  "timeout_sec": 120,
  "purpose": "Run the public tests after implementing the fix"
}
```

Other actions:

```json
{ "action": "finish", "reason": "Public tests pass and required files are written" }
{ "action": "abort", "reason": "Budget exhausted or environment unrecoverable" }
```

Do not expose host shell. Do not mount Docker socket. Do not pass `GEMINI_API_KEY` into the sandbox.

### Timeout and safety

Initial defaults:

```text
max_steps: 80
max_model_calls: 80
default_command_timeout_sec: 120
hard_command_timeout_sec: 600
max_observation_chars_per_step: 30000
max_total_observation_chars: bounded by summarization/compression policy
loop detector: same command or same failing verifier pattern 3x => critic gate
```

Denylist:

```text
terminal-bench.org
tbench.ai
github.com/harbor-framework/terminal-bench
github.com/laude-institute/terminal-bench*
/logs/verifier before final verifier
host paths outside sandbox
printing env vars wholesale
```

The “no Terminal-Bench website/GitHub access” rule matters for leaderboard validity. ([Hugging Face][6])

### Observation window

Give the model:

```text
task instruction
bootstrap snapshot
current ledger
last N shell actions
current file tree summary
latest command stdout/stderr head+tail
public verification evidence
known failure hypotheses
```

Do **not** dump infinite terminal history. Terminal-Bench trials can run long and consume huge token volumes in extreme cases, so context discipline is not optional. ([arXiv][8])

### Verifier integration

During agent execution:

```text
run only public tests or commands explicitly available in the task environment
never inspect hidden verifier internals
record public test output as verification evidence
```

After agent returns, Harbor runs the verifier and writes verifier artifacts such as `reward.txt`, `test-stdout.txt`, and `test-stderr.txt` in the trial directory. Harbor’s documented job layout already expects agent and verifier outputs under each trial. ([Harbor][4])

### Logs

Emit three layers:

```text
agent/log.jsonl                 internal event log
agent/trajectory.json           Harbor ATIF-compatible trajectory
artifacts/trace-code/           dehydrated trace-as-code bundle
```

Harbor’s ATIF format captures messages, tool calls, observations, metrics, and supports validation; Harbor also automatically collects files written under `/logs/artifacts/`. ([Harbor][9])

---

## 4. Trace-as-code design

This is independent from Flow World. Use the idea only: **a compact executable-ish artifact that makes failures analyzable and partially replayable**.

### File layout per trial

```text
trace-code/
  trace.yaml
  harness.yaml
  task.md
  ledger.jsonl
  steps/
    0001.model.yaml
    0001.exec.yaml
    0002.model.yaml
    0002.exec.yaml
  observations/
    0001.stdout.txt
    0001.stderr.txt
  files/
    touched-files.json
    final-file-hashes.json
    selected-diffs.patch
  verification/
    public-checks.jsonl
    final-harbor-result.json
    verifier-stdout.txt
    verifier-stderr.txt
  replay/
    replay_commands.sh
    replay_notes.md
  analysis/
    failure_digest.md
    scorecard.yaml
```

### `trace.yaml`

```yaml
schema: gterm-trace/v0
trial_id: ...
task_id: regex-log
dataset: terminal-bench/terminal-bench-2
agent: GeminiDirectAgent
agent_version: C000
model: gemini-3.5-flash
started_at: ...
ended_at: ...
status: pass|fail|timeout|agent_error
reward: 0|1|null
budgets:
  max_steps: 80
  max_model_calls: 80
  default_command_timeout_sec: 120
redactions:
  api_keys: redacted
  env_vars: redacted
```

### What to record

Record:

```text
model ID and generation config
prompt template version/hash
task instruction
environment bootstrap snapshot
each shell command, cwd, timeout, duration, exit code
stdout/stderr head+tail plus full compressed local copy when safe
files touched
public tests run by the agent
final Harbor verifier result
token counts/cost if returned by API
stop reason
critic decisions
```

Do not record:

```text
GEMINI_API_KEY
raw host env
hidden verifier internals before completion
full massive workspace by default
unredacted provider internals that are not needed for public artifact
```

### What to dehydrate

The dehydrated artifact should be small enough for a proposer/critic to read:

```text
task instruction
harness config
step summaries
commands
exit codes
truncated observations
file touch set
verification evidence
failure digest
```

Full raw logs can stay local/private. Public repo gets dehydrated traces and selected failure bundles.

### Replay affordance

`replay_commands.sh` should replay the command sequence from a clean task container, with comments showing which commands were model-generated. This is not guaranteed to recreate model decisions; it should recreate terminal effects enough to debug shell mistakes.

Example:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /app

# step 0001: inspect files
ls -la

# step 0002: inspect tests
sed -n '1,200p' /app/test_outputs.py

# step 0003: write solution
cat > /app/regex.txt <<'EOF'
...
EOF
```

---

## 5. Meta-Harness adaptation for Terminal-Bench v2 + Gemini 3.5 Flash

### Candidate harness components

Search over these first:

```text
initial prompt structure
environment bootstrap snapshot
task classification: build/debug/data/security/sysadmin/etc.
ledger format shown to model
observation truncation/head-tail policy
command timeout policy
public verification cadence
critic-before-finish gate
loop detector
file tree summarizer
error recovery snippets
completion checklist
```

Do **not** search over:

```text
hardcoded task solutions
task-ID-specific prompts
known leaderboard answers
verifier leakage
external retrieval from Terminal-Bench repos/sites
timeout/resource overrides for leaderboard runs
```

Meta-Harness found value in TerminalBench-2 by searching harness behavior and using execution traces/source/scores as rich prior experience; it also explicitly discusses overfitting inspection and regex audits for task-specific leakage. ([arXiv][5])

### Scoring

Primary:

```text
pass_rate = passed_tasks / attempted_tasks
```

Secondary:

```text
valid_trial_rate
agent_crash_rate
mean wall-clock
mean model calls
mean prompt tokens
mean output tokens
mean shell steps
timeouts
no-secret audit pass/fail
leaderboard-validity audit pass/fail
```

For n=5, do not over-interpret. Use it to identify harness breakage and gross signal. For real claims, run a much larger panel and then full benchmark.

### Proposer/evaluator loop

```text
C000 baseline direct shell agent
C001 add env bootstrap snapshot
C002 improve observation truncation
C003 add critic-before-finish
C004 add public-test repair loop
C005 tune stop conditions
```

Each candidate directory contains:

```text
candidate.yaml
diff.patch
prompt_templates/
scorecard.yaml
failure_digest.md
accepted_or_rejected.md
```

Promotion rule:

```text
Promote if:
  pass count improves, OR
  same pass count with fewer invalid trials and materially lower cost/time.

Reject if:
  leakage audit fails,
  task-specific hardcoding appears,
  agent crash rate worsens,
  trace quality regresses.
```

---

## 6. Ralph / oh-my-codex adaptation

Use those ideas as **discipline inside the agent**, not as vibes.

### State machine

```text
BOOTSTRAP
  collect pwd, ls, language/package hints, key files

UNDERSTAND
  restate required outputs and constraints into ledger

PLAN
  write 3-7 step plan, identify public checks

ACT
  execute one shell action

OBSERVE
  summarize result, update touched files and hypothesis

VERIFY
  run public tests or direct sanity checks

REPAIR
  if verification fails, diagnose one concrete cause and patch

CRITIC_GATE
  before finish, ask: required files? tests? hidden constraints? accidental cheating?

FINISH
  return control to Harbor verifier

ABORT
  budget exhausted, unrecoverable environment, repeated loop
```

### Ledgers

Maintain `ledger.jsonl`:

```json
{"phase":"UNDERSTAND","required_outputs":["/app/regex.txt"],"constraints":["Python re.findall","last date on IPv4 line"]}
{"phase":"ACT","step":4,"command":"pytest -q","purpose":"run public tests"}
{"phase":"VERIFY","status":"failed","evidence":"expected 6 matches, got 5","next_fix":"handle multiple dates greedily"}
```

### Critic gates

Gate before finish:

```text
Have all required files been created?
Did we run the strongest available public check?
Are outputs in the exact requested path/format?
Did we accidentally depend on hidden state?
Are there background services that need to remain running?
Did we modify forbidden files?
Is the current solution robust to hidden tests?
```

Gate after repeated failure:

```text
Same error twice?
Same command twice?
Package install failing?
Need alternate implementation path?
Need inspect task files again?
```

### Stop conditions

```text
finish after public tests pass and checklist is clean
abort after max_steps
abort after repeated no-progress loop
abort after API budget exceeded
abort after environment unrecoverable
never continue “just in case” after clear completion
```

---

## 7. Exact n=5 smoke plan

### Task selection

Use this fixed panel:

```text
regex-log
cancel-async-tasks
query-optimize
build-pmars
break-filter-js-from-html
```

Why this panel:

```text
regex-log: fast parser task; validates basic write/run/verify loop
cancel-async-tasks: Python implementation; validates iterative code repair
query-optimize: correctness-preserving optimization; validates inspection discipline
build-pmars: system build/debug; validates package/build command loop
break-filter-js-from-html: adversarial artifact; validates security-task caution in sandbox
```

### Commands

```bash
set -a
source /opt/appzilla/secrets.env
set +a

uv sync

uv run python scripts/check_gemini_direct.py \
  --model gemini-3.5-flash

uv run python scripts/audit_no_secrets.py .

uv run python scripts/materialize_tb2_subset.py \
  --dataset terminal-bench/terminal-bench-2 \
  --tasks regex-log,cancel-async-tasks,query-optimize,build-pmars,break-filter-js-from-html \
  --out .cache/tb2-smoke-5

harbor run \
  -p .cache/tb2-smoke-5 \
  --agent-import-path gterm_agent.harbor_agent:GeminiDirectAgent \
  -m google/gemini-3.5-flash \
  --jobs-dir runs/tb2-smoke-5 \
  --n-concurrent 1

uv run python scripts/summarize_job.py runs/tb2-smoke-5
uv run python scripts/audit_no_secrets.py runs/tb2-smoke-5
uv run python scripts/audit_leaderboard_validity.py runs/tb2-smoke-5
```

### Success criteria

Infrastructure success:

```text
5/5 trials produce result.json
5/5 trials produce agent/trajectory.json
5/5 trials produce trace-code bundle
0 agent crashes
0 leaked secrets
0 invalid JSON/tool actions after retry
Harbor verifier runs for every trial
```

Performance smoke success:

```text
>=2/5 pass is good enough to continue optimization
1/5 pass is acceptable if failures are clearly harness-fixable
0/5 pass means stop and fix agent loop, not prompts
```

### Inspect after each run

For each trial:

```text
result.json: pass/fail/error/timeout
verifier/reward.txt
verifier/test-stdout.txt
verifier/test-stderr.txt
agent/trajectory.json validity
trace-code/analysis/failure_digest.md
last 5 shell commands
public tests run before finish
number of model calls
token usage
largest observation truncation
loop detector events
any denied command
files touched
```

Use Harbor’s viewer once artifacts are being produced; Harbor documents `harbor view jobs` for browsing trials, trajectories, timing, verifier output, and artifacts. ([Harbor][4])

---

## 8. Risks and mitigations

### Cost/time blowup

Risk: Terminal-Bench tasks can run long; the paper reports some trials reaching two hours, hundreds of calls, and nearly 100M tokens. ([arXiv][8])

Mitigation:

```text
start n=1, then n=5
sequential smoke
hard max_model_calls
hard max_steps
summarize observations
do not retry API forever
stop after completion checklist passes
track token usage per trial
```

### Gemini API 500s / transient failures

Mitigation:

```text
exponential backoff with jitter
max 3 retries per model call
record API errors in trace
on persistent 5xx, abort trial as agent_error, not infinite loop
never switch to gemini-cli fallback
```

### Sandbox safety

Mitigation:

```text
external Harbor agent only
API key stays on host
no key in container
no Docker socket in task container
prefer Docker/gVisor/runsc where Appzilla supports it
deny Terminal-Bench website/repo access
redact all env-like outputs
```

### Compose/DNS issues

Mitigation:

```text
document Appzilla fix: network_mode bridge overlay for Compose DNS
keep this in docs/APPZILLA_RUNBOOK.md
add preflight task that starts a multi-container env if needed
do not debug Compose during full runs
```

### Leaderboard validity

Mitigation:

```text
no timeout/resource overrides in official candidate run
no hidden-verifier inspection
no Terminal-Bench website/GitHub access by agent
five trials per task for official leaderboard packaging, if current rules remain
keep metadata.yaml ready but wait for reopened process
```

The current leaderboard page says submissions are closed and lists validation constraints, so keep the repo submission-ready but do not claim official leaderboard submission until the new process is available. ([Hugging Face][6])

### Overfitting

Mitigation:

```text
static lint candidate prompts for task IDs
regex audit for known task names and hardcoded paths not sourced from runtime instruction
require candidate diffs to be harness-general
hold back a second n=5 panel after C003
manually inspect winning candidate traces
```

---

## 9. Next coding goal-mode backlog

Do this in order:

```text
1. Create repo skeleton, pyproject, .gitignore, README, and docs stubs.

2. Implement scripts/check_gemini_direct.py:
   - reads GEMINI_API_KEY from env
   - calls models/gemini-3.5-flash
   - prints model, latency, short response
   - never logs key

3. Implement gterm_agent.gemini_client:
   - generateContent wrapper
   - retries
   - token/usage capture
   - redaction guard

4. Implement gterm_agent.shell_protocol:
   - strict action schema
   - parse/validate model action
   - denylist checks
   - timeout normalization

5. Implement gterm_agent.trace_writer:
   - log.jsonl
   - trace-code bundle
   - ATIF-compatible trajectory.json

6. Implement gterm_agent.harbor_agent:GeminiDirectAgent:
   - BaseAgent name/version/setup/run
   - environment bootstrap
   - action loop
   - ledger update
   - finish/abort handling
   - context metrics population

7. Implement scripts/audit_no_secrets.py:
   - scan repo/runs for GEMINI_API_KEY patterns
   - scan for actual key prefix if env present
   - fail closed

8. Implement scripts/materialize_tb2_subset.py:
   - create local Harbor dataset subset for five task IDs
   - emit configs/tb2-smoke-5.job.yaml

9. Run n=1 smoke:
   - fix import/env/path/logging issues only
   - no harness optimization yet

10. Run n=5 smoke:
    - summarize failures
    - write C000 scorecard
    - choose first two candidate harness changes
```

The core bet is simple: **C000 should be boring, valid, and inspectable. C001+ should improve only one harness dimension at a time.**

[1]: https://harborframework.com/docs/tutorials/running-terminal-bench "Running Terminal-Bench"
[2]: https://www.harborframework.com/docs/agents "Agents"
[3]: https://www.tbench.ai/benchmarks/terminal-bench-2 "Terminal-Bench"
[4]: https://www.harborframework.com/docs/run-jobs/run-evals "Evals"
[5]: https://arxiv.org/html/2603.28052v1 "Meta-Harness: End-to-End Optimization of Model Harnesses"
[6]: https://huggingface.co/datasets/alexgshaw/terminal-bench-2-leaderboard "harborframework/terminal-bench-2-leaderboard · Datasets at Hugging Face"
[7]: https://ai.google.dev/gemini-api/docs/interactions/whats-new-gemini-3.5 "Gemini Interactions API  |  Google AI for Developers"
[8]: https://arxiv.org/html/2601.11868v1 "Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces"
[9]: https://www.harborframework.com/docs/agents/trajectory-format "Agent Trajectory Format (ATIF)"


