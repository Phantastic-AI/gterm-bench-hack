from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass


def _install_harbor_stubs() -> None:
    harbor = types.ModuleType("harbor")
    agents = types.ModuleType("harbor.agents")
    agents_base = types.ModuleType("harbor.agents.base")
    environments = types.ModuleType("harbor.environments")
    environments_base = types.ModuleType("harbor.environments.base")
    models = types.ModuleType("harbor.models")
    models_agent = types.ModuleType("harbor.models.agent")
    models_agent_context = types.ModuleType("harbor.models.agent.context")

    class BaseAgent:
        pass

    class BaseEnvironment:
        pass

    class AgentContext:
        pass

    agents_base.BaseAgent = BaseAgent
    environments_base.BaseEnvironment = BaseEnvironment
    models_agent_context.AgentContext = AgentContext
    for name, module in {
        "harbor": harbor,
        "harbor.agents": agents,
        "harbor.agents.base": agents_base,
        "harbor.environments": environments,
        "harbor.environments.base": environments_base,
        "harbor.models": models,
        "harbor.models.agent": models_agent,
        "harbor.models.agent.context": models_agent_context,
    }.items():
        sys.modules.setdefault(name, module)


_install_harbor_stubs()

from gterm_agent.harbor_agent import GeminiDirectAgent, _json_obj_from_text  # noqa: E402
from gterm_agent.shell_protocol import parse_action  # noqa: E402
from gterm_agent.state import AgentState, PublicCheck, RequiredOutput, classify_task_budget, extract_required_outputs, infer_model_profile, infer_task_traits  # noqa: E402


@dataclass
class _Result:
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0


class _FakeEnv:
    def __init__(self, results: list[_Result] | None = None):
        self.results = list(results or [])
        self.commands: list[str] = []

    async def exec(self, command: str, cwd: str = "/app", timeout_sec: int = 120):
        self.commands.append(command)
        if self.results:
            return self.results.pop(0)
        return _Result(stdout="ok", return_code=0)


