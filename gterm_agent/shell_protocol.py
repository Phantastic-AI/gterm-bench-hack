from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from typing import Any, Literal

ActionName = Literal["read_file", "write_file", "list_files", "shell", "reflect", "finish", "abort"]

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
    valid = {"read_file", "write_file", "list_files", "shell", "reflect", "finish", "abort"}
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
    if action == "reflect":
        message = str(data.get("reflection") or data.get("message") or data.get("reason") or ledger or "")
        if not message.strip():
            raise ValueError("reflect action requires reflection/message text")
        return AgentAction("reflect", reason=message, message=message, ledger=ledger, raw=data)
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
    variants: list[str] = []
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    variants.append(raw)
    extracted = _extract_balanced_object(raw)
    if extracted and extracted not in variants:
        variants.append(extracted)
    sanitized = _escape_control_chars_in_strings(extracted or raw)
    if sanitized not in variants:
        variants.append(sanitized)
    stripped = _strip_bad_control_chars(extracted or raw)
    if stripped not in variants:
        variants.append(stripped)

    errors: list[str] = []
    for candidate in variants:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError as e:
            try:
                start = candidate.find("{")
                if start == -1:
                    raise
                decoder = json.JSONDecoder()
                obj, _end = decoder.raw_decode(candidate[start:])
            except Exception as inner:  # noqa: BLE001
                errors.append(str(inner or e))
                continue
        if not isinstance(obj, dict):
            raise ValueError("Gemini action JSON must be an object")
        return obj
    raise ValueError("Unable to parse action JSON after repair attempts: " + "; ".join(errors[-3:]))


def _extract_balanced_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def _strip_bad_control_chars(text: str) -> str:
    return "".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 32)


def _escape_control_chars_in_strings(text: str) -> str:
    out: list[str] = []
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                out.append(ch)
                escape = False
                continue
            if ch == "\\":
                out.append(ch)
                escape = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif ord(ch) < 32:
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
            continue
        if ch == '"':
            in_string = True
        out.append(ch)
    return "".join(out)
