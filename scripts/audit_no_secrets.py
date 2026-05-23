#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PATTERNS = [
    re.compile(rb"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(rb"(?i)(GEMINI_API_KEY|GOOGLE_API_KEY)\s*=\s*[^.\s]+"),
]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in (argv or ["."])]
    secrets = [v.encode() for k, v in os.environ.items() if v and len(v) >= 8 and any(t in k.upper() for t in ("KEY", "TOKEN", "SECRET", "PASSWORD"))]
    findings: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in files:
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                data = path.read_bytes()
            except Exception:
                continue
            for pat in PATTERNS:
                if pat.search(data):
                    findings.append(str(path))
                    break
            else:
                if any(secret in data for secret in secrets):
                    findings.append(str(path))
    if findings:
        print("Secret-like content found in:", file=sys.stderr)
        for f in sorted(set(findings)):
            print(f"- {f}", file=sys.stderr)
        return 1
    print("no-secret audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
