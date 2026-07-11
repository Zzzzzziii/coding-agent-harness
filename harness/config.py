from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass(frozen=True)
class LLMConfig:
    model: str; base_url: str; max_tokens: int; temperature: float

@dataclass(frozen=True)
class AgentConfig:
    max_iters: int; system_prompt_file: str

@dataclass(frozen=True)
class GovernanceConfig:
    allowed_paths: list[str]; dangerous_patterns: list[str]
    deny_patterns: list[str]; hitl_timeout_seconds: int

@dataclass(frozen=True)
class TestsConfig:
    command: str

@dataclass(frozen=True)
class Config:
    llm: LLMConfig; agent: AgentConfig
    governance: GovernanceConfig; tests: TestsConfig

    @staticmethod
    def load(path: str) -> "Config":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        required = ["llm", "agent", "governance", "tests"]
        for key in required:
            if key not in raw:
                raise ValueError(f"Config missing required section: {key}")
        g = raw["governance"]
        return Config(
            llm=LLMConfig(model=raw["llm"]["model"], base_url=raw["llm"]["base_url"],
                          max_tokens=raw["llm"]["max_tokens"], temperature=raw["llm"]["temperature"]),
            agent=AgentConfig(max_iters=raw["agent"]["max_iters"],
                              system_prompt_file=raw["agent"]["system_prompt_file"]),
            governance=GovernanceConfig(
                allowed_paths=g["allowed_paths"], dangerous_patterns=g.get("dangerous_patterns", []),
                deny_patterns=g.get("deny_patterns", []), hitl_timeout_seconds=g["hitl_timeout_seconds"]),
            tests=TestsConfig(command=raw["tests"]["command"]),
        )