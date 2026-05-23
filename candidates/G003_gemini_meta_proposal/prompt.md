Review this compact C002 trace/result summary and propose one narrow harness patch.

Required output JSON schema:
{
  "proposal_title": "short title",
  "candidate_boundary": "state clearly: proposal artifact only; not the actual C003 unless integrated later",
  "problem_observed": "specific behavior from the summary",
  "narrow_patch": "one general harness change",
  "files_likely_touched_if_integrated": ["example/path.py"],
  "implementation_sketch": ["step 1", "step 2", "step 3"],
  "validation_plan": ["syntax/test/check 1", "runtime/evidence check 2"],
  "risks": ["risk 1"],
  "anti_overfit_checks": ["check 1", "check 2"],
  "expected_effect": "one sentence"
}

C002 summary:
--- BEGIN SUMMARY ---
{
  "candidate": "C002_budgeted_repair",
  "source": "docs/c002-results.md live snapshot 2026-05-23 21:58 UTC",
  "status": "panel in progress at snapshot",
  "run_root": "../runs/c002-10-20260523T213552Z/job",
  "scored_mean_so_far": 0.375,
  "counts": {
    "completed": 8,
    "errors": 1,
    "running": 1,
    "pending": 1
  },
  "reward_1_tasks": [
    "regex-log",
    "build-pmars",
    "fix-git"
  ],
  "reward_0_tasks": [
    "break-filter-js-from-html",
    "cancel-async-tasks",
    "extract-elf",
    "count-dataset-tokens"
  ],
  "infra_classified": [
    {
      "task": "filter-js-from-html",
      "classification": "infra_verifier_staging_missing_tests"
    }
  ],
  "lessons_for_next_candidate": [
    "Parser recovery worked: malformed JSON/control-character abort did not recur as a harness-stopping error.",
    "Budgeting worked operationally: hard tasks stopped faster and produced final state artifacts.",
    "Auto-finish is too permissive for code-debug and browser/security tasks.",
    "Required-output extraction needs stricter negative-context filtering.",
    "Infra classification should become a runner-side retry policy."
  ],
  "constraints_for_optimizer": [
    "Propose one narrow harness patch only.",
    "Do not hardcode task IDs, known solutions, leaderboard artifacts, or hidden-verifier assumptions.",
    "Do not edit live harness files as part of this artifact.",
    "Prefer general behavior changes with clear validation evidence."
  ]
}

--- END SUMMARY ---
