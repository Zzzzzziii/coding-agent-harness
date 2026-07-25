from harness.models import Action, GovernanceDecision

class Governance:
    def __init__(self, scope_fence, guardrail, hitl):
        self.scope_fence = scope_fence
        self.guardrail = guardrail
        self.hitl = hitl

    @staticmethod
    def _paths(action: Action) -> list[str]:
        args = action.args or {}
        for key in ("path", "file"):
            if key in args:
                return [args[key]]
        return []

    @staticmethod
    def _command(action: Action) -> str | None:
        if action.tool in ("run_shell", "run_tests"):
            return (action.args or {}).get("command") or (action.args or {}).get("test_cmd")
        return None

    def check(self, action: Action, approver=None) -> GovernanceDecision:
        for p in self._paths(action):
            if not self.scope_fence.is_allowed(p):
                return GovernanceDecision(blocked=True, reason=f"out of scope: {p}", layer="scope_fence")
        cmd = self._command(action)
        if cmd is not None:
            if self.guardrail.is_denied(cmd):
                return GovernanceDecision(blocked=True, reason=f"denied command: {cmd}", layer="guardrail")
            if self.guardrail.is_dangerous(cmd):
                rec = self.hitl.create(action)
                if approver is None:
                    return GovernanceDecision(blocked=True, reason="awaiting HITL", layer="hitl", approval_id=rec.id)
                if approver(rec):
                    if rec.status == "pending":
                        self.hitl.approve(rec.id)
                    action.status = "approved"
                    return GovernanceDecision(blocked=False, reason="approved", layer="hitl", approval_id=rec.id)
                else:
                    if rec.status == "pending":
                        self.hitl.reject(rec.id, "rejected by human")
                    action.status = "rejected"
                    return GovernanceDecision(blocked=True, reason="rejected by human", layer="hitl", approval_id=rec.id)
        return GovernanceDecision(blocked=False, reason="ok", layer=None)