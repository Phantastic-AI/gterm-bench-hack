#!/usr/bin/env python3
"""Gemini 3.5 Flash outer-loop harness proposal generator.

This script is intentionally artifact-only: it reads compact C002 evidence,
asks Gemini for one narrow harness patch proposal, and writes reviewable files.
It does not edit gterm_agent, run Harbor, or apply patches.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "gemini-3.5-flash"
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?i)(GEMINI_API_KEY|GOOGLE_API_KEY)\s*=\s*[^\s'\"]+"),
]

SYSTEM_PROMPT = """You are a conservative Terminal-Bench harness optimizer.
You are reviewing compact C002 run evidence for a Gemini 3.5 Flash Harbor-compatible harness.
Your job is to propose exactly one narrow, general harness patch for a future candidate.
Do not solve benchmark tasks. Do not hardcode task IDs, hidden verifier behavior, leaderboard artifacts, or known answers.
Prefer changes that reduce false finishes, improve evidence gating, or make retry/classification safer.
Return strict JSON only, matching the requested schema."""

USER_TEMPLATE = """Review this compact C002 trace/result summary and propose one narrow harness patch.

Required output JSON schema:
{{
  "proposal_title": "short title",
  "candidate_boundary": "state clearly: proposal artifact only; not the actual C003 unless integrated later",
  "problem_observed": "specific behavior from the summary",
  "narrow_patch": "one general harness change",
  "files_likely_touched_if_integrated": ["example/path.py"],
  "implementation_sketch": ["step 1", "step 2", "step 3"],
  "validation_plan": ["syntax/test/check 1", "runtime/evidence check 2"],
  "risks": ["risk 1"],
  "anti_overfit_checks": ["check 1", "check 2"],
  "expected_effect": "one sentence"
}}

