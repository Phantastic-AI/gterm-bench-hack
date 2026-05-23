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
    action_fingerprint,
    classify_task_budget,
    compact_text,
    extract_required_outputs,
    is_passive_action,
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
        self.system_prompt = load_system_prompt() + "\n\nC003 runtime addendum: use adaptive Gemini 3 thinkingLevel policy, preserve C001/C002 trace/gate behavior, require behavioral public checks before finishing code/data/browser tasks, and keep required-output extraction conservative."

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
        budget = classify_task_budget(instruction, self.max_steps, self.max_wall_time_sec, self.max_shell_calls, self.command_timeout_sec)
        state.task_class = budget.task_class
        state.task_budget = budget.__dict__.copy()
        state.required_outputs = extract_required_outputs(instruction)
        state.add_ledger(f"Initialized C004 {budget.task_class} budget: steps={budget.max_steps}, shell={budget.max_shell_calls}, wall={budget.max_wall_time_sec}s, outputs={len(state.required_outputs)}.")
        self.trace = TraceWriter(self.logs_dir, candidate_id=CANDIDATE_ID, model=self.gemini_model, run_id=environment.session_id)
        self.trace.write_task(instruction)
        client = GeminiClient(model=self.gemini_model)

        bootstrap = await self._exec(
            environment,
            "pwd; echo '---'; ls -la; echo '---'; find . -maxdepth 3 -type f | sed 's#^./##' | head -200",
            "/app",
            min(45, budget.command_timeout_sec),
            "bootstrap environment",
            step=0,
            state=state,
        )
        bootstrap_digest = compact_text(bootstrap, 8000)
        last_action_result = bootstrap_digest
        forced_message: str | None = None
        stop_reason = "budget exhausted"
        status = "abort"

        for step in range(1, budget.max_steps + 1):
            state.step = step
            if state.elapsed_sec() >= budget.max_wall_time_sec:
                stop_reason = f"max_wall_time_sec {budget.max_wall_time_sec} reached"
                state.abort_reason = stop_reason
                break
            if state.shell_calls >= budget.max_shell_calls:
                stop_reason = f"max_shell_calls {budget.max_shell_calls} reached"
                state.abort_reason = stop_reason
                break
            if state.no_progress_count >= budget.no_progress_budget:
                stop_reason = f"no-progress loop detected after {state.no_progress_count} passive/repeated actions"
                state.abort_reason = stop_reason
                break

            forced_message = forced_message or self._artifact_contract_message(state)
            state.phase = self._choose_phase(state)
            if self.trace:
                self.trace.state_update(step, state.to_prompt_dict())
            prompt = render_turn_context(
                task_text=instruction,
                state=state,
                bootstrap_digest=bootstrap_digest,
                last_action_result=last_action_result,
                max_steps=budget.max_steps,
                max_shell_calls=budget.max_shell_calls,
                max_wall_time_sec=budget.max_wall_time_sec,
                forced_message=forced_message,
            )
            forced_message = None

            try:
                thinking_level = self._choose_thinking_level(state)
                resp = client.generate([_user_part(prompt)], temperature=0.1, max_output_tokens=8192, system_prompt=self.system_prompt, thinking_level=thinking_level)
                state.add_recent({"step": step, "action": "model", "thinking_level": thinking_level}, max_items=8)
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
                state.parse_repair_attempts += 1
                forced_message = f"Your last response was invalid but C004 will recover if you comply: {redact_text(err)}. Return exactly one JSON object using the action protocol. Escape newlines inside JSON strings as \n; no markdown."
                last_action_result = forced_message
                continue

            state.last_action = action.raw or {"action": action.action}
            if self._violates_artifact_contract(state, action):
                state.artifact_contract_repairs += 1
                required = ", ".join(ro.path for ro in state.required_outputs)
                state.add_ledger(f"Artifact action rejected: required output still missing ({required})")
                if self.trace:
                    self.trace.model_action(step, action.raw or {"action": action.action})
                    self.trace.event("artifact_contract_reject", step=step, action=action.raw or {"action": action.action}, required_outputs=required)
                forced_message = (
                    "Artifact contract rejection: that action does not create the required output artifact. "
                    f"The required output path is {required}. Return exactly one JSON action now, and it must be "
                    "either write_file with path set to that required path, or a shell command that redirects/tees "
                    "content into that exact path. Do not create helper scripts, list files, test interpreters, or "
                    "read files before writing the required artifact."
                )
                last_action_result = forced_message
                continue
            state.add_ledger(action.ledger or action.purpose or action.reason or action.message)
            if self.trace:
                self.trace.model_action(step, action.raw or {"action": action.action})

            if action.action == "finish":
                state.phase = "CRITIC_GATE"
                if self._has_unrepaired_failed_check(state):
                    gate = GateResult(False, "latest failed public/self-check has not been repaired", stale_verification=True, no_public_check=False, evidence=[state.last_failed_check_digest])
                    if self.trace:
                        self.trace.critic_gate(step, gate.to_dict())
                    state.phase = "REPAIR"
                    state.repair_hypotheses.append(gate.reason)
                    state.add_ledger(f"Finish rejected: {gate.reason}")
                    forced_message = self._behavior_repair_message(state) or gate.repair_prompt()
                    last_action_result = forced_message
                    continue
                gate = await self._pre_finish_gate(environment, state, action.message or action.reason)
                if self.trace:
                    self.trace.critic_gate(step, gate.to_dict())
                if gate.ok:
                    status = "finish"
                    stop_reason = action.message or action.reason or "C004 pre-finish gate passed"
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

            obs = await self._dispatch_action(environment, step, action, state, budget.command_timeout_sec)
            last_action_result = obs
            state.phase = "OBSERVE"
            forced_message = forced_message or self._behavior_repair_message(state)
            auto_gate = await self._auto_finish_gate(environment, state, action)
            if auto_gate is not None:
                if self.trace:
                    self.trace.critic_gate(step, auto_gate.to_dict())
                if auto_gate.ok:
                    status = "finish"
                    stop_reason = f"C004 auto-finish: {auto_gate.reason}"
                    state.phase = "FINISH"
                    break
                state.add_ledger(f"Auto-finish gate not ready: {auto_gate.reason}")
            forced_message = forced_message or self._artifact_contract_message(state)
        else:
            stop_reason = f"max_steps {budget.max_steps} reached"
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
            "task_budget": state.task_budget,
            "task_class": state.task_class,
            "parse_repair_attempts": state.parse_repair_attempts,
            "infra_classification": state.infra_classification,
            "behavior_repair_attempts": state.behavior_repair_attempts,
        }


    def _choose_thinking_level(self, state: AgentState) -> str:
        if state.parse_errors or state.repair_hypotheses or state.no_progress_count or state.failure_signatures:
            return "high"
        if state.task_class == "simple_file":
            return "medium"
        return "high"


    def _choose_phase(self, state: AgentState) -> str:
        if state.step == 1:
            return "UNDERSTAND"
        if state.repair_hypotheses or state.failure_signatures:
            return "REPAIR"
        if state.public_checks:
            return "VERIFY"
        return "ACT"

    def _artifact_contract_message(self, state: AgentState) -> str | None:
        if not state.required_outputs:
            return None
        missing = [ro.path for ro in state.required_outputs if not ro.exists and ro.path not in state.touched_files]
        if not missing:
            return None
        if state.task_class == "simple_file" and state.action_calls >= 2 and state.last_mutation_step == 0:
            state.artifact_contract_repairs += 1
            paths = ", ".join(missing)
            return (
                "Artifact contract repair: the task explicitly requires output artifact(s) "
                f"{paths}, but none have been created. Your next action must be write_file "
                "or a shell command that writes one of those exact paths. Do not run another "
                "interpreter/tool availability check before creating the artifact. A missing "
                "required output is an automatic verifier failure."
            )
        if state.last_required_output_check_step and missing:
            state.artifact_contract_repairs += 1
            paths = ", ".join(missing)
            return (
                "Artifact contract repair: runtime checked the required output path(s) and they are still missing: "
                f"{paths}. Create or edit the required artifact now, then verify it exists."
            )
        return None

    def _violates_artifact_contract(self, state: AgentState, action: AgentAction) -> bool:
        if state.task_class != "simple_file" or not state.required_outputs:
            return False
        required = {ro.path for ro in state.required_outputs}
        missing_required = [ro.path for ro in state.required_outputs if ro.path not in state.touched_files]
        if not missing_required:
            return False
        contract_active = state.artifact_contract_repairs > 0 or state.action_calls >= 2 or state.last_required_output_check_step > 0
        if not contract_active:
            return False
        if action.action == "write_file" and action.path in required:
            return False
        if action.action == "shell" and _shell_writes_required(action.command or "", required):
            return False
        return action.action not in {"finish", "abort"}

    def _behavior_repair_message(self, state: AgentState) -> str | None:
        if state.task_class == "simple_file" or not state.public_checks:
            return None
        latest = state.public_checks[-1]
        if latest.passed or latest.step <= state.last_mutation_step:
            return None
        if state.last_failed_check_step == latest.step:
            return None
        state.last_failed_check_step = latest.step
        state.last_failed_check_digest = compact_text(latest.evidence, 1800)
        state.behavior_repair_attempts += 1
        return (
            "Behavior repair required: the latest public/self-check failed. Treat this failure as the current source of truth. "
            "Do not finish and do not repeat broad exploration. Extract the failing assertion/traceback/diff/missing behavior, "
            "patch the code/artifact to address that exact behavior, then rerun the focused check.\n\n"
            f"FAILED_CHECK_DIGEST:\n{state.last_failed_check_digest}"
        )

    def _has_unrepaired_failed_check(self, state: AgentState) -> bool:
        latest = state.public_checks[-1] if state.public_checks else None
        return bool(latest and not latest.passed and state.last_mutation_step <= latest.step)

    async def _dispatch_action(self, environment: BaseEnvironment, step: int, action: AgentAction, state: AgentState, budget_timeout_sec: int) -> str:
        state.action_calls += 1
        if action.action == "read_file":
            obs = await self._read_file(environment, step, action, state)
            self._update_progress_after_action(state, action, obs)
            return obs
        if action.action == "write_file":
            obs = await self._write_file(environment, step, action, state)
            self._update_progress_after_action(state, action, obs)
            return obs
        if action.action == "list_files":
            obs = await self._list_files(environment, step, action, state)
            self._update_progress_after_action(state, action, obs)
            return obs
        if action.action == "shell":
            purpose = action.purpose or action.ledger or "shell action"
            timeout = min(action.timeout_sec or budget_timeout_sec, budget_timeout_sec)
            obs = await self._exec(environment, action.command or "true", action.cwd, timeout, purpose, step=step, state=state)
            if action.is_public_check or is_public_check_command(action.command or "", purpose):
                self._record_public_check(state, step, action.command or "", obs)
            self._update_progress_after_action(state, action, obs)
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
        return obs


    def _update_progress_after_action(self, state: AgentState, action: AgentAction, obs: str) -> None:
        raw = action.raw or {"action": action.action, "path": action.path, "command": action.command}
        fp = action_fingerprint(raw)
        count = state.action_fingerprints.get(fp, 0) + 1 if fp else 0
        if fp:
            state.action_fingerprints[fp] = count
            state.last_action_fingerprint = fp
        passive = is_passive_action(raw)
        rc = _extract_exit_code(obs)
        changed = action.action == "write_file" or (action.action == "shell" and _looks_mutating(action.command or ""))
        check = action.is_public_check or is_public_check_command(action.command or "", action.purpose or action.ledger or "")
        if changed or (check and rc == 0):
            state.no_progress_count = 0
            state.repeated_passive_actions = 0
            return
        if passive and count >= 2:
            state.repeated_passive_actions += 1
            state.no_progress_count += 1
            state.add_ledger(f"No-progress warning: repeated passive action {fp} count={count}")
        elif rc != 0:
            state.no_progress_count += 1
        else:
            state.no_progress_count = max(0, state.no_progress_count - 1)

    async def _auto_finish_gate(self, environment: BaseEnvironment, state: AgentState, action: AgentAction) -> GateResult | None:
        if not state.required_outputs:
            return None
        latest_check = state.public_checks[-1] if state.public_checks else None
        latest_check_fresh = bool(latest_check and latest_check.after_last_mutation and latest_check.passed)
        wrote_required = bool(action.action == "write_file" and action.path in {ro.path for ro in state.required_outputs})
        if state.task_class == "simple_file":
            if not latest_check_fresh and not wrote_required:
                return None
        else:
            # C004: code/data/browser/binary tasks must have a real behavioral check,
            # not just an existing output file.
            if not latest_check_fresh:
                return None
            if state.task_class in {"code_debug", "data_query", "browser_security", "binary_reverse"} and not self._public_check_is_meaningful(state, latest_check.command if latest_check else ""):
                return GateResult(False, f"{state.task_class} requires a meaningful behavioral public check before auto-finish")
        gate = await self._pre_finish_gate(environment, state, "C004 auto-finish after fresh evidence")
        return gate

    def _public_check_is_meaningful(self, state: AgentState, command: str) -> bool:
        cmd = command.lower()
        if state.task_class == "simple_file":
            return True
        if state.task_class == "data_query":
            return any(k in cmd for k in ("sol.sql", "my-sql-query.sql", "golden", "sqlite3", "pytest", "test_outputs.py"))
        if state.task_class == "browser_security":
            return any(k in cmd for k in ("test_outputs.py", "pytest", "selenium", "chrome", "chromium", "alert", "playwright"))
        if state.task_class == "binary_reverse":
            return any(k in cmd for k in ("test_outputs.py", "pytest", "readelf", "objdump", "file ", "./"))
        if state.task_class == "code_debug":
            return any(k in cmd for k in ("test_outputs.py", "pytest", "npm test", "yarn test", "pnpm test", "python -m", "python3 -m", "./test", "go test", "cargo test", "make test"))
        return any(k in cmd for k in ("test", "pytest", "check", "verify"))


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
        if state.task_class != "simple_file":
            latest_check = state.public_checks[-1] if state.public_checks else None
            if not latest_check or not latest_check.passed or not latest_check.after_last_mutation:
                return GateResult(False, f"{state.task_class} requires a fresh passing public/self-check", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
            if not self._public_check_is_meaningful(state, latest_check.command):
                return GateResult(False, f"{state.task_class} public/self-check is not behavioral enough", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
        if no_public_check and not output_check_fresh:
            return GateResult(False, "no fresh public/self-check or required-output evidence", stale_verification=stale_verification, no_public_check=True, evidence=evidence)
        if stale_verification and not output_check_fresh:
            return GateResult(False, "verification is stale relative to latest mutation", stale_verification=True, no_public_check=no_public_check, evidence=evidence)
        evidence.append("finish gate passed")
        state.add_ledger(f"Finish gate passed: {reason}")
        return GateResult(True, "finish gate passed", stale_verification=False, no_public_check=no_public_check, evidence=evidence)


def _looks_mutating(command: str) -> bool:
    low = command.lower()
    return any(k in low for k in (" >", ">>", "tee ", "sed -i", "cat >", "touch ", "mkdir ", "cp ", "mv ", "rm ", "base64 -d >", "python - <<", "python3 - <<"))


def _shell_writes_required(command: str, required_paths: set[str]) -> bool:
    for path in required_paths:
        q = shlex.quote(path)
        patterns = (
            f"> {path}",
            f">{path}",
            f">> {path}",
            f">>{path}",
            f"tee {path}",
            f"tee -a {path}",
            f"cat > {path}",
            f"cat >{path}",
            f"> {q}",
            f">{q}",
            f"tee {q}",
            f"cat > {q}",
        )
        if any(p in command for p in patterns):
            return True
    return False


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
