#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from gterm_agent.harbor_agent import GeminiDirectAgent
from gterm_agent.state import CANDIDATE_ID


def main() -> int:
    agent = GeminiDirectAgent(logs_dir=Path("/tmp/gterm-agent-import-check"), model_name="google/gemini-3.5-flash")
    print({
        "name": agent.name(),
        "version": agent.version(),
        "candidate_id": CANDIDATE_ID,
        "import_path": agent.import_path(),
        "supports_atif": agent.SUPPORTS_ATIF,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
