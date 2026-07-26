# harness/web/app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from harness.governance.hitl import HITLStateMachine


class RejectBody(BaseModel):
    reason: str = "rejected"


def make_app(hitl: HITLStateMachine) -> FastAPI:
    app = FastAPI(title="Coding Agent Harness — HITL")

    @app.get("/approvals")
    def list_pending():
        return {"pending": [{"id": r.id, "tool": r.action.tool, "args": r.action.args} for r in hitl.pending()]}

    @app.post("/approvals/{approval_id}/approve")
    def approve(approval_id: str):
        if not hitl.get(approval_id) or hitl.get(approval_id).status != "pending":
            raise HTTPException(404, "not pending")
        hitl.approve(approval_id); return {"status": "approved"}

    @app.post("/approvals/{approval_id}/reject")
    def reject(approval_id: str, body: RejectBody | None = None):
        if not hitl.get(approval_id) or hitl.get(approval_id).status != "pending":
            raise HTTPException(404, "not pending")
        hitl.reject(approval_id, (body.reason if body else "rejected")); return {"status": "rejected"}

    @app.get("/approvals/{approval_id}/approve")  # convenience link
    def approve_link(approval_id: str):
        return approve(approval_id)

    @app.get("/approvals/{approval_id}/reject")
    def reject_link(approval_id: str, reason: str = "rejected"):
        return reject(approval_id, RejectBody(reason=reason))

    return app