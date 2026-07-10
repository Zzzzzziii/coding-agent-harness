from dataclasses import dataclass

@dataclass
class Message:
    role: str
    content: str
    tool_call_id: str | None = None

@dataclass
class Action:
    tool: str
    args: dict
    raw_llm_response: str | None = None
    blocked: bool = False
    block_reason: str | None = None
    approval_id: str | None = None
    status: str | None = None

@dataclass
class ToolResult:
    ok: bool
    output: dict
    error: str | None = None

@dataclass
class GovernanceDecision:
    blocked: bool
    reason: str
    layer: str | None = None
    approval_id: str | None = None

@dataclass
class TestFeedback:
    passed: int
    failed: int
    errors: list[str]
    raw_output: str
    __test__ = False  # suppress PytestCollectionWarning (class name starts with "Test")
    @property
    def success(self) -> bool:
        return self.failed == 0

@dataclass
class AgentRunResult:
    final_status: str
    iterations: int
    actions: list[Action]
    executed_commands: list[str]