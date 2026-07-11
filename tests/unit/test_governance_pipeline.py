# tests/unit/test_governance_pipeline.py
from harness.governance.scope_fence import ScopeFence
from harness.governance.guardrail import Guardrail
from harness.governance.hitl import HITLStateMachine
from harness.governance.pipeline import Governance
from harness.models import Action

def g():
    return Governance(
        ScopeFence(["/workspace/"]),
        Guardrail(dangerous_patterns=[r"git\s+push\s+--force"], deny_patterns=[r"rm\s+-rf\s+/"]),
        HITLStateMachine())

def test_out_of_scope_blocked_at_fence():
    gov = g()
    d = gov.check(Action("write_file", {"path": "/etc/passwd", "content": "x"}))
    assert d.blocked and d.layer == "scope_fence"

def test_deny_hard_blocked():
    gov = g()
    d = gov.check(Action("run_shell", {"command": "rm -rf /"}))
    assert d.blocked and d.layer == "guardrail"

def test_dangerous_approved_via_approver():
    gov = g()
    d = gov.check(Action("run_shell", {"command": "git push --force"}),
                  approver=lambda rec: True)
    assert not d.blocked
    assert d.layer == "hitl"
    assert d.approval_id is not None

def test_dangerous_rejected_via_approver():
    gov = g()
    d = gov.check(Action("run_shell", {"command": "git push --force"}),
                  approver=lambda rec: False)
    assert d.blocked and d.layer == "hitl"

def test_safe_action_passes():
    gov = g()
    d = gov.check(Action("write_file", {"path": "/workspace/a.py", "content": "x"}))
    assert not d.blocked and d.layer is None