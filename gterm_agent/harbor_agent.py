from __future__ import annotations

import base64
import json
import re
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
    infer_model_profile,
    infer_task_traits,
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
        self.system_prompt = load_system_prompt() + "\n\nC007.1 runtime addendum: use a tight single-action coding-agent loop. Return exactly one observable action per turn. Do not use broad transaction actions; the runtime will reject them. Keep plan/debug/decision state in concise ledger text and host-side traces. Finish only through deterministic class gates: required paths, fresh meaningful checks, and no unrepaired failures. Semantic critic approval is not a completion signal."

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
        state.task_traits = infer_task_traits(instruction, state.required_outputs, state.task_class)
        state.model_profile = infer_model_profile(self.gemini_model)
        state.plan_doc = {
            "goal": "Solve the Terminal-Bench task using visible files, local commands, and fresh checks.",
            "current_hypothesis": "Initial environment inspection is required.",
            "next_check": "Inspect working directory and task-relevant files.",
            "fallback_if_fails": "Replan around missing tools/files using available POSIX primitives.",
        }
        state.add_ledger(f"Initialized C007 {budget.task_class} traits={state.task_traits} model_profile={state.model_profile} budget: steps={budget.max_steps}, shell={budget.max_shell_calls}, wall={budget.max_wall_time_sec}s, outputs={len(state.required_outputs)}.")
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
                forced_message = f"Your last response was invalid but C007 will recover if you comply: {redact_text(err)}. Return exactly one JSON object using the single-action protocol. Use write_file_b64 for code/HTML/SQL/regex if JSON escaping is brittle. Do not use transaction. Escape newlines inside JSON strings as \\n; no markdown."
                last_action_result = forced_message
                continue

            state.last_action = action.raw or {"action": action.action}
            if self._requires_reflection(state) and action.action != "reflect":
                state.behavior_repair_attempts += 1
                state.add_ledger("Reflection required before next repair action")
                if self.trace:
                    self.trace.model_action(step, action.raw or {"action": action.action})
                    self.trace.event("reflection_required", step=step, action=action.raw or {"action": action.action}, failed_check_step=state.last_failed_check_step)
                forced_message = self._reflection_required_message(state)
                last_action_result = forced_message
                continue

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

            if action.action == "reflect":
                self._record_reflection(state, step, action)
                forced_message = self._post_reflection_repair_message(state)
                last_action_result = forced_message
                continue

            if action.action == "transaction":
                state.add_ledger("C007 rejected broad transaction; single observable action required")
                if self.trace:
                    self.trace.event("transaction_rejected", step=step, reason="C007 single-action policy")
                forced_message = (
                    "C007 disables broad transactions because they hide intermediate failures. "
                    "Return exactly one single action now: read_file, write_file/write_file_b64, list_files, shell, finish, or abort. "
                    "Put your plan/debug/decision note in the ledger field. Do not use transaction again."
                )
                last_action_result = forced_message
                continue

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
                # C007: deterministic gate approval is sufficient; semantic critic cannot approve completion.
                if self.trace:
                    self.trace.critic_gate(step, gate.to_dict())
                if gate.ok:
                    audit_gate = await self._pre_finish_self_audit(client, instruction, state)
                    if audit_gate is not None and not audit_gate.ok:
                        if self.trace:
                            self.trace.critic_gate(step, audit_gate.to_dict())
                        state.phase = "REPAIR"
                        state.repair_hypotheses.append(audit_gate.reason)
                        state.add_ledger(f"Finish rejected: {audit_gate.reason}")
                        forced_message = audit_gate.repair_prompt()
                        last_action_result = forced_message
                        continue
                    status = "finish"
                    stop_reason = action.message or action.reason or "C007 pre-finish gate passed"
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
            self._update_dynamic_traits(state, action, obs)
            last_action_result = obs
            state.phase = "OBSERVE"
            forced_message = forced_message or self._behavior_repair_message(state)
            auto_gate = await self._auto_finish_gate(environment, state, action)
            if auto_gate is not None:
                # C007: auto-finish uses deterministic runtime gates, not semantic self-approval.
                if self.trace:
                    self.trace.critic_gate(step, auto_gate.to_dict())
                if auto_gate.ok:
                    audit_gate = await self._pre_finish_self_audit(client, instruction, state)
                    if audit_gate is not None and not audit_gate.ok:
                        if self.trace:
                            self.trace.critic_gate(step, audit_gate.to_dict())
                        state.add_ledger(f"Auto-finish self-audit rejected: {audit_gate.reason}")
                        forced_message = audit_gate.repair_prompt()
                        last_action_result = forced_message
                        continue
                    status = "finish"
                    stop_reason = f"C007 auto-finish: {auto_gate.reason}"
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


    def _update_dynamic_traits(self, state: AgentState, action: AgentAction, obs: str) -> None:
        text = f"{action.command or ''}\n{action.ledger or ''}\n{obs}".lower()
        additions: list[str] = []
        if any(k in text for k in ("git reflog", "git merge", "merge conflict", "unmerged paths", "head@{", ".git", "git status")):
            additions.append("git_repair")
        if any(k in text for k in ("elf", "readelf", "objdump", "extract.js", "out.json", "section headers", "program headers")):
            additions.append("binary_reverse")
            if state.task_class == "build_compile_install" and not _has_trait(state, "build_install"):
                state.task_class = "binary_reverse"
        if any(k in text for k in ("cancellederror", "keyboardinterrupt", "max_concurrent", "cleaned up", "asyncio")):
            additions.append("async_cancel")
        if any(k in text for k in ("onerror", "javascript:", "<script", "selenium", "webdriver", "alert detected", "xss")):
            additions.append("html_sanitizer")
        for trait in additions:
            if trait not in state.task_traits:
                state.task_traits.append(trait)
                state.add_ledger(f"Dynamic trait inferred: {trait}")

    def _choose_thinking_level(self, state: AgentState) -> str:
        if state.task_class == "simple_file":
            # Simple artifact tasks suffer more from Gemini Flash overthinking into
            # truncated JSON than from insufficient reasoning. Keep the action small.
            return "low"
        if state.parse_errors or state.repair_hypotheses or state.no_progress_count or state.failure_signatures:
            return "high"
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
        force_classes = {"simple_file", "answer_requires_computation", "data_query", "binary_reverse"}
        if state.task_class == "simple_file" and state.last_mutation_step == 0 and (state.action_calls >= 1 or _latest_failed_optional_runtime_probe(state)):
            state.artifact_contract_repairs += 1
            paths = ", ".join(missing)
            return (
                "Artifact contract repair: simple artifact tasks fail if the required file is missing. "
                f"Required path(s): {paths}. Your next action should be write_file/write_file_b64 "
                "or a POSIX shell redirect/tee that writes one exact required path. If Python is unavailable, one pure local "
                "capability probe such as which/command -v for already-installed tools is allowed; otherwise stop probing package managers "
                "and derive the artifact from the prompt/visible files now."
            )
        if state.last_required_output_check_step and missing:
            if _has_trait(state, "html_sanitizer"):
                return None
            state.artifact_contract_repairs += 1
            paths = ", ".join(missing)
            if state.task_class in force_classes:
                return (
                    "Artifact contract repair: runtime repeatedly checked required output path(s) and they are still missing: "
                    f"{paths}. Your next action must create or edit one of those exact deliverable paths with write_file/write_file_b64 "
                    "or a shell redirect/tee. Do not continue exploration until an explicit deliverable exists."
                )
            return (
                "Artifact contract repair: runtime checked the required output path(s) and they are still missing: "
                f"{paths}. Create or edit the required artifact as soon as the class milestones make it possible, then verify it exists."
            )
        return None

    def _violates_artifact_contract(self, state: AgentState, action: AgentAction) -> bool:
        if not state.required_outputs:
            return False
        force_classes = {"simple_file", "answer_requires_computation", "data_query", "binary_reverse"}
        if state.task_class not in force_classes:
            return False
        required = {ro.path for ro in state.required_outputs}
        missing_required = [ro.path for ro in state.required_outputs if ro.path not in state.touched_files]
        if not missing_required:
            return False
        contract_active = state.artifact_contract_repairs > 0 or (state.task_class == "simple_file" and (state.action_calls >= 1 or _latest_failed_optional_runtime_probe(state))) or state.last_required_output_check_step > 0
        if not contract_active:
            return False
        if action.action == "write_file" and action.path in required:
            return False
        if action.action == "shell" and _shell_writes_required(action.command or "", required):
            return False
        if action.action == "shell" and state.task_class == "simple_file" and state.last_mutation_step == 0 and _is_local_capability_probe(action.command or ""):
            return False
        return action.action not in {"finish", "abort"}

    def _behavior_repair_message(self, state: AgentState) -> str | None:
        if state.task_class == "simple_file" or not state.public_checks:
            return None
        latest = state.public_checks[-1]
        if latest.passed or latest.step <= state.last_mutation_step:
            return None
        if state.last_failed_check_step != latest.step:
            state.last_failed_check_step = latest.step
            state.last_failed_check_digest = compact_text(latest.evidence, 1800)
            state.behavior_repair_attempts += 1
        if self._requires_reflection(state):
            return self._reflection_required_message(state)
        return self._post_reflection_repair_message(state)

    def _requires_reflection(self, state: AgentState) -> bool:
        if state.task_class == "simple_file":
            return False
        latest = state.public_checks[-1] if state.public_checks else None
        needs = bool(
            latest
            and not latest.passed
            and latest.step > state.last_mutation_step
            and state.last_reflection_failed_check_step < latest.step
        )
        if needs and latest and state.last_failed_check_step != latest.step:
            state.last_failed_check_step = latest.step
            state.last_failed_check_digest = compact_text(latest.evidence, 1800)
            state.behavior_repair_attempts += 1
        return needs

    def _reflection_required_message(self, state: AgentState) -> str:
        return (
            "Reflection required before repair. Return exactly one JSON object with action=reflect. "
            "Do not patch yet. The reflection must answer: "
            "1) what exact assertion/check failed, 2) what behavior was expected, "
            "3) which file/function likely controls it, 4) the smallest patch, "
            "5) the focused check to rerun.\n\n"
            f"FAILED_CHECK_DIGEST:\n{state.last_failed_check_digest}"
        )

    def _post_reflection_repair_message(self, state: AgentState) -> str:
        return (
            "Reflection accepted. Now perform the smallest repair described by the reflection. "
            "Prefer read_file only if you need exact local context; otherwise patch the implicated file/artifact, "
            "then rerun the focused check from the reflection. Do not finish until fresh behavioral evidence passes.\n\n"
            f"REFLECTION:\n{state.last_reflection}"
        )

    def _record_reflection(self, state: AgentState, step: int, action: AgentAction) -> None:
        state.last_reflection_step = step
        state.last_reflection_failed_check_step = state.last_failed_check_step
        state.last_reflection = compact_text(action.message or action.reason or action.ledger, 1800)
        state.add_ledger(f"Reflection step {step}: {state.last_reflection}")
        if self.trace:
            self.trace.event("reflection", step=step, failed_check_step=state.last_failed_check_step, reflection=state.last_reflection)

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
            if _looks_mutating(action.command or ""):
                state.last_mutation_step = step
            if action.is_public_check or is_public_check_command(action.command or "", purpose):
                self._record_public_check(state, step, action.command or "", obs)
            self._update_progress_after_action(state, action, obs)
            return obs
        return f"Unsupported dispatch action: {action.action}"

    async def _dispatch_transaction(self, environment: BaseEnvironment, step: int, action: AgentAction, state: AgentState, budget_timeout_sec: int) -> str:
        self._apply_transaction_memory(state, action)
        observations: list[str] = []
        stopped = False
        for i, raw_step in enumerate(action.steps or [], start=1):
            tool = str(raw_step.get("tool") or raw_step.get("action") or "")
            purpose = str(raw_step.get("purpose") or raw_step.get("ledger") or f"transaction step {i}: {tool}")
            sub = AgentAction(
                action=tool,  # type: ignore[arg-type]
                command=raw_step.get("command"),
                cwd=str(raw_step.get("cwd") or "/app"),
                timeout_sec=int(raw_step.get("timeout_sec") or budget_timeout_sec),
                purpose=purpose,
                ledger=str(raw_step.get("ledger") or purpose),
                path=raw_step.get("path"),
                content=raw_step.get("content"),
                max_bytes=int(raw_step.get("max_bytes") or 12000),
                max_depth=int(raw_step.get("max_depth") or 3),
                is_public_check=bool(raw_step.get("is_public_check") or raw_step.get("public_check")),
                raw={"action": tool, **raw_step},
            )
            obs = await self._dispatch_action(environment, step, sub, state, budget_timeout_sec)
            observations.append(f"TRANSACTION_STEP {i}/{len(action.steps or [])} tool={tool}\n{compact_text(obs, 5000)}")
            if tool == "shell" and _extract_exit_code(obs) != 0:
                stopped = True
                state.add_ledger(f"Transaction stopped on failed shell step {i}: {compact_text(purpose, 120)}")
                break
        summary = "\n\n".join(observations)
        if stopped:
            summary += "\n\nTRANSACTION_STATUS: stopped_on_failed_shell_step; replan or reflect from this evidence."
        else:
            summary += "\n\nTRANSACTION_STATUS: completed_all_steps."
        if self.trace:
            self.trace.write_working_memory(state.to_prompt_dict())
            self.trace.event("transaction", step=step, step_count=len(action.steps or []), stopped=stopped, finish_request=action.finish_request)
        return compact_text(summary, 12000)

    def _apply_transaction_memory(self, state: AgentState, action: AgentAction) -> None:
        if action.plan_update:
            for key, value in action.plan_update.items():
                if value is not None:
                    state.plan_doc[str(key)] = compact_text(str(value), 1200)
        for item in action.debug_log or []:
            state.debug_log.append(item)
        state.debug_log = state.debug_log[-60:]
        for item in action.decision_log or []:
            state.decision_log.append(item)
        state.decision_log = state.decision_log[-60:]
        if action.ledger:
            state.add_ledger(action.ledger)

    async def _semantic_finish_critic(self, client: GeminiClient, instruction: str, state: AgentState) -> GateResult:
        if state.task_class == "simple_file":
            return GateResult(True, "simple_file hard gates passed; semantic critic skipped")
        state.semantic_critic_calls += 1
        prompt = f"""You are the semantic finish critic for a Terminal-Bench agent. Judge only visible evidence; do not assume hidden verifier access. Be terse.

TASK:
{compact_text(instruction, 4000)}

CRITIC_DIGEST_JSON:
{json.dumps(_critic_state_digest(state), ensure_ascii=False, indent=2)}

Return minified JSON only, max 60 words:
{{"verdict":"pass|repair","reason":"...","required_next_action":"...","check_to_run":"..."}}

PASS only if the touched artifacts plausibly solve the task and the latest relevant check is meaningful and fresh. REPAIR if evidence is stale, superficial, semantically unrelated, or contradicted by failures."""
        try:
            resp = client.generate([_user_part(prompt)], temperature=0.0, max_output_tokens=512, system_prompt="Return one minified JSON object. No prose.", thinking_level="medium")
            state.model_calls += 1
            if self.trace:
                self.trace.model_step(state.step * 1000 + state.semantic_critic_calls, prompt, resp.text, resp.usage, resp.latency_ms)
            verdict = _json_obj_from_text(resp.text)
            state.latest_semantic_critic = verdict
            if self.trace:
                self.trace.event("semantic_critic", step=state.step, verdict=verdict)
                self.trace.write_working_memory(state.to_prompt_dict())
            if str(verdict.get("verdict", "")).lower() == "pass":
                return GateResult(True, "semantic critic approved finish", evidence=[str(verdict.get("reason", ""))])
            reason = str(verdict.get("reason") or "semantic critic requested repair")
            next_action = str(verdict.get("required_next_action") or "")
            check = str(verdict.get("check_to_run") or "")
            return GateResult(False, f"semantic critic requested repair: {reason}", evidence=[next_action, check])
        except Exception as e:  # noqa: BLE001
            reason = f"semantic critic failed closed: {redact_text(str(e), max_chars=800)}"
            state.latest_semantic_critic = {"verdict": "repair", "reason": reason}
            return GateResult(False, reason, evidence=["critic_error"])

    async def _pre_finish_self_audit(self, client: GeminiClient, instruction: str, state: AgentState) -> GateResult | None:
        if state.task_class == "simple_file":
            return None
        if state.semantic_critic_calls >= 1:
            return None
        audit = await self._semantic_finish_critic(client, instruction, state)
        if audit.ok:
            state.add_ledger("Self-audit passed before finish")
            return None
        return audit

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
        milestone = _is_milestone_progress(state.task_class, action.command or "", obs)
        if changed or milestone or (check and rc == 0):
            state.no_progress_count = 0
            state.repeated_passive_actions = 0
            if milestone:
                state.add_ledger(f"Progress milestone for {state.task_class}: {compact_text(action.command or action.action, 180)}")
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
        latest_check = state.public_checks[-1] if state.public_checks else None
        latest_check_fresh = bool(latest_check and latest_check.after_last_mutation and latest_check.passed)
        wrote_required = bool(action.action == "write_file" and action.path in {ro.path for ro in state.required_outputs})
        if state.task_class == "simple_file":
            if not state.required_outputs:
                return None
            if not latest_check_fresh and not wrote_required:
                return None
        else:
            # C007: non-simple classes need fresh behavioral evidence. This also lets
            # no-output tasks like git/build tasks finish immediately after a real check.
            if not latest_check_fresh:
                return None
            if not self._public_check_is_meaningful(state, latest_check.command if latest_check else ""):
                return GateResult(False, f"{state.task_class} requires a meaningful behavioral public check before auto-finish")
        gate = await self._pre_finish_gate(environment, state, "C007 auto-finish after fresh objective evidence")
        return gate

    def _public_check_is_meaningful(self, state: AgentState, command: str) -> bool:
        cmd = command.lower()
        if state.task_class == "simple_file":
            return True
        checks: list[bool] = []
        if state.task_class == "answer_requires_computation":
            checks.append(any(k in cmd for k in ("awk", "python", "python3", "wc ", "jq", "sqlite3", "grep", "cut", "sort", "uniq", "answer.txt")))
        if _has_trait(state, "build_install"):
            checks.append(any(k in cmd for k in ("/usr/local/bin/", "which ", "ldd ", " pmars ", "pmars -", "tail -n", "dpkg -L")))
        if state.task_class == "data_query":
            checks.append(any(k in cmd for k in ("sol.sql", "my-sql-query.sql", "sqlite3", "explain", "select", "pytest")))
        if _has_trait(state, "git_repair"):
            checks.append(any(k in cmd for k in ("git status", "git diff", "git log", "git reflog", "git branch", "pytest", "cmp ", "md5sum", "sha1sum")))
        if _has_trait(state, "html_sanitizer"):
            checks.append(any(k in cmd for k in ("pytest", "selenium", "webdriver", "chromedriver", "chrome", "chromium", "playwright")))
        if _has_trait(state, "binary_reverse"):
            checks.append(any(k in cmd for k in ("readelf", "objdump", "file ", "strings", "node ", "python", "jq", "./", "extract.js", "out.json")))
        if _has_trait(state, "async_cancel"):
            checks.append(any(k in cmd for k in ("cancel", "cleaned up", "unittest", "pytest", "python", "run.py")))
        if state.task_class == "code_debug":
            checks.append(any(k in cmd for k in ("pytest", "npm test", "yarn test", "pnpm test", "python -m", "python3 -m", "python -c", "python3 -c", "./test", "go test", "cargo test", "make test", "unittest")))
        if checks:
            return any(checks)
        return any(k in cmd for k in ("test", "pytest", "check", "verify", "make", "./"))


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
        if _has_trait(state, "html_sanitizer") and any(_browser_output_looks_dummy(ro) for ro in state.required_outputs if ro.path.endswith((".html", ".htm"))):
            return GateResult(False, "browser_security output is generic/dummy HTML, not adversarial or behavior-relevant", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
        if state.task_class != "simple_file":
            latest_check = state.public_checks[-1] if state.public_checks else None
            if not latest_check or not latest_check.passed or not latest_check.after_last_mutation:
                return GateResult(False, f"{state.task_class} requires a fresh passing public/self-check", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
            if not self._public_check_is_meaningful(state, latest_check.command):
                return GateResult(False, f"{state.task_class} public/self-check is not behavioral enough", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
            if _has_trait(state, "html_sanitizer") and not _browser_check_has_real_execution(latest_check.command, latest_check.evidence):
                return GateResult(False, "html_sanitizer requires real pytest/Selenium/browser execution evidence", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
            if _has_trait(state, "build_install") and not _build_check_has_install_smoke(latest_check.command, latest_check.evidence):
                return GateResult(False, "build_compile_install requires installed binary plus direct smoke/ldd/which evidence", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
            if _has_trait(state, "git_repair"):
                git_gate = await self._git_repair_gate(environment, state, evidence, stale_verification, no_public_check)
                if not git_gate.ok:
                    return git_gate
            if _has_trait(state, "async_cancel") and not _async_check_has_cancel_cleanup(latest_check.command, latest_check.evidence):
                return GateResult(False, "async_cancel requires cancellation cleanup evidence for all started tasks", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
            if _has_trait(state, "binary_reverse") and not _binary_check_is_output_or_extraction(latest_check.command, latest_check.evidence):
                return GateResult(False, "binary_reverse requires extraction/output validation evidence", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
        if no_public_check and not output_check_fresh:
            return GateResult(False, "no fresh public/self-check or required-output evidence", stale_verification=stale_verification, no_public_check=True, evidence=evidence)
        if stale_verification and not output_check_fresh:
            return GateResult(False, "verification is stale relative to latest mutation", stale_verification=True, no_public_check=no_public_check, evidence=evidence)
        evidence.append("finish gate passed")
        state.add_ledger(f"Finish gate passed: {reason}")
        return GateResult(True, "finish gate passed", stale_verification=False, no_public_check=no_public_check, evidence=evidence)

    async def _git_repair_gate(self, environment: BaseEnvironment, state: AgentState, evidence: list[str], stale_verification: bool, no_public_check: bool) -> GateResult:
        if state.last_mutation_step == 0:
            return GateResult(False, "git_repair requires a visible git mutation before finish", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)
        command = r'''set -eu
repo_git=$(find /app -maxdepth 3 -type d -name .git | head -n 1 || true)
if [ -z "$repo_git" ]; then echo NO_GIT_REPO; exit 1; fi
repo=${repo_git%/.git}
cd "$repo"
echo "repo=$repo"
status=$(git status --porcelain=v1)
printf '%s\n' "$status"
if [ -n "$status" ]; then echo GIT_STATUS_NOT_CLEAN; exit 1; fi
git diff --quiet --check
patchdir=/app/resources/patch_files
if [ -d "$patchdir" ]; then
  for src in "$patchdir"/*; do
    [ -f "$src" ] || continue
    base=$(basename "$src")
    matches=$(find "$repo" -path "$repo/.git" -prune -o -type f -name "$base" -print)
    count=$(printf '%s\n' "$matches" | sed '/^$/d' | wc -l | tr -d ' ')
    if [ "$count" = "1" ]; then
      dst=$(printf '%s\n' "$matches" | sed '/^$/d' | head -n 1)
      cmp -s "$src" "$dst" || { echo "PATCH_MISMATCH $src $dst"; exit 1; }
      echo "PATCH_MATCH $base"
    else
      echo "PATCH_SKIP $base count=$count"
    fi
  done
fi
echo GIT_REPAIR_CLEAN'''
        obs = await self._exec(environment, command, "/app", 90, "pre-finish git repair clean/patch check", step=state.step, state=state)
        rc = _extract_exit_code(obs)
        evidence.append(f"git repair gate exit={rc}")
        if rc != 0:
            return GateResult(False, "git_repair repo is not clean or recovered patch files do not match", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence + [compact_text(obs, 1200)])
        return GateResult(True, "git repair gate passed", stale_verification=stale_verification, no_public_check=no_public_check, evidence=evidence)


def _has_trait(state: AgentState, trait: str) -> bool:
    aliases = {
        "build_install": {"build_compile_install"},
        "html_sanitizer": {"browser_security"},
        "simple_artifact": {"simple_file"},
    }
    return trait == state.task_class or state.task_class in aliases.get(trait, set()) or trait in getattr(state, "task_traits", [])


def _latest_failed_optional_runtime_probe(state: AgentState) -> bool:
    latest = state.public_checks[-1] if state.public_checks else None
    if not latest or latest.passed:
        return False
    cmd = latest.command.lower()
    return any(k in cmd for k in ("python", "python3", "node", "ruby", "perl", "pip", "npm", "apt-get", "apt "))


def _build_check_has_install_smoke(command: str, evidence: str) -> bool:
    text = f"{command}\n{evidence}".lower()
    install_signal = any(k in text for k in ("/usr/local/bin/", "which pmars", "install -", "cp pmars /usr/local/bin"))
    smoke_signal = any(k in text for k in ("ldd", "pmars -", "results:", "tail -n", "no x11", "not found"))
    return install_signal and smoke_signal

def _command_is_inline_python(command: str) -> bool:
    cmd = command.lower()
    return bool(
        re.search(r"\bpython(?:3(?:\.\d+)?)?\b[^;|&\n]*\s-c\b", cmd)
        or re.search(r"\bpython(?:3(?:\.\d+)?)?\b[^;|&\n]*(?:\s-)?\s*<<", cmd)
    )


def _runs_file_backed_python_test(command: str) -> bool:
    cmd = command.lower()
    return bool(re.search(r"\bpython(?:3(?:\.\d+)?)?\b[^;|&<>\n]*(?:test_[\w./-]+|[\w./-]+_test|tests?)[\w./-]*\.py\b", cmd))


def _async_check_has_cancel_cleanup(command: str, evidence: str) -> bool:
    cmd = command.lower()
    text = f"{command}\n{evidence}".lower()
    if "echo " in cmd or _command_is_inline_python(command):
        return False
    if "pytest" not in cmd and "unittest" not in cmd and not _runs_file_backed_python_test(command):
        return False
    if not ("cancel" in text or "keyboardinterrupt" in text or "cancellederror" in text):
        return False
    if "exit_code=0" not in text and "passed" not in text and " ok" not in text:
        return False
    counts = {name: int(value) for name, value in re.findall(r"(started_count|cleanup_count|cancelled_count)\s*=\s*(\d+)", text)}
    counts_match = counts.get("started_count", 0) >= 1 and counts.get("cleanup_count", -1) >= counts.get("started_count", 0)
    assertion_signal = "cleanup_assertion_passed" in text or "all_started_cleaned=true" in text
    return counts_match and assertion_signal


def _browser_check_has_real_execution(command: str, evidence: str) -> bool:
    cmd = command.lower()
    text = f"{command}\n{evidence}".lower()
    if cmd.strip().startswith("echo") or "echo pytest" in cmd or _command_is_inline_python(command):
        return False
    pytest_run = "pytest" in cmd and "test session starts" in text and "collected" in text and " passed" in text
    browser_signal = any(k in text for k in ("selenium", "webdriver", "chromedriver", "chrome", "chromium", "playwright"))
    explicit_browser_run = any(k in cmd for k in ("selenium", "webdriver", "chromedriver", "chrome", "chromium", "playwright"))
    explicit_alert_success = "alert successfully triggered" in text or "alert_detected=true" in text
    return (pytest_run and (browser_signal or explicit_alert_success)) or (explicit_browser_run and explicit_alert_success)


def _binary_check_is_output_or_extraction(command: str, evidence: str) -> bool:
    cmd = command.lower()
    cmd_no_comments = "\n".join(part.split("#", 1)[0] for part in cmd.splitlines())
    text = f"{command}\n{evidence}".lower()
    if "exit_code=0" not in text and "passed" not in text and " ok" not in text:
        return False
    if re.match(r"\s*(echo|printf|cat|grep|head|tail)\b", cmd_no_comments):
        return False
    ran_extractor = bool(
        re.search(r"\bnode\s+[^;&|#\n]*extract\.js\b", cmd_no_comments)
        or re.search(r"\bpython(?:3(?:\.\d+)?)?\s+[^;&|#\n]*extract\.py\b", cmd_no_comments)
        or re.search(r"(?:^|[;&|]\s*)\./[^;&|#\n]*extract[^;&|#\n]*", cmd_no_comments)
    )
    validated_output = bool(
        re.search(r"(?:^|[;&|]\s*)jq\s+[^;&|#\n]*/?out\.json\b", cmd_no_comments)
        or re.search(r"\bpython(?:3(?:\.\d+)?)?\s+-m\s+json\.tool\s+[^;&|#\n]*/?out\.json\b", cmd_no_comments)
        or ("node -e" in cmd_no_comments and "json.parse" in cmd_no_comments and "out.json" in cmd_no_comments)
    )
    output_signal = "out.json" in text and ("{" in evidence or "[" in evidence or "valid_json=true" in text)
    return ran_extractor and validated_output and output_signal


def _browser_output_looks_dummy(ro: Any) -> bool:
    text = (getattr(ro, "evidence", "") or "").lower()
    if not text:
        return False
    dangerous_or_relevant = ("<script" in text or "onerror" in text or "onload" in text or "javascript:" in text or "alert(" in text or "<svg" in text or "<iframe" in text)
    generic = any(k in text for k in ("hello world", "<h1>hello", "<body>hello", "<p>hello", "placeholder"))
    return generic and not dangerous_or_relevant


def _looks_mutating(command: str) -> bool:
    low = command.lower()
    return any(k in low for k in (" >", ">>", "tee ", "sed -i", "cat >", "touch ", "mkdir ", "cp ", "mv ", "rm ", "base64 -d >", "python - <<", "python3 - <<", "apt-get ", "apt ", "make", "cmake", "gcc", " cc ", "chmod ", "install ", "dpkg-source", "git merge", "git cherry-pick", "git revert", "git reset", "git commit", "git add", "git checkout ", "git restore", "git apply", "git am"))


def _is_milestone_progress(task_class: str, command: str, obs: str) -> bool:
    cmd = command.lower()
    low = obs.lower()
    if task_class == "build_compile_install":
        return any(k in cmd for k in ("apt-get source", "apt-cache", "apt-get update", "apt-get install", "dpkg-source", "tar ", "make", "cmake", "gcc", "./configure", "chmod", "install ", "ldd", "which ", "/usr/local/bin/")) or any(k in low for k in ("makefile", "configure", "gcc", "compil", "link", "undefined reference", "no rule to make", "installed", "/usr/local/bin"))
    if task_class == "git_repair":
        return any(k in cmd for k in ("git status", "git diff", "git log", "git reflog", "git merge", "git cherry-pick", "git commit", "git add", "cmp ", "pytest")) or any(k in low for k in ("conflict", "working tree clean", "nothing to commit", "patch_match"))
    if task_class == "code_debug":
        return any(k in cmd for k in ("pytest", "unittest", "npm test", "go test", "cargo test", "python -m", "python3 -m", "sed -i", "cat >", "tee ")) or any(k in low for k in ("assert", "traceback", "failed", "passed"))
    if task_class == "answer_requires_computation":
        return any(k in cmd for k in ("awk", "wc ", "jq", "python", "python3", "grep", "sort", "uniq", "answer.txt"))
    if task_class == "data_query":
        return any(k in cmd for k in ("sqlite3", "select", "explain", "sol.sql", "my-sql-query.sql"))
    if task_class == "browser_security":
        return any(k in cmd for k in ("pytest", "selenium", "chrome", "chromium", "playwright", "alert", "onerror", "javascript:"))
    if task_class == "binary_reverse":
        return any(k in cmd for k in ("file ", "readelf", "objdump", "strings", "jq", "node ", "python"))
    return False


def _is_local_capability_probe(command: str) -> bool:
    cmd = command.strip().lower()
    if any(k in cmd for k in ("apt", "pip", "npm", "curl", "wget", "git ", ">", "|", ";", "&&", "||")):
        return False
    return bool(re.match(r"^(which|command -v|type -p) [a-z0-9_+./ -]+$", cmd))


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


def _critic_state_digest(state: AgentState) -> dict[str, Any]:
    return {
        "task_class": state.task_class,
        "required_outputs": [ro.__dict__ for ro in state.required_outputs],
        "touched_files": state.touched_files,
        "plan_doc": state.plan_doc,
        "latest_action": state.last_action,
        "latest_checks": [pc.__dict__ for pc in state.public_checks[-4:]],
        "last_mutation_step": state.last_mutation_step,
        "last_verification_step": state.last_verification_step,
        "last_failed_check_step": state.last_failed_check_step,
        "last_failed_check_digest": compact_text(state.last_failed_check_digest, 1500),
        "recent_events": state.recent_events[-5:],
    }


def _json_obj_from_text(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(raw[start : end + 1])
                return obj if isinstance(obj, dict) else {}
            except Exception:
                pass
        low = raw.lower()
        if '"verdict"' in low and '"pass"' in low:
            return {"verdict": "pass", "reason": compact_text(raw, 300), "required_next_action": "", "check_to_run": ""}
        if '"verdict"' in low and '"repair"' in low:
            return {"verdict": "repair", "reason": compact_text(raw, 300), "required_next_action": "", "check_to_run": ""}
        raise
