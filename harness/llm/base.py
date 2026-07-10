from dataclasses import dataclass
from typing import Protocol
from harness.models import Action

@dataclass
class ToolCall:
    id: str; name: str; args: dict

@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str

class LLMClient(Protocol):
    def chat(self, messages: list, tools: list[dict] | None = None) -> LLMResponse: ...

def next_action(resp: LLMResponse) -> Action | None:
    if resp.tool_calls:
        tc = resp.tool_calls[0]
        return Action(tool=tc.name, args=tc.args, raw_llm_response=resp.content)
    return None