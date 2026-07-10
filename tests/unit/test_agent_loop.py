# tests/unit/test_agent_loop.py
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
from harness.config import AgentConfig

def build_loop(mock, tmp_path, approver=None):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    gov = Governance(ScopeFence([str(tmp_path)+"/"]), Guardrail([], [r"rm\s+-rf\s+/"]), HITLStateMachine())
    class C: max_iters=10
    cs = ContextStore("sys")  # ONE store shared by loop + injector so feedback reaches the LLM
    return AgentLoop(mock, C(), gov, reg, cs, FeedbackInjector(cs), TestRunner(), approver=approver)

def test_loop_stops_on_done(tmp_path):
    mock = MockLLMClient([LLMResponse("done", [], "stop")])
    r = build_loop(mock, tmp_path).run("hi")
    assert r.final_status == "success" and r.iterations == 1

def test_loop_executes_then_done(tmp_path):
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "write_file", {"path": str(tmp_path/"a.py"), "content": "x"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = build_loop(mock, tmp_path).run("write a.py")
    assert r.final_status == "success"
    assert (tmp_path/"a.py").read_text() == "x"
    assert r.iterations == 2