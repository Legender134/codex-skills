"""Canonical policy objects and safe template access for Codex routing."""

from .errors import RoutingConfigError
from .spec import (
    AGENT_POLICIES,
    GLOBAL_POLICIES,
    REPO_POLICIES,
    AgentPolicy,
    GlobalPolicy,
    RepoPolicy,
)
from .templates import load_template

__all__ = [
    "AGENT_POLICIES",
    "GLOBAL_POLICIES",
    "REPO_POLICIES",
    "AgentPolicy",
    "GlobalPolicy",
    "RepoPolicy",
    "RoutingConfigError",
    "load_template",
]
