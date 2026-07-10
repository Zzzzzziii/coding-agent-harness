from harness.llm.base import LLMResponse, ToolCall

class MockLLMClient:
    def __init__(self, script: list[LLMResponse]):
        self.script = list(script)
        self._idx = 0

    def chat(self, messages, tools=None) -> LLMResponse:
        if self._idx >= len(self.script):
            raise StopIteration("MockLLMClient script exhausted")
        resp = self.script[self._idx]
        self._idx += 1
        return resp