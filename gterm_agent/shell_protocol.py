from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from typing import Any, Literal

ActionName = Literal["shell", "finish", "abort"]

DENYLIST_PATTERNS = [
    re.compile(r"\b(printenv|env)\b.*\b(GEMINI|GOOGLE|KEY|TOKEN|SECRET)", re.I),
    re.compile(r"\bcat\s+/(logs|tmp)/verifier\b", re.I),
    re.compile(r"\b(curl|wget|git|python\s+-m\s+pip|pip)\b.*(tbench\.ai|terminal-bench|harbor-framework|github\.com)", re.I),
    re.compile(r"/var/run/docker\.sock"),
]


@dataclass
class AgentAction:
    action: ActionName
    command: str | None = None
    cwd: str = "/app"
    timeout_sec: int = 120
    purpose: str = ""
    reason: str = ""
    raw: dict[str, Any] | None = None


def parse_action(text: str) -> AgentAction:
    data = _json_from_text(text)
    action = data.get("action")
    if action not in {"shell", "finish", "abort"}:
        raise ValueError(f"Invalid action {action!r}; expected shell, finish, or abort")
    if action == "shell":
        command = str(data.get("command") or "").strip()
        if not command:
            raise ValueError("shell action requires non-empty command")
        cwd = str(data.get("cwd") or "/app")
        timeout_sec = int(data.get("timeout_sec") or 120)
        timeout_sec = max(1, min(timeout_sec, 600))
        validate_command(command)
        return AgentAction("shell", command=command, cwd=cwd, timeout_sec=timeout_sec, purpose=str(data.get("purpose") or ""), raw=data)
    return AgentAction(action, reason=str(data.get("reason") or data.get("finish_reason") or ""), raw=data)


def validate_command(command: str) -> None:
    for pattern in DENYLIST_PATTERNS:
        if pattern.search(command):
            raise ValueError(f"Denied unsafe or leaderboard-invalid command: {command}")
    if "GEMINI_API_KEY" in command or "GOOGLE_API_KEY" in command:
        raise ValueError("Denied command mentioning Gemini/Google API key variables")


def shell_wrap_json_probe(command: str) -> str:
    return "bash -lc " + shlex.quote(command)


def _json_from_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start == -1:
            raise
        decoder = json.JSONDecoder()
        obj, _end = decoder.raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise ValueError("Gemini action JSON must be an object")
    return obj
