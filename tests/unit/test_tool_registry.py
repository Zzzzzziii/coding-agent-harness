# tests/unit/test_tool_registry.py
import pytest
from harness.tools.base import ToolRegistry
from harness.models import Action, ToolResult

def echo(args): return ToolResult(ok=True, output={"echo": args})
def boom(args): raise RuntimeError("kaboom")

def test_dispatch_known_tool():
    r = ToolRegistry().register("echo", {"name": "echo"}, echo).dispatch(Action("echo", {"x": 1}))
    assert r.ok and r.output == {"echo": {"x": 1}}

def test_unknown_tool_returns_error():
    r = ToolRegistry().dispatch(Action("nope", {}))
    assert not r.ok and "unknown tool" in (r.error or "").lower()

def test_handler_exception_caught():
    r = ToolRegistry().register("boom", {}, boom).dispatch(Action("boom", {}))
    assert not r.ok and "kaboom" in (r.error or "")