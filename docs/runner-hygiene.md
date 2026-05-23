# C001 Runner Hygiene: Isolated Job Folders + Verifier Staging Guardrails

## Canonical recommendation

Use a **new run folder for every Harbor job**. Do not reuse a `--jobs-dir`/`--job-name` pair.

Recommended shape:

```bash
run_root="../runs/c001-n5-$(date -u +%Y%m%dT%H%M%SZ)"
job="job"
mkdir -p "$run_root"

harbor run -d terminal-bench/terminal-bench-2 \
  -i terminal-bench/regex-log \
  -i terminal-bench/cancel-async-tasks \
  -i terminal-bench/query-optimize \
  -i terminal-bench/build-pmars \
  -i terminal-bench/break-filter-js-from-html \
  --agent-import-path gterm_agent.harbor_agent:GeminiDirectAgent \
  -m google/gemini-3.5-flash \
  --ak max_steps=60 \
  --ak command_timeout_sec=120 \
  --jobs-dir "$run_root" \
  --job-name "$job" \
  --n-concurrent 1 \
  --extra-docker-compose ../docker-compose-network-bridge.yaml \
  --no-delete \
  --yes
```

This produces exactly one self-contained job directory:

```text
../runs/c001-n5-YYYYMMDDTHHMMSSZ/job/
```

Do **not** use a shared parent such as `../runs/c001-n5` with many timestamped children for final evidence. It is too easy to inspect the wrong child or mix partial artifacts.

## Why

Two C001 `regex-log` runs with normal delete mode produced infra failures:

```text
bash: line 1: /tests/test.sh: No such file or directory
RewardFileNotFoundError
```

The agent had already created and checked the required output (`/app/regex.txt`). The missing file was Harbor's verifier-side `/tests/test.sh`, not the task output. A diagnostic rerun with `--no-delete` passed reward `1.0`.

Root-cause classification:

- Not model failure.
- Not missing agent output.
- Not obvious stale agent state.
- Likely Harbor/Docker verifier test-staging or compose-copy visibility failure.

## Required run hygiene

1. **Fresh run root per job**: `../runs/<candidate>-<panel>-<timestamp>/job`.
2. **Unique Harbor job name inside that root**: use `--job-name job` when the root already has the timestamp.
3. **Sequential execution for diagnostics**: `--n-concurrent 1`.
4. **Keep containers while debugging verifier anomalies**: `--no-delete`.
5. **Post-run validation before reporting**:
   ```bash
   python scripts/summarize_job.py "$run_root/job"
   python scripts/validate_atif.py "$run_root/job"
   python scripts/audit_no_secrets.py "$run_root/job"
   ```
6. **Inspect verifier failures before scoring the agent**:
   ```bash
   find "$run_root/job" -path '*/verifier/test-stdout.txt' -print -exec sed -n '1,80p' {} \;
   find "$run_root/job" -path '*/exception.txt' -print -exec sed -n '1,80p' {} \;
   find "$run_root/job" -path '*/agent/trace-code/state/final_state.json' -print
   ```
7. **Classify this signature as infra/retryable**:
   ```text
   RewardFileNotFoundError + /tests/test.sh: No such file or directory
   ```
8. **Manual cleanup after evidence capture**: remove only containers/networks/volumes whose names match the current task/job trials. Never run broad Docker prune on Appzilla during shared use.

## Future Harbor-side hardening

Add a runner-side pre-verifier assertion after test upload and before verifier execution:

```bash
ls -la /tests && test -x /tests/test.sh
```

If that check fails, mark the trial as `infra_verifier_staging_failed` instead of charging it as an agent/model failure.
