"""Immutable routing policy definitions approved for the rollout."""

from dataclasses import dataclass
from typing import Literal


PlatformName = Literal["windows", "wsl"]


@dataclass(frozen=True)
class GlobalPolicy:
    """The model and concurrency policy for one host platform."""

    platform: PlatformName
    primary_model: str
    primary_effort: str
    max_threads: int
    default_subagent_model: str = "gpt-6-sol"
    default_subagent_effort: str = "high"
    interrupt_message: bool = True


@dataclass(frozen=True)
class AgentPolicy:
    """The model, reasoning, and sandbox boundary for a named role."""

    name: str
    model: str
    effort: str
    sandbox_mode: str


GLOBAL_POLICIES: dict[str, GlobalPolicy] = {
    "windows": GlobalPolicy("windows", "gpt-6-sol", "high", 2),
    "wsl": GlobalPolicy("wsl", "gpt-6-sol", "high", 2),
}


AGENT_POLICIES: dict[str, AgentPolicy] = {
    "scout": AgentPolicy("scout", "gpt-6-luna", "low", "read-only"),
    "explorer": AgentPolicy("explorer", "gpt-6-luna", "high", "read-only"),
    "worker": AgentPolicy("worker", "gpt-6-luna", "max", "workspace-write"),
    "reviewer": AgentPolicy("reviewer", "gpt-6-sol", "high", "read-only"),
    "routine_worker": AgentPolicy("routine_worker", "gpt-6-luna", "high", "workspace-write"),
    "critical_reviewer": AgentPolicy("critical_reviewer", "gpt-6-astra", "high", "read-only"),
}
