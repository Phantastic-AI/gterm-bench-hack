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
from gterm_agent.state import AgentState, PublicCheck, RequiredOutput, extract_required_outputs  # noqa: E402


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
