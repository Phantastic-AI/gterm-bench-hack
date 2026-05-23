from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import redact_text


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TraceWriter:
    def __init__(self, logs_dir: Path, *, candidate_id: str, model: str, run_id: str | None = None):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.trace_dir = self.logs_dir / "trace-code"
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        for sub in ["steps", "observations", "files", "verification", "replay", "analysis"]:
            (self.trace_dir / sub).mkdir(exist_ok=True)
        self.candidate_id = candidate_id
        self.model = model
        self.run_id = run_id or f"run-{int(time.time())}"
        self.event_i = 0
        self.atif_steps: list[dict[str, Any]] = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.replay_commands: list[tuple[str, str]] = []
        self.status = "running"
        self.started_at = utc_now()
        self.log_path = self.logs_dir / "pi-style-trace.jsonl"

    def event(self, type_: str, **fields: Any) -> dict[str, Any]:
        self.event_i += 1
        event = {
            "ts": utc_now(),
            "event_id": f"{self.event_i:06d}",
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "type": type_,
            **_redact_obj(fields),
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    def write_task(self, instruction: str) -> None:
        (self.trace_dir / "task.md").write_text(redact_text(instruction), encoding="utf-8")
        self.event("task", instruction_chars=len(instruction))
        self.atif_steps.append({"step_id": len(self.atif_steps)+1, "timestamp": utc_now(), "source": "user", "message": redact_text(instruction, max_chars=12000)})

    def model_step(self, step_no: int, prompt: str, response: str, usage: dict[str, Any], latency_ms: int) -> None:
        prompt_tokens = int(usage.get("promptTokenCount") or usage.get("totalTokenCount") or 0)
        completion_tokens = int(usage.get("candidatesTokenCount") or 0)
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        payload = {"prompt_chars": len(prompt), "response": redact_text(response, max_chars=12000), "usage": usage, "latency_ms": latency_ms}
        (self.trace_dir / "steps" / f"{step_no:04d}.model.json").write_text(json.dumps(_redact_obj(payload), indent=2), encoding="utf-8")
        self.event("model_call", step=step_no, response_chars=len(response), usage=usage, latency_ms=latency_ms)
        self.atif_steps.append({
            "step_id": len(self.atif_steps)+1,
            "timestamp": utc_now(),
            "source": "agent",
            "model_name": self.model,
            "message": redact_text(response, max_chars=12000),
            "llm_call_count": 1,
            "metrics": {"prompt_tokens": prompt_tokens or None, "completion_tokens": completion_tokens or None},
        })

    def exec_step(self, step_no: int, command: str, cwd: str, timeout_sec: int, result: Any, duration_ms: int, purpose: str = "") -> None:
        stdout = redact_text(getattr(result, "stdout", "") or "", max_chars=30000)
        stderr = redact_text(getattr(result, "stderr", "") or "", max_chars=30000)
        rc = int(getattr(result, "return_code", -1))
        (self.trace_dir / "observations" / f"{step_no:04d}.stdout.headtail.txt").write_text(stdout, encoding="utf-8")
        (self.trace_dir / "observations" / f"{step_no:04d}.stderr.headtail.txt").write_text(stderr, encoding="utf-8")
        payload = {"command": command, "cwd": cwd, "timeout_sec": timeout_sec, "duration_ms": duration_ms, "return_code": rc, "purpose": purpose}
        (self.trace_dir / "steps" / f"{step_no:04d}.exec.json").write_text(json.dumps(_redact_obj(payload), indent=2), encoding="utf-8")
        self.event("tool_call", step=step_no, **payload, stdout_chars=len(stdout), stderr_chars=len(stderr))
        call_id = f"shell-{step_no:04d}"
        self.atif_steps.append({
            "step_id": len(self.atif_steps)+1,
            "timestamp": utc_now(),
            "source": "agent",
            "message": purpose or "shell action",
            "tool_calls": [{"tool_call_id": call_id, "function_name": "shell", "arguments": {"command": command, "cwd": cwd, "timeout_sec": timeout_sec}}],
            "observation": {"results": [{"source_call_id": call_id, "content": f"exit_code={rc}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"[:40000], "extra": {"return_code": rc, "duration_ms": duration_ms}}]},
            "llm_call_count": 0,
        })
        self.replay_commands.append((purpose, command))

    def finish(self, status: str, reason: str = "") -> None:
        self.status = status
        self.event("finish", status=status, reason=reason)
        (self.trace_dir / "trace.yaml").write_text(_yamlish({
            "schema": "gterm-trace/v0",
            "candidate_id": self.candidate_id,
            "model": self.model,
            "started_at": self.started_at,
            "ended_at": utc_now(),
            "status": status,
            "event_count": self.event_i,
        }), encoding="utf-8")
        (self.trace_dir / "harness.yaml").write_text(_yamlish({"candidate_id": self.candidate_id, "agent": "GeminiDirectAgent", "version": "0.1.0-c000", "max_steps": os.environ.get("GTERM_MAX_STEPS", "40")}), encoding="utf-8")
        (self.trace_dir / "ledger.jsonl").write_text((self.logs_dir / "pi-style-trace.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        replay = ["#!/usr/bin/env bash", "set -euo pipefail", "cd /app", ""]
        for purpose, command in self.replay_commands:
            replay.append(f"# {redact_text(purpose)}")
            replay.append(command)
            replay.append("")
        rp = self.trace_dir / "replay" / "replay_commands.sh"
        rp.write_text("\n".join(replay), encoding="utf-8")
        rp.chmod(0o755)
        (self.trace_dir / "analysis" / "failure_digest.md").write_text(f"# C000 trial digest\n\nStatus: {status}\n\nReason: {redact_text(reason)}\n\nSee `../ledger.jsonl` and `../replay/replay_commands.sh`.\n", encoding="utf-8")
        self._write_trajectory()

    def _write_trajectory(self) -> None:
        if not self.atif_steps:
            self.atif_steps.append({"step_id": 1, "timestamp": utc_now(), "source": "agent", "message": "no steps", "llm_call_count": 0})
        trajectory = {
            "schema_version": "ATIF-v1.7",
            "session_id": self.run_id,
            "trajectory_id": f"{self.run_id}-{self.candidate_id}",
            "agent": {"name": "gterm-gemini-direct", "version": "0.1.0-c000", "model_name": self.model},
            "steps": self.atif_steps,
            "notes": "C000 direct Gemini shell agent trajectory",
            "final_metrics": {"total_prompt_tokens": self.total_prompt_tokens or None, "total_completion_tokens": self.total_completion_tokens or None, "total_steps": len(self.atif_steps)},
            "extra": {"candidate_id": self.candidate_id, "status": self.status},
        }
        (self.logs_dir / "trajectory.json").write_text(json.dumps(trajectory, indent=2), encoding="utf-8")


def _redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redact_obj(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _redact_obj(v) for k, v in value.items()}
    return value


def _yamlish(d: dict[str, Any]) -> str:
    return "\n".join(f"{k}: {json.dumps(v) if not isinstance(v, (int, float)) else v}" for k, v in d.items()) + "\n"
