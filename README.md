# gterm-bench-hack

Gemini 3.5 Flash + Terminal-Bench v2 harness experiments in the style of Meta-Harness.

## Goal

Hold the base model fixed as **Gemini 3.5 Flash** and optimize the surrounding terminal-agent harness for **Terminal-Bench v2**.

This repository will hold public-clean artifacts:

- harness code
- run configs
- submission metadata
- result summaries / leaderboard-ready result JSON
- reproducibility notes

Raw local secrets, API keys, private host paths, and benchmark oracle leakage do not belong here.

## Execution host

Heavy runs are staged on Appzilla under:

```text
/srv/appzilla/tbench-gemini-flash/
```

Appzilla is used because it has Docker, runsc/gVisor, and a large `/srv/appzilla` volume. Discovery/control-plane should not run full sweeps.

## Initial plan

1. H0: plain Gemini 3.5 Flash Terminal-Bench harness.
2. H1: environment-bootstrap harness inspired by Meta-Harness TB2 artifact.
3. Meta-Harness loop over candidate harness code:
   - propose
   - validate
   - evaluate on search slice
   - store full traces/source/scores
   - repeat
4. Add flow-like primitives only if Terminal-Bench traces justify them.

## Submission target

For TB2 leaderboard submission, use the Harbor/Terminal-Bench Hugging Face leaderboard dataset structure under:

```text
submissions/terminal-bench/2.0/<agent>__<model>/
```

Final target/version will be confirmed before submission.

## Current research docs

- [Custom Harness Plan](docs/custom-harness-plan.md)
- [Research Synthesis](docs/research-synthesis.md)
- [Trace-as-Code Methodology](docs/trace-as-code-methodology.md)
- [Ralph / oh-my-codex Lessons](docs/omx-ralph-lessons.md)
- [Oracle Master Plan](docs/oracle-master-plan.md)
- [Runner Strategy](docs/runner-strategy.md)
- [Appzilla Runbook](docs/appzilla-runbook.md)
- [Submission Notes](docs/submission.md)
- [C000 Smoke Results](docs/c000-smoke-results.md)
- [C001 System Prompt](docs/C001_LEDGER_VERIFY_SYSTEM_PROMPT.md)


## Documents
- [C001 runner hygiene](docs/runner-hygiene.md) — canonical isolated-job run layout and verifier-staging guardrails.
