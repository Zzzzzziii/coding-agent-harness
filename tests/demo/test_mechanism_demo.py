# tests/demo/test_mechanism_demo.py
import pytest
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient
from harness.governance.pipeline import Governance
from harness.governance.scope_fence import ScopeFence
from harness.governance.guardrail import Guardrail
from harness.governance.hitl import HITLStateMachine
from harness.tools.base import ToolRegistry
from harness.tools.builtin import register_builtins
from harness.feedback.injector import FeedbackInjector
from harness.feedback.test_runner import TestRunner
from harness.memory.context_store import ContextStore
from harness.loop import AgentLoop
from harness.models import ToolResult

class _Scripted:  # canned run_tests output; keeps TestRunner parsing real
    def __init__(self, results): self._r = list(results); self._i = 0
    def __call__(self, args):
        r = self._r[self._i]; self._i += 1; return r

def _loop(mock, tmp_path, approver=None, dangerous=None, deny=None, test_results=None):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    if test_results is not None:
        reg.register("run_tests", {}, _Scripted(test_results))
    gov = Governance(ScopeFence([str(tmp_path) + "/"]),
                     Guardrail(dangerous or [], deny or []), HITLStateMachine())
    cs = ContextStore("sys")
    class C: max_iters = 20
    return AgentLoop(mock, C(), gov, reg, cs, FeedbackInjector(cs), TestRunner(), approver=approver)

@pytest.mark.demo
def test_demo_1_guardrail_intercepts(tmp_path):
    """① Guardrail hard-blocks a catastrophic command (rm -rf /) — never executed."""
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "run_shell", {"command": "rm -rf /"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = _loop(mock, tmp_path, deny=[r"rm\s+-rf\s+/"]).run("delete everything")
    assert r.actions[0].blocked is True
    assert "denied" in (r.actions[0].block_reason or "").lower()
    assert r.executed_commands == []                       # rm -rf / never ran

@pytest.mark.demo
def test_demo_2_feedback_self_correction(tmp_path):
    """② A failing test is parsed & fed back; agent changes action and tests pass."""
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "write_file", {"path": str(tmp_path/"t.py"), "content": "syntax error!!"})], "tool_calls"),
        LLMResponse(None, [ToolCall("c1", "run_tests", {})], "tool_calls"),
        LLMResponse(None, [ToolCall("c2", "write_file", {"path": str(tmp_path/"t.py"), "content": "def test_ok():\n    assert True\n"})], "tool_calls"),
        LLMResponse(None, [ToolCall("c3", "run_tests", {})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = _loop(mock, tmp_path, test_results=[
        ToolResult(False, {"stdout": "==== 1 failed in 0.1s ====", "exit_code": 1, "command": "pytest"}, None),
        ToolResult(True,  {"stdout": "==== 1 passed in 0.1s ====", "exit_code": 0, "command": "pytest"}, None),
    ]).run("fix the test")
    assert r.final_status == "success" and r.iterations == 5
    assert r.actions[1].tool == "run_tests" and r.actions[3].tool == "run_tests"

@pytest.mark.demo
def test_demo_3_hitl_rejection_changes_strategy(tmp_path):
    """③ HITL rejects a dangerous command; agent retries with a safe command."""
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "run_shell", {"command": "git push --force"})], "tool_calls"),
        LLMResponse(None, [ToolCall("c1", "run_shell", {"command": "git status"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = _loop(mock, tmp_path, approver=lambda rec: False,
              dangerous=[r"git\s+push\s+--force"]).run("push my code")
    assert r.actions[0].status == "rejected"
    assert r.actions[0].blocked is True
    assert "git push --force" not in r.executed_commands
    assert "git status" in r.executed_commands