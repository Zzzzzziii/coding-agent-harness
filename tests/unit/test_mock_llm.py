# tests/unit/test_mock_llm.py
import pytest
from harness.llm.base import LLMResponse, ToolCall
from harness.llm.mock import MockLLMClient

def test_scripted_responses_in_order():
    m = MockLLMClient([
        LLMResponse(None, [ToolCall("c0", "read_file", {"path": "/a"})], "tool_calls"),
        LLMResponse("done", [], "stop"),
    ])
    assert m.chat([]).tool_calls[0].name == "read_file"
    assert m.chat([]).finish_reason == "stop"

def test_exhausted_raises():
    m = MockLLMClient([LLMResponse("done", [], "stop")])
    m.chat([])
    with pytest.raises(StopIteration):
        m.chat([])