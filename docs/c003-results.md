# C003 Adaptive Thinking Results

Status: implementation ready; Appzilla runs pending.

## What changed from C002

C003 is still one general harness, not per-task tuning. It adds automatic policy inside the harness:

- Gemini 3 `thinkingLevel` support.
- `medium` thinking for simple file-output tasks.
- `high` thinking for code/debug, SQL/data query, browser/security, binary/reverse, and unknown tasks.
- escalation to `high` after parse repair, finish-gate rejection, no-progress, or failure signatures.
- stricter finish policy: non-simple tasks need meaningful behavioral public checks, not just an existing output file.
- new task classes: `data_query`, `binary_reverse`.
- tighter required-output filtering for false positives like `e.g.`.

## Planned evidence

- [ ] n=1 smoke on `regex-log` under `../runs/c003-n1-<timestamp>/job`.
- [ ] n=10 same diagnostic batch as C002 under `../runs/c003-10-<timestamp>/job`.
- [ ] `summarize_job.py` output.
- [ ] `validate_atif.py` output.
- [ ] `audit_no_secrets.py` output.
- [ ] comparison against C002 snapshot.
