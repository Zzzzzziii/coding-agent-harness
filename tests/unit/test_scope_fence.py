# tests/unit/test_scope_fence.py
from harness.governance.scope_fence import ScopeFence

def test_allows_within_workspace():
    f = ScopeFence(["/workspace/"])
    assert f.is_allowed("/workspace/foo.py") is True
    assert f.is_allowed("/workspace/sub/bar.py") is True

def test_rejects_outside_workspace():
    f = ScopeFence(["/workspace/"])
    assert f.is_allowed("/etc/passwd") is False
    assert f.is_allowed("/workspace_evil/x") is False  # prefix-not-segment attack

def test_traversal_blocked():
    f = ScopeFence(["/workspace/"])
    assert f.is_allowed("/workspace/../etc/passwd") is False

def test_relative_path_normalized(tmp_path, monkeypatch):
    f = ScopeFence([str(tmp_path)])
    monkeypatch.chdir(tmp_path)
    assert f.is_allowed("./sub/file.py") is True    # relative → normalized under workspace
    assert f.is_allowed("../outside.py") is False   # escapes the root