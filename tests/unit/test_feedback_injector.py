# tests/unit/test_feedback_injector.py
from harness.memory.context_store import ContextStore
from harness.feedback.injector import FeedbackInjector
from harness.models import Action, ToolResult, GovernanceDecision, TestFeedback

def cs(): return ContextStore(system_prompt="sys")

def test_inject_result_appends_tool_message():
    s = cs(); fi = FeedbackInjector(s)
    fi.inject_result(Action("read_file", {"path": "/a"}), ToolResult(True, {"content": "hi"}), "c0")
    assert s.messages[-1].role == "tool"
    assert "hi" in s.messages[-1].content and s.messages[-1].tool_call_id == "c0"

def test_inject_test_serializes_feedback():
    s = cs(); fi = FeedbackInjector(s)
    fi.inject_test(Action("run_tests", {}), TestFeedback(2, 1, ["e"], "raw"), "c0")
    assert "failed=1" in s.messages[-1].content and "errors=[e]" in s.messages[-1].content

def test_inject_block_reports_block_reason():
    s = cs(); fi = FeedbackInjector(s)
    fi.inject_block(Action("run_shell", {"command": "rm -rf /"}),
                    GovernanceDecision(True, "denied command", "guardrail"), "c0")
    assert "BLOCKED" in s.messages[-1].content and "denied command" in s.messages[-1].content