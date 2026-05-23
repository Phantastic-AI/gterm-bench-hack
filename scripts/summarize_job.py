#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

INFRA_SIGNATURES = (
    ("/tests/test.sh", "No such file or directory", "infra_verifier_staging_missing_tests"),
    ("RewardFileNotFoundError", "", "infra_reward_file_missing"),
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    args = ap.parse_args()
    job = Path(args.job_dir)
    result = read_json(job / "result.json")
    stats = result.get("stats", {})
    print(f"job: {job}")
    print(f"completed: {stats.get('n_completed_trials')} errors: {stats.get('n_errored_trials')} running: {stats.get('n_running_trials')} pending: {stats.get('n_pending_trials')}")
    evals = stats.get("evals") or {}
    for name, ev in evals.items():
        print(f"eval: {name}")
        print(f"  trials: {ev.get('n_trials')} errors: {ev.get('n_errors')} metrics: {ev.get('metrics')}")
        print(f"  rewards: {ev.get('reward_stats', {}).get('reward')}")
    for trial in sorted(p for p in job.iterdir() if p.is_dir() and not p.name.startswith("c00")):
        tr = read_json(trial / "result.json")
        reward = (trial / "verifier/reward.txt").read_text().strip() if (trial / "verifier/reward.txt").exists() else "?"
        meta = (tr.get("agent_result") or {}).get("metadata") or {}
        required = meta.get("required_outputs") or []
        checks = meta.get("public_checks") or []
        infra = classify_infra(trial)
        artifacts = {
            "result": (trial / "result.json").exists(),
            "trace": (trial / "agent/pi-style-trace.jsonl").exists(),
            "trajectory": (trial / "agent/trajectory.json").exists(),
            "trace_code": (trial / "agent/trace-code/trace.yaml").exists(),
            "final_state": (trial / "agent/trace-code/state/final_state.json").exists(),
        }
        print(f"trial: {trial.name}")
        print(f"  reward={reward} status={meta.get('status')} stop={meta.get('stop_reason')}")
        if infra:
            print(f"  infra_classification={infra}")
        print(f"  required_outputs={required}")
        print(f"  public_checks={len(checks)} artifacts={artifacts}")
    return 0


def classify_infra(trial: Path) -> str:
    texts = []
    for rel in ["verifier/test-stdout.txt", "exception.txt", "result.json"]:
        path = trial / rel
        if path.exists():
            texts.append(path.read_text(errors="replace")[:20000])
    blob = "\n".join(texts)
    for a, b, label in INFRA_SIGNATURES:
        if a in blob and (not b or b in blob):
            return label
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
