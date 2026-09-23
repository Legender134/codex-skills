"""Conservative, line-preserving edits for Codex global TOML configuration."""

from __future__ import annotations

import copy
import json
import math
import re
import tomllib
from dataclasses import dataclass

from codex_routing.errors import RoutingConfigError
from codex_routing.spec import GlobalPolicy


OWNED_TOP_LEVEL = ("model", "model_reasoning_effort")
OWNED_AGENT_KEYS = (
    "enabled",
    "max_concurrent_threads_per_session",
    "default_subagent_model",
    "default_subagent_reasoning_effort",
    "interrupt_message",
)

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_MISSING = object()


@dataclass(frozen=True)
class AssignmentLocation:
    """The value span for one supported, directly owned TOML assignment."""

    path: tuple[str, ...]
    line_index: int
    value_start: int
    value_end: int


@dataclass
class AssignmentScan:
    """Line locations and table boundaries needed for surgical edits."""

    lines: list[str]
    assignments: dict[tuple[str, ...], list[AssignmentLocation]]
    first_table_index: int | None
    agents_header_index: int | None
    agents_end_index: int | None
    saw_agents_descendant: bool


def managed_config_values(policy: GlobalPolicy) -> dict[str, object]:
    """Return the complete global settings owned by the routing policy."""

    return {
        "model": policy.primary_model,
        "model_reasoning_effort": policy.primary_effort,
        "agents": {
            "enabled": True,
            "max_concurrent_threads_per_session": policy.max_threads,
            "default_subagent_model": policy.default_subagent_model,
            "default_subagent_reasoning_effort": policy.default_subagent_effort,
            "interrupt_message": policy.interrupt_message,
        },
    }


def merge_global_config(existing: str, policy: GlobalPolicy) -> str:
    """Merge one policy without rewriting or removing unmanaged TOML settings."""

    locations = scan_simple_assignments(existing)
    reject_ambiguous_owned_assignments(locations)
    before = _parse_toml(existing)
    _validate_existing_managed_values(before)

    merged = replace_or_insert_owned_assignments(existing, policy, locations)
    after = _parse_toml(merged)
    if not _same_toml_value(unmanaged_view(after), unmanaged_view(before)):
        raise RoutingConfigError("merge changed an unmanaged setting")
    assert_managed_values(after, policy)
    return preserve_newline_style(existing, merged)


def scan_simple_assignments(existing: str) -> AssignmentScan:
    """Locate editable managed assignments while rejecting ambiguous forms."""

    # TOML lines end at LF/CRLF, not at Unicode separators inside strings.
    parts = existing.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    scan = AssignmentScan(
        lines=lines,
        assignments={},
        first_table_index=None,
        agents_header_index=None,
        agents_end_index=None,
        saw_agents_descendant=False,
    )
    current_table: tuple[str, ...] | None = ()
    table_indexes: list[int] = []
    multiline_quote: str | None = None
    container_depth = 0

    for line_index, line in enumerate(lines):
        raw_line = _line_body(line)
        continued_value = multiline_quote is not None or container_depth > 0
        multiline_quote, container_depth = _next_value_state(
            raw_line, multiline_quote, container_depth
        )
        if continued_value:
            continue
        comment_index = _comment_index(raw_line)
        code = raw_line[:comment_index]
        header = _table_header(code)
        if header is not None:
            kind, body, path, bare_parts = header
            table_indexes.append(line_index)
            if scan.first_table_index is None:
                scan.first_table_index = line_index
            current_table = path
            if path == ("agents",):
                if kind != "table" or body != "agents" or not all(bare_parts):
                    _raise_unsupported(("agents",))
                if scan.agents_header_index is not None:
                    raise RoutingConfigError("managed key [agents] table is duplicated")
                scan.agents_header_index = line_index
            elif path and path[0] == "agents":
                scan.saw_agents_descendant = True
            continue

        assignment = _assignment_parts(raw_line)
        if assignment is None or current_table is None:
            continue
        key_source, value_start, value_end, value_source = assignment
        parsed_key = _parse_key_path(key_source)
        if parsed_key is None:
            continue
        key_parts, bare_parts = parsed_key
        path = current_table + key_parts

        if current_table == () and len(key_parts) > 1 and key_parts[0] == "agents":
            scan.saw_agents_descendant = True

        if not _is_owned_path(path):
            continue
        if len(key_parts) != 1 or not all(bare_parts):
            _raise_unsupported(path)
        if _is_unsupported_value_form(value_source):
            _raise_unsupported(path)

        location = AssignmentLocation(path, line_index, value_start, value_end)
        scan.assignments.setdefault(path, []).append(location)

    if scan.agents_header_index is not None:
        scan.agents_end_index = next(
            (index for index in table_indexes if index > scan.agents_header_index),
            len(lines),
        )
    elif scan.saw_agents_descendant:
        raise RoutingConfigError("managed key [agents] table has an unsupported implicit form")

    return scan


