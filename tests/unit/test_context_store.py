# tests/unit/test_context_store.py
from harness.memory.context_store import ContextStore
from harness.models import Message

def test_system_prompt_always_first():
    s = ContextStore("sys", max_messages=10)
    assert s.messages[0].role == "system" and s.messages[0].content == "sys"

def test_truncate_drops_oldest_non_system():
    s = ContextStore("sys", max_messages=4)
    for i in range(6):
        s.add(Message("user", f"u{i}"))
    s.truncate()
    assert len(s.messages) == 4
    assert s.messages[0].role == "system"
    assert s.messages[-1].content == "u5"           # newest kept
    assert s.messages[1].content == "u3"            # oldest non-system dropped (u0,u1,u2)

def test_add_keeps_system_first():
    s = ContextStore("sys")
    s.add(Message("user", "hi"))
    assert s.messages[0].role == "system"