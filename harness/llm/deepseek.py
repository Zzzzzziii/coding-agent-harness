# harness/llm/deepseek.py
import json
import logging
from openai import OpenAI
from harness.llm.base import LLMResponse, ToolCall

_log = logging.getLogger("harness.llm")


def _redact(key):
    if not key:
        return "<unset>"
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}***...***{key[-3:]}"


class DeepSeekClient:
    def __init__(self, api_key, model, base_url, max_tokens=4096, temperature=0.0):
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        _log.debug("DeepSeekClient ready model=%s base_url=%s key=%s",
                   model, base_url, _redact(api_key))

    def chat(self, messages, tools=None) -> LLMResponse:
        oai_msgs = [{"role": m.role, "content": m.content} for m in messages]
        kwargs = {"model": self.model, "messages": oai_msgs,
                  "max_tokens": self.max_tokens, "temperature": self.temperature}
        if tools:
            kwargs["tools"] = tools
        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        tcs = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tcs.append(ToolCall(id=tc.id, name=tc.function.name,
                                    args=json.loads(tc.function.arguments or "{}")))
        return LLMResponse(content=choice.message.content, tool_calls=tcs,
                           finish_reason=choice.finish_reason or "stop")