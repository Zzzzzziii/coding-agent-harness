# tests/unit/test_credential_store.py
from harness.creds import CredentialStore

def test_status_does_not_echo_plaintext(tmp_path, monkeypatch):
    env = tmp_path / ".env"; env.write_text("DEEPSEEK_API_KEY=sk-secret-12345\n")
    cs = CredentialStore(env_path=str(env))
    assert cs.status() == {"configured": True}
    assert cs.get() == "sk-secret-12345"

def test_status_when_missing(tmp_path):
    cs = CredentialStore(env_path=str(tmp_path / ".env"))
    assert cs.status() == {"configured": False}
    assert cs.get() is None

def test_set_and_clear(tmp_path):
    env = tmp_path / ".env"; cs = CredentialStore(env_path=str(env))
    cs.set("sk-new"); assert cs.get() == "sk-new"
    cs.clear(); assert cs.get() is None
    # file mode must be 0600 on posix
    import os, stat
    if os.name == "posix":
        assert stat.S_IMODE(env.stat().st_mode) == 0o600