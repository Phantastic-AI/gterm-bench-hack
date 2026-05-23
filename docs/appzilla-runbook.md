# Appzilla Runbook

Workspace:

```bash
ssh appzilla
cd /srv/appzilla/tbench-gemini-flash
source .venv/bin/activate
```

Installed tooling:

- Python 3.12 via `uv python install 3.12`
- `harbor`
- `terminal-bench`

Safety policy:

- Start with one official oracle smoke task.
- Run concurrency 1 until stable.
- Keep raw outputs in `/srv/appzilla/tbench-gemini-flash/runs`.
- Never commit API keys or `.env` files.
- Prefer disposable/worker host for full sweeps.

Known Appzilla quirk:

- Appzilla currently has standalone `docker-compose`, but Harbor invokes `docker compose`.
- The Appzilla workspace provides a local `bin/docker` compatibility wrapper that translates `docker compose ...` to `docker-compose ...` when running Harbor from this workspace.
