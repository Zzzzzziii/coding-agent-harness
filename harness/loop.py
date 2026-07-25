# harness/loop.py
from harness.models import Action, AgentRunResult, Message
from harness.llm.base import next_action

class AgentLoop:
    def __init__(self, llm, config, governance, tools, context_store,
                 feedback_injector, test_runner, approver=None, on_event=None):
        self.llm = llm
        self.config = config
        self.governance = governance
        self.tools = tools
        self.context_store = context_store
        self.feedback_injector = feedback_injector
        self.test_runner = test_runner
        self.approver = approver
        self.on_event = on_event

    def _emit(self, event):
        if self.on_event is not None:
            self.on_event(event)

    def run(self, task: str) -> AgentRunResult:
        actions: list[Action] = []
        executed: list[str] = []
        self.context_store.add(Message("user", task))
        max_iters = getattr(self.config, "max_iters", 20)
        for i in range(1, max_iters + 1):
            self._emit({"type": "step", "iter": i})
            try:
                resp = self._chat_with_retry()
            except StopIteration:  # mock script exhausted → end gracefully, don't crash
                self._emit({"type": "error", "final_status": "error", "iterations": i})
                return AgentRunResult("error", i, actions, executed)
            if resp is None:
                self._emit({"type": "error", "final_status": "error", "iterations": i})
                return AgentRunResult("error", i, actions, executed)
            action = next_action(resp)
            if action is None:
                self._emit({"type": "success", "final_status": "success", "iterations": i})
                return AgentRunResult("success", i, actions, executed)
            self._emit({"type": "action", "tool": action.tool, "args": action.args})
            decision = self.governance.check(action, approver=self.approver)
            action.blocked = decision.blocked
            action.block_reason = decision.reason
            action.approval_id = decision.approval_id
            actions.append(action)
            self._emit({"type": "governance", "blocked": decision.blocked,
                        "reason": decision.reason, "layer": decision.layer,
                        "approval_id": decision.approval_id})
            tool_call_id = resp.tool_calls[0].id if resp.tool_calls else f"step{i}"
            if decision.blocked:
                self.feedback_injector.inject_block(action, decision, tool_call_id)
                continue
            result = self.tools.dispatch(action)
            self._emit({"type": "tool_result", "tool": action.tool, "ok": result.ok,
                        "output": result.output, "error": result.error})
            if action.tool == "run_tests":
                tf = self.test_runner.parse(result)
                self.feedback_injector.inject_test(action, tf, tool_call_id)
                executed.append(action.args.get("test_cmd") or "pytest")
            else:
                self.feedback_injector.inject_result(action, result, tool_call_id)
                if action.tool in ("run_shell",):
                    executed.append(action.args.get("command", ""))
        self._emit({"type": "max_iters", "final_status": "max_iters", "iterations": max_iters})
        return AgentRunResult("max_iters", max_iters, actions, executed)

    def _chat_with_retry(self, retries: int = 3):
        last = None
        for _ in range(retries):
            try:
                return self.llm.chat(self.context_store.messages, tools=self.tools.schemas())
            except StopIteration:
                raise
            except Exception as e:
                last = e
        return None