def reject_ambiguous_owned_assignments(scan: AssignmentScan) -> None:
    """Reject duplicate direct assignments before TOML parsing hides their source."""

    for path, locations in scan.assignments.items():
        if len(locations) > 1:
            raise RoutingConfigError(
                f"managed key '{_display_path(path)}' is duplicated"
            )


def replace_or_insert_owned_assignments(
    existing: str,
    policy: GlobalPolicy,
    scan: AssignmentScan,
) -> str:
    """Make the smallest text edits needed to materialize the desired policy."""

    del existing
    values = managed_config_values(policy)
    agent_values = values["agents"]
    assert isinstance(agent_values, dict)
    lines = list(scan.lines)
    desired = {
        ("model",): values["model"],
        ("model_reasoning_effort",): values["model_reasoning_effort"],
        **{
            ("agents", key): agent_values[key]
            for key in OWNED_AGENT_KEYS
        },
    }

    for path, locations in scan.assignments.items():
        location = locations[0]
        lines[location.line_index] = (
            lines[location.line_index][: location.value_start]
            + _toml_scalar(desired[path])
            + lines[location.line_index][location.value_end :]
        )

    newline = _newline_style(scan.lines)
    missing_agents = [
        key for key in OWNED_AGENT_KEYS if ("agents", key) not in scan.assignments
    ]
    if scan.agents_header_index is not None and missing_agents:
        assert scan.agents_end_index is not None
        _insert_lines(
            lines,
            scan.agents_end_index,
            [_assignment_line(key, desired[("agents", key)], newline) for key in missing_agents],
            newline,
        )

    missing_top_level = [
        key for key in OWNED_TOP_LEVEL if (key,) not in scan.assignments
    ]
    if missing_top_level:
        top_level_index = (
            scan.first_table_index
            if scan.first_table_index is not None
            else len(lines)
        )
        _insert_lines(
            lines,
            top_level_index,
            [_assignment_line(key, desired[(key,)], newline) for key in missing_top_level],
            newline,
        )

    if scan.agents_header_index is None:
        _insert_lines(
            lines,
            len(lines),
            [f"[agents]{newline}"]
            + [_assignment_line(key, desired[("agents", key)], newline) for key in OWNED_AGENT_KEYS],
            newline,
        )

    return "".join(lines)


def unmanaged_view(payload: dict[str, object]) -> dict[str, object]:
    """Return parsed TOML after removing the settings owned by this merger."""

    view = copy.deepcopy(payload)
    for key in OWNED_TOP_LEVEL:
        view.pop(key, None)
    agents = view.get("agents")
    if isinstance(agents, dict):
        for key in OWNED_AGENT_KEYS:
            agents.pop(key, None)
        if not agents:
            view.pop("agents", None)
    return view


def assert_managed_values(payload: dict[str, object], policy: GlobalPolicy) -> None:
    """Check that the merged TOML exactly reflects the supplied policy."""

    values = managed_config_values(policy)
    if (
        payload.get("model") != values["model"]
        or payload.get("model_reasoning_effort") != values["model_reasoning_effort"]
    ):
        raise RoutingConfigError("merged managed values do not match the policy")
    agents = payload.get("agents")
    expected_agents = values["agents"]
    if not isinstance(agents, dict) or not isinstance(expected_agents, dict):
        raise RoutingConfigError("merged managed values do not match the policy")
    if any(agents.get(key) != expected_agents[key] for key in OWNED_AGENT_KEYS):
        raise RoutingConfigError("merged managed values do not match the policy")


def preserve_newline_style(existing: str, merged: str) -> str:
    """Keep existing newline bytes untouched; generated lines use the input style."""

    del existing
    return merged


def _parse_toml(text: str) -> dict[str, object]:
    if not text.strip():
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RoutingConfigError(f"invalid TOML: {exc}") from exc


def _validate_existing_managed_values(payload: dict[str, object]) -> None:
    for key in OWNED_TOP_LEVEL:
        if key in payload and not _is_scalar(payload[key]):
            _raise_unsupported((key,))

    agents = payload.get("agents", _MISSING)
    if agents is _MISSING:
        return
    if not isinstance(agents, dict):
        _raise_unsupported(("agents",))
    for key in OWNED_AGENT_KEYS:
        if key in agents and not _is_scalar(agents[key]):
            _raise_unsupported(("agents", key))


def _is_scalar(value: object) -> bool:
    return type(value) in (str, int, bool)


def _line_body(line: str) -> str:
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1]
    return line


