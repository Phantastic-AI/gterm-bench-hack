from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Phase = Literal[
    "BOOTSTRAP",
    "UNDERSTAND",
    "PLAN",
    "ACT",
    "OBSERVE",
    "VERIFY",
    "REPAIR",
    "CRITIC_GATE",
    "FINISH",
    "ABORT",
]

CANDIDATE_ID = "C001_ledger_verify"
AGENT_VERSION = "0.1.0-c001"
MAX_PROMPT_TOKENS_BEFORE_COMPACT = 80_000
PROMPT_CHAR_BUDGET = MAX_PROMPT_TOKENS_BEFORE_COMPACT * 4


@dataclass
class RequiredOutput:
    path: str
    source: str
    exists: bool = False
    checked_step: int = 0
    evidence: str = ""


@dataclass
class PublicCheck:
    step: int
    command: str
    exit_code: int
    passed: bool
    evidence: str
    after_last_mutation: bool


@dataclass
class FailureSignature:
    key: str
    count: int = 1
    first_step: int = 0
    last_step: int = 0
    hypothesis: str = ""


@dataclass
class GateResult:
    ok: bool
    reason: str
    missing_outputs: list[str] = field(default_factory=list)
    stale_verification: bool = False
    no_public_check: bool = False
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def repair_prompt(self) -> str:
        missing = "\n".join(f"- {p}" for p in self.missing_outputs) or "- none"
        stale = "yes" if self.stale_verification else "no"
        no_check = "yes" if self.no_public_check else "no"
        evidence = "\n".join(f"- {e}" for e in self.evidence[-8:]) or "- none"
        return f"""Finish rejected by runtime pre-finish gate.

Reason:
{self.reason}

Missing outputs:
{missing}

Stale verification: {stale}
No public/self-check: {no_check}

Evidence:
{evidence}

Required next behavior:
- Do not finish again immediately.
- Inspect or fix the listed issue.
- Re-run the relevant public/self-check or produce fresh visible evidence.
- Finish only after required output paths and freshness requirements are satisfied."""


@dataclass
class AgentState:
    candidate_id: str = CANDIDATE_ID
    version: str = AGENT_VERSION
    phase: Phase = "BOOTSTRAP"
    step: int = 0
    model_calls: int = 0
    shell_calls: int = 0
    action_calls: int = 0
    started_monotonic: float = field(default_factory=time.monotonic)
    required_outputs: list[RequiredOutput] = field(default_factory=list)
    public_checks: list[PublicCheck] = field(default_factory=list)
    failure_signatures: list[FailureSignature] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    repair_hypotheses: list[str] = field(default_factory=list)
    touched_files: list[str] = field(default_factory=list)
    rolling_ledger: list[str] = field(default_factory=list)
    last_action: dict[str, Any] | None = None
    last_observation_digest: str = ""
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    last_mutation_step: int = 0
    last_verification_step: int = 0
    last_required_output_check_step: int = 0
    denied_actions: int = 0
    parse_errors: int = 0
    no_progress_count: int = 0
    abort_reason: str = ""

    def elapsed_sec(self) -> int:
        return int(time.monotonic() - self.started_monotonic)

    def add_ledger(self, text: str, *, max_items: int = 32) -> None:
        text = compact_text(text, 500).strip()
        if not text:
            return
        self.rolling_ledger.append(text)
        self.rolling_ledger = self.rolling_ledger[-max_items:]

    def add_recent(self, event: dict[str, Any], *, max_items: int = 8) -> None:
        self.recent_events.append(event)
        self.recent_events = self.recent_events[-max_items:]

    def add_fact(self, fact: str, *, max_items: int = 24) -> None:
        fact = compact_text(fact, 300).strip()
        if fact and fact not in self.facts:
            self.facts.append(fact)
            self.facts = self.facts[-max_items:]

    def record_failure(self, step: int, stdout: str, stderr: str, hypothesis: str = "") -> FailureSignature | None:
        key = normalize_failure(stdout=stdout, stderr=stderr)
        if not key:
            return None
        for sig in self.failure_signatures:
            if sig.key == key:
                sig.count += 1
                sig.last_step = step
                if hypothesis:
                    sig.hypothesis = compact_text(hypothesis, 240)
                return sig
        sig = FailureSignature(key=key, count=1, first_step=step, last_step=step, hypothesis=compact_text(hypothesis, 240))
        self.failure_signatures.append(sig)
        self.failure_signatures = self.failure_signatures[-10:]
        return sig

    def to_prompt_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("started_monotonic", None)
        d["elapsed_sec"] = self.elapsed_sec()
        return d


def compact_text(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return text[:head] + f"\n...[compact {len(text) - max_chars} chars]...\n" + text[-tail:]


def normalize_failure(stdout: str = "", stderr: str = "") -> str:
    text = (stderr or stdout or "").strip()
    if not text:
        return ""
    text = text[-4000:]
    text = re.sub(r"/tmp/[A-Za-z0-9_.-]+", "/tmp/...", text)
    text = re.sub(r"line \d+", "line N", text, flags=re.I)
    text = re.sub(r"\d+\.\d+s", "Xs", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "HASH", text, flags=re.I)
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


_PATH_RE = re.compile(r"(?P<path>(?:/app/|\./)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9_.-]+)")
_APP_PATH_RE = re.compile(r"(?P<path>/app/[A-Za-z0-9_./-]+)")


def extract_required_outputs(instruction: str) -> list[RequiredOutput]:
    outputs: list[RequiredOutput] = []
    seen: set[str] = set()
    lines = instruction.splitlines()
    for line in lines:
        low = line.lower()
        intent = any(word in low for word in ("save", "write", "create", "output", "store", "put", "place"))
        patterns = [_APP_PATH_RE]
        if intent:
            patterns.append(_PATH_RE)
        for pattern in patterns:
            for match in pattern.finditer(line):
                path = match.group("path").strip("'\"`.,:;)")
                if not path:
                    continue
                if not path.startswith("/app/"):
                    path = "/app/" + path.lstrip("./")
                if any(bad in path for bad in ("/verifier", "/.git", "/logs/")):
                    continue
                if path not in seen:
                    seen.add(path)
                    outputs.append(RequiredOutput(path=path, source="instruction_regex"))
    return outputs


def is_public_check_command(command: str, purpose: str = "") -> bool:
    text = f"{purpose}\n{command}".lower()
    keywords = ("test", "check", "verify", "pytest", "npm test", "yarn test", "pnpm test", "make test", "cargo test", "go test", "mvn test", "gradle test", "./test")
    return any(k in text for k in keywords)
