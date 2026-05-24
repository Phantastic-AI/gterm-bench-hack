# C007.x honest optimization runbook

Goal: improve Gemini 3.5 Flash Terminal-Bench performance with generic agent-loop improvements only. No task-name solutions, no hidden verifier access, no reward hacking.

## Current candidate

- Repo: `Phantastic-AI/gterm-bench-hack`
- Harness import: `gterm_agent.harbor_agent:GeminiDirectAgent`
- Candidate id: `C007_trait_self_audit`
- Latest deployed commit on Appzilla for C007.4: `1686157`
- Latest 10-task run root: `/srv/appzilla/tbench-gemini-flash/runs/c0074-10-20260524T035115Z`

## Review gates before reruns

Every harness patch must pass:

```bash
python3 -m unittest tests/test_harness_state_machine.py -v
PYTHONPATH=$PWD python3 -m compileall -q gterm_agent scripts meta_optimizer
python3 scripts/audit_no_secrets.py gterm_agent tests docs/c006-plan.md
python3 scripts/check_agent_import.py
```

Plus reviewer/critic check for:
- no task-name or known-answer overfit
- no hidden verifier access
- no keyword-only fake self-checks
- tests cover every new gate/exception

## C007.4 launch command

```bash
harbor run -d terminal-bench/terminal-bench-2 \
  -i terminal-bench/regex-log \
  -i terminal-bench/cancel-async-tasks \
  -i terminal-bench/query-optimize \
  -i terminal-bench/build-pmars \
  -i terminal-bench/break-filter-js-from-html \
  -i terminal-bench/gpt2-codegolf \
  -i terminal-bench/extract-elf \
  -i terminal-bench/filter-js-from-html \
  -i terminal-bench/fix-git \
  -i terminal-bench/count-dataset-tokens \
  --agent-import-path gterm_agent.harbor_agent:GeminiDirectAgent \
  -m google/gemini-3.5-flash \
  --ak max_steps=70 \
  --ak command_timeout_sec=120 \
  --jobs-dir ../runs/c0074-10-<timestamp> \
  --job-name job \
  --n-concurrent 4 \
  --verifier-timeout-multiplier 0.35 \
  --extra-docker-compose ../docker-compose-network-bridge.yaml \
  --no-delete --yes
```

## Generic improvements added after C007.1/C007.2 traces

- Browser sanitizer: do not force early artifact writes; require real pytest/Selenium/browser evidence before finish; reject echo/python/heredoc fake checks.
- Async cancellation: require structured cleanup counts and assertion evidence; accept file-backed test runs, reject echo/python/heredoc fake checks.
- Simple artifacts: permit pure local capability probes when Python is unavailable, but block network/mutating chains; lower simple-file thinking to reduce Gemini Flash JSON truncation.
- Binary reverse: distinguish input paths from deliverables; require extractor-shaped execution plus JSON validation over output; reject keyword/comment-only fake checks.

## Known run evidence

- C007.1 (`../runs/c0071-10-20260524T031159Z`): partial score 2/5 when killed/replaced; passes included `fix-git`, `regex-log`; failures included `cancel-async`, `break-filter-js`, `extract-elf`.
- C007.2/C007.3 were smoke/probe runs killed stale after generic fixes; traces informed the above patches.
- C007.4 is the current clean 10-task run.
