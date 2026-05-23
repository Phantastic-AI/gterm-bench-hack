from __future__ import annotations

import os
import re

SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?i)(gemini|google|api)[_-]?(key|token|secret)\s*=\s*[^\s'\"]+"),
]


def _known_secret_values() -> list[str]:
    values: list[str] = []
    for key, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        upper = key.upper()
        if any(term in upper for term in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            values.append(value)
    return values


def redact_text(text: str | None, *, max_chars: int | None = None) -> str:
    if text is None:
        return ""
    out = str(text)
    for secret in _known_secret_values():
        out = out.replace(secret, "[REDACTED_SECRET]")
    for pattern in SECRET_PATTERNS:
        out = pattern.sub("[REDACTED_SECRET]", out)
    if max_chars is not None and len(out) > max_chars:
        head = max_chars // 2
        tail = max_chars - head
        out = out[:head] + f"\n...[truncated {len(out) - max_chars} chars]...\n" + out[-tail:]
    return out
