import re

class Guardrail:
    def __init__(self, dangerous_patterns: list[str], deny_patterns: list[str]):
        self._dangerous = [re.compile(p, re.IGNORECASE) for p in dangerous_patterns]
        self._deny = [re.compile(p, re.IGNORECASE) for p in deny_patterns]

    def is_denied(self, command: str) -> bool:
        return any(p.search(command) for p in self._deny)

    def is_dangerous(self, command: str) -> bool:
        if self.is_denied(command):
            return False  # deny tier handles it; not also flagged for HITL
        return any(p.search(command) for p in self._dangerous)