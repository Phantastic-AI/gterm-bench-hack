from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .state import PROMPT_CHAR_BUDGET, AgentState, compact_text

_PROMPT_DOC = Path(__file__).resolve().parents[1] / "docs" / "C001_LEDGER_VERIFY_SYSTEM_PROMPT.md"


def _extract_block(markdown: str, heading: str) -> str:
    idx = markdown.find(f"## {heading}")
    if idx == -1:
        raise RuntimeError(f"Missing prompt heading {heading}")
    sub = markdown[idx:]
    match = re.search(r"```text\n(.*?)\n```", sub, re.S)
    if not match:
        raise RuntimeError(f"Missing text block for {heading}")
    return match.group(1).strip()


def load_system_prompt() -> str:
    return _extract_block(_PROMPT_DOC.read_text(encoding="utf-8"), "SYSTEM_PROMPT")


def load_finish_gate_template() -> str:
    return _extract_block(_PROMPT_DOC.read_text(encoding="utf-8"), "FINISH_GATE_REJECTION_TEMPLATE")


def render_turn_context(
    *,
    task_text: str,
    state: AgentState,
    bootstrap_digest: str,
    last_action_result: str,
    max_steps: int,
    max_shell_calls: int,
    max_wall_time_sec: int,
    forced_message: str | None = None,
) -> str:
    remaining_actions = max(0, max_steps - state.step + 1)
    remaining_shell = max(0, max_shell_calls - state.shell_calls)
    remaining_time = max(0, max_wall_time_sec - state.elapsed_sec())
    state_dict = state.to_prompt_dict()
    context = {
        "candidate": state.candidate_id,
        "phase": state.phase,
        "bootstrap_digest": compact_text(bootstrap_digest, 6000),
        "state": state_dict,
        "required_output_paths": [ro.__dict__ for ro in state.required_outputs],
        "rolling_ledger": state.rolling_ledger[-24:],
        "recent_events": state.recent_events[-8:],
        "failure_signatures": [fs.__dict__ for fs in state.failure_signatures[-8:]],
        "public_checks": [pc.__dict__ for pc in state.public_checks[-8:]],
        "plan_doc": state.plan_doc,
        "debug_log": state.debug_log[-12:],
        "decision_log": state.decision_log[-12:],
        "latest_semantic_critic": state.latest_semantic_critic,
    }
    task_policy = _task_policy(state)
    text = f"""TASK:
{task_text}

RUNTIME_STATE:
state={json.dumps(context, ensure_ascii=False, indent=2)}
goal_mode=C006_hybrid_scoring single-action loop with broad task-class gates, compact host-side ledger, and deterministic finish gates
remaining_actions={remaining_actions}
remaining_shell_calls={remaining_shell}
remaining_time_sec={remaining_time}
context_budget=max 80000 tokens before forced compaction; this prompt is compacted by runtime

REQUIRED_OUTPUT_PATHS:
{json.dumps([ro.__dict__ for ro in state.required_outputs], ensure_ascii=False, indent=2)}

ROLLING_LEDGER:
{json.dumps(state.rolling_ledger[-24:], ensure_ascii=False, indent=2)}

RECENT_EVENTS:
{json.dumps(state.recent_events[-8:], ensure_ascii=False, indent=2)}

LAST_ACTION_RESULT:
{compact_text(last_action_result, 9000)}

FRESHNESS_REQUIREMENTS:
- Required output paths must exist before finish.
- Public/self-check evidence must be fresh relative to the latest relevant edits.
- If checks are unavailable or not applicable, explain the visible evidence used instead in the finish message.

TASK_POLICY:
{task_policy}

C006_SINGLE_ACTION_GUIDANCE:
- Return exactly one observable action per turn. Do not use transaction.
- Put concise plan/debug/decision state in the ledger field; the runtime records host-side trace artifacts.
- Use write_file_b64 for code, HTML, SQL, or regex content if raw JSON escaping is brittle.
- Replan inside the same run when observations contradict assumptions: missing runtime, file not found, unexpected output, failed check, stale hypothesis, or repeated passive action.
- Finish immediately after objective runtime gates are satisfied; do not keep exploring after a fresh meaningful check passes.

"""
    if forced_message:
        text += f"RUNTIME_GATE_MESSAGE:\n{forced_message}\n\n"
    text += "NEXT_RESPONSE:\nReturn exactly one JSON action object. No markdown. No prose outside JSON. Escape literal newlines inside JSON strings."
    if len(text) > PROMPT_CHAR_BUDGET:
        # Last-ditch deterministic compaction. Normal prompts should be far smaller.
        text = compact_text(text, PROMPT_CHAR_BUDGET)
    return text


def _task_policy(state: AgentState) -> str:
    if state.task_class == "simple_file":
        required_paths = ", ".join(ro.path for ro in state.required_outputs) or "the requested output path"
        return (
            "Class simple_artifact/simple_file: write the requested artifact early. You are in a minimal Terminal-Bench "
            "container; do not assume Python/Node/package managers/compilers/network exist. Prefer POSIX shell and "
            "write_file/write_file_b64. Do not burn steps probing optional interpreters. If the answer can be derived "
            f"from the prompt or visible files, write a first candidate to {required_paths}, then verify existence/content "
            "with test/stat/head/grep/sed/awk before finish."
        )
    if state.task_class == "answer_requires_computation":
        required_paths = ", ".join(ro.path for ro in state.required_outputs) or "the requested answer file"
        return (
            "Class answer_requires_computation: do not guess or write 0/empty without evidence. First identify and inspect "
            "the relevant input data, then run a visible computation with POSIX tools or an available runtime, write "
            f"the supported answer to {required_paths}, and verify the answer file plus the computation log before finish."
        )
    if state.task_class == "build_compile_install":
        return (
            "Class build_compile_install: progress milestones are source/package located, dependencies identified, build attempted, "
            "new compiler/linker error understood, patch applied, build succeeds, install target exists, and smoke command runs. "
            "Do not abort just because package probing fails; inspect visible source trees and README/Makefile files. Finish only after "
            "the requested binary/install target is present and a direct smoke/which/ldd/run check passes."
        )
    if state.task_class == "code_debug":
        return (
            "Class code_debug: file existence is not enough. Inspect the implicated source, make the smallest behavior patch, "
            "and run a focused behavioral check (pytest/unittest/CLI/import/smoke as available). If a check fails, reflect once "
            "on the exact assertion and then patch/rerun. Finish only after fresh passing behavior evidence."
        )
    if state.task_class == "browser_security":
        return (
            "Class browser_security: generic harmless HTML is not success. Preserve required benign content while checking adversarial "
            "payload behavior. Run or create a local check for script/event-handler/javascript: removal or payload execution as the "
            "task requires. Barely executing a file that only defines tests is not enough; use pytest/browser/adversarial assertions."
        )
    if state.task_class == "data_query":
        return (
            "Class data_query: use the exact required SQL/query filename, inspect schema/data, execute or parse the query against "
            "available DB files, and verify sample rows/counts or EXPLAIN output when relevant. Do not finish with SQL-ish text only."
        )
    if state.task_class == "binary_reverse":
        return (
            "Class binary_reverse: inspect the binary with file/readelf/objdump/strings or available scripts, run extraction against "
            "the binary, validate output format, and avoid treating helper/input filenames as deliverables."
        )
    return (
        "Assume a minimal Terminal-Bench container. Prefer POSIX shell primitives before optional runtimes; "
        "only probe/install language tools when the task clearly requires them or visible files justify it."
    )
