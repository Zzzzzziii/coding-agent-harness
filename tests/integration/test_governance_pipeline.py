# tests/integration/test_governance_pipeline.py
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


def _loop(mock, tmp_path, approver=None, dangerous=None, deny=None):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    gov = Governance(ScopeFence([str(tmp_path) + "/"]),
                     Guardrail(dangerous or [], deny or []), HITLStateMachine())
    cs = ContextStore("sys")

    class C:
        max_iters = 20

    return AgentLoop(mock, C(), gov, reg, cs, FeedbackInjector(cs), TestRunner(), approver=approver)


def test_scope_fence_blocks_out_of_scope_write(tmp_path):
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "write_file", {"path": "/etc/passwd", "content": "x"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = _loop(mock, tmp_path).run("write outside")
    assert r.actions[0].blocked is True
    assert "scope" in (r.actions[0].block_reason or "").lower()
    assert r.executed_commands == []


def test_deny_blocks_catastrophic_shell(tmp_path):
    mock = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "run_shell", {"command": "rm -rf /"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    r = _loop(mock, tmp_path, deny=[r"rm\s+-rf\s+/"]).run("delete all")
    assert r.actions[0].blocked is True
    assert "denied" in (r.actions[0].block_reason or "").lower()
    assert r.executed_commands == []