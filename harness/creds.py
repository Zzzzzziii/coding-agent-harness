# harness/creds.py
import os
from pathlib import Path
from dotenv import dotenv_values

ENV_KEY = "DEEPSEEK_API_KEY"


class CredentialStore:
    """Loads the API key from `.env` (primary) or the process environment (fallback).

    Reading `.env` uses dotenv_values so the process environment is never polluted
    (avoids cross-test contamination). The process-env fallback lets Docker pass
    the key via `docker run -e DEEPSEEK_API_KEY=...` with no `.env` in the image.
    Status never echoes the plaintext key.
    """

    def __init__(self, env_path: str = ".env"):
        self.env_path = Path(env_path)

    def _load(self) -> str | None:
        if self.env_path.exists():
            vals = dotenv_values(self.env_path)
            if vals.get(ENV_KEY):
                return vals[ENV_KEY]
        return os.environ.get(ENV_KEY)

    def get(self) -> str | None:
        return self._load()

    def status(self) -> dict:
        return {"configured": bool(self._load())}

    def set(self, key: str) -> None:
        self._write_env(key)

    def clear(self) -> None:
        self._write_env(None)

    def _write_env(self, key: str | None) -> None:
        kept = []
        if self.env_path.exists():
            kept = [ln for ln in self.env_path.read_text(encoding="utf-8").splitlines()
                    if not ln.startswith(f"{ENV_KEY}=")]
        if key is not None:
            kept.append(f"{ENV_KEY}={key}")
        self.env_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        if os.name == "posix":
            os.chmod(self.env_path, 0o600)

    @staticmethod
    def interactive_first_run(env_path: str = ".env") -> str | None:
        cs = CredentialStore(env_path)
        if cs.get():
            return cs.get()
        import getpass
        key = getpass.getpass("Enter DEEPSEEK_API_KEY (hidden, no echo): ").strip()
        if key:
            cs.set(key)
        return cs.get()
