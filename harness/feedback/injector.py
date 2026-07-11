from harness.models import Action, ToolResult, GovernanceDecision, TestFeedback, Message

class FeedbackInjector:
    def __init__(self, context_store):
        self.context_store = context_store

    def _add(self, content: str, tool_call_id: str) -> None:
        self.context_store.add(Message(role="tool", content=content, tool_call_id=tool_call_id))

    def inject_result(self, action: Action, result: ToolResult, tool_call_id: str) -> None:
        if result.ok:
            self._add(f"[ok] {action.tool} -> {result.output}", tool_call_id)
        else:
            self._add(f"[error] {action.tool} failed: {result.error}", tool_call_id)

    def inject_test(self, action: Action, tf: TestFeedback, tool_call_id: str) -> None:
        status = "PASSED" if tf.success else "FAILED"
        errs = "; ".join(tf.errors) if tf.errors else ""
        self._add(f"[test {status}] passed={tf.passed} failed={tf.failed} errors=[{errs}]", tool_call_id)

    def inject_block(self, action: Action, decision: GovernanceDecision, tool_call_id: str) -> None:
        self._add(f"[BLOCKED by {decision.layer}] {decision.reason}", tool_call_id)