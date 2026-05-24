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

CANDIDATE_ID = "C007_trait_self_audit"
AGENT_VERSION = "0.7.1-c007-trait-dynamic"
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
class TaskBudget:
    task_class: str
    max_steps: int
    max_wall_time_sec: int
    max_shell_calls: int
    no_progress_budget: int
    command_timeout_sec: int
    rationale: str = ""


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
    task_class: str = "unknown"
    task_traits: list[str] = field(default_factory=list)
    model_profile: str = "generic"
    task_budget: dict[str, Any] = field(default_factory=dict)
    action_fingerprints: dict[str, int] = field(default_factory=dict)
    last_action_fingerprint: str = ""
    repeated_passive_actions: int = 0
    parse_repair_attempts: int = 0
    infra_classification: str = ""
    artifact_contract_repairs: int = 0
    behavior_repair_attempts: int = 0
    last_failed_check_step: int = 0
    last_failed_check_digest: str = ""
    last_reflection_step: int = 0
    last_reflection_failed_check_step: int = 0
    last_reflection: str = ""
    plan_doc: dict[str, Any] = field(default_factory=dict)
    debug_log: list[Any] = field(default_factory=list)
    decision_log: list[Any] = field(default_factory=list)
    semantic_critic_calls: int = 0
    latest_semantic_critic: dict[str, Any] = field(default_factory=dict)

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


def classify_task_budget(instruction: str, requested_max_steps: int, requested_wall_time_sec: int, requested_shell_calls: int, requested_timeout_sec: int) -> TaskBudget:
    """Pick a broad, non-task-name-specific budget from visible task instructions only."""
    text = instruction.lower()
    has_regex_task = any(k in text for k in ("regex", "regular expression"))
    has_data_query = (not has_regex_task) and (any(k in text for k in ("sql", "sqlite", "cte", "window function", "database", "sol.sql", "my-sql-query")) or bool(re.search(r"\bquery\b", text) and re.search(r"\b(optimi[sz]e|sql|database|sqlite)\b", text)))
    has_browser = any(k in text for k in ("selenium", "browser", "chrome", "xss", "html", "javascript", "alert", "iframe", "sanitize", "script tag", "event handler"))
    has_binary = any(k in text for k in ("elf", "extract.js", "out.json", "reverse engineer", "disassemble", "objdump", "readelf")) or ("binary" in text and any(k in text for k in ("extract", "json", "parse", "symbols", "sections", "segments")))
    has_build = any(k in text for k in ("makefile", "cmake", "source package", "apt-get source", "from source", "/usr/local/bin", "binary should be installed")) or ("install" in text and any(k in text for k in ("binary", "executable", "source", "build", "compile", "/usr/local/bin"))) or ("build" in text and any(k in text for k in ("binary", "executable", "source", "make", "install"))) or ("compile" in text and any(k in text for k in ("binary", "executable", "source", "make", "install")))
    has_git_repair = any(k in text for k in ("git", "reflog", "lost commit", "merge conflict", "unmerged", "branch", "commit")) and any(k in text for k in ("fix", "recover", "restore", "merge", "lost", "conflict", "commit", "branch"))
    has_code = any(k in text for k in ("fix", "bug", "test", "pytest", "npm", "implement", "function", "script", "async"))
    has_computation_answer = any(k in text for k in ("count", "sum", "average", "token", "tokens", "dataset", "parse", "compute", "calculate", "statistics", "answer.txt")) and any(k in text for k in ("answer", "output", "write", "save", "result"))
    has_output_path = bool(_APP_PATH_RE.search(instruction) or _ABS_OUTPUT_PATH_RE.search(instruction) or _PATH_RE.search(instruction))
    has_simple_output = (any(k in text for k in ("write", "create", "save", "output", "put", "store")) or has_regex_task) and has_output_path
    if has_data_query:
        cls, steps, wall, shells, no_prog, timeout, why = "data_query", 34, 540, 56, 5, 120, "SQL/data tasks need schema inspection plus execution"
    elif has_binary:
        cls, steps, wall, shells, no_prog, timeout, why = "binary_reverse", 36, 600, 70, 6, 150, "binary/reverse tasks need binary inspection and conservative outputs"
    elif has_build:
        cls, steps, wall, shells, no_prog, timeout, why = "build_compile_install", 40, 660, 74, 7, 180, "build/install tasks need source/dependency/build/install/smoke milestones"
    elif has_browser:
        cls, steps, wall, shells, no_prog, timeout, why = "browser_security", 32, 480, 60, 5, 120, "browser/security tasks require adversarial and benign checks before finish"
    elif has_git_repair:
        cls, steps, wall, shells, no_prog, timeout, why = "git_repair", 32, 520, 64, 5, 120, "git repair tasks require a mutation, clean status, and fresh verification"
    elif has_regex_task and has_output_path:
        cls, steps, wall, shells, no_prog, timeout, why = "simple_file", 18, 300, 34, 10, 60, "regex artifact task should write the requested pattern early"
    elif has_computation_answer:
        cls, steps, wall, shells, no_prog, timeout, why = "answer_requires_computation", 28, 420, 48, 5, 120, "answer-file task requires inspecting inputs and running a computation"
    elif has_simple_output and not has_code:
        cls, steps, wall, shells, no_prog, timeout, why = "simple_file", 18, 300, 34, 10, 60, "simple artifact task should write the requested output early"
    elif has_code:
        cls, steps, wall, shells, no_prog, timeout, why = "code_debug", 32, 520, 60, 5, 120, "code/debug task must pass a behavioral check before finish"
    else:
        cls, steps, wall, shells, no_prog, timeout, why = "unknown", 28, 420, 50, 4, 90, "unknown task gets bounded diagnostic budget"
    return TaskBudget(
        task_class=cls,
        max_steps=min(int(requested_max_steps), steps),
        max_wall_time_sec=min(int(requested_wall_time_sec), wall),
        max_shell_calls=min(int(requested_shell_calls), shells),
        no_progress_budget=no_prog,
        command_timeout_sec=min(int(requested_timeout_sec), timeout),
        rationale=why,
    )



