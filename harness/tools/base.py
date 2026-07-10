from typing import Callable
from harness.models import Action, ToolResult

ToolHandler = Callable[[dict], ToolResult]

class ToolRegistry:
    def __init__(self):
        self._handlers: dict[str, ToolHandler] = {}
        self._schemas: dict[str, dict] = {}

    def register(self, name: str, schema: dict, handler: ToolHandler) -> "ToolRegistry":
        self._handlers[name] = handler
        self._schemas[name] = schema
        return self

    def dispatch(self, action: Action) -> ToolResult:
        h = self._handlers.get(action.tool)
        if h is None:
            return ToolResult(ok=False, output={}, error=f"unknown tool: {action.tool}")
        try:
            return h(action.args or {})
        except Exception as e:  # never crash the loop
            return ToolResult(ok=False, output={}, error=f"{type(e).__name__}: {e}")

    def schemas(self) -> list[dict]:
        return list(self._schemas.values())