# n=5 Diagnostic Command

Run after C000 n=1 is clean:

```bash
cd /srv/appzilla/tbench-gemini-flash/repo
source ../.venv/bin/activate
set -a; source ../secrets.env; set +a
export PATH=/srv/appzilla/tbench-gemini-flash/bin:$PATH
export PYTHONPATH=$PWD
job="c000-n5-$(date -u +%Y%m%dT%H%M%SZ)"
harbor run -d terminal-bench/terminal-bench-2 \
  -i terminal-bench/regex-log -i terminal-bench/cancel-async-tasks -i terminal-bench/query-optimize -i terminal-bench/build-pmars -i terminal-bench/break-filter-js-from-html \
  --agent-import-path gterm_agent.harbor_agent:GeminiDirectAgent \
  -m google/gemini-3.5-flash \
  --jobs-dir ../runs/c000-n5 \
  --job-name "$job" \
  --n-concurrent 1 \
  --extra-docker-compose ../docker-compose-network-bridge.yaml \
  --yes
python scripts/audit_no_secrets.py ../runs/c000-n5/$job
```
