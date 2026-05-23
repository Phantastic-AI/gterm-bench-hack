from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .gemini_client import GeminiClient
from .redaction import redact_text
from .shell_protocol import AgentAction, parse_action
from .trace_writer import TraceWriter


class GeminiDirectAgent(BaseAgent):
    SUPPORTS_ATIF = True
    SUPPORTS_WINDOWS = False

    def __init__(self, *args: Any, max_steps: int = 40, command_timeout_sec: int = 120, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_steps = int(max_steps)
        self.command_timeout_sec = int(command_timeout_sec)
        model = self.model_name or "google/gemini-3.5-flash"
        self.gemini_model = model.split("/", 1)[1] if model.startswith("google/") else model
        self.trace: TraceWriter | None = None

    @staticmethod
    def name() -> str:
        return "gterm-gemini-direct"

    def version(self) -> str | None:
        return "0.1.0-c000"

    async def setup(self, environment: BaseEnvironment) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "setup.txt").write_text("C000 direct Gemini agent: no in-container install required.\n", encoding="utf-8")

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        self.trace = TraceWriter(self.logs_dir, candidate_id="C000_baseline", model=self.gemini_model, run_id=environment.session_id)
        self.trace.write_task(instruction)
        client = GeminiClient(model=self.gemini_model)
        contents: list[dict[str, Any]] = []

        bootstrap = await self._exec(environment, "pwd; echo '---'; ls -la; echo '---'; find . -maxdepth 2 -type f | sed 's#^./##' | head -200", "/app", 60, "bootstrap environment")
        contents.append(_user_part(_initial_prompt(instruction, bootstrap)))

        consecutive_parse_errors = 0
        stop_reason = "budget exhausted"
        status = "abort"
        for step in range(1, self.max_steps + 1):
            prompt_text = contents[-1]["parts"][0]["text"]
            try:
                resp = client.generate(contents, temperature=0.2, max_output_tokens=4096)
                self.trace.model_step(step, prompt_text, resp.text, resp.usage, resp.latency_ms)
                action = parse_action(resp.text)
                consecutive_parse_errors = 0
            except Exception as e:  # noqa: BLE001
                consecutive_parse_errors += 1
                err = f"Could not parse or obtain action: {e}"
                self.trace.event("error", step=step, error=err)
                if consecutive_parse_errors >= 3:
                    stop_reason = err
                    break
                contents.append(_model_part(resp.text if 'resp' in locals() else ""))
                contents.append(_user_part(f"Your last response was invalid: {redact_text(err)}\nReturn only valid JSON with action shell, finish, or abort."))
                continue

            contents.append(_model_part(resp.text))
            if action.action == "finish":
                stop_reason = action.reason or "model finished"
                status = "finish"
                break
            if action.action == "abort":
                stop_reason = action.reason or "model aborted"
                break
            obs = await self._run_shell_action(environment, step, action)
            contents.append(_user_part(_observation_prompt(step, obs)))
        else:
            stop_reason = f"max_steps {self.max_steps} reached"

        self.trace.finish(status, stop_reason)
        context.n_input_tokens = self.trace.total_prompt_tokens or None
        context.n_output_tokens = self.trace.total_completion_tokens or None
        context.metadata = {"candidate_id": "C000_baseline", "status": status, "stop_reason": stop_reason, "trace": "agent/trace-code"}

    async def _run_shell_action(self, environment: BaseEnvironment, step: int, action: AgentAction) -> str:
        command = action.command or "true"
        cwd = action.cwd or "/app"
        timeout = action.timeout_sec or self.command_timeout_sec
        return await self._exec(environment, command, cwd, timeout, action.purpose or f"step {step}", step=step)

    async def _exec(self, environment: BaseEnvironment, command: str, cwd: str, timeout: int, purpose: str, step: int = 0) -> str:
        started = time.monotonic()
        try:
            result = await environment.exec(command, cwd=cwd, timeout_sec=timeout)
        except Exception as e:  # noqa: BLE001
            class _R:
                stdout = ""
                stderr = f"environment.exec exception: {e}"
                return_code = -1
            result = _R()
        duration_ms = int((time.monotonic() - started) * 1000)
        if self.trace:
            self.trace.exec_step(step, command, cwd, timeout, result, duration_ms, purpose)
        stdout = redact_text(getattr(result, "stdout", "") or "", max_chars=16000)
        stderr = redact_text(getattr(result, "stderr", "") or "", max_chars=16000)
        return f"purpose={purpose}\ncommand={command}\nexit_code={getattr(result, 'return_code', -1)}\nstdout:\n{stdout}\nstderr:\n{stderr}"


def _user_part(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def _model_part(text: str) -> dict[str, Any]:
    return {"role": "model", "parts": [{"text": text}]}


def _initial_prompt(instruction: str, bootstrap: str) -> str:
    return f"""You are C000, a direct Gemini terminal agent solving one Terminal-Bench task.

Rules:
- Work only inside the benchmark task environment, usually /app.
- Use shell commands to inspect, edit, build, and run public checks.
- Do not browse Terminal-Bench websites/repos or seek known answers.
- Do not print API keys or host env secrets.
- Before finishing, run the strongest public check you can find and verify requested output paths/formats.
- Return ONLY JSON. No markdown.

JSON actions:
{{"action":"shell","command":"...","cwd":"/app","timeout_sec":120,"purpose":"..."}}
{{"action":"finish","reason":"public checks pass and requested outputs are in place"}}
{{"action":"abort","reason":"..."}}

Task instruction:
{instruction}

Initial environment snapshot:
{bootstrap}

Choose the next single shell action."""


def _observation_prompt(step: int, obs: str) -> str:
    return f"""Observation from shell step {step}:
{obs}

Update your plan internally. Return the next single JSON action. If you are confident the task is complete, return finish only after verifying outputs/tests."""
