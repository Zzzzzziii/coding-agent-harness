# tests/unit/test_wrap_approver.py
from harness.server import wrap_approver
from harness.governance.hitl import ApprovalRecord
from harness.models import Action


def _rec(i="apv_1", cmd="git push --force"):
    return ApprovalRecord(id=i, action=Action("run_shell", {"command": cmd}))


def test_wrap_approver_pending_then_resolved_approved():
    events = []
    w = wrap_approver(lambda rec: True, events.append)
    assert w(_rec()) is True
    assert events[0] == {"type": "hitl_pending", "approval_id": "apv_1",
                          "tool": "run_shell", "args": {"command": "git push --force"}}
    assert events[1] == {"type": "hitl_resolved", "approval_id": "apv_1", "status": "approved"}


def test_wrap_approver_rejected():
    events = []
    w = wrap_approver(lambda rec: False, events.append)
    assert w(_rec("apv_2")) is False
    assert events[1] == {"type": "hitl_resolved", "approval_id": "apv_2", "status": "rejected"}
