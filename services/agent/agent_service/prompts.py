from dataclasses import dataclass
from pathlib import Path

import yaml


def _find_prompts_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "prompts").is_dir():
            return parent / "prompts"
    raise RuntimeError("prompts directory not found")


PROMPTS_DIR = _find_prompts_dir()


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    system: str
    input: str
    tools: dict[str, str]


def load_prompt(name: str) -> Prompt:
    """Load prompts/<id>.<version>.yaml, for example `orchestrator.v1`."""
    prompt_id, _, version = name.partition(".")
    data = yaml.safe_load((PROMPTS_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    return Prompt(
        id=prompt_id,
        version=version,
        system=data["system"],
        input=data["input"],
        tools=data.get("tools", {}),
    )