class HarnessStateMachineTests(unittest.IsolatedAsyncioTestCase):
    def _harness(self) -> GeminiDirectAgent:
        h = object.__new__(GeminiDirectAgent)
        h.trace = None
        return h

    def test_c006_classifies_build_and_computation_without_task_names(self):
        build = classify_task_budget(
            "Build the visible source package from source and install the binary to /usr/local/bin/tool, then smoke test it.",
            60, 840, 120, 240,
        )
        self.assertEqual(build.task_class, "build_compile_install")
        self.assertGreaterEqual(build.no_progress_budget, 6)

        computation = classify_task_budget(
            "Count the dataset tokens in the files under /app/data and write the final answer to /app/answer.txt.",
            60, 840, 120, 240,
        )
        self.assertEqual(computation.task_class, "answer_requires_computation")

    def test_write_file_b64_decodes_to_normal_write_action(self):
        action = parse_action('{"action":"write_file_b64","path":"/app/filter.py","content_b64":"cHJpbnQoJ29rJykK","ledger":"write safely"}')
        self.assertEqual(action.action, "write_file")
        self.assertEqual(action.path, "/app/filter.py")
        self.assertEqual(action.content, "print('ok')\n")

    def test_c006_meaningful_checks_are_class_specific(self):
        h = self._harness()
        build_state = AgentState(task_class="build_compile_install")
        self.assertTrue(h._public_check_is_meaningful(build_state, "which pmars && ldd /usr/local/bin/pmars && /usr/local/bin/pmars -r 1 sample.red"))

        browser_state = AgentState(task_class="browser_security")
        self.assertFalse(h._public_check_is_meaningful(browser_state, "python3 /app/test_outputs.py"))
        self.assertTrue(h._public_check_is_meaningful(browser_state, "pytest -q /app/test_outputs.py"))

    async def test_c006_auto_finish_allows_no_output_tasks_after_meaningful_check(self):
        h = self._harness()
        state = AgentState(task_class="build_compile_install", last_mutation_step=2, last_verification_step=3)
        state.public_checks.append(
            PublicCheck(step=3, command="which pmars && ldd /usr/local/bin/pmars && /usr/local/bin/pmars -r 1 sample.red", exit_code=0, passed=True, evidence="/usr/local/bin/pmars\nldd ok\nresults: ok", after_last_mutation=True)
        )
        gate = await h._auto_finish_gate(_FakeEnv(), state, parse_action('{"action":"shell","command":"which pmars && ldd /usr/local/bin/pmars && /usr/local/bin/pmars -r 1 sample.red"}'))
        self.assertIsNotNone(gate)
        self.assertTrue(gate.ok)

    def test_c007_browser_security_does_not_force_artifact_during_exploration(self):
        h = self._harness()
        state = AgentState(task_class="browser_security", task_traits=["browser_security", "html_sanitizer"], action_calls=5, last_required_output_check_step=4)
        state.required_outputs.append(RequiredOutput(path="/app/out.html", source="test", exists=False, checked_step=4))
        self.assertIsNone(h._artifact_contract_message(state))
        self.assertFalse(h._violates_artifact_contract(state, parse_action('{"action":"read_file","path":"/app/filter.py"}')))

    async def test_c007_browser_finish_requires_real_browser_execution(self):
        h = self._harness()
        state = AgentState(task_class="browser_security", task_traits=["browser_security", "html_sanitizer"], last_mutation_step=2, last_verification_step=3)
        state.required_outputs.append(RequiredOutput(path="/app/out.html", source="test", exists=False))
        state.public_checks.append(PublicCheck(step=3, command="pytest /app/test_outputs.py", exit_code=0, passed=True, evidence="exit_code=0\nstdout: alert text mentioned but no browser execution", after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv([_Result("/app/out.html 31 bytes\n---\n<script>alert(1)</script>", return_code=0)]), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("html_sanitizer", gate.reason)

    async def test_c007_async_finish_requires_cleanup_evidence(self):
        h = self._harness()
        state = AgentState(task_class="code_debug", task_traits=["code_debug", "async_cancel"], last_mutation_step=2, last_verification_step=3)
        state.public_checks.append(PublicCheck(step=3, command="python3 -u -c \"print('hello')\"", exit_code=0, passed=True, evidence="exit_code=0\nstdout:\nhello", after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("async_cancel", gate.reason)

    async def test_c007_async_finish_rejects_keyword_only_fake_check(self):
        h = self._harness()
        state = AgentState(task_class="code_debug", task_traits=["code_debug", "async_cancel"], last_mutation_step=2, last_verification_step=3)
        state.public_checks.append(PublicCheck(step=3, command="echo cancel cleanup_count passed", exit_code=0, passed=True, evidence="exit_code=0\ncancel cleanup_count passed", after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("async_cancel", gate.reason)


    async def test_c007_async_finish_rejects_inline_python_fake_check(self):
        h = self._harness()
        state = AgentState(task_class="code_debug", task_traits=["code_debug", "async_cancel"], last_mutation_step=2, last_verification_step=3)
        evidence = "exit_code=0\nstdout:\ncancel started_count=1 cleanup_count=1 cancelled_count=1 cleanup_assertion_passed"
        state.public_checks.append(PublicCheck(step=3, command="python3 -c \"print('cancel started_count=1 cleanup_count=1 cancelled_count=1 cleanup_assertion_passed')\"", exit_code=0, passed=True, evidence=evidence, after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("async_cancel", gate.reason)


    async def test_c007_async_finish_accepts_file_backed_python_unittest(self):
        h = self._harness()
        state = AgentState(task_class="code_debug", task_traits=["code_debug", "async_cancel"], last_mutation_step=2, last_verification_step=3)
        evidence = "exit_code=0\nstdout:\nRan 1 test in 0.01s\nOK\nstarted_count=2 cleanup_count=2 cancelled_count=2 cleanup_assertion_passed"
        state.public_checks.append(PublicCheck(step=3, command="python3 /app/test_run.py", exit_code=0, passed=True, evidence=evidence, after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertTrue(gate.ok)

    async def test_c007_async_finish_rejects_python_heredoc_fake_check(self):
        h = self._harness()
        state = AgentState(task_class="code_debug", task_traits=["code_debug", "async_cancel"], last_mutation_step=2, last_verification_step=3)
        evidence = "exit_code=0\nstdout:\ncancel started_count=1 cleanup_count=1 cancelled_count=1 cleanup_assertion_passed"
        command = "python3 <<'PY' # pytest\nprint('cancel started_count=1 cleanup_count=1 cancelled_count=1 cleanup_assertion_passed')\nPY"
        state.public_checks.append(PublicCheck(step=3, command=command, exit_code=0, passed=True, evidence=evidence, after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("async_cancel", gate.reason)

    async def test_c007_async_finish_accepts_structured_cleanup_count(self):
        h = self._harness()
        state = AgentState(task_class="code_debug", task_traits=["code_debug", "async_cancel"], last_mutation_step=2, last_verification_step=3)
        evidence = "exit_code=0\nstdout:\nstarted_count=2 cleanup_count=2 cancelled_count=2 cleanup_assertion_passed"
        state.public_checks.append(PublicCheck(step=3, command="python3 -m unittest /app/test_cancel.py", exit_code=0, passed=True, evidence=evidence, after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertTrue(gate.ok)

    async def test_c007_browser_finish_rejects_keyword_only_fake_check(self):
        h = self._harness()
        state = AgentState(task_class="browser_security", task_traits=["browser_security", "html_sanitizer"], last_mutation_step=2, last_verification_step=3)
        state.required_outputs.append(RequiredOutput(path="/app/out.html", source="test", exists=False))
        state.public_checks.append(PublicCheck(step=3, command="echo pytest chromium passed", exit_code=0, passed=True, evidence="exit_code=0\npytest chromium passed", after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv([_Result("/app/out.html 31 bytes\n---\n<script>alert(1)</script>", return_code=0)]), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("html_sanitizer", gate.reason)

    async def test_c007_browser_finish_rejects_inline_python_fake_check(self):
        h = self._harness()
        state = AgentState(task_class="browser_security", task_traits=["browser_security", "html_sanitizer"], last_mutation_step=2, last_verification_step=3)
        state.required_outputs.append(RequiredOutput(path="/app/out.html", source="test", exists=False))
        evidence = "exit_code=0\nstdout:\ntest session starts collected 1 item 1 passed alert_detected=true selenium"
        state.public_checks.append(PublicCheck(step=3, command="python3 -c \"print('test session starts collected 1 item 1 passed alert_detected=true selenium')\" # pytest", exit_code=0, passed=True, evidence=evidence, after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv([_Result("/app/out.html 31 bytes\n---\n<script>alert(1)</script>", return_code=0)]), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("html_sanitizer", gate.reason)

    async def test_c007_browser_finish_rejects_python_heredoc_fake_check(self):
        h = self._harness()
        state = AgentState(task_class="browser_security", task_traits=["browser_security", "html_sanitizer"], last_mutation_step=2, last_verification_step=3)
        state.required_outputs.append(RequiredOutput(path="/app/out.html", source="test", exists=False))
        evidence = "exit_code=0\nstdout:\ntest session starts collected 1 item 1 passed alert_detected=true selenium"
        command = "python3 <<'PY' # pytest\nprint('test session starts collected 1 item 1 passed alert_detected=true selenium')\nPY"
        state.public_checks.append(PublicCheck(step=3, command=command, exit_code=0, passed=True, evidence=evidence, after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv([_Result("/app/out.html 31 bytes\n---\n<script>alert(1)</script>", return_code=0)]), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("html_sanitizer", gate.reason)


    def test_c006_simple_file_forces_write_after_failed_runtime_probe(self):
        h = self._harness()
        state = AgentState(task_class="simple_file", action_calls=1, last_mutation_step=0)
        state.required_outputs.append(RequiredOutput(path="/app/regex.txt", source="test"))
        state.public_checks.append(PublicCheck(step=1, command="python3 --version", exit_code=127, passed=False, evidence="not found", after_last_mutation=True))
        self.assertIn("required file is missing", h._artifact_contract_message(state))
        self.assertTrue(h._violates_artifact_contract(state, parse_action('{"action":"shell","command":"python3 --version"}')))
        self.assertFalse(h._violates_artifact_contract(state, parse_action('{"action":"write_file","path":"/app/regex.txt","content":"x"}')))


    def test_c007_simple_file_allows_local_capability_probe_after_python_missing(self):
        h = self._harness()
        state = AgentState(task_class="simple_file", action_calls=1, last_mutation_step=0)
        state.required_outputs.append(RequiredOutput(path="/app/regex.txt", source="test"))
        state.public_checks.append(PublicCheck(step=1, command="python3 --version", exit_code=127, passed=False, evidence="not found", after_last_mutation=True))
        action = parse_action('{"action":"shell","command":"which perl node grep sed awk"}')
        self.assertFalse(h._violates_artifact_contract(state, action))
        network_action = parse_action('{"action":"shell","command":"which perl || apt-get update"}')
        self.assertTrue(h._violates_artifact_contract(state, network_action))

    async def test_c006_build_gate_rejects_makefile_grep_as_finish_check(self):
        h = self._harness()
        state = AgentState(task_class="build_compile_install", last_mutation_step=2, last_verification_step=3)
        state.public_checks.append(PublicCheck(step=3, command="grep -i x11 Makefile", exit_code=0, passed=True, evidence="x11 text", after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("behavioral", gate.reason)

    async def test_c006_build_gate_accepts_install_and_smoke_evidence(self):
        h = self._harness()
        state = AgentState(task_class="build_compile_install", last_mutation_step=2, last_verification_step=3)
        cmd = "which pmars && ldd /usr/local/bin/pmars && pmars -b -r 50 -f flashpaper.red rave.red | tail -n 1"
        ev = "purpose=smoke\ncommand=" + cmd + "\nexit_code=0\nstdout:\n/usr/local/bin/pmars\nResults: 1 2 3\nstderr:\n"
        state.public_checks.append(PublicCheck(step=3, command=cmd, exit_code=0, passed=True, evidence=ev, after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertTrue(gate.ok)

    def test_c006_regex_output_stays_simple_file_even_with_parse_wording(self):
        budget = classify_task_budget(
            "Write a regex expression. Save your regex in /app/regex.txt. The regex will be read from the file and applied to log file contents using Python re.findall.",
            60, 840, 120, 240,
        )
        self.assertEqual(budget.task_class, "simple_file")

    def test_c006_cancel_async_instruction_classifies_as_code_debug(self):
        budget = classify_task_budget(
            "Create a Python function called async run_tasks(tasks: list[Callable[[], Awaitable[None]]], max_concurrent: int) -> None. Put the function in /app/run.py. Feel free to install packages if you need to. Sometimes I cancel runs via keyboard interrupt but I want cleanup code to still run.",
            60, 840, 120, 240,
        )
        self.assertEqual(budget.task_class, "code_debug")

    def test_c006_git_repair_instruction_classifies_as_git_repair(self):
        budget = classify_task_budget(
            "Recover the lost git commit from the reflog, merge it into master, resolve any merge conflict, and commit the result.",
            60, 840, 120, 240,
        )
        self.assertEqual(budget.task_class, "git_repair")

    def test_c007_simple_file_uses_low_thinking_to_protect_json_actions(self):
        h = self._harness()
        state = AgentState(task_class="simple_file")
        self.assertEqual(h._choose_thinking_level(state), "low")

    def test_c007_traits_are_composable_and_model_profile_is_swappable(self):
        instruction = "Download the Debian source package, build it from source, install the binary to /usr/local/bin/tool, and commit the git fix."
        budget = classify_task_budget(instruction, 60, 840, 120, 240)
        traits = infer_task_traits(instruction, [], budget.task_class)
        self.assertIn("build_install", traits)
        self.assertIn("download_source", traits)
        self.assertIn("git_repair", traits)
        self.assertEqual(infer_model_profile("google/gemini-3.5-flash"), "gemini_flash")
        self.assertEqual(infer_model_profile("anthropic/claude-opus-4.6"), "claude")

    def test_c007_meaningful_checks_union_over_traits(self):
        h = self._harness()
        state = AgentState(task_class="build_compile_install", task_traits=["build_compile_install", "build_install", "git_repair"])
        self.assertTrue(h._public_check_is_meaningful(state, "git status --porcelain=v1 && git diff --check"))
        self.assertTrue(h._public_check_is_meaningful(state, "which pmars && ldd /usr/local/bin/pmars && pmars -r 1 sample.red"))

    def test_c007_dynamic_traits_recover_from_prompt_miss(self):
        h = self._harness()
        state = AgentState(task_class="unknown")
        h._update_dynamic_traits(state, parse_action('{"action":"shell","command":"cd repo && git merge abc"}'), "CONFLICT (content): Merge conflict in f")
        self.assertIn("git_repair", state.task_traits)

    def test_c007_extract_elf_classifies_as_binary_not_build(self):
        budget = classify_task_budget(
            "Given an ELF binary /app/a.out, create /app/extract.js that extracts section data and writes /app/out.json.",
            60, 840, 120, 240,
        )
        self.assertEqual(budget.task_class, "binary_reverse")

    async def test_c006_git_repair_gate_rejects_dirty_repo(self):
        h = self._harness()
        state = AgentState(task_class="git_repair", last_mutation_step=3, last_verification_step=4)
        state.public_checks.append(PublicCheck(step=4, command="git status --porcelain=v1", exit_code=0, passed=True, evidence="UU _includes/about.md", after_last_mutation=True))
        env = _FakeEnv([_Result("repo=/app/personal-site\nUU _includes/about.md\nGIT_STATUS_NOT_CLEAN\n", return_code=1)])
        gate = await h._pre_finish_gate(env, state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("git_repair repo is not clean", gate.reason)

    async def test_c006_browser_finish_rejects_dummy_html(self):
        h = self._harness()
        state = AgentState(task_class="browser_security", last_mutation_step=2, last_verification_step=3)
        state.required_outputs.append(RequiredOutput(path="/app/out.html", source="test", exists=False))
        state.public_checks.append(PublicCheck(step=3, command="python3 -c 'print(\"alert\")'", exit_code=0, passed=True, evidence="alert", after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv([_Result("/app/out.html 31 bytes\n---\n<html><body>Hello</body></html>", return_code=0)]), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("dummy", gate.reason)

    def test_c007_extract_required_outputs_skips_given_input_paths_on_mixed_line(self):
        instruction = "Given /app/a.out, create /app/extract.js and write /app/out.json."
        paths = [output.path for output in extract_required_outputs(instruction)]
        self.assertNotIn("/app/a.out", paths)
        self.assertIn("/app/extract.js", paths)
        self.assertIn("/app/out.json", paths)

    async def test_c007_binary_finish_requires_extractor_run_and_json_validation(self):
        h = self._harness()
        state = AgentState(task_class="binary_reverse", task_traits=["binary_reverse"], last_mutation_step=2, last_verification_step=3)
        state.required_outputs.append(RequiredOutput(path="/app/out.json", source="test", exists=True))
        state.public_checks.append(PublicCheck(step=3, command="strings /app/a.out | head && cat /app/out.json", exit_code=0, passed=True, evidence="exit_code=0\nout.json\n6a617e69 666c5f68", after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("binary_reverse", gate.reason)

    async def test_c007_binary_finish_accepts_json_validated_extractor_run(self):
        h = self._harness()
        state = AgentState(task_class="binary_reverse", task_traits=["binary_reverse"], last_mutation_step=2, last_verification_step=3)
        state.required_outputs.append(RequiredOutput(path="/app/out.json", source="test", exists=True))
        evidence = 'exit_code=0\nstdout:\nvalid_json=true /app/out.json {"secret":"ok"}'
        state.public_checks.append(PublicCheck(step=3, command="node /app/extract.js /app/a.out > /app/out.json && jq . /app/out.json", exit_code=0, passed=True, evidence=evidence, after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertTrue(gate.ok)


    async def test_c007_binary_finish_rejects_keyword_only_fake_check(self):
        h = self._harness()
        state = AgentState(task_class="binary_reverse", task_traits=["binary_reverse"], last_mutation_step=2, last_verification_step=3)
        state.required_outputs.append(RequiredOutput(path="/app/out.json", source="test", exists=True))
        evidence = 'exit_code=0\nstdout:\nvalid_json=true /app/out.json {"x":1}'
        state.public_checks.append(PublicCheck(step=3, command="echo extract.js jq out.json", exit_code=0, passed=True, evidence=evidence, after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("binary_reverse", gate.reason)

    async def test_c007_binary_finish_rejects_comment_only_fake_check(self):
        h = self._harness()
        state = AgentState(task_class="binary_reverse", task_traits=["binary_reverse"], last_mutation_step=2, last_verification_step=3)
        state.required_outputs.append(RequiredOutput(path="/app/out.json", source="test", exists=True))
        evidence = 'exit_code=0\nstdout:\nvalid_json=true /app/out.json {"x":1}'
        state.public_checks.append(PublicCheck(step=3, command="cat /app/out.json # extract.js jq", exit_code=0, passed=True, evidence=evidence, after_last_mutation=True))
        gate = await h._pre_finish_gate(_FakeEnv(), state, "test")
        self.assertFalse(gate.ok)
        self.assertIn("binary_reverse", gate.reason)

    def test_required_output_extraction_handles_create_filter_but_not_tests(self):
        instruction = """
        Create a python file /app/filter.py that removes JavaScript.
        The provided verifier uses /app/test_outputs.py; do not edit test files.
        """
        paths = [output.path for output in extract_required_outputs(instruction)]
        self.assertIn("/app/filter.py", paths)
        self.assertNotIn("/app/test_outputs.py", paths)

    def test_transaction_protocol_normalizes_steps_and_keeps_memory_fields(self):
        action = parse_action(
            '{"action":"transaction","ledger":"repair turn",'
            '"plan_update":{"goal":"fix behavior"},'
            '"debug_log":[{"observation":"test failed"}],'
            '"decision_log":[{"decision":"patch smallest file"}],'
            '"steps":[{"tool":"read_file","path":"foo.py"},'
            '{"tool":"shell","command":"python3 -m pytest -q","is_public_check":true}],'
            '"finish_request":true}'
        )
        self.assertEqual(action.action, "transaction")
        self.assertTrue(action.finish_request)
        self.assertEqual(action.plan_update["goal"], "fix behavior")
        self.assertEqual(action.steps[0]["path"], "/app/foo.py")
        self.assertEqual(action.steps[1]["cwd"], "/app")
        self.assertEqual(action.steps[1]["timeout_sec"], 120)

    async def test_transaction_applies_memory_and_stops_after_failed_shell_step(self):
        h = self._harness()
        state = AgentState(task_class="code_debug")
        action = parse_action(
            '{"action":"transaction","ledger":"one repair turn",'
            '"plan_update":{"goal":"make tests pass","next_check":"pytest"},'
            '"debug_log":[{"observation":"initial failure"}],'
            '"decision_log":[{"decision":"run focused test"}],'
            '"steps":[{"tool":"shell","command":"echo before"},'
            '{"tool":"shell","command":"false","is_public_check":true},'
            '{"tool":"shell","command":"echo after"}]}'
        )
        env = _FakeEnv([_Result("before", return_code=0), _Result("boom", return_code=1), _Result("after", return_code=0)])

        obs = await h._dispatch_transaction(env, 1, action, state, 30)

        self.assertEqual(len(env.commands), 2, "transaction must stop on first failed shell step")
        self.assertIn("stopped_on_failed_shell_step", obs)
        self.assertEqual(state.plan_doc["goal"], "make tests pass")
        self.assertEqual(state.debug_log[-1]["observation"], "initial failure")
        self.assertEqual(state.decision_log[-1]["decision"], "run focused test")
        self.assertEqual(state.public_checks[-1].exit_code, 1)

    def test_reflection_gate_records_failed_check_and_skips_simple_file_tasks(self):
        h = self._harness()
        code_state = AgentState(task_class="code_debug", last_mutation_step=0)
        code_state.public_checks.append(
            PublicCheck(step=4, command="python3 -m pytest -q", exit_code=1, passed=False, evidence="AssertionError", after_last_mutation=True)
        )
        self.assertTrue(h._requires_reflection(code_state))
        self.assertEqual(code_state.last_failed_check_step, 4)
        h._record_reflection(code_state, 5, parse_action('{"action":"reflect","reflection":"failed pytest; patch foo; rerun pytest"}'))
        self.assertFalse(h._requires_reflection(code_state), "recorded reflection should unlock repair path")

        simple_state = AgentState(task_class="simple_file", last_mutation_step=0)
        simple_state.public_checks.append(
            PublicCheck(step=1, command="python3 --version", exit_code=127, passed=False, evidence="python missing", after_last_mutation=True)
        )
        self.assertFalse(h._requires_reflection(simple_state), "simple artifact tasks should replan/write, not reflect on missing optional tools")

    async def test_auto_finish_gate_blocks_non_behavioral_code_check(self):
        h = self._harness()
        state = AgentState(task_class="code_debug", last_mutation_step=2, last_verification_step=3)
        state.required_outputs.append(RequiredOutput(path="/app/foo.py", source="test"))
        state.public_checks.append(
            PublicCheck(step=3, command="cat /app/foo.py", exit_code=0, passed=True, evidence="file text", after_last_mutation=True)
        )
        gate = await h._auto_finish_gate(_FakeEnv([_Result("/app/foo.py 10 bytes", return_code=0)]), state, parse_action('{"action":"write_file","path":"/app/foo.py","content":"x"}'))
        self.assertIsNotNone(gate)
        self.assertFalse(gate.ok)
        self.assertIn("meaningful behavioral", gate.reason)

    async def test_semantic_critic_accepts_truncated_explicit_pass_verdict(self):
        class _FakeClient:
            def generate(self, *args, **kwargs):
                return types.SimpleNamespace(
                    text='{"verdict":"pass","reason":"visible tests pass and artifact is fresh',
                    usage={},
                    latency_ms=1,
                )

        h = self._harness()
        state = AgentState(task_class="code_debug")
        gate = await h._semantic_finish_critic(_FakeClient(), "fix task", state)
        self.assertTrue(gate.ok)
        self.assertEqual(state.latest_semantic_critic["verdict"], "pass")

    def test_json_verdict_parser_falls_back_without_blessing_missing_verdicts(self):
        self.assertEqual(_json_obj_from_text('{"verdict":"repair","reason":"needs pytest"')["verdict"], "repair")
        with self.assertRaises(Exception):
            _json_obj_from_text("not a verdict")


if __name__ == "__main__":
    unittest.main()
