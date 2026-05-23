from __future__ import annotations

import base64
import json
import shlex
import time
from typing import Any

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from .gemini_client import GeminiClient
from .prompt_templates import load_system_prompt, render_turn_context
from .redaction import redact_text
from .shell_protocol import AgentAction, parse_action
from .state import (
    AGENT_VERSION,
    CANDIDATE_ID,
    AgentState,
    GateResult,
    PublicCheck,
    compact_text,
    extract_required_outputs,
    is_public_check_command,
)
from .trace_writer import TraceWriter


class GeminiDirectAgent(BaseAgent):
    SUPPORTS_ATIF = True
    SUPPORTS_WINDOWS = False

    def __init__(
        self,
        *args: Any,
        max_steps: int = 60,
        command_timeout_sec: int = 120,
        max_shell_calls: int = 120,
        max_wall_time_sec: int = 840,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.max_steps = int(max_steps)
        self.command_timeout_sec = int(command_timeout_sec)
        self.max_shell_calls = int(max_shell_calls)
        self.max_wall_time_sec = int(max_wall_time_sec)
        model = self.model_name or "google/gemini-3.5-flash"
        self.gemini_model = model.split("/", 1)[1] if model.startswith("google/") else model
        self.trace: TraceWriter | None = None
        self.system_prompt = load_system_prompt()

    @staticmethod
    def name() -> str:
        return "gterm-gemini-direct"

    def version(self) -> str | None:
        return AGENT_VERSION

    async def setup(self, environment: BaseEnvironment) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "setup.txt").write_text(
            f"{CANDIDATE_ID}: direct Gemini agent, no in-container install required.\n",
            encoding="utf-8",
        )

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        state = AgentState()
        state.required_outputs = extract_required_outputs(instruction)
        state.add_ledger(f"Initialized C001 with {len(state.required_outputs)} required output candidate(s).")
        self.trace = TraceWriter(self.logs_dir, candidate_id=CANDIDATE_ID, model=self.gemini_model, run_id=environment.session_id)
        self.trace.write_task(instruction)
        client = GeminiClient(model=self.gemini_model)

        bootstrap = await self._exec(
            environment,
            "pwd; echo '---'; ls -la; echo '---'; find . -maxdepth 3 -type f | sed 's#^./##' | head -240",
            "/app",
            60,
            "bootstrap environment",
            step=0,
            state=state,
        )
        bootstrap_digest = compact_text(bootstrap, 8000)
        last_action_result = bootstrap_digest
        forced_message: str | None = None
        stop_reason = "budget exhausted"
        status = "abort"

        for step in range(1, self.max_steps + 1):
            state.step = step
            if state.elapsed_sec() >= self.max_wall_time_sec:
                stop_reason = f"max_wall_time_sec {self.max_wall_time_sec} reached"
                state.abort_reason = stop_reason
                break
            if state.shell_calls >= self.max_shell_calls:
                stop_reason = f"max_shell_calls {self.max_shell_calls} reached"
                state.abort_reason = stop_reason
                break
            if state.no_progress_count >= 4:
                stop_reason = "no-progress loop detected"
                state.abort_reason = stop_reason
                break

            state.phase = self._choose_phase(state)
            if self.trace:
                self.trace.state_update(step, state.to_prompt_dict())
            prompt = render_turn_context(
                task_text=instruction,
                state=state,
                bootstrap_digest=bootstrap_digest,
                last_action_result=last_action_result,
                max_steps=self.max_steps,
                max_shell_calls=self.max_shell_calls,
                max_wall_time_sec=self.max_wall_time_sec,
                forced_message=forced_message,
            )
            forced_message = None

            try:
                resp = client.generate([_user_part(prompt)], temperature=0.1, max_output_tokens=8192, system_prompt=self.system_prompt)
                state.model_calls += 1
                if self.trace:
                    self.trace.model_step(step, prompt, resp.text, resp.usage, resp.latency_ms)
                action = parse_action(resp.text)
                state.parse_errors = 0
            except Exception as e:  # noqa: BLE001
                state.parse_errors += 1
                err = f"Could not obtain valid action: {e}"
                state.add_ledger(err)
                if self.trace:
                    self.trace.event("error", step=step, error=err)
                if state.parse_errors >= 3:
                    stop_reason = err
                    state.abort_reason = stop_reason
                    break
                forced_message = f"Your last response was invalid: {redact_text(err)}. Return exactly one JSON object using the C001 action protocol."
                last_action_result = forced_message
                continue

            state.last_action = action.raw or {"action": action.action}
            state.add_ledger(action.ledger or action.purpose or action.reason or action.message)
            if self.trace:
                self.trace.model_action(step, action.raw or {"action": action.action})

            if action.action == "finish":
                state.phase = "CRITIC_GATE"
                gate = await self._pre_finish_gate(environment, state, action.message or action.reason)
                if self.trace:
                    self.trace.critic_gate(step, gate.to_dict())
                if gate.ok:
                    status = "finish"
                    stop_reason = action.message or action.reason or "C001 pre-finish gate passed"
                    state.phase = "FINISH"
                    break
                state.phase = "REPAIR"
                state.repair_hypotheses.append(gate.reason)
                state.add_ledger(f"Finish rejected: {gate.reason}")
                forced_message = gate.repair_prompt()
                last_action_result = forced_message
                continue

            if action.action == "abort":
                status = "abort"
                stop_reason = action.reason or action.message or "model aborted"
                state.abort_reason = stop_reason
                state.phase = "ABORT"
                break

            obs = await self._dispatch_action(environment, step, action, state)
            last_action_result = obs
            state.phase = "OBSERVE"
        else:
            stop_reason = f"max_steps {self.max_steps} reached"
            state.abort_reason = stop_reason

        if self.trace:
            self.trace.finish(status, stop_reason, final_state=state.to_prompt_dict())
        context.n_input_tokens = self.trace.total_prompt_tokens if self.trace and self.trace.total_prompt_tokens else None
        context.n_output_tokens = self.trace.total_completion_tokens if self.trace and self.trace.total_completion_tokens else None
        context.metadata = {
            "candidate_id": CANDIDATE_ID,
            "status": status,
            "stop_reason": stop_reason,
            "trace": "agent/trace-code",
            "required_outputs": [ro.__dict__ for ro in state.required_outputs],
            "public_checks": [pc.__dict__ for pc in state.public_checks[-6:]],
        }

    def _choose_phase(self, state: AgentState) -> str:
        if state.step == 1:
            return "UNDERSTAND"
        if state.repair_hypotheses or state.failure_signatures:
            return "REPAIR"
        if state.public_checks:
            return "VERIFY"
        return "ACT"

    async def _dispatch_action(self, environment: BaseEnvironment, step: int, action: AgentAction, state: AgentState) -> str:
        state.action_calls += 1
        if action.action == "read_file":
            return await self._read_file(environment, step, action, state)
        if action.action == "write_file":
            return await self._write_file(environment, step, action, state)
        if action.action == "list_files":
            return await self._list_files(environment, step, action, state)
        if action.action == "shell":
            purpose = action.purpose or action.ledger or "shell action"
            obs = await self._exec(environment, action.command or "true", action.cwd, action.timeout_sec or self.command_timeout_sec, purpose, step=step, state=state)
            if action.is_public_check or is_public_check_command(action.command or "", purpose):
                self._record_public_check(state, step, action.command or "", obs)
            return obs
        return f"Unsupported dispatch action: {action.action}"

    async def _read_file(self, environment: BaseEnvironment, step: int, action: AgentAction, state: AgentState) -> str:
        path = action.path or "/app"
        max_bytes = action.max_bytes
        command = f"test -f {shlex.quote(path)} && head -c {max_bytes} {shlex.quote(path)}"
        return await self._exec(environment, command, "/app", 30, action.purpose or f"read {path}", step=step, state=state)

    async def _write_file(self, environment: BaseEnvironment, step: int, action: AgentAction, state: AgentState) -> str:
        path = action.path or "/app/output.txt"
        content = action.content or ""
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        command = f"mkdir -p {shlex.quote(posix_dirname(path))} && printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)} && stat -c '%n %s bytes' {shlex.quote(path)}"
        state.last_mutation_step = step
        if path not in state.touched_files:
            state.touched_files.append(path)
        return await self._exec(environment, command, "/app", 60, action.purpose or f"write {path}", step=step, state=state)

    async def _list_files(self, environment: BaseEnvironment, step: int, action: AgentAction, state: AgentState) -> str:
        path = action.path or "/app"
        depth = action.max_depth or 3
        command = f"find {shlex.quote(path)} -maxdepth {depth} -printf '%y %p %s bytes\\n' | sort | head -300"
        return await self._exec(environment, command, "/app", 30, action.purpose or f"list {path}", step=step, state=state)

    async def _exec(self, environment: BaseEnvironment, command: str, cwd: str, timeout: int, purpose: str, step: int = 0, state: AgentState | None = None) -> str:
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
        rc = int(getattr(result, "return_code", -1))
        obs = f"purpose={purpose}\ncommand={command}\nexit_code={rc}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        if state is not None:
            state.shell_calls += 1
            state.last_observation_digest = compact_text(obs, 1200)
            state.add_recent({"step": step, "action": "shell", "purpose": purpose, "exit_code": rc, "digest": state.last_observation_digest})
            if rc != 0:
                sig = state.record_failure(step, stdout, stderr, purpose)
                if sig and self.trace:
                    self.trace.failure_signature(step, sig.__dict__)
            else:
                state.no_progress_count = 0
        return obs

    def _record_public_check(self, state: AgentState, step: int, command: str, obs: str) -> None:
        exit_code = _extract_exit_code(obs)
        check = PublicCheck(
            step=step,
            command=command,
            exit_code=exit_code,
            passed=exit_code == 0,
            evidence=compact_text(obs, 1200),
            after_last_mutation=step >= state.last_mutation_step,
        )
        state.public_checks.append(check)
        state.last_verification_step = step
        state.add_ledger(f"Public/self-check step {step} exit={exit_code}: {compact_text(command, 160)}")
        if self.trace:
            self.trace.public_verify(step, check.__dict__)

    async def _pre_finish_gate(self, environment: BaseEnvironment, state: AgentState, reason: str) -> GateResult:
        evidence: list[str] = []
        missing: list[str] = []
        for ro in state.required_outputs:
            command = f"if test -e {shlex.quote(ro.path)}; then stat -c '%n %s bytes' {shlex.quote(ro.path)}; echo '---'; head -c 4000 {shlex.quote(ro.path)}; else echo MISSING; exit 1; fi"
            obs = await self._exec(environment, command, "/app", 30, f"pre-finish required output check {ro.path}", step=state.step, state=state)
            rc = _extract_exit_code(obs)
            ro.checked_step = state.step
            ro.exists = rc == 0
            ro.evidence = compact_text(obs, 1000)
            evidence.append(f"{ro.path}: {'exists' if ro.exists else 'missing'}")
            if not ro.exists:
                missing.append(ro.path)
        if state.required_outputs:
            state.last_required_output_check_step = state.step

        stale_verification = bool(state.last_mutation_step and state.last_verification_step and state.last_verification_step < state.last_mutation_step)
        no_public_check = not state.public_checks
        output_check_fresh = bool(state.required_outputs and state.last_required_output_check_step >= state.last_mutation_step)

        if missing:
            return GateResult(False, "required output path(s) missing", missing_outputs=missing, stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
        if state.denied_actions:
            return GateResult(False, "denied unsafe/invalid action occurred", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
        if no_public_check and not output_check_fresh:
            return GateResult(False, "no fresh public/self-check or required-output evidence", stale_verification=stale_verification, no_public_check=True, evidence=evidence)
        if stale_verification and not output_check_fresh:
            return GateResult(False, "verification is stale relative to latest mutation", stale_verification=True, no_public_check=no_public_check, evidence=evidence)
        evidence.append("finish gate passed")
        state.add_ledger(f"Finish gate passed: {reason}")
        return GateResult(True, "finish gate passed", stale_verification=False, no_public_check=no_public_check, evidence=evidence)


def _user_part(text: str) -> dict[str, Any]:
    return {"role": "user", "parts": [{"text": text}]}


def _extract_exit_code(obs: str) -> int:
    for line in obs.splitlines():
        if line.startswith("exit_code="):
            try:
                return int(line.split("=", 1)[1])
            except ValueError:
                return -1
    return -1


def posix_dirname(path: str) -> str:
    if "/" not in path.rstrip("/"):
        return "/app"
    return path.rsplit("/", 1)[0] or "/"
