# C007.x honest optimization runbook

Goal: improve Gemini 3.5 Flash Terminal-Bench performance with generic agent-loop improvements only. No task-name solutions, no hidden verifier access, no reward hacking.

## Current candidate

- Repo: `Phantastic-AI/gterm-bench-hack`
- Harness import: `gterm_agent.harbor_agent:GeminiDirectAgent`
- Candidate id: `C007_trait_self_audit`
- Latest pushed commit: `cb9587c` (`Keep container exec hangs from wedging runs`)
- Latest 10-task run root: `/srv/appzilla/tbench-gemini-flash/runs/c00715-10-hosttimeout-composefix-20260524T063907Z`
- Best reliable observed full-verifier score on the 10-task panel: **2/10** in C007.12, passing `fix-git` and `regex-log`. Later C007.13 wedged in Harbor/container exec, and C007.15 stopped early after the Gemini key began returning HTTP 403 permission errors.

## Review gates before reruns

Every harness patch must pass:

```bash
python3 -m unittest tests/test_harness_state_machine.py -v
PYTHONPATH=$PWD python3 -m compileall -q gterm_agent scripts meta_optimizer
python3 scripts/audit_no_secrets.py gterm_agent tests docs/c006-plan.md
PYTHONPATH=$PWD python3 scripts/check_agent_import.py
```

Plus reviewer/critic check for:
- no task-name or known-answer overfit
- no hidden verifier access
- no keyword-only fake self-checks
- tests cover every new gate/exception

## C007.11 launch command

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
  --jobs-dir ../runs/c00711-10-<timestamp> \
  --job-name job \
  --n-concurrent 3 \
  --extra-docker-compose ../docker-compose-network-bridge.yaml \
  --no-delete --yes
```

## Generic improvements in C007.x

- Browser sanitizer:
  - Do not force early artifact writes during initial exploration.
  - After repeated passive exploration, force the declared deliverable path instead of rereading tests forever.
  - Require real pytest/Selenium/browser evidence before finish; reject echo/python/heredoc fake checks.
- Async cancellation:
  - Require structured cleanup counts and assertion evidence.
  - Accept file-backed test runs; reject echo/python/heredoc fake checks.
  - Require SIGINT/subprocess evidence when the prompt mentions keyboard interrupt.
- Simple artifacts:
  - Permit pure local capability probes when Python is unavailable, but block network/mutating chains.
  - Use low thinking to reduce Gemini Flash JSON truncation.
- Binary reverse:
  - Distinguish input paths from deliverables.
  - Let binary_reverse gate take precedence over noisy build_install traits.
  - Allow a short early inspection window before forcing required extractor artifact creation.
  - Require extractor-shaped execution plus JSON validation over the produced output; reject keyword/comment-only fake checks.
- Generic runtime loop:
  - Clamp tiny model-requested shell timeouts to a practical 30s floor while respecting the task budget.
  - Prevent git-repair observation noise from dynamically adding binary_reverse gates.
  - Feed failed deterministic auto-finish gates back as repair prompts so the model sees concrete missing evidence.

## Known run evidence

- C007.1 (`../runs/c0071-10-20260524T031159Z`): partial score 2 passes before replacement; passes included `fix-git`, `regex-log`; failures included `cancel-async`, `break-filter-js`, `extract-elf`.
- C007.4/C007.5: same two-pass pattern on scored partials, with better traces for async/browser/binary failures.
- C007.6/C007.7/C007.8/C007.10 were killed/replaced after generic fixes; each run root remains under `/srv/appzilla/tbench-gemini-flash/runs/` for trace review.
- C007.11 (`../runs/c00711-10-20260524T051302Z`, commit `55e52c7`): aggressive verifier timeout caused false verifier errors; only `fix-git` passed reliably.
- C007.12 (`../runs/c00712-10-fullverifier-20260524T054550Z`, commit `be68257`): full verifier, best reliable score **2/10**; passed `fix-git` and `regex-log`, failed the remaining visible 10-task panel.
- C007.13 (`../runs/c00713-10-fullverifier-20260524T062311Z`, commit `cb18bd8`): killed as stale/wedged; traces showed environment actions could run far past nominal shell timeouts.
- C007.14 (`../runs/c00714-10-hosttimeout-20260524T063722Z`, commit `cb9587c`): invalid infra run; Docker Compose CLI plugin was missing so all 10 errored before agent work.
- C007.15 (`../runs/c00715-10-hosttimeout-composefix-20260524T063907Z`, commit `cb9587c`): Docker Compose restored; run stopped after Gemini API began returning HTTP 403 `PERMISSION_DENIED`; first completed trials were aborted, not meaningful score evidence.

## Infrastructure notes from final reruns

- Appzilla needs Docker Compose v2 available as `docker compose`; restoring `~/.docker/cli-plugins/docker-compose -> /usr/local/bin/docker-compose` fixed C007.14's `unknown flag: --project-name` setup failures.
- C007.13 exposed a generic harness robustness issue: Harbor/container `environment.exec` can fail to yield prompt timeout evidence. Commit `cb9587c` adds a host-side `asyncio.wait_for` deadline and a focused hanging-environment regression test.
- Final blocker: Gemini API calls with the provided key returned HTTP 403 `PERMISSION_DENIED` during C007.15 and in direct `scripts/check_gemini_direct.py` smoke.

## Current honest read

The harness is submission-clean and well-tested, but Gemini 3.5 Flash remained weak on deep semantic repair tasks. The best reliable score on this 10-task slice is **2/10** (`fix-git`, `regex-log`) from C007.12. Do not add task-name or known-answer patches to chase the slice. With the hackathon Gemini key returning HTTP 403, further runs are blocked until credentials are refreshed.
