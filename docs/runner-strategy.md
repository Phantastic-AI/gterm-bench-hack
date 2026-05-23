# Runner Strategy: Docker vs Daytona, Gemini CLI, and Expected Runtime

## Current Harbor support

Harbor `0.8.0` already exposes both pieces we care about:

- Agent: `--agent gemini-cli`
- Environment: `--env daytona`

Verified from installed Harbor on Appzilla:

```bash
harbor run --help
# Agent choices include: gemini-cli
# Environment choices include: docker, daytona, e2b, modal, runloop, gke, ...
```

The installed Gemini CLI adapter:

- installs Node 22 + `@google/gemini-cli` inside the task agent environment
- runs `gemini --yolo --model=<model> --prompt=<task>`
- forwards auth from host env vars:
  - `GEMINI_API_KEY`
  - `GOOGLE_API_KEY`
  - `GOOGLE_APPLICATION_CREDENTIALS`
  - `GOOGLE_CLOUD_PROJECT`
  - `GOOGLE_CLOUD_LOCATION`
  - `GOOGLE_GENAI_USE_VERTEXAI`
- writes logs under `/logs/agent/gemini-cli.txt`
- copies Gemini trajectory JSON/JSONL into `/logs/agent/` when available

The installed Daytona environment requires either:

- `DAYTONA_API_KEY`, or
- both `DAYTONA_JWT_TOKEN` and `DAYTONA_ORGANIZATION_ID`

Harbor's Daytona support is optional-extra backed. If `--env daytona` errors with a missing extra, install with the Daytona extra or install the `daytona` package in the Appzilla venv.

## Is Daytona better than local Docker?

For this project: **probably yes for full/search runs, but not necessary for first smoke.**

Local Docker on Appzilla is good for:

- quick oracle smoke
- verifying Harbor/TB/Gemini CLI plumbing
- debugging our harness
- runs where we want all artifacts on `/srv/appzilla`

Daytona is better for:

- stronger isolation from Appzilla host state
- disposable sandboxes
- fewer worries about Docker cleanup and host volume leakage
- parallel or longer-running benchmark sweeps

Tradeoff:

- Daytona adds another credential and cloud dependency.
- First failure mode becomes provider/sandbox provisioning instead of local Docker.
- We still need Appzilla as the orchestrator/log sink unless we upload directly to Harbor.

Recommended sequence:

1. Local Docker oracle smoke on Appzilla. Done: infrastructure now works with PATH compose wrapper.
2. Local Docker Gemini smoke on one task after API key is available.
3. Daytona smoke on the same task if Daytona credentials are available.
4. Choose runner for search/full sweep based on reliability and cost.

## Expected full-benchmark duration

Terminal-Bench v2 has 89 tasks in the Meta-Harness TB2 artifact reporting context. Each task can have large timeouts; the smoke task pulled by Harbor (`gpt2-codegolf`) declares:

- agent timeout: 900s
- verifier timeout: 900s
- build timeout: 600s

Sequential wall time depends heavily on Gemini behavior and task mix.

Reasonable planning estimates for **one attempt over 89 tasks sequentially**:

- optimistic average 5 min/task: ~7.5 hours
- moderate average 10 min/task: ~15 hours
- conservative average 15 min/task: ~22 hours
- worst-case near 900s agent timeout: ~22.25 hours before build/verifier overhead
- if many tasks hit agent + verifier/build ceilings, >24h is plausible

For leaderboard-style `--n-attempts 5`, multiply roughly by 5 if sequential:

- moderate: ~3 days
- conservative/worst: ~5 days

So full sequential runs are long. We should use:

- `-n 1` for first smokes
- small search slice for harness iteration
- parallelism only after one-task and three-task stability
- Daytona or another disposable environment for full sweeps if credentials permit

## Key handling

Do not commit keys. Preferred Appzilla location:

```bash
/srv/appzilla/tbench-gemini-flash/secrets.env
```

Permissions:

```bash
chmod 600 /srv/appzilla/tbench-gemini-flash/secrets.env
```

For Gemini API key, write both names to avoid adapter/client ambiguity:

```bash
GEMINI_API_KEY=...
GOOGLE_API_KEY=...
```

For Daytona, append if used:

```bash
DAYTONA_API_KEY=...
# or:
DAYTONA_JWT_TOKEN=...
DAYTONA_ORGANIZATION_ID=...
```

Run commands should load it explicitly:

```bash
set -a
source /srv/appzilla/tbench-gemini-flash/secrets.env
set +a
```

Do not copy `secrets.env` into this repo or task docs.

## Gemini smoke command shape

After `secrets.env` exists:

```bash
ssh appzilla
cd /srv/appzilla/tbench-gemini-flash
source .venv/bin/activate
export PATH=/srv/appzilla/tbench-gemini-flash/bin:$PATH
set -a; source secrets.env; set +a

harbor run \
  -d terminal-bench@2.0 \
  --agent gemini-cli \
  --model google/gemini-3.5-flash \
  --agent-kwarg reasoning_effort=medium \
  -l 1 \
  -n 1 \
  -o runs/gemini-smoke \
  --job-name gemini-35-flash-smoke-$(date -u +%Y%m%dT%H%M%SZ)
```

If the model alias is not accepted by Gemini CLI, adjust only the `--model` string after checking `gemini --help` / Gemini API docs. Keep the experiment model fixed once confirmed.

## Current Appzilla Docker note

Appzilla currently has standalone `docker-compose`, while Harbor invokes `docker compose`. The repo includes:

```text
scripts/docker-compose-compat
```

On Appzilla it is installed as:

```text
/srv/appzilla/tbench-gemini-flash/bin/docker
```

Use this for Harbor local-Docker runs until the Docker Compose plugin is installed system-wide:

```bash
export PATH=/srv/appzilla/tbench-gemini-flash/bin:$PATH
```
