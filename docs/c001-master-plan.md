# C001 Ledger Verify Plan

C001 keeps the C000 direct Gemini + Harbor plumbing and adds runtime-enforced goal-loop discipline.

Implementation targets:

- Load `docs/C001_LEDGER_VERIFY_SYSTEM_PROMPT.md` into every Gemini call as the system prompt.
- Render each turn from compact state, not raw transcript replay.
- Keep live context under 80k tokens; raw history is offloaded to trace files.
- Add `AgentState` with required outputs, public checks, failure signatures, touched files, rolling ledger, and budgets.
- Add actions: `read_file`, `write_file`, `list_files`, `shell`, `finish`, `abort`.
- Add pre-finish gate: required outputs exist, checks/evidence are fresh, no forbidden actions happened.
- Add trace events: `state_update`, `model_action`, `public_verify`, `critic_gate`, `failure_signature`.

Validation plan:

```bash
python -m compileall -q gterm_agent scripts
python scripts/check_agent_import.py
python scripts/check_gemini_direct.py --model gemini-3.5-flash
python scripts/audit_no_secrets.py .
```

Then Appzilla:

```bash
harbor run -d terminal-bench/terminal-bench-2 \
  -i terminal-bench/regex-log \
  --agent-import-path gterm_agent.harbor_agent:GeminiDirectAgent \
  -m google/gemini-3.5-flash \
  --jobs-dir ../runs/c001-n1 \
  --job-name "c001-n1-regex-log-$(date -u +%Y%m%dT%H%M%SZ)" \
  --n-concurrent 1 \
  --extra-docker-compose ../docker-compose-network-bridge.yaml \
  --yes
```

Fixed n=5 panel remains:

- `terminal-bench/regex-log`
- `terminal-bench/cancel-async-tasks`
- `terminal-bench/query-optimize`
- `terminal-bench/build-pmars`
- `terminal-bench/break-filter-js-from-html`
