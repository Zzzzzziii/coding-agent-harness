# harness/__main__.py
import sys
from harness.creds import CredentialStore


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("usage: harness [run <task>|serve|creds {status|set|clear}] [--mock]"); return 0
    cmd = argv[0]
    if cmd == "creds":
        sub = argv[1] if len(argv) > 1 else "status"
        cs = CredentialStore()
        if sub == "status":
            print(f"configured: {'true' if cs.get() else 'false'}"); return 0
        if sub == "set":
            import getpass
            key = getpass.getpass("Paste DEEPSEEK_API_KEY (hidden, no echo): ").strip()
            cs.set(key); print("stored."); return 0
        if sub == "clear":
            cs.clear(); print("cleared."); return 0
        print(f"unknown creds subcommand: {sub}"); return 2
    if cmd == "serve":
        from harness.server import serve; serve(); return 0
    if cmd == "run":
        return _run(argv[1:])
    print(f"unknown command: {cmd}"); return 2


def _run(args):
    from harness.config import Config
    from harness.creds import CredentialStore
    from harness.tools.base import ToolRegistry
    from harness.tools.builtin import register_builtins
    from harness.governance.pipeline import Governance
    from harness.governance.scope_fence import ScopeFence
    from harness.governance.guardrail import Guardrail
    from harness.governance.hitl import HITLStateMachine
    from harness.memory.context_store import ContextStore
    from harness.feedback.injector import FeedbackInjector
    from harness.feedback.test_runner import TestRunner
    from harness.loop import AgentLoop
    cfg = Config.load("config.yaml")
    sys_prompt = open(cfg.agent.system_prompt_file, encoding="utf-8").read()
    if "--mock" in args:
        from harness.llm.mock import MockLLMClient
        from harness.llm.base import LLMResponse, ToolCall
        llm = MockLLMClient([LLMResponse("done", [], "stop")])
        task = " ".join(a for a in args if a != "--mock")
    else:
        from harness.llm.deepseek import DeepSeekClient
        key = CredentialStore.interactive_first_run()
        llm = DeepSeekClient(api_key=key, model=cfg.llm.model, base_url=cfg.llm.base_url,
                             max_tokens=cfg.llm.max_tokens, temperature=cfg.llm.temperature)
        task = " ".join(args)
    reg = ToolRegistry(); register_builtins(reg, cfg)
    gov = Governance(ScopeFence(cfg.governance.allowed_paths),
                     Guardrail(cfg.governance.dangerous_patterns, cfg.governance.deny_patterns),
                     HITLStateMachine())
    cs = ContextStore(sys_prompt)  # shared store — feedback reaches the LLM context
    loop = AgentLoop(llm, cfg, gov, reg, cs, FeedbackInjector(cs), TestRunner())
    result = loop.run(task)
    print(f"status={result.final_status} iters={result.iterations} "
          f"actions={len(result.actions)} executed={len(result.executed_commands)}")
    return 0 if result.final_status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())