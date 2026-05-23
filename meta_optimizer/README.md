# Gemini 3.5 Flash meta-optimizer

This is an outer-loop **proposal artifact** for T280. It does not modify or run the live Harbor harness.

The optimizer reads a compact C002 trace/result summary, asks `gemini-3.5-flash` to propose exactly one narrow harness patch, and saves the model output as reviewable artifacts.

It is intentionally separate from C003. A proposal becomes C003 only if a human/agent later integrates it into the live harness under the normal candidate workflow.

## Quick start

```bash
python3 meta_optimizer/gemini_meta_optimizer.py \
  --input meta_optimizer/samples/c002_compact_summary.json \
  --output-dir candidates/G003_gemini_meta_proposal
```

The script loads `GEMINI_API_KEY` or `GOOGLE_API_KEY` from the environment, then optionally from `.env` in the current directory, repo root, or the parent task directory.
