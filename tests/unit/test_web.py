from fastapi.testclient import TestClient
from harness.governance.hitl import HITLStateMachine
from harness.models import Action
from harness.web.app import make_app


def test_pending_list_and_approve():
    sm = HITLStateMachine()
    rec = sm.create(Action("run_shell", {"command": "git push --force"}))
    c = TestClient(make_app(sm))
    r = c.get("/approvals"); assert r.status_code == 200
    assert rec.id in [a["id"] for a in r.json()["pending"]]
    c.post(f"/approvals/{rec.id}/approve")
    assert sm.get(rec.id).status == "approved"


def test_reject_records_reason():
    sm = HITLStateMachine()
    rec = sm.create(Action("run_shell", {"command": "x"}))
    c = TestClient(make_app(sm))
    c.post(f"/approvals/{rec.id}/reject", json={"reason": "no"})
    assert sm.get(rec.id).status == "rejected"
    assert sm.get(rec.id).feedback_to_agent == "no"


def test_unknown_id_404():
    c = TestClient(make_app(HITLStateMachine()))
    assert c.post("/approvals/nope/approve").status_code == 404