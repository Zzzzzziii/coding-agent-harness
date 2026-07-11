import subprocess, sys
from harness.__main__ import main


def test_creds_status_when_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    rc = main(["creds", "status"])
    out = capsys.readouterr().out
    assert rc == 0 and "configured: false" in out.lower()


def test_run_mock_returns_success():
    # config.yaml + prompts/system.md exist at repo root; --mock uses MockLLMClient([done]) -> success.
    from harness.__main__ import main
    rc = main(["run", "--mock", "hi"])
    assert rc == 0