# tests/unit/test_llm_parser.py
from harness.llm.base import LLMResponse, ToolCall, next_action

def test_next_action_returns_first_tool_call():
    resp = LLMResponse(content=None, tool_calls=[
        ToolCall(id="c0", name="read_file", args={"path": "/a"}),
        ToolCall(id="c1", name="write_file", args={"path": "/b", "content": "x"}),
    ], finish_reason="tool_calls")
    a = next_action(resp)
    assert a is not None and a.tool == "read_file" and a.args == {"path": "/a"}

def test_next_action_none_when_done():
    resp = LLMResponse(content="done", tool_calls=[], finish_reason="stop")
    assert next_action(resp) is None