def infer_task_traits(instruction: str, required_outputs: list[RequiredOutput], task_class: str = "unknown") -> list[str]:
    """Infer composable task traits from instruction text only; no task-name lookup."""
    text = instruction.lower()
    traits: list[str] = []

    def add(name: str, cond: bool = True) -> None:
        if cond and name not in traits:
            traits.append(name)

    add(task_class, task_class != "unknown")
    add("git_repair", any(k in text for k in ("git", "reflog", "lost commit", "merge conflict", "unmerged", "branch", "commit")) and any(k in text for k in ("fix", "recover", "restore", "merge", "lost", "conflict", "commit", "branch")))
    add("download_source", any(k in text for k in ("download", "apt-get source", "source package", "fetch", "curl", "wget", "from source", "debian package")))
    add("build_install", task_class == "build_compile_install" or any(k in text for k in ("/usr/local/bin", "build", "compile", "install the binary", "makefile")))
    add("async_cancel", any(k in text for k in ("async", "cancel", "cancelled", "keyboard interrupt", "max_concurrent", "cleanup")))
    add("html_sanitizer", any(k in text for k in ("html", "javascript", "script", "event handler", "xss", "sanitize", "alert", "browser")))
    add("simple_artifact", bool(required_outputs) and task_class == "simple_file")
    add("answer_file", any(path.path.endswith(("answer.txt", "out.txt", "out.json")) for path in required_outputs))
    return traits


def infer_model_profile(model_name: str) -> str:
    low = model_name.lower()
    if "gemini" in low and "flash" in low:
        return "gemini_flash"
    if "gemini" in low:
        return "gemini"
    if "claude" in low:
        return "claude"
    if "gpt" in low or "openai" in low:
        return "openai"
    return "generic"

