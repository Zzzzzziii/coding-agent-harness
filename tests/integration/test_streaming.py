# tests/integration/test_streaming.py
import json
import time
import textwrap
from fastapi.testclient import TestClient
from harness.config import Config
from harness.server import HarnessServer, build_app


def _cfg(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system.md").write_text("sys")
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        llm: {model: deepseek-chat, base_url: "https://api.deepseek.com", max_tokens: 4096, temperature: 0.0}
        agent: {max_iters: 20, system_prompt_file: prompts/system.md}
        governance: {allowed_paths: ["/workspace/"], dangerous_patterns: ["git push --force"], deny_patterns: ["rm -rf /"], hitl_timeout_seconds: 300}
        tests: {command: "pytest -q"}
    """))
    return Config.load(str(p))


def _wait_for_pending(srv, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = srv.hitl.pending()
        if p:
            return p[0]
        time.sleep(0.02)
    raise AssertionError("no HITL pending record appeared in time")


def _events(resp):
    return [json.loads(line[len("data:"):].strip())
            for line in resp.text.splitlines() if line.startswith("data:")]


def test_chat_stream_demo_approve(tmp_path):
    srv = HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))
    c = TestClient(build_app(srv))
    r = c.post("/chat?task=demo&mock=true")
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    rec = _wait_for_pending(srv)  # worker reached git push --force → HITL pending
    c.post(f"/approvals/{rec.id}/approve")  # HTTP approve unblocks the worker

    events = _events(c.get(f"/chat/{run_id}/stream"))
    types = [e["type"] for e in events]
    assert "hitl_pending" in types
    assert {"type": "hitl_resolved", "approval_id": rec.id, "status": "approved"} in events
    assert types[-1] == "success"


def test_chat_stream_demo_reject(tmp_path):
    srv = HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))
    c = TestClient(build_app(srv))
    run_id = c.post("/chat?task=demo&mock=true").json()["run_id"]
    rec = _wait_for_pending(srv)
    c.post(f"/approvals/{rec.id}/reject", json={"reason": "no"})

    events = _events(c.get(f"/chat/{run_id}/stream"))
    types = [e["type"] for e in events]
    assert {"type": "hitl_resolved", "approval_id": rec.id, "status": "rejected"} in events
    assert types[-1] == "success"  # rejected push → loop continues to git status → done


def test_chat_unknown_run_404(tmp_path):
    c = TestClient(build_app(HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))))
    assert c.get("/chat/run_bogus/stream").status_code == 404


def test_health_still_ok(tmp_path):
    c = TestClient(build_app(HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))))
    assert c.get("/health").json() == {"status": "ok"}


def test_root_serves_chat_ui(tmp_path):
    c = TestClient(build_app(HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))))
    r = c.get("/")
    assert r.status_code == 200
    assert "chat" in r.text.lower()
    assert "EventSource" in r.text or "/chat/" in r.text
