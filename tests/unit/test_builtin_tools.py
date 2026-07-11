# tests/unit/test_builtin_tools.py
from harness.tools.base import ToolRegistry
from harness.tools.builtin import register_builtins
from harness.models import Action, ToolResult

def test_read_write_file_roundtrip(tmp_path):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    w = reg.dispatch(Action("write_file", {"path": str(tmp_path/"a.py"), "content": "hi"}))
    assert w.ok and w.output["bytes_written"] == 2
    r = reg.dispatch(Action("read_file", {"path": str(tmp_path/"a.py")}))
    assert r.ok and r.output["content"] == "hi"

def test_read_missing_file_is_error(tmp_path):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    r = reg.dispatch(Action("read_file", {"path": str(tmp_path/"nope.py")}))
    assert not r.ok

def test_run_shell_captures_output(tmp_path):
    reg = ToolRegistry(); register_builtins(reg, None, workspace=str(tmp_path))
    r = reg.dispatch(Action("run_shell", {"command": "echo hello"}))
    assert r.ok and "hello" in r.output["stdout"]