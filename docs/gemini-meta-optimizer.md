# Gemini 3.5 Flash meta-optimizer artifact

This is a **proposal-only** outer loop for T280. It is deliberately isolated from the live Harbor harness.

Allowed write locations for this artifact:

- `meta_optimizer/**`
- `docs/gemini-meta-optimizer.md`
- optional generated proposal artifacts under `candidates/G003_gemini_meta_proposal/**`

It does **not** edit `gterm_agent/**`, does **not** run Harbor jobs, and is **not** the actual C003 unless integrated later.

## What it does

`meta_optimizer/gemini_meta_optimizer.py`:

1. reads a compact C002 trace/result summary from JSON or markdown;
2. builds a small optimizer prompt;
3. calls `gemini-3.5-flash` through the Gemini API;
4. asks for exactly one narrow, general harness patch proposal;
5. saves `proposal.json`, `proposal.md`, and `prompt.md` as review artifacts.

A sample C002 summary lives at:

```text
meta_optimizer/samples/c002_compact_summary.json
```

The sample is derived from `docs/c002-results.md` and includes the important C002 lessons: parser recovery helped, budgets helped, auto-finish was too permissive, required-output extraction needs stricter negative-context filtering, and infra classification should become runner-side retry policy.

## Run command

From repo root:

```bash
python3 meta_optimizer/gemini_meta_optimizer.py \
  --input meta_optimizer/samples/c002_compact_summary.json \
  --output-dir candidates/G003_gemini_meta_proposal
```

The script loads `GEMINI_API_KEY` or `GOOGLE_API_KEY` from the environment first, then from `.env` in the current directory, repo root, or parent task directory if present.

If no key is available and you only want to verify artifact writing without calling Gemini:

```bash
python3 meta_optimizer/gemini_meta_optimizer.py \
  --input meta_optimizer/samples/c002_compact_summary.json \
  --output-dir /tmp/gemini-meta-proposal \
  --offline-if-no-key
```

## Integration boundary

The output is a candidate proposal, not a patch. A future agent may review it and decide whether to implement it as C003/G003. That future integration must separately touch the live harness, run syntax/tests, and run Harbor diagnostics under the runner-hygiene rules.
