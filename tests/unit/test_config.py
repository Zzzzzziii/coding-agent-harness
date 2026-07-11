# tests/unit/test_config.py
import textwrap, pathlib
from harness.config import Config

def test_load_valid_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        llm: {model: deepseek-chat, base_url: "https://api.deepseek.com", max_tokens: 4096, temperature: 0.0}
        agent: {max_iters: 20, system_prompt_file: prompts/system.md}
        governance:
          allowed_paths: ["/workspace/"]
          dangerous_patterns: ["git push --force"]
          deny_patterns: ["rm -rf /"]
          hitl_timeout_seconds: 300
        tests: {command: "pytest tests/ -v --tb=short"}
    """))
    c = Config.load(str(cfg))
    assert c.agent.max_iters == 20
    assert c.governance.allowed_paths == ["/workspace/"]
    assert c.governance.deny_patterns == ["rm -rf /"]

def test_missing_required_field_raises(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("llm: {model: x}\n")   # missing base_url, agent, governance, tests
    try:
        Config.load(str(cfg)); assert False, "should have raised"
    except Exception as e:
        assert "missing" in str(e).lower() or "required" in str(e).lower()