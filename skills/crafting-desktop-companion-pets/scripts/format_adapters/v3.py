from __future__ import annotations

from dataclasses import dataclass
import re

from .base import (
    ImageAsset,
    PackageCheck,
    PackageContext,
    PackageInputError,
    grid_cell_visible,
    is_integer,
    is_number,
    load_asset,
    require_list,
    require_mapping,
    require_text,
)


_V3_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ACTION_ID = re.compile(r"^[a-z][a-zA-Z0-9_-]{0,63}$")
_ROLES = frozenset({"idle", "move", "interaction", "burstMove", "gaze"})
_DIRECT_FIELDS = frozenset(
    {
        "label", "role", "direction", "row", "startColumn", "frameCount", "frameMs",
        "frameDurations", "loop", "repeatCount", "holdMs", "showInMenu",
        "includeInShowcase", "autoplayWeight", "cooldownMs", "autoplayGroup",
        "minDistance", "travelStartFrame", "travelEndFrame", "travelDistanceRatio",
        "maxVerticalRatio",
    }
)
_MIRROR_FIELDS = frozenset(
    {
        "label", "role", "direction", "mirrorOf", "showInMenu", "includeInShowcase",
        "autoplayWeight", "cooldownMs", "autoplayGroup", "minDistance",
        "travelDistanceRatio", "maxVerticalRatio",
    }
)


@dataclass(frozen=True)
class _Action:
    key: str
    role: str
    direction: str | None
    row: int
    start_column: int
    frame_count: int
    loop: bool
    direct: bool
    show_in_menu: bool
    autoplay_weight: int


def _validate_common(
    key: str, entry: dict[str, object]
) -> tuple[str, str | None, int, bool]:
    label = entry.get("label")
    role = entry.get("role")
    if (
        not isinstance(label, str)
        or not label.strip()
        or len(label.strip()) > 32
        or not all(character.isprintable() for character in label.strip())
    ):
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key}.label is invalid")
    if not isinstance(role, str) or role not in _ROLES:
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key}.role is unsupported")
    direction = entry.get("direction")
    if role in {"move", "burstMove"}:
        if direction not in {"left", "right"}:
            raise PackageInputError(
                "V3_ACTION_INVALID", f"actions.{key}.direction must be left or right"
            )
    elif direction is not None:
        raise PackageInputError(
            "V3_ACTION_INVALID", f"actions.{key}.direction is only for movement"
        )
    weight = entry.get("autoplayWeight", 10 if role == "move" else 0)
    if not is_integer(weight, 0, 100):
        raise PackageInputError(
            "V3_ACTION_INVALID", f"actions.{key}.autoplayWeight is invalid"
        )
    if role in {"idle", "gaze"} and weight != 0:
        raise PackageInputError(
            "V3_ACTION_INVALID", f"actions.{key}.autoplayWeight must be zero"
        )
    show_in_menu = entry.get("showInMenu", role != "gaze")
    include_in_showcase = entry.get("includeInShowcase", True)
    if not isinstance(show_in_menu, bool) or not isinstance(include_in_showcase, bool):
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key} menu flags are invalid")
    group = entry.get("autoplayGroup", "")
    if not isinstance(group, str) or (group and not re.fullmatch(r"[a-z][a-zA-Z0-9_-]{0,31}", group)):
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key}.autoplayGroup is invalid")
    if role != "interaction" and group:
        raise PackageInputError(
            "V3_ACTION_INVALID", f"actions.{key}.autoplayGroup requires interaction"
        )
    cooldown = entry.get("cooldownMs", 0)
    if not is_integer(cooldown, 0, 600_000):
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key}.cooldownMs is invalid")
    distance = entry.get("minDistance", 0)
    if not is_integer(distance, 0, 10_000) or (role != "burstMove" and distance != 0):
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key}.minDistance is invalid")
    for name, lower, upper in (
        ("travelDistanceRatio", 0.05, 1.0),
        ("maxVerticalRatio", 0.0, 1.0),
    ):
        value = entry.get(name)
        if value is not None and not is_number(value, lower, upper):
            raise PackageInputError("V3_ACTION_INVALID", f"actions.{key}.{name} is invalid")
        if role != "burstMove" and value is not None:
            raise PackageInputError("V3_ACTION_INVALID", f"actions.{key}.{name} requires burstMove")
    return role, direction if isinstance(direction, str) else None, weight, show_in_menu


