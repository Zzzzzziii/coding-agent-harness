# tests/unit/test_models.py
from harness.models import (Message, Action, ToolResult, GovernanceDecision,
                            TestFeedback, AgentRunResult)

def test_action_defaults():
    a = Action(tool="read_file", args={"path": "/x"})
    assert a.blocked is False
    assert a.status is None
    assert a.approval_id is None

def test_test_feedback_success():
    tf = TestFeedback(passed=3, failed=0, errors=[], raw_output="")
    assert tf.success is True
    tf2 = TestFeedback(passed=2, failed=1, errors=["boom"], raw_output="")
    assert tf2.success is False

def test_message_roles():
    m = Message(role="tool", content="x", tool_call_id="c1")
    assert m.tool_call_id == "c1"