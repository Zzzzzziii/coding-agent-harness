# tests/unit/test_credential_store.py
import os
import stat
import pytest
from harness.creds import CredentialStore, ENV_KEY


@pytest.fixture(autouse=True)
def _clean_process_env(monkeypatch):
    """Ensure no host DEEPSEEK_API_KEY leaks into these tests."""
    monkeypatch.delenv(ENV_KEY, raising=False)


def test_status_does_not_echo_plaintext(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=sk-secret-12345\n")
    cs = CredentialStore(env_path=str(env))
    assert cs.status() == {"configured": True}
    assert cs.get() == "sk-secret-12345"


def test_status_when_missing(tmp_path):
    cs = CredentialStore(env_path=str(tmp_path / ".env"))
    assert cs.status() == {"configured": False}
    assert cs.get() is None


def test_process_env_fallback(tmp_path, monkeypatch):
    """Docker-style: no .env file, key passed via process environment."""
    monkeypatch.setenv(ENV_KEY, "sk-from-env-xyz")
    cs = CredentialStore(env_path=str(tmp_path / ".env"))
    assert cs.get() == "sk-from-env-xyz"
    assert cs.status() == {"configured": True}


def test_dotenv_takes_precedence_over_process_env(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_KEY, "sk-from-env-xyz")
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=sk-from-file\n")
    cs = CredentialStore(env_path=str(env))
    assert cs.get() == "sk-from-file"


def test_set_and_clear(tmp_path):
    env = tmp_path / ".env"
    cs = CredentialStore(env_path=str(env))
    cs.set("sk-new")
    assert cs.get() == "sk-new"
    cs.clear()
    assert cs.get() is None
    if os.name == "posix":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