def compact_text(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return text[:head] + f"\n...[compact {len(text) - max_chars} chars]...\n" + text[-tail:]


def action_fingerprint(action: dict[str, Any] | None) -> str:
    if not action:
        return ""
    name = str(action.get("action") or "")
    if name in {"read_file", "write_file", "list_files"}:
        return f"{name}:{action.get('path') or ''}"
    if name == "shell":
        cmd = re.sub(r"\s+", " ", str(action.get("command") or "")).strip()
        return f"shell:{cmd[:220]}"
    return name


def is_passive_action(action: dict[str, Any] | None) -> bool:
    if not action:
        return False
    name = str(action.get("action") or "")
    if name in {"read_file", "list_files"}:
        return True
    if name != "shell":
        return False
    cmd = str(action.get("command") or "").strip().lower()
    mutators = (" >", ">>", "tee ", "sed -i", "python - <<", "python3 - <<", "cat >", "touch ", "mkdir ", "cp ", "mv ", "rm ", "npm install", "pip install", "apt ", "apt-get ", "make", "cmake", "gcc", "cc ", "chmod ", "install ", "dpkg-source")
    return not any(m in cmd for m in mutators)


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


def classify_infra_failure_text(text: str) -> str:
    low = text.lower()
    if "/tests/test.sh" in low and "no such file" in low:
        return "infra_verifier_staging_missing_tests"
    if "rewardfilenotfounderror" in low:
        return "infra_reward_file_missing"
    return ""


_PATH_RE = re.compile(r"(?P<path>(?:/app/|\./)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9_.-]+)")
_APP_PATH_RE = re.compile(r"(?P<path>/app/[A-Za-z0-9_./-]+)")
_ABS_OUTPUT_PATH_RE = re.compile(r"(?P<path>/(?:usr/local/bin|usr/bin|bin)/[A-Za-z0-9_.-]+)")


def extract_required_outputs(instruction: str) -> list[RequiredOutput]:
    outputs: list[RequiredOutput] = []
    seen: set[str] = set()
    output_intents = ("save", "write", "create", "output", "store", "put", "place", "submit", "final", "result", "named", "called", "file should", "fix", "modify", "edit", "craft", "payload", "bypass", "break")
    negative_context = ("provided", "already", "reference", "read ", "inspect ", "test file", "tests are", "verify with")
    for line in instruction.splitlines():
        low = line.lower()
        intent = any(word in low for word in output_intents)
        if not intent:
            continue
        patterns = [_APP_PATH_RE, _ABS_OUTPUT_PATH_RE, _PATH_RE]
        for pattern in patterns:
            for match in pattern.finditer(line):
                path = match.group("path").strip("'\"`.,:;)")
                if not path:
                    continue
                base_raw = path.rsplit("/", 1)[-1].lower().strip()
                if base_raw in {"e.g", "i.e", "etc.", "example.com"}:
                    continue
                if not path.startswith("/"):
                    path = "/app/" + path.lstrip("./")
                base = path.rsplit("/", 1)[-1].lower()
                if base in {"e.g", "i.e", "etc."}:
                    continue
                if any(bad in path for bad in ("/verifier", "/.git", "/logs/")):
                    continue
                # Common benchmark helper/test files are visible evidence, not deliverables,
                # unless the instruction explicitly asks to edit/fix/modify them.
                if base.startswith("test_") or base in {"test_outputs.py", "tests.py"}:
                    continue
                if base in {"filter.py"} and not any(w in low for w in ("fix", "modify", "edit", "write", "create", "save", "output")):
                    continue
                if any(ctx in low for ctx in negative_context) and not any(w in low for w in ("fix", "modify", "edit", "write", "create", "save", "output", "craft", "payload", "bypass", "break")):
                    continue
                if path not in seen:
                    seen.add(path)
                    outputs.append(RequiredOutput(path=path, source="instruction_regex"))
    return outputs


def is_public_check_command(command: str, purpose: str = "") -> bool:
    text = f"{purpose}\n{command}".lower()
    keywords = ("test", "check", "verify", "pytest", "npm test", "yarn test", "pnpm test", "make test", "cargo test", "go test", "mvn test", "gradle test", "./test", "sqlite3", "readelf", "objdump", "file ", "ldd", "which ", "/usr/local/bin/", "make", "cmake", "git status", "git diff", "git log", "git reflog", "git branch")
    return any(k in text for k in keywords)
