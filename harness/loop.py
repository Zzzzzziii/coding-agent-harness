# harness/loop.py
from harness.models import Action, AgentRunResult, Message
from harness.llm.base import next_action

class AgentLoop:
    def __init__(self, llm, config, governance, tools, context_store,
                 feedback_injector, test_runner, approver=None):
        self.llm = llm
        self.config = config
        self.governance = governance
        self.tools = tools
        self.context_store = context_store
        self.feedback_injector = feedback_injector
        self.test_runner = test_runner
        self.approver = approver

    def run(self, task: str) -> AgentRunResult:
        actions: list[Action] = []
        executed: list[str] = []
        self.context_store.add(Message("user", task))
        max_iters = getattr(self.config, "max_iters", 20)
        for i in range(1, max_iters + 1):
            try:
                resp = self._chat_with_retry()
            except StopIteration:  # mock script exhausted → end gracefully, don't crash
                return AgentRunResult("error", i, actions, executed)
            if resp is None:
                return AgentRunResult("error", i, actions, executed)
            action = next_action(resp)
            if action is None:
                return AgentRunResult("success", i, actions, executed)
            decision = self.governance.check(action, approver=self.approver)
            action.blocked = decision.blocked
            action.block_reason = decision.reason
            action.approval_id = decision.approval_id
            actions.append(action)
            tool_call_id = resp.tool_calls[0].id if resp.tool_calls else f"step{i}"
            if decision.blocked:
                self.feedback_injector.inject_block(action, decision, tool_call_id)
                continue
            result = self.tools.dispatch(action)
            if action.tool == "run_tests":
                tf = self.test_runner.parse(result)
                self.feedback_injector.inject_test(action, tf, tool_call_id)
                executed.append(action.args.get("test_cmd") or "pytest")
            else:
                self.feedback_injector.inject_result(action, result, tool_call_id)
                if action.tool in ("run_shell",):
                    executed.append(action.args.get("command", ""))
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