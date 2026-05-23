# Trace-as-Code Methodology

## Intent

Use Flow-World-style dehydration as an analysis primitive, not as a runtime.

The benchmark agent should leave behind an artifact that is small, deterministic-looking, and useful for failure analysis. Raw logs are too noisy; summaries alone erase the evidence Meta-Harness needs. Trace-as-code is the middle layer.

## Outputs per trial

```text
/logs/agent/
  log.jsonl                  # full agent event stream
  trajectory.json            # Harbor/ATIF-compatible trajectory when available
  trace-code/
    trace.yaml               # trial metadata and budgets
    harness.yaml             # candidate config and prompt hashes
    task.md                  # task instruction as seen by the agent
    ledger.jsonl             # phase/state ledger
    steps/
      0001.model.yaml
      0001.exec.yaml
      ...
    observations/
      0001.stdout.headtail.txt
      0001.stderr.headtail.txt
    files/
      touched-files.json
      final-file-hashes.json
      selected-diffs.patch
    verification/
      public-checks.jsonl
      final-result.json
    replay/
      replay_commands.sh
      replay_notes.md
    analysis/
      failure_digest.md
      scorecard.yaml
```

## Event stream

Every material event becomes JSONL:

```json
{
  "ts": "2026-05-23T19:00:00Z",
  "run_id": "tb2-smoke-5",
  "trial_id": "regex-log-1",
  "candidate_id": "C000_baseline",
  "event_id": "000012",
  "type": "tool_call",
  "phase": "ACT",
  "cwd": "/app",
  "command": "pytest -q",
  "timeout_sec": 120,
  "duration_ms": 1832,
  "exit_code": 1,
  "stdout_ref": "observations/0012.stdout.headtail.txt",
  "stderr_ref": "observations/0012.stderr.headtail.txt"
}
```

Important event types:

- `bootstrap`
- `model_call`
- `model_action`
- `tool_call`
- `state_update`
- `public_verify`
- `critic_gate`
- `finish`
- `abort`
- `error`

## Dehydration rules

Keep:

- task instruction;
- candidate ID and prompt/template hashes;
- shell commands, cwd, timeouts, durations, exit codes;
- stdout/stderr head+tail;
- file touch set and selected diffs;
- public test evidence;
- token/cost/latency metadata;
- final Harbor result;
- failure digest.

Drop or redact:

- API keys and host environment;
- raw giant logs by default;
- hidden verifier internals before the official verifier run;
- unrelated workspace files;
- provider/session internals that do not help reproduce the terminal behavior.

## Replay contract

`replay_commands.sh` is not a full model replay. It is a terminal-effect replay.

It should:

- run commands in the same order the agent ran them;
- include comments for model-generated intent;
- recreate file writes where safe;
- stop at the first mismatch unless explicitly invoked with `--best-effort` later;
- help a human or Meta-Harness proposer see where the terminal trajectory diverged from success.

## Failure digest

Each failed trial gets `analysis/failure_digest.md`:

```markdown
# Failure digest: regex-log / C000

## Outcome
Fail: verifier expected `/app/answer.txt`; agent wrote `/app/output.txt`.

## Strongest evidence
- Step 0008: public check passed only for local sample.
- Step 0010: critic gate did not check required output path.
- Final verifier: missing file.

## Harness hypothesis
The pre-finish checklist is too weak on exact output paths.

## Candidate fix
C003 should add an output-path assertion extracted from the task instruction before `finish`.
```

This file is the main input for the next Meta-Harness proposer iteration.
