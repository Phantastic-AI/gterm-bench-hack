from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from typing import Any, Literal

ActionName = Literal["read_file", "write_file", "list_files", "shell", "finish", "abort"]

DENYLIST_PATTERNS = [
    re.compile(r"\b(printenv|env)\b.*\b(GEMINI|GOOGLE|KEY|TOKEN|SECRET)", re.I),
    re.compile(r"/(logs|tmp)/verifier\b", re.I),
    re.compile(r"\b(curl|wget|git)\b.*(tbench\.ai|terminal-bench|harbor-framework|github\.com)", re.I),
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
    message: str = ""
    ledger: str = ""
    path: str | None = None
    content: str | None = None
    max_bytes: int = 12000
    max_depth: int = 3
    is_public_check: bool = False
    raw: dict[str, Any] | None = None


def parse_action(text: str) -> AgentAction:
    data = _json_from_text(text)
    action = data.get("action")
    valid = {"read_file", "write_file", "list_files", "shell", "finish", "abort"}
    if action not in valid:
        raise ValueError(f"Invalid action {action!r}; expected one of {sorted(valid)}")
    ledger = str(data.get("ledger") or "")
    purpose = str(data.get("purpose") or ledger or "")
    if action == "shell":
        command = str(data.get("command") or "").strip()
        if not command:
            raise ValueError("shell action requires non-empty command")
        cwd = normalize_app_path(str(data.get("cwd") or "/app"), allow_file=False)
        timeout_sec = max(1, min(int(data.get("timeout_sec") or 120), 600))
        validate_command(command)
        return AgentAction("shell", command=command, cwd=cwd, timeout_sec=timeout_sec, purpose=purpose, ledger=ledger, is_public_check=bool(data.get("is_public_check") or data.get("public_check")), raw=data)
    if action == "read_file":
        path = normalize_app_path(str(data.get("path") or ""), allow_file=True)
        max_bytes = max(1, min(int(data.get("max_bytes") or 12000), 40000))
        return AgentAction("read_file", path=path, max_bytes=max_bytes, purpose=purpose, ledger=ledger, raw=data)
    if action == "write_file":
        path = normalize_app_path(str(data.get("path") or ""), allow_file=True)
        content = str(data.get("content") if data.get("content") is not None else "")
        if len(content.encode("utf-8")) > 256 * 1024:
            raise ValueError("write_file content exceeds 256KB C001 cap")
        return AgentAction("write_file", path=path, content=content, purpose=purpose, ledger=ledger, raw=data)
    if action == "list_files":
        path = normalize_app_path(str(data.get("path") or "/app"), allow_file=False)
        max_depth = max(1, min(int(data.get("max_depth") or 3), 6))
        return AgentAction("list_files", path=path, max_depth=max_depth, purpose=purpose, ledger=ledger, raw=data)
    reason = str(data.get("reason") or data.get("finish_reason") or data.get("message") or "")
    return AgentAction(action, reason=reason, message=str(data.get("message") or reason), ledger=ledger, raw=data)


def normalize_app_path(path: str, *, allow_file: bool) -> str:
    if not path:
        raise ValueError("path is required")
    path = path.strip()
    if path.startswith("~"):
        raise ValueError("home paths are not allowed")
    if not path.startswith("/"):
        path = "/app/" + path.lstrip("./")
    norm = posixpath.normpath(path)
    if norm != "/app" and not norm.startswith("/app/"):
        raise ValueError(f"path must stay under /app: {path}")
    if any(bad in norm for bad in ("/logs/verifier", "/tmp/verifier", "/.git")):
        raise ValueError(f"path is denied: {path}")
    if not allow_file and norm != "/app" and "." in posixpath.basename(norm):
        # Directories can contain dots, so this is advisory only; leave allowed.
        pass
    return norm


def validate_command(command: str) -> None:
    for pattern in DENYLIST_PATTERNS:
        if pattern.search(command):
            raise ValueError(f"Denied unsafe or leaderboard-invalid command: {command}")
    if "GEMINI_API_KEY" in command or "GOOGLE_API_KEY" in command:
        raise ValueError("Denied command mentioning Gemini/Google API key variables")


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
