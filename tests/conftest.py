import pytest
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient
from harness.models import ToolResult

@pytest.fixture
def llm_response():
    def _make(tool=None, args=None, finish=False, content=None):
        if finish:
            return LLMResponse(content or "done", [], "stop")
        return LLMResponse(None, [ToolCall(f"c{x}", tool, args or {})], "tool_calls")
    return _make

class ScriptedTool:
    """Returns canned ToolResults in order (keeps feedback parsing real)."""
    def __init__(self, results):
        self._results = list(results); self._i = 0
    def __call__(self, args):
        r = self._results[self._i]; self._i += 1; return r

@pytest.fixture
def scripted_tool():
    return ScriptedTool