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
    }
    text = f"""TASK:
{task_text}

RUNTIME_STATE:
state={json.dumps(context, ensure_ascii=False, indent=2)}
goal_mode=C002_budgeted_repair with runtime-enforced finish gate and budgeted repair
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

"""
    if forced_message:
        text += f"RUNTIME_GATE_MESSAGE:\n{forced_message}\n\n"
    text += "NEXT_RESPONSE:\nReturn exactly one JSON action object. No markdown. No prose outside JSON. Escape literal newlines inside JSON strings."
    if len(text) > PROMPT_CHAR_BUDGET:
        # Last-ditch deterministic compaction. Normal prompts should be far smaller.
        text = compact_text(text, PROMPT_CHAR_BUDGET)
    return text
