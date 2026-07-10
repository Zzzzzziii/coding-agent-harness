# harness/creds.py
import os, stat
from pathlib import Path
from dotenv import load_dotenv

ENV_KEY = "DEEPSEEK_API_KEY"

class CredentialStore:
    def __init__(self, env_path: str = ".env"):
        self.env_path = Path(env_path)

    def _load(self) -> str | None:
        if self.env_path.exists():
            load_dotenv(self.env_path, override=True)
            return os.environ.get(ENV_KEY)
        return None

    def get(self) -> str | None:
        return self._load()

    def status(self) -> dict:
        return {"configured": bool(self._load())}

    def set(self, key: str) -> None:
        self._write_env({ENV_KEY: key})

    def clear(self) -> None:
        self._write_env({ENV_KEY: ""}, remove=True)

    def _write_env(self, kv: dict, remove: bool = False) -> None:
        lines = []
        if self.env_path.exists():
            lines = [l for l in self.env_path.read_text(encoding="utf-8").splitlines()
                     if not l.startswith(f"{ENV_KEY}=")]
        if not remove:
            lines.append(f"{ENV_KEY}={kv[ENV_KEY]}")
        self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if os.name == "posix":
            os.chmod(self.env_path, 0o600)
        os.environ.pop(ENV_KEY, None)
        load_dotenv(self.env_path, override=True)

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