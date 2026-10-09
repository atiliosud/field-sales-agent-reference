import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mcp_url: str
    context_url: str
    max_steps: int
    tool_timeout_s: float
    turn_timeout_s: float
    prompt_orchestrator: str
    prompt_specialist: str
    azure_endpoint: str
    azure_api_key: str
    azure_deployment: str
    azure_api_version: str

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            mcp_url=env["MCP_URL"],
            context_url=env["CONTEXT_URL"],
            max_steps=int(env.get("HARNESS_MAX_STEPS", "6")),
            tool_timeout_s=float(env.get("HARNESS_TOOL_TIMEOUT_S", "10")),
            turn_timeout_s=float(env.get("HARNESS_TURN_TIMEOUT_S", "60")),
            prompt_orchestrator=env.get("PROMPT_ORCHESTRATOR", "orchestrator.v2"),
            prompt_specialist=env.get("PROMPT_SPECIALIST", "specialist.v1"),
            azure_endpoint=env.get("AZURE_OPENAI_ENDPOINT", ""),
            azure_api_key=env.get("AZURE_OPENAI_API_KEY", ""),
            azure_deployment=env.get("AZURE_OPENAI_DEPLOYMENT", ""),
            azure_api_version=env.get("AZURE_OPENAI_API_VERSION", ""),
        )
