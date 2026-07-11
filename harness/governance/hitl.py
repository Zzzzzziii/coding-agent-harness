from dataclasses import dataclass, field
from harness.models import Action

@dataclass
class ApprovalRecord:
    id: str
    action: Action
    status: str = "pending"          # pending | approved | rejected
    created_at: float = 0.0          # injected by caller → deterministic in tests
    decided_at: float | None = None
    feedback_to_agent: str | None = None

class HITLStateMachine:
    def __init__(self):
        self._records: dict[str, ApprovalRecord] = {}
        self._counter = 0

    def create(self, action: Action) -> ApprovalRecord:
        self._counter += 1
        rec = ApprovalRecord(id=f"apv_{self._counter}", action=action)
        self._records[rec.id] = rec
        return rec

    def _decide(self, approval_id: str, status: str, reason: str | None, ts: float) -> ApprovalRecord:
        rec = self._records.get(approval_id)
        if rec is None:
            raise KeyError(approval_id)
        if rec.status != "pending":
            raise ValueError(f"approval {approval_id} already {rec.status}")
        rec.status = status
        rec.decided_at = ts
        if reason is not None:
            rec.feedback_to_agent = reason
        return rec

    def approve(self, approval_id, ts: float = 0.0) -> ApprovalRecord:
        return self._decide(approval_id, "approved", None, ts)

    def reject(self, approval_id, reason: str, ts: float = 0.0) -> ApprovalRecord:
        return self._decide(approval_id, "rejected", reason, ts)

    def get(self, approval_id) -> ApprovalRecord | None:
        return self._records.get(approval_id)

    def pending(self) -> list[ApprovalRecord]:
        return [r for r in self._records.values() if r.status == "pending"]