C002 summary:
--- BEGIN SUMMARY ---
{summary}
--- END SUMMARY ---"""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def redact(text: str) -> str:
    out = text
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(key)
        if value:
            out = out.replace(value, "[REDACTED_SECRET]")
    for pattern in SECRET_PATTERNS:
        out = pattern.sub("[REDACTED_SECRET]", out)
    return out


def read_summary(path: Path, max_chars: int) -> str:
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > max_chars:
        data = data[: max_chars // 2] + f"\n...[truncated {len(data) - max_chars} chars]...\n" + data[-max_chars // 2 :]
    return data


def gemini_generate(model: str, prompt: str, key: str, timeout_sec: int) -> tuple[str, dict[str, Any]]:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.15,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini HTTP {exc.code}: {redact(body)}") from exc
    text = extract_text(raw)
    return text, raw.get("usageMetadata") or {}


def extract_text(raw: dict[str, Any]) -> str:
    candidates = raw.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini response had no candidates: {redact(json.dumps(raw)[:1000])}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise RuntimeError(f"Gemini response had no text: {redact(json.dumps(raw)[:1000])}")
    return text


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini output was not valid JSON: {exc}\n{text[:1000]}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Gemini output JSON must be an object")
    return parsed


def write_artifacts(output_dir: Path, model: str, input_path: Path, prompt: str, proposal: dict[str, Any], usage: dict[str, Any], ran: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata = {
        "generated_at": generated_at,
        "model": model,
        "input": str(input_path),
        "proposal_only": True,
        "live_harness_modified": False,
        "gemini_api_called": ran,
        "usage": usage,
    }
    (output_dir / "proposal.json").write_text(
        json.dumps({"metadata": metadata, "proposal": proposal}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md = render_markdown(metadata, proposal)
    (output_dir / "proposal.md").write_text(md, encoding="utf-8")
    (output_dir / "prompt.md").write_text(redact(prompt) + "\n", encoding="utf-8")


def render_markdown(metadata: dict[str, Any], proposal: dict[str, Any]) -> str:
    lines = [
        "# Gemini meta-optimizer proposal",
        "",
        "> Proposal artifact only. This is not the live C003 harness unless integrated later.",
        "",
        "## Metadata",
        "",
        f"- Generated at: `{metadata['generated_at']}`",
        f"- Model: `{metadata['model']}`",
        f"- Input: `{metadata['input']}`",
        f"- Gemini API called: `{metadata['gemini_api_called']}`",
        "- Live harness modified: `False`",
        "",
        "## Proposal",
        "",
        f"**Title:** {proposal.get('proposal_title', 'untitled')}",
        "",
        f"**Boundary:** {proposal.get('candidate_boundary', '')}",
        "",
        f"**Problem observed:** {proposal.get('problem_observed', '')}",
        "",
        f"**Narrow patch:** {proposal.get('narrow_patch', '')}",
        "",
    ]
    for heading, key in [
        ("Files likely touched if integrated", "files_likely_touched_if_integrated"),
        ("Implementation sketch", "implementation_sketch"),
        ("Validation plan", "validation_plan"),
        ("Risks", "risks"),
        ("Anti-overfit checks", "anti_overfit_checks"),
    ]:
        lines += [f"## {heading}", ""]
        value = proposal.get(key) or []
        if isinstance(value, list):
            lines += [f"- {item}" for item in value]
        else:
            lines.append(str(value))
        lines.append("")
    lines += ["## Expected effect", "", str(proposal.get("expected_effect", "")), ""]
    return "\n".join(lines)


def offline_stub(input_path: Path) -> dict[str, Any]:
    return {
        "proposal_title": "Tighten auto-finish with negative-context evidence gate",
        "candidate_boundary": "Offline fallback proposal artifact only; it is not C003 and must be reviewed before integration.",
        "problem_observed": "C002 notes say auto-finish is too permissive for code-debug and browser/security tasks while required-output extraction needs stricter negative-context filtering.",
        "narrow_patch": "Require a final evidence scan that rejects finish when recent observations contain unresolved negative signals near the claimed required output.",
        "files_likely_touched_if_integrated": ["gterm_agent/state.py", "gterm_agent/harbor_agent.py"],
        "implementation_sketch": [
            "Add a small negative-signal matcher for phrases like failing tests, traceback, missing file, permission denied, and TODO-needs-fix.",
            "Before auto-finish, scan the last N observations plus the final claimed output for negative signals scoped to the task class.",
            "Force another repair turn instead of finish when negative signals conflict with claimed success.",
        ],
        "validation_plan": [
            "Compile the touched Python files.",
            "Unit-test synthetic summaries where required output exists but nearby observations still show failure.",
            "Run a small Harbor diagnostic panel only after integration, not from this artifact.",
        ],
        "risks": ["May reduce successful fast finishes on tasks with benign warning text."],
        "anti_overfit_checks": [
            f"Do not branch on source input path {input_path.name} or task IDs.",
            "Use task-class/general failure signals rather than known benchmark names.",
        ],
        "expected_effect": "Fewer false-positive finishes on code-debug and browser/security tasks at the cost of a small number of extra repair turns.",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Compact C002 summary JSON or markdown")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for proposal artifacts")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-input-chars", type=int, default=12000)
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--offline-if-no-key", action="store_true", help="Write a deterministic offline stub when no key is available")
    args = parser.parse_args(argv)

    for env_path in (Path.cwd() / ".env", repo_root() / ".env", repo_root().parent / ".env"):
        load_dotenv(env_path)
    summary = read_summary(args.input, args.max_input_chars)
    prompt = USER_TEMPLATE.format(summary=summary)
    key = api_key()
    usage: dict[str, Any] = {}
    ran = False
    if key:
        text, usage = gemini_generate(args.model, prompt, key, args.timeout_sec)
        proposal = parse_json_object(text)
        ran = True
    elif args.offline_if_no_key:
        proposal = offline_stub(args.input)
    else:
        print(
            "No GEMINI_API_KEY or GOOGLE_API_KEY found in env or repo .env. "
            "Run with: GEMINI_API_KEY=... python3 meta_optimizer/gemini_meta_optimizer.py "
            "--input meta_optimizer/samples/c002_compact_summary.json "
            "--output-dir candidates/G003_gemini_meta_proposal",
            file=sys.stderr,
        )
        return 2

    write_artifacts(args.output_dir, args.model, args.input, prompt, proposal, usage, ran)
    print(json.dumps({"output_dir": str(args.output_dir), "gemini_api_called": ran, "proposal_title": proposal.get("proposal_title")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