def _next_value_state(
    text: str, quote: str | None, depth: int
) -> tuple[str | None, int]:
    """Track continued values without treating their contents as statements.

    Single-line strings and comments cannot open a multiline string. Escapes in
    basic strings and closing runs of four or five quotes must be consumed before
    scanning the rest of the line. Brackets outside strings/comments track array
    and inline-table nesting. tomllib still validates the complete syntax.
    """

    index = 0
    while index < len(text):
        character = text[index]
        if quote is not None:
            if quote[0] == '"' and character == "\\":
                index += 2
                continue
            if text.startswith(quote, index):
                index += len(quote)
                if len(quote) == 3:
                    while index < len(text) and text[index] == quote[0]:
                        index += 1
                quote = None
                continue
        elif character == "#":
            break
        elif character in ('"', "'"):
            quote = character * 3 if text.startswith(character * 3, index) else character
            index += len(quote)
            continue
        elif character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
        index += 1
    return (quote if quote is not None and len(quote) == 3 else None), depth


def _same_toml_value(left: object, right: object) -> bool:
    """Compare parsed values, including TOML's non-reflexive NaN floats."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_toml_value(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_toml_value(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, float) and math.isnan(left):
        return math.isnan(right)
    return left == right


def _comment_index(text: str) -> int:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text):
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif quote == "'":
            if char == "'":
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "#":
            return index
    return len(text)


def _unquoted_index(text: str, target: str) -> int | None:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(text):
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif quote == "'":
            if char == "'":
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == target:
            return index
    return None


def _table_header(
    code: str,
) -> tuple[str, str, tuple[str, ...], tuple[bool, ...]] | None:
    stripped = code.strip()
    if stripped.startswith("[[") and stripped.endswith("]]"):
        body = stripped[2:-2]
        kind = "array"
    elif stripped.startswith("[") and stripped.endswith("]"):
        body = stripped[1:-1]
        kind = "table"
    else:
        return None

    parsed = _parse_key_path(body)
    if parsed is None:
        return None
    path, bare_parts = parsed
    return kind, body, path, bare_parts


def _assignment_parts(raw_line: str) -> tuple[str, int, int, str] | None:
    comment_index = _comment_index(raw_line)
    code = raw_line[:comment_index]
    equals_index = _unquoted_index(code, "=")
    if equals_index is None:
        return None

    key_source = code[:equals_index].strip()
    value_source = code[equals_index + 1 :]
    value_without_padding = value_source.strip(" \t")
    if not key_source or not value_without_padding:
        return None
    leading_padding = len(value_source) - len(value_source.lstrip(" \t"))
    trailing_padding = len(value_source) - len(value_source.rstrip(" \t"))
    value_start = equals_index + 1 + leading_padding
    value_end = equals_index + 1 + len(value_source) - trailing_padding
    return key_source, value_start, value_end, value_without_padding


def _parse_key_path(source: str) -> tuple[tuple[str, ...], tuple[bool, ...]] | None:
    components = _split_key_components(source)
    if components is None:
        return None

    values: list[str] = []
    bare_parts: list[bool] = []
    for component in components:
        if _BARE_KEY.fullmatch(component):
            values.append(component)
            bare_parts.append(True)
            continue
        if not component or component[0] not in ('"', "'"):
            return None
        try:
            value = tomllib.loads(f"value = {component}")["value"]
        except tomllib.TOMLDecodeError:
            return None
        if not isinstance(value, str):
            return None
        values.append(value)
        bare_parts.append(False)
    return tuple(values), tuple(bare_parts)


def _split_key_components(source: str) -> list[str] | None:
    components: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    for index, char in enumerate(source):
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif quote == "'":
            if char == "'":
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == ".":
            component = source[start:index].strip()
            if not component:
                return None
            components.append(component)
            start = index + 1
    if quote is not None:
        return None
    component = source[start:].strip()
    if not component:
        return None
    components.append(component)
    return components


def _is_owned_path(path: tuple[str, ...]) -> bool:
    return (len(path) == 1 and path[0] in OWNED_TOP_LEVEL) or (
        len(path) == 2 and path[0] == "agents" and path[1] in OWNED_AGENT_KEYS
    )


def _is_unsupported_value_form(value: str) -> bool:
    return value.startswith(('"""', "'''", "[", "{"))


def _raise_unsupported(path: tuple[str, ...]) -> None:
    raise RoutingConfigError(
        f"managed key '{_display_path(path)}' uses an unsupported form"
    )


def _display_path(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _newline_style(lines: list[str]) -> str:
    return "\r\n" if any("\r\n" in line for line in lines) else "\n"


def _assignment_line(key: str, value: object, newline: str) -> str:
    return f"{key} = {_toml_scalar(value)}{newline}"


def _toml_scalar(value: object) -> str:
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False)
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    raise TypeError(f"unsupported managed value type: {type(value).__name__}")


def _insert_lines(
    lines: list[str], index: int, inserted: list[str], newline: str
) -> None:
    if index and not _has_line_ending(lines[index - 1]):
        lines[index - 1] += newline
    lines[index:index] = inserted


def _has_line_ending(line: str) -> bool:
    return line.endswith("\n") or line.endswith("\r")
