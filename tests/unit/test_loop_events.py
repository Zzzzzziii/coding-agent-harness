# tests/unit/test_loop_events.py
from harness.models import ToolResult
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient
from harness.governance.pipeline import Governance
from harness.governance.scope_fence import ScopeFence
from harness.governance.guardrail import Guardrail
from harness.governance.hitl import HITLStateMachine
from harness.tools.base import ToolRegistry
from harness.feedback.injector import FeedbackInjector
from harness.feedback.test_runner import TestRunner
from harness.memory.context_store import ContextStore
from harness.loop import AgentLoop


def _loop(mock, tmp_path, on_event=None):
    reg = ToolRegistry()
    reg.register("run_shell", {}, lambda args: ToolResult(
        ok=True, output={"stdout": args.get("command", "")}, error=None))
    gov = Governance(ScopeFence([str(tmp_path) + "/"]), Guardrail([], []), HITLStateMachine())
    cs = ContextStore("sys")

    class C:
        max_iters = 20

    return AgentLoop(mock, C(), gov, reg, cs, FeedbackInjector(cs), TestRunner(), on_event=on_event)


def test_on_event_emits_full_sequence(tmp_path):
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "run_shell", {"command": "echo hi"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    events = []
    _loop(mock, tmp_path, on_event=events.append).run("say hi")
    types = [e["type"] for e in events]
    assert types[0] == "step"
    assert {"type": "action", "tool": "run_shell", "args": {"command": "echo hi"}} in events
    assert any(e["type"] == "governance" and e["blocked"] is False for e in events)
    assert any(e["type"] == "tool_result" and e["tool"] == "run_shell" for e in events)
    assert types[-1] == "success"


def test_on_event_none_no_crash(tmp_path):
    mock = MockLLMClient([LLMResponse("done", [], "stop")])
    r = _loop(mock, tmp_path).run("hi")  # on_event defaults None
    assert r.final_status == "success"