# tests/unit/test_hitl_state_machine.py
import pytest
from harness.governance.hitl import HITLStateMachine, ApprovalRecord
from harness.models import Action

def test_create_is_pending():
    sm = HITLStateMachine()
    a = Action(tool="run_shell", args={"command": "git push --force"})
    rec = sm.create(a)
    assert rec.status == "pending"
    assert rec.action is a
    assert sm.get(rec.id) is rec
    assert rec in sm.pending()

def test_approve_then_reject_is_rejected_state():
    sm = HITLStateMachine()
    rec = sm.create(Action("run_shell", {"command": "x"}))
    approved = sm.approve(rec.id)
    assert approved.status == "approved"
    assert approved.decided_at is not None
    with pytest.raises(ValueError):
        sm.reject(rec.id, "too late")  # already decided

def test_reject_sets_feedback():
    sm = HITLStateMachine()
    rec = sm.create(Action("run_shell", {"command": "rm foo"}))
    rej = sm.reject(rec.id, "user said no")
    assert rej.status == "rejected"
    assert rej.feedback_to_agent == "user said no"

def test_unknown_id_raises():
    sm = HITLStateMachine()
    with pytest.raises(KeyError):
        sm.approve("nope")