# Custom Harness Plan: Direct Gemini + Pi-Style Recorder

## Why move off `gemini-cli`

The hackathon key works against the Gemini API directly:

- `models` endpoint returned `models/gemini-3.5-flash`
- direct `generateContent` smoke to `models/gemini-3.5-flash` returned exactly `ok`
- usage metadata was returned, including prompt/output/thought token counts

The Harbor `gemini-cli` smoke reached Gemini, but got stuck in Gemini CLI tool behavior:

- agent install succeeded after Appzilla Docker networking was fixed
- CLI started solving `extract-elf`
- CLI attempted workspace glob outside `/app`
- CLI then invoked web search and hit repeated Gemini API `500 INTERNAL` errors

Conclusion: the API key/model are good; Gemini CLI is the wrong first harness surface for this hack.

## Proposed direction

Build our own Harbor-compatible installed/custom agent around the direct Gemini API, with a Pi-recorder-inspired trace format.

This does **not** mean using Flow World. It means borrowing the recorder discipline:

- every model call is an event
- every terminal command is an event
- every file edit/check/verifier attempt is an event
- events are JSONL and replayable enough for Meta-Harness proposer inspection
- the proposer optimizes harness code from raw traces, not summaries

## Minimal agent loop H0

Inside the Terminal-Bench task environment:

1. Observe task instruction.
2. Observe environment snapshot:
   - `pwd`
   - `ls -la`
   - selected `find` depth 2
   - tool availability (`python3`, `node`, `gcc`, `make`, `pytest`, etc.)
3. Ask Gemini for next action in strict JSON:

```json
{
  "thought_summary": "short private-free rationale",
  "action": "shell|finish",
  "command": "...",
  "finish_reason": "..."
}
```

4. If `shell`, run command with timeout and append stdout/stderr/exit code to state.
5. Repeat until `finish` or max turns.
6. Let Harbor verifier score the result.

## H1 environment-bootstrap harness

H1 is H0 plus a stronger first prompt:

- compact environment snapshot before first model turn
- known file list and sizes
- explicit task success criteria
- explicit instruction to verify by running local tests or checking output format before finish

This mirrors the high-signal Meta-Harness TB2 artifact idea without relying on Gemini CLI.

## Recorder event schema v0

Write JSONL to `/logs/agent/pi-style-trace.jsonl` and mirror into run artifacts.

```json
{
  "ts": "2026-05-23T19:00:00Z",
  "run_id": "...",
  "trial_id": "...",
  "candidate_id": "H0",
  "event_id": "000001",
  "parent_event_id": null,
  "type": "model_call|tool_call|state_update|decision|finish|error",
  "phase": "observe|plan|act|verify|finish",
  "payload": {},
  "metrics": {}
}
```

For model calls, store:

- model name
- prompt hash
- redacted prompt or full prompt depending on submission policy
- response text
- parsed JSON
- usage metadata
- latency
- error/retry info

For shell calls, store:

- command
- cwd
- timeout
- exit code
- stdout/stderr paths or truncated inline output
- latency

## Why this fits Meta-Harness

Candidate harnesses become normal code directories:

```text
candidates/H0-direct-gemini/
  agent.py
  prompt.md
  notes.md
  eval/<task>/<attempt>/trace.jsonl
```

The proposer can inspect traces and patch harness code directly.

## Immediate implementation target

Create `agent.py` exposing a Harbor custom agent import path. The first version can be minimal and ugly, but must be:

- direct Gemini API, no Gemini CLI
- no web search/tool side effects except shell commands in task container
- trace JSONL written every turn
- token usage recorded from Gemini API response
- model fixed to `gemini-3.5-flash`

Smoke command target:

```bash
harbor run \
  -d terminal-bench@2.0 \
  --agent-import-path agent:AgentHarness \
  -i extract-elf \
  -n 1 \
  --extra-docker-compose /srv/appzilla/tbench-gemini-flash/docker-compose-network-bridge.yaml \
  -o runs/direct-gemini-smoke \
  --job-name direct-gemini-35-flash-extract-elf-$(date -u +%Y%m%dT%H%M%SZ)
```
