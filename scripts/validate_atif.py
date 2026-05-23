#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from harbor.models.trajectories.trajectory import Trajectory


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="Harbor job/trial directory")
    args = ap.parse_args()
    root = Path(args.path)
    files = sorted(root.glob("*/agent/trajectory.json"))
    if root.name == "trajectory.json":
        files = [root]
    elif (root / "agent/trajectory.json").exists():
        files = [root / "agent/trajectory.json"]
    if not files:
        raise SystemExit(f"no trajectory.json files under {root}")
    for path in files:
        Trajectory.model_validate(json.loads(path.read_text()))
        print(f"valid {path}")
    print(f"validated {len(files)} ATIF trajector{'y' if len(files)==1 else 'ies'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
