# tests/unit/test_guardrail.py
from harness.governance.guardrail import Guardrail

def make():
    return Guardrail(
        dangerous_patterns=[r"git\s+push\s+--force", r"drop\s+(table|database)"],
        deny_patterns=[r"rm\s+-rf\s+/", r":\(\)\{.*\};:"])

def test_deny_hard_blocks_catastrophic():
    g = make()
    assert g.is_denied("rm -rf /") is True
    assert g.is_denied(":(){ :|:& };:") is True

def test_dangerous_goes_to_hitl():
    g = make()
    assert g.is_dangerous("git push --force origin main") is True
    assert g.is_dangerous("DROP TABLE users") is True
    assert g.is_dangerous("ls -la") is False

def test_deny_precedence_over_dangerous():
    g = Guardrail(dangerous_patterns=[r"rm"], deny_patterns=[r"rm\s+-rf\s+/"])
    assert g.is_denied("rm -rf /etc") is True
    assert g.is_dangerous("rm -rf /etc") is False  # denied ones aren't also "dangerous"