def _parse_direct(key: str, entry: dict[str, object]) -> _Action:
    if set(entry) - _DIRECT_FIELDS:
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key} has unknown fields")
    role, direction, weight, show_in_menu = _validate_common(key, entry)
    row = entry.get("row")
    start_column = entry.get("startColumn", 0)
    frame_count = entry.get("frameCount")
    if not is_integer(row, 0, 127) or not is_integer(start_column, 0, 63) or not is_integer(frame_count, 1, 512):
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key} has invalid frame coordinates")
    frame_ms = entry.get("frameMs")
    frame_durations = entry.get("frameDurations")
    if (frame_ms is None) == (frame_durations is None):
        raise PackageInputError(
            "V3_FRAME_DURATIONS_INVALID", f"actions.{key} needs exactly one duration form"
        )
    if frame_ms is not None and not is_integer(frame_ms, 33, 2_000):
        raise PackageInputError(
            "V3_FRAME_DURATIONS_INVALID", f"actions.{key}.frameMs is invalid"
        )
    if frame_durations is not None and (
        not isinstance(frame_durations, list)
        or len(frame_durations) != frame_count
        or any(not is_integer(value, 33, 2_000) for value in frame_durations)
    ):
        raise PackageInputError(
            "V3_FRAME_DURATIONS_INVALID", f"actions.{key}.frameDurations is invalid"
        )
    loop = entry.get("loop", role == "idle")
    if not isinstance(loop, bool):
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key}.loop is invalid")
    repeat_count = entry.get("repeatCount", 1)
    if not is_integer(repeat_count, 1, 20) or (loop and "repeatCount" in entry):
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key}.repeatCount is invalid")
    hold_ms = entry.get("holdMs", 0)
    if not is_integer(hold_ms, 0, 10_000):
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key}.holdMs is invalid")
    if role == "idle" and not loop:
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key} idle must loop")
    if role in {"interaction", "burstMove"} and loop:
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key} finite action may not loop")
    if role == "gaze" and frame_count not in {16, 32, 64}:
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key} gaze frame count is invalid")
    if role == "burstMove":
        start = entry.get("travelStartFrame", max(1, frame_count // 3))
        if not is_integer(start, 0, frame_count - 2):
            raise PackageInputError(
                "V3_ACTION_INVALID", f"actions.{key} burstMove timing is invalid"
            )
        end = entry.get(
            "travelEndFrame",
            min(frame_count - 1, max(start + 1, frame_count * 2 // 3)),
        )
        if (
            frame_count < 3
            or repeat_count != 1
            or not is_integer(end, start + 1, frame_count - 1)
        ):
            raise PackageInputError("V3_ACTION_INVALID", f"actions.{key} burstMove timing is invalid")
    elif "travelStartFrame" in entry or "travelEndFrame" in entry:
        raise PackageInputError("V3_ACTION_INVALID", f"actions.{key} travel frames require burstMove")
    return _Action(
        key,
        role,
        direction,
        row,
        start_column,
        frame_count,
        loop,
        True,
        show_in_menu,
        weight,
    )


def _validate_cells(asset: ImageAsset, action: _Action) -> None:
    columns = asset.width // 192
    rows = asset.height // 208
    start = action.row * columns + action.start_column
    for offset in range(action.frame_count):
        row, column = divmod(start + offset, columns)
        if row >= rows:
            raise PackageInputError(
                "V3_CELL_OUT_OF_BOUNDS",
                "v3 action frame extends outside spritesheet",
                {"action": action.key, "frame": offset},
            )
        if not grid_cell_visible(asset, 192, 208, row, column):
            raise PackageInputError(
                "V3_REFERENCED_CELL_EMPTY",
                "v3 action references an empty atlas cell",
                {"action": action.key, "row": row, "column": column},
            )


def _validate_states(manifest: dict[str, object], actions: dict[str, _Action]) -> None:
    states = manifest.get("states")
    if states is None:
        return
    mapping = require_mapping(states, "V3_STATES_INVALID", "v3 states must be an object")
    if not 1 <= len(mapping) <= 16:
        raise PackageInputError("V3_STATES_INVALID", "v3 state count is invalid")
    used_actions: set[str] = set()
    for key, value in mapping.items():
        if not isinstance(key, str) or _ACTION_ID.fullmatch(key) is None:
            raise PackageInputError("V3_STATES_INVALID", "v3 state id is invalid")
        entry = require_mapping(value, "V3_STATES_INVALID", f"states.{key} is invalid")
        required = {
            "label", "enterAction", "residentActions", "exitAction", "minDurationMs",
            "rampDurationMs", "maxDurationMs", "exitChanceAfterMin", "exitChanceAfterRamp",
        }
        if set(entry) != required:
            raise PackageInputError("V3_STATES_INVALID", f"states.{key} has invalid fields")
        label = entry.get("label")
        if (
            not isinstance(label, str)
            or not label.strip()
            or len(label.strip()) > 32
            or not all(character.isprintable() for character in label.strip())
        ):
            raise PackageInputError("V3_STATES_INVALID", f"states.{key}.label is invalid")
        residents = require_list(
            entry.get("residentActions"), "V3_STATES_INVALID", f"states.{key}.residentActions is invalid"
        )
        if not 2 <= len(residents) <= 16:
            raise PackageInputError("V3_STATES_INVALID", f"states.{key}.residentActions is invalid")
        ids = [entry.get("enterAction"), entry.get("exitAction")]
        for choice in residents:
            if not isinstance(choice, dict) or set(choice) != {"action", "weight"}:
                raise PackageInputError("V3_STATES_INVALID", f"states.{key} resident choice is invalid")
            if not is_integer(choice.get("weight"), 1, 100):
                raise PackageInputError("V3_STATES_INVALID", f"states.{key} resident weight is invalid")
            ids.append(choice.get("action"))
        if (
            any(not isinstance(action_id, str) or action_id not in actions for action_id in ids)
            or len(set(ids)) != len(ids)
            or any(actions[str(action_id)].role != "interaction" for action_id in ids)
            or any(str(action_id) in used_actions for action_id in ids)
        ):
            raise PackageInputError("V3_STATES_INVALID", f"states.{key} action references are invalid")
        enter = actions[str(entry["enterAction"])]
        internal = [
            actions[str(choice["action"])] for choice in residents
        ] + [actions[str(entry["exitAction"])]]
        if any(action.show_in_menu or action.autoplay_weight for action in internal):
            raise PackageInputError(
                "V3_STATES_INVALID",
                f"states.{key} resident and exit actions must be hidden with autoplayWeight 0",
            )
        if not enter.show_in_menu and not enter.autoplay_weight:
            raise PackageInputError(
                "V3_STATES_INVALID",
                f"states.{key}.enterAction must be visible or eligible for autoplay",
            )
        minimum = entry.get("minDurationMs")
        ramp = entry.get("rampDurationMs")
        maximum = entry.get("maxDurationMs")
        if (
            not is_integer(minimum, 5_000, 300_000)
            or not is_integer(ramp, 0, 300_000)
            or not is_integer(maximum, 10_000, 600_000)
            or int(maximum) < int(minimum) + int(ramp)
            or not is_integer(entry.get("exitChanceAfterMin"), 0, 100)
            or not is_integer(entry.get("exitChanceAfterRamp"), int(entry.get("exitChanceAfterMin", 0)), 100)
        ):
            raise PackageInputError("V3_STATES_INVALID", f"states.{key} timing is invalid")
        used_actions.update(str(action_id) for action_id in ids)


def validate(context: PackageContext) -> list[PackageCheck]:
    manifest = context.manifest
    package_id = require_text(manifest.get("id"), "V3_ID_INVALID", "v3 id must be text")
    if _V3_ID.fullmatch(package_id) is None:
        raise PackageInputError("V3_ID_INVALID", "v3 id is not a supported package id")
    display_name = manifest.get("displayName")
    if not isinstance(display_name, str) or not display_name.strip() or len(display_name.strip()) > 64:
        raise PackageInputError("V3_DISPLAY_NAME_INVALID", "v3 displayName is invalid")
    spritesheet_path = manifest.get("spritesheetPath")
    atlas = load_asset(context, spritesheet_path, "spritesheetPath")
    if spritesheet_path != "spritesheet.webp":
        raise PackageInputError(
            "V3_SPRITESHEET_PATH", "v3 spritesheetPath must be spritesheet.webp"
        )
    if atlas.width % 192 or atlas.height % 208:
        raise PackageInputError(
            "V3_ATLAS_DIMENSIONS", "v3 spritesheet dimensions must be cell-size multiples"
        )
    if (atlas.width // 192) * (atlas.height // 208) > 2_048:
        raise PackageInputError("V3_ATLAS_DIMENSIONS", "v3 spritesheet grid is too large")
    raw_actions = require_mapping(
        manifest.get("actions"), "V3_ACTIONS_INVALID", "v3 actions must be an object"
    )
    if not 3 <= len(raw_actions) <= 64:
        raise PackageInputError("V3_ACTIONS_INVALID", "v3 action count must be 3 through 64")
    if any(not isinstance(key, str) or _ACTION_ID.fullmatch(key) is None for key in raw_actions):
        raise PackageInputError("V3_ACTIONS_INVALID", "v3 action ids are invalid")
    parsed: dict[str, _Action] = {}
    mirrors: list[tuple[str, dict[str, object]]] = []
    for key, raw_entry in raw_actions.items():
        entry = require_mapping(raw_entry, "V3_ACTION_INVALID", f"actions.{key} is invalid")
        if "mirrorOf" in entry:
            mirrors.append((key, entry))
            continue
        parsed[key] = _parse_direct(key, entry)
    for key, entry in mirrors:
        if set(entry) - _MIRROR_FIELDS:
            raise PackageInputError("V3_MIRROR_INVALID", f"actions.{key} has fields forbidden with mirrorOf")
        role, direction, weight, show_in_menu = _validate_common(key, entry)
        source_key = entry.get("mirrorOf")
        source = parsed.get(source_key) if isinstance(source_key, str) else None
        if (
            source is None
            or not source.direct
            or source.role != role
            or not (
                (source.direction is None and direction is None)
                or (
                    source.direction is not None
                    and direction is not None
                    and source.direction != direction
                )
            )
        ):
            raise PackageInputError(
                "V3_MIRROR_INVALID", f"actions.{key}.mirrorOf must name a compatible direct action"
            )
        parsed[key] = _Action(
            key,
            role,
            direction,
            source.row,
            source.start_column,
            source.frame_count,
            source.loop,
            False,
            show_in_menu,
            weight,
        )
    idle = [action for action in parsed.values() if action.role == "idle"]
    if len(idle) != 1 or not idle[0].loop:
        raise PackageInputError("V3_IDLE_REQUIRED", "v3 needs exactly one looping idle action")
    if not any(action.role == "interaction" for action in parsed.values()):
        raise PackageInputError("V3_INTERACTION_REQUIRED", "v3 needs at least one interaction action")
    for direction in ("left", "right"):
        if not any(
            action.role == "move" and action.direction == direction
            for action in parsed.values()
        ):
            raise PackageInputError(
                "V3_MOVE_REQUIRED", f"v3 needs a normal {direction} movement action"
            )
    if sum(action.role == "gaze" for action in parsed.values()) > 1:
        raise PackageInputError("V3_GAZE_INVALID", "v3 may have at most one gaze action")
    for action in parsed.values():
        if action.direct:
            _validate_cells(atlas, action)
    icon = manifest.get("iconFrame", {"row": 0, "column": 0})
    if not isinstance(icon, dict) or set(icon) != {"row", "column"}:
        raise PackageInputError("V3_ICON_FRAME_INVALID", "v3 iconFrame is invalid")
    row = icon.get("row")
    column = icon.get("column")
    if not grid_cell_visible(atlas, 192, 208, row, column):
        raise PackageInputError("V3_ICON_FRAME_INVALID", "v3 iconFrame must select a visible cell")
    _validate_states(manifest, parsed)
    return [
        PackageCheck(
            "V3_PACKAGE_VALIDATION",
            "pass",
            "v3 dynamic atlas and capability checks passed",
            {"cell": [192, 208], "actionCount": len(parsed), "id": package_id},
        )
    ]
