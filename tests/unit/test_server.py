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


def test_health_and_approvals_empty(tmp_path):
    srv = HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))
    c = TestClient(build_app(srv))
    assert c.get("/health").json() == {"status": "ok"}
    assert c.get("/approvals").json() == {"pending": []}


def test_run_mock_starts(tmp_path):
    srv = HarnessServer(_cfg(tmp_path), workspace=str(tmp_path))
    c = TestClient(build_app(srv))
    r = c.post("/run?task=demo&mock=true")
    assert r.status_code == 200
    assert r.json() == {"started": True, "task": "demo", "mock": True}