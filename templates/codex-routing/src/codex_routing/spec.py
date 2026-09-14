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
    default_subagent_model: str = "gpt-5.6-sol"
    default_subagent_effort: str = "medium"
    interrupt_message: bool = True


@dataclass(frozen=True)
class AgentPolicy:
    """The model, reasoning, and sandbox boundary for a named role."""

    name: str
    model: str
    effort: str
    sandbox_mode: str


@dataclass(frozen=True)
class RepoPolicy:
    """The project instruction template associated with one EGS repository."""

    name: str
    instructions_template: str


GLOBAL_POLICIES: dict[str, GlobalPolicy] = {
    "windows": GlobalPolicy("windows", "gpt-6-astra", "low", 1),
    "wsl": GlobalPolicy("wsl", "gpt-6-astra", "low", 1),
}


AGENT_POLICIES: dict[str, AgentPolicy] = {
    "scout": AgentPolicy("scout", "gpt-5.6-luna", "high", "read-only"),
    "explorer": AgentPolicy("explorer", "gpt-5.6-terra", "medium", "read-only"),
    "worker": AgentPolicy("worker", "gpt-5.6-sol", "medium", "workspace-write"),
    "reviewer": AgentPolicy("reviewer", "gpt-6-astra", "low", "read-only"),
    "routine_worker": AgentPolicy("routine_worker", "gpt-5.6-terra", "medium", "workspace-write"),
    "critical_reviewer": AgentPolicy("critical_reviewer", "gpt-6-astra", "high", "read-only"),
}


REPO_POLICIES: dict[str, RepoPolicy] = {
    "preprocess-cli": RepoPolicy(
        "preprocess-cli", "projects/preprocess-cli-AGENTS.md"
    ),
    "3dgs-gen": RepoPolicy("3dgs-gen", "projects/3dgs-gen-AGENTS.md"),
    "egs-main": RepoPolicy("egs-main", "projects/egs-main-AGENTS.md"),
}
