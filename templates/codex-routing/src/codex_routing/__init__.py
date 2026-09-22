"""Canonical policy objects and safe template access for Codex routing."""

from .errors import RoutingConfigError
from .spec import (
    AGENT_POLICIES,
    GLOBAL_POLICIES,
    AgentPolicy,
    GlobalPolicy,
)
from .templates import load_template

__all__ = [
    "AGENT_POLICIES",
    "GLOBAL_POLICIES",
    "AgentPolicy",
    "GlobalPolicy",
    "RoutingConfigError",
    "load_template",
]
