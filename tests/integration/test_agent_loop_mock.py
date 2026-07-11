# tests/integration/test_agent_loop_mock.py
from harness.loop import AgentLoop
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
from harness.models import ToolResult
from tests.conftest import ScriptedTool

def build(mock, tmp_path, approver=None, test_results=None):
    reg = ToolRegistry()
    register_builtins(reg, None, workspace=str(tmp_path))   # read/write/shell/tests first
    if test_results is not None:
        reg.register("run_tests", {}, ScriptedTool(test_results))  # OVERRIDE tests w/ canned output
    gov = Governance(ScopeFence([str(tmp_path)+"/"]),
                     Guardrail([r"git\s+push\s+--force"], [r"rm\s+-rf\s+/"]), HITLStateMachine())
    class C: max_iters=20
    cs = ContextStore("sys")
    return AgentLoop(mock, C(), gov, reg, cs, FeedbackInjector(cs), TestRunner(), approver=approver)

def test_read_modify_test_pass_loop(tmp_path):
    # LLM: read file -> run_tests (fails) -> write fix -> run_tests (passes) -> done
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "read_file", {"path": str(tmp_path/"t.py")})], "tool_calls"),
        LLMResponse(None, [ToolCall("c1", "run_tests", {})], "tool_calls"),
        LLMResponse(None, [ToolCall("c2", "write_file", {"path": str(tmp_path/"t.py"), "content": "ok"})], "tool_calls"),
        LLMResponse(None, [ToolCall("c3", "run_tests", {})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    loop = build(mock, tmp_path, test_results=[
        ToolResult(False, {"stdout": "==== 1 failed in 0.1s ====", "exit_code": 1, "command": "pytest"}, None),
        ToolResult(True,  {"stdout": "==== 1 passed in 0.1s ====", "exit_code": 0, "command": "pytest"}, None),
    ])
    r = loop.run("fix the test")
    assert r.final_status == "success" and r.iterations == 5