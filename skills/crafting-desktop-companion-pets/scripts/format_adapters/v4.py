from __future__ import annotations

from dataclasses import dataclass
import re

from .base import (
    MAX_TOTAL_DECODED_PIXELS,
    MAX_TOTAL_ENCODED_IMAGE_BYTES,
    AssetSnapshot,
    ImageAsset,
    PackageCheck,
    PackageContext,
    PackageInputError,
    decode_snapshot_rgba,
    grid_cell_visible,
    is_integer,
    is_number,
    require_list,
    require_mapping,
    require_text,
    snapshot_webp,
)


_KEY = re.compile(r"^[a-z][A-Za-z0-9]{0,63}$")
_WEBP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.webp$")
_ROLES = frozenset({"idle", "move", "interaction", "burstMove", "gaze"})
_ROOT_FIELDS = frozenset(
    {
        "id", "displayName", "description", "spriteVersionNumber", "defaultForm",
        "iconFrame", "atlases", "cooldownGroups", "actions", "forms",
        "transformations", "sequences",
    }
)
_ACTION_FIELDS = frozenset(
    {
        "label", "role", "direction", "showInMenu", "includeInShowcase",
        "autoplayWeight", "cooldownMs", "autoplayGroup", "minDistance",
        "travelDistanceRatio", "maxVerticalRatio", "mirrorOf", "frameCount",
        "frameMs", "frameDurations", "loop", "repeatCount", "holdMs",
        "travelStartFrame", "travelEndFrame", "layers",
    }
)
_LAYER_REQUIRED = frozenset({"atlas", "row", "startColumn", "anchorX", "anchorY"})
_LAYER_FIELDS = _LAYER_REQUIRED | frozenset(
    {"offsetX", "offsetY", "scalePercent", "opacityPercent", "hitTest", "optionalInSimplified", "frameMap"}
)
_MAX_REFERENCED_CELLS = 128 * 8 * 512


@dataclass(frozen=True)
class _Atlas:
    key: str
    asset: ImageAsset
    cell_width: int
    cell_height: int


@dataclass(frozen=True)
class _Layer:
    atlas: _Atlas
    row: int
    start_column: int
    frame_map: tuple[int | None, ...] | None
    hit_test: bool
    optional_in_simplified: bool


@dataclass(frozen=True)
class _Action:
    key: str
    role: str
    direction: str | None
    frame_count: int
    loop: bool
    layers: tuple[_Layer, ...]
    mirror_of: str | None


def _key(value: object, code: str, message: str) -> str:
    value = require_text(value, code, message)
    if _KEY.fullmatch(value) is None:
        raise PackageInputError(code, message)
    return value


def _visible_text(value: object, code: str, message: str) -> str:
    value = require_text(value, code, message)
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > 80
        or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in stripped)
    ):
        raise PackageInputError(code, message)
    return stripped


def _parse_atlases(context: PackageContext) -> dict[str, _Atlas]:
    raw_atlases = require_mapping(
        context.manifest.get("atlases"), "V4_ATLASES_INVALID", "v4 atlases must be an object"
    )
    if not 1 <= len(raw_atlases) <= 8:
        raise PackageInputError("V4_ATLASES_INVALID", "v4 needs one through eight atlases")
    prepared: list[tuple[str, AssetSnapshot, int, int, str]] = []
    identities: set[tuple[int, int]] = set()
    encoded_total = 0
    decoded_total = 0
    for key, value in raw_atlases.items():
        atlas_key = _key(key, "V4_ATLASES_INVALID", "v4 atlas id is invalid")
        entry = require_mapping(value, "V4_ATLASES_INVALID", f"atlases.{atlas_key} is invalid")
        if set(entry) != {"path", "cellWidth", "cellHeight"}:
            raise PackageInputError("V4_ATLASES_INVALID", f"atlases.{atlas_key} has invalid fields")
        path_value = entry.get("path")
        if (
            not isinstance(path_value, str)
            or _WEBP_NAME.fullmatch(path_value) is None
            or "/" in path_value
            or "\\" in path_value
        ):
            raise PackageInputError("V4_ATLAS_PATH", f"atlases.{atlas_key}.path is invalid")
        cell_width = entry.get("cellWidth")
        cell_height = entry.get("cellHeight")
        if not is_integer(cell_width, 1, 2**31 - 1) or not is_integer(cell_height, 1, 2**31 - 1):
            raise PackageInputError("V4_ATLASES_INVALID", f"atlases.{atlas_key} cell dimensions are invalid")
        field = f"atlases.{atlas_key}.path"
        snapshot = snapshot_webp(context, path_value, field)
        if snapshot.identity in identities:
            raise PackageInputError(
                "V4_ATLAS_PATH", "v4 atlas paths must resolve to distinct files"
            )
        if snapshot.width % cell_width or snapshot.height % cell_height:
            raise PackageInputError(
                "V4_ATLAS_DIMENSIONS", f"atlases.{atlas_key} dimensions must be cell multiples"
            )
        encoded_total += len(snapshot.encoded)
        decoded_total += snapshot.width * snapshot.height
        if encoded_total > MAX_TOTAL_ENCODED_IMAGE_BYTES:
            raise PackageInputError("V4_ATLAS_BYTES_LIMIT", "v4 atlas files exceed 32 MiB total")
        if decoded_total > MAX_TOTAL_DECODED_PIXELS:
            raise PackageInputError("V4_ATLAS_PIXELS_LIMIT", "v4 atlas pixels exceed the aggregate limit")
        identities.add(snapshot.identity)
        prepared.append((atlas_key, snapshot, cell_width, cell_height, field))
    parsed: dict[str, _Atlas] = {}
    for atlas_key, snapshot, cell_width, cell_height, field in prepared:
        asset = context.remember(decode_snapshot_rgba(snapshot, field))
        parsed[atlas_key] = _Atlas(atlas_key, asset, cell_width, cell_height)
    return parsed


def _parse_layers(
    action_key: str,
    value: object,
    frame_count: int,
    atlases: dict[str, _Atlas],
    referenced_cell_count: list[int],
) -> tuple[_Layer, ...]:
    raw_layers = require_list(value, "V4_LAYERS_INVALID", f"actions.{action_key}.layers is invalid")
    if not 1 <= len(raw_layers) <= 8:
        raise PackageInputError("V4_LAYERS_INVALID", f"actions.{action_key} needs one through eight layers")
    layers: list[_Layer] = []
    for index, raw_layer in enumerate(raw_layers):
        prefix = f"actions.{action_key}.layers[{index}]"
        layer = require_mapping(raw_layer, "V4_LAYERS_INVALID", f"{prefix} is invalid")
        if not _LAYER_REQUIRED <= set(layer) or set(layer) - _LAYER_FIELDS:
            raise PackageInputError("V4_LAYERS_INVALID", f"{prefix} has invalid fields")
        atlas_id = _key(layer.get("atlas"), "V4_LAYERS_INVALID", f"{prefix}.atlas is invalid")
        atlas = atlases.get(atlas_id)
        if atlas is None:
            raise PackageInputError("V4_ATLAS_REFERENCE_INVALID", f"{prefix} references an unknown atlas")
        row = layer.get("row")
        start_column = layer.get("startColumn")
        anchor_x = layer.get("anchorX")
        anchor_y = layer.get("anchorY")
        if not all(is_integer(item, 0, 2**31 - 1) for item in (row, start_column, anchor_x, anchor_y)):
            raise PackageInputError("V4_LAYERS_INVALID", f"{prefix} coordinates are invalid")
        if not is_integer(layer.get("offsetX", 0), -100_000, 100_000) or not is_integer(layer.get("offsetY", 0), -100_000, 100_000):
            raise PackageInputError("V4_LAYERS_INVALID", f"{prefix} offsets are invalid")
        if not is_integer(layer.get("scalePercent", 100), 1, 1_000) or not is_integer(layer.get("opacityPercent", 100), 0, 100):
            raise PackageInputError("V4_LAYERS_INVALID", f"{prefix} appearance values are invalid")
        hit_test = layer.get("hitTest", False)
        optional = layer.get("optionalInSimplified", False)
        if not isinstance(hit_test, bool) or not isinstance(optional, bool):
            raise PackageInputError("V4_LAYERS_INVALID", f"{prefix} flags are invalid")
        raw_map = layer.get("frameMap")
        frame_map: tuple[int | None, ...] | None = None
        if raw_map is not None:
            if (
                not isinstance(raw_map, list)
                or len(raw_map) != frame_count
                or any(item is not None and not is_integer(item, 0, 511) for item in raw_map)
            ):
                raise PackageInputError(
                    "V4_LAYER_MAPPING_INVALID", f"{prefix}.frameMap is invalid"
                )
            frame_map = tuple(raw_map)
        local_indices = frame_map if frame_map is not None else tuple(range(frame_count))
        columns = atlas.asset.width // atlas.cell_width
        rows = atlas.asset.height // atlas.cell_height
        for local_index in local_indices:
            if local_index is None:
                continue
            referenced_cell_count[0] += 1
            if referenced_cell_count[0] > _MAX_REFERENCED_CELLS:
                raise PackageInputError(
                    "V4_REFERENCED_CELLS_LIMIT", "v4 references too many atlas cells"
                )
            cell_row, cell_column = divmod(int(row) * columns + int(start_column) + local_index, columns)
            if cell_row >= rows:
                raise PackageInputError(
                    "V4_LAYER_CELL_OUT_OF_BOUNDS",
                    f"{prefix} references an unavailable atlas cell",
                )
            if not grid_cell_visible(atlas.asset, atlas.cell_width, atlas.cell_height, cell_row, cell_column):
                raise PackageInputError(
                    "V4_REFERENCED_CELL_EMPTY", f"{prefix} references an empty atlas cell"
                )
        layers.append(
            _Layer(atlas, int(row), int(start_column), frame_map, hit_test, optional)
        )
    if sum(layer.hit_test for layer in layers) != 1:
        raise PackageInputError(
            "V4_HIT_TEST_LAYER", f"actions.{action_key} must contain exactly one hitTest layer"
        )
    for frame in range(frame_count):
        full = False
        simplified = False
        for layer in layers:
            local_index = layer.frame_map[frame] if layer.frame_map is not None else frame
            if local_index is None:
                continue
            full = True
            if not layer.optional_in_simplified:
                simplified = True
        if not full:
            raise PackageInputError("V4_FULL_FRAME_EMPTY", f"actions.{action_key} has an empty full frame")
        if not simplified:
            raise PackageInputError(
                "V4_SIMPLIFIED_FRAME_EMPTY", f"actions.{action_key} has an empty simplified frame"
            )
    return tuple(layers)


def _parse_actions(
    manifest: dict[str, object], atlases: dict[str, _Atlas]
) -> dict[str, _Action]:
    raw_actions = require_mapping(
        manifest.get("actions"), "V4_ACTIONS_INVALID", "v4 actions must be an object"
    )
    if not 1 <= len(raw_actions) <= 128:
        raise PackageInputError("V4_ACTIONS_INVALID", "v4 action count is invalid")
    actions: dict[str, _Action] = {}
    referenced_cell_count = [0]
    for key, value in raw_actions.items():
        action_key = _key(key, "V4_ACTIONS_INVALID", "v4 action id is invalid")
        entry = require_mapping(value, "V4_ACTIONS_INVALID", f"actions.{action_key} is invalid")
        if not {"label", "role", "frameCount", "layers"} <= set(entry) or set(entry) - _ACTION_FIELDS:
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key} has invalid fields")
        _visible_text(entry.get("label"), "V4_ACTIONS_INVALID", f"actions.{action_key}.label is invalid")
        role = entry.get("role")
        if not isinstance(role, str) or role not in _ROLES:
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.role is invalid")
        direction = entry.get("direction")
        if role in {"move", "burstMove"}:
            if direction not in {"left", "right"}:
                raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.direction is invalid")
        elif direction is not None:
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.direction is invalid")
        frame_count = entry.get("frameCount")
        if not is_integer(frame_count, 1, 512):
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.frameCount is invalid")
        frame_ms = entry.get("frameMs")
        frame_durations = entry.get("frameDurations")
        if (frame_ms is None) == (frame_durations is None):
            raise PackageInputError("V4_FRAME_DURATIONS_INVALID", f"actions.{action_key} needs one duration form")
        if frame_ms is not None and not is_integer(frame_ms, 33, 2_000):
            raise PackageInputError("V4_FRAME_DURATIONS_INVALID", f"actions.{action_key}.frameMs is invalid")
        if frame_durations is not None and (
            not isinstance(frame_durations, list)
            or len(frame_durations) != frame_count
            or any(not is_integer(item, 33, 2_000) for item in frame_durations)
        ):
            raise PackageInputError(
                "V4_FRAME_DURATIONS_INVALID", f"actions.{action_key}.frameDurations is invalid"
            )
        loop = entry.get("loop", role == "idle")
        if not isinstance(loop, bool):
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.loop is invalid")
        repeat_count = entry.get("repeatCount", 1)
        if not is_integer(repeat_count, 1, 20) or (loop and "repeatCount" in entry):
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.repeatCount is invalid")
        if not is_integer(entry.get("holdMs", 0), 0, 10_000):
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.holdMs is invalid")
        if role == "idle" and not loop:
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key} idle must loop")
        if role in {"interaction", "burstMove"} and loop:
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key} finite action may not loop")
        if role == "gaze" and frame_count not in {16, 32, 64}:
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key} gaze frame count is invalid")
        weight = entry.get("autoplayWeight", 10 if role == "move" else 0)
        if not is_integer(weight, 0, 100) or (role in {"idle", "gaze"} and weight != 0):
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.autoplayWeight is invalid")
        if not isinstance(entry.get("showInMenu", role != "gaze"), bool) or not isinstance(entry.get("includeInShowcase", True), bool):
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key} menu flags are invalid")
        if not is_integer(entry.get("cooldownMs", 0), 0, 1_200_000):
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.cooldownMs is invalid")
        group = entry.get("autoplayGroup", "")
        if not isinstance(group, str) or (group and _KEY.fullmatch(group) is None) or (role != "interaction" and group):
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.autoplayGroup is invalid")
        distance = entry.get("minDistance", 0)
        if not is_integer(distance, 0, 10_000) or (role != "burstMove" and distance != 0):
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.minDistance is invalid")
        for name, low, high in (("travelDistanceRatio", 0.05, 1.0), ("maxVerticalRatio", 0.0, 1.0)):
            number = entry.get(name)
            if number is not None and not is_number(number, low, high):
                raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.{name} is invalid")
            if role != "burstMove" and number is not None:
                raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key}.{name} requires burstMove")
        if role == "burstMove":
            start = entry.get("travelStartFrame", max(1, int(frame_count) // 3))
            if not is_integer(start, 0, int(frame_count) - 2):
                raise PackageInputError(
                    "V4_ACTIONS_INVALID", f"actions.{action_key} burstMove timing is invalid"
                )
            end = entry.get(
                "travelEndFrame",
                min(
                    int(frame_count) - 1,
                    max(start + 1, int(frame_count) * 2 // 3),
                ),
            )
            if (
                int(frame_count) < 3
                or repeat_count != 1
                or not is_integer(end, start + 1, int(frame_count) - 1)
            ):
                raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key} burstMove timing is invalid")
        elif "travelStartFrame" in entry or "travelEndFrame" in entry:
            raise PackageInputError("V4_ACTIONS_INVALID", f"actions.{action_key} travel frames require burstMove")
        mirror = entry.get("mirrorOf")
        if mirror is not None:
            mirror = _key(mirror, "V4_MIRROR_INVALID", f"actions.{action_key}.mirrorOf is invalid")
        layers = _parse_layers(action_key, entry.get("layers"), int(frame_count), atlases, referenced_cell_count)
        actions[action_key] = _Action(
            action_key, role, direction if isinstance(direction, str) else None,
            int(frame_count), loop, layers, mirror,
        )
    for action in actions.values():
        if action.mirror_of is None:
            continue
        source = actions.get(action.mirror_of)
        if (
            source is None
            or source.mirror_of is not None
            or source.role != action.role
            or not (
                (source.direction is None and action.direction is None)
                or (
                    source.direction is not None
                    and action.direction is not None
                    and source.direction != action.direction
                )
            )
        ):
            raise PackageInputError(
                "V4_MIRROR_INVALID", f"actions.{action.key}.mirrorOf is not a compatible direct action"
            )
    return actions


def _parse_cooldown_groups(manifest: dict[str, object]) -> set[str]:
    raw_groups = manifest.get("cooldownGroups", {})
    groups = require_mapping(raw_groups, "V4_COOLDOWN_GROUP_INVALID", "v4 cooldownGroups is invalid")
    if len(groups) > 32:
        raise PackageInputError("V4_COOLDOWN_GROUP_INVALID", "v4 has too many cooldown groups")
    result: set[str] = set()
    for key, value in groups.items():
        group_key = _key(key, "V4_COOLDOWN_GROUP_INVALID", "v4 cooldown group id is invalid")
        entry = require_mapping(value, "V4_COOLDOWN_GROUP_INVALID", f"cooldownGroups.{group_key} is invalid")
        if set(entry) != {"cooldownMs"} or not is_integer(entry.get("cooldownMs"), 0, 1_200_000):
            raise PackageInputError("V4_COOLDOWN_GROUP_INVALID", f"cooldownGroups.{group_key} is invalid")
        result.add(group_key)
    return result


def _parse_autoplay(
    value: object,
    prefix: str,
    group_keys: set[str],
    bucket_signatures: dict[str, tuple[int, int, tuple[str, ...]]],
) -> None:
    if value is None:
        return
    entry = require_mapping(value, "V4_AUTOPLAY_INVALID", f"{prefix} is invalid")
    required = {"bucket", "weight", "minDelayMs", "maxDelayMs", "cooldownGroups"}
    if set(entry) != required:
        raise PackageInputError("V4_AUTOPLAY_INVALID", f"{prefix} has invalid fields")
    bucket = _key(entry.get("bucket"), "V4_AUTOPLAY_INVALID", f"{prefix}.bucket is invalid")
    weight = entry.get("weight")
    minimum = entry.get("minDelayMs")
    maximum = entry.get("maxDelayMs")
    groups = require_list(entry.get("cooldownGroups"), "V4_AUTOPLAY_INVALID", f"{prefix}.cooldownGroups is invalid")
    if (
        not is_integer(weight, 1, 100)
        or not is_integer(minimum, 0, 1_200_000)
        or not is_integer(maximum, 0, 1_200_000)
        or int(minimum) > int(maximum)
        or len(groups) > 32
        or any(not isinstance(group, str) or _KEY.fullmatch(group) is None for group in groups)
        or len(set(groups)) != len(groups)
    ):
        raise PackageInputError("V4_AUTOPLAY_INVALID", f"{prefix} is invalid")
    unknown = set(groups) - group_keys
    if unknown:
        raise PackageInputError(
            "V4_COOLDOWN_GROUP_UNKNOWN", f"{prefix} references an unknown cooldown group"
        )
    signature = (int(minimum), int(maximum), tuple(groups))
    existing = bucket_signatures.setdefault(bucket, signature)
    if existing != signature:
        raise PackageInputError(
            "V4_AUTOPLAY_BUCKET_MISMATCH", "v4 autoplay bucket definitions must match"
        )


def _parse_forms(
    manifest: dict[str, object], actions: dict[str, _Action]
) -> tuple[dict[str, dict[str, object]], str]:
    raw_forms = require_mapping(
        manifest.get("forms"), "V4_FORMS_INVALID", "v4 forms must be an object"
    )
    if not 1 <= len(raw_forms) <= 16:
        raise PackageInputError("V4_FORMS_INVALID", "v4 form count is invalid")
    default_form = _key(manifest.get("defaultForm"), "V4_FORMS_INVALID", "v4 defaultForm is invalid")
    forms: dict[str, dict[str, object]] = {}
    required = {"label", "idleAction", "moveRightAction", "moveLeftAction", "representativeAction", "interactionActions"}
    for key, value in raw_forms.items():
        form_key = _key(key, "V4_FORMS_INVALID", "v4 form id is invalid")
        entry = require_mapping(value, "V4_FORMS_INVALID", f"forms.{form_key} is invalid")
        if not required <= set(entry) or set(entry) - (required | {"gazeAction"}):
            raise PackageInputError("V4_FORMS_INVALID", f"forms.{form_key} has invalid fields")
        _visible_text(entry.get("label"), "V4_FORMS_INVALID", f"forms.{form_key}.label is invalid")
        references = [entry.get(name) for name in ("idleAction", "moveRightAction", "moveLeftAction", "representativeAction")]
        gaze = entry.get("gazeAction")
        if gaze is not None:
            references.append(gaze)
        interactions = require_list(
            entry.get("interactionActions"), "V4_FORMS_INVALID", f"forms.{form_key}.interactionActions is invalid"
        )
        if (
            not 1 <= len(interactions) <= 128
            or any(not isinstance(item, str) for item in interactions)
            or len(set(interactions)) != len(interactions)
        ):
            raise PackageInputError("V4_FORMS_INVALID", f"forms.{form_key}.interactionActions is invalid")
        references.extend(interactions)
        if any(not isinstance(reference, str) or reference not in actions for reference in references):
            raise PackageInputError("V4_FORM_ACTION_UNKNOWN", f"forms.{form_key} references an unknown action")
        idle = actions[str(entry["idleAction"])]
        right = actions[str(entry["moveRightAction"])]
        left = actions[str(entry["moveLeftAction"])]
        if not (idle.role == "idle" and right.role == "move" and right.direction == "right" and left.role == "move" and left.direction == "left"):
            raise PackageInputError("V4_FORM_CAPABILITIES_INVALID", f"forms.{form_key} lacks idle or normal movement")
        if any(actions[str(item)].role != "interaction" for item in interactions):
            raise PackageInputError("V4_FORM_CAPABILITIES_INVALID", f"forms.{form_key} interactions are invalid")
        if gaze is not None:
            if form_key != default_form:
                raise PackageInputError("V4_GAZE_DEFAULT_ONLY", "only the default form may define gazeAction")
            if actions[str(gaze)].role != "gaze":
                raise PackageInputError("V4_FORM_CAPABILITIES_INVALID", f"forms.{form_key}.gazeAction is invalid")
        forms[form_key] = entry
    if default_form not in forms:
        raise PackageInputError("V4_FORMS_INVALID", "v4 defaultForm is unknown")
    return forms, default_form


def _parse_transformations(
    manifest: dict[str, object],
    forms: dict[str, dict[str, object]],
    default_form: str,
    actions: dict[str, _Action],
    group_keys: set[str],
    bucket_signatures: dict[str, tuple[int, int, tuple[str, ...]]],
) -> set[str]:
    raw = manifest.get("transformations", {})
    transformations = require_mapping(raw, "V4_TRANSFORMATIONS_INVALID", "v4 transformations are invalid")
    if len(transformations) > 32:
        raise PackageInputError("V4_TRANSFORMATIONS_INVALID", "v4 has too many transformations")
    targets: set[str] = set()
    required = {"label", "fromForm", "toForm", "enterAction", "residentActions", "exitAction", "minDurationMs", "maxDurationMs", "showInMenu"}
    for key, value in transformations.items():
        transformation_key = _key(key, "V4_TRANSFORMATIONS_INVALID", "v4 transformation id is invalid")
        entry = require_mapping(value, "V4_TRANSFORMATIONS_INVALID", f"transformations.{transformation_key} is invalid")
        if not required <= set(entry) or set(entry) - (required | {"autoplay"}):
            raise PackageInputError("V4_TRANSFORMATIONS_INVALID", f"transformations.{transformation_key} has invalid fields")
        _visible_text(entry.get("label"), "V4_TRANSFORMATIONS_INVALID", f"transformations.{transformation_key}.label is invalid")
        from_form = entry.get("fromForm")
        to_form = entry.get("toForm")
        action_ids = [entry.get("enterAction"), entry.get("exitAction")]
        residents = require_list(
            entry.get("residentActions"), "V4_TRANSFORMATIONS_INVALID", f"transformations.{transformation_key}.residentActions is invalid"
        )
        if not 1 <= len(residents) <= 128:
            raise PackageInputError("V4_TRANSFORMATIONS_INVALID", f"transformations.{transformation_key}.residentActions is invalid")
        resident_ids: list[object] = []
        for item in residents:
            if not isinstance(item, dict) or set(item) != {"action", "weight"} or not is_integer(item.get("weight"), 1, 100):
                raise PackageInputError("V4_TRANSFORMATIONS_INVALID", f"transformations.{transformation_key} resident is invalid")
            resident_ids.append(item.get("action"))
        if (
            any(not isinstance(action_id, str) for action_id in resident_ids)
            or len(set(resident_ids)) != len(resident_ids)
        ):
            raise PackageInputError("V4_TRANSFORMATIONS_INVALID", f"transformations.{transformation_key} repeats resident actions")
        action_ids.extend(resident_ids)
        if (
            not isinstance(from_form, str)
            or not isinstance(to_form, str)
            or from_form != default_form
            or to_form not in forms
            or any(not isinstance(action_id, str) or action_id not in actions for action_id in action_ids)
        ):
            raise PackageInputError("V4_TRANSFORMATION_REFERENCE_INVALID", f"transformations.{transformation_key} has invalid references")
        minimum = entry.get("minDurationMs")
        maximum = entry.get("maxDurationMs")
        if not is_integer(minimum, 0, 1_200_000) or not is_integer(maximum, 0, 1_200_000) or int(minimum) > int(maximum):
            raise PackageInputError("V4_TRANSFORMATIONS_INVALID", f"transformations.{transformation_key} duration is invalid")
        if not isinstance(entry.get("showInMenu"), bool):
            raise PackageInputError("V4_TRANSFORMATIONS_INVALID", f"transformations.{transformation_key}.showInMenu is invalid")
        _parse_autoplay(entry.get("autoplay"), f"transformations.{transformation_key}.autoplay", group_keys, bucket_signatures)
        targets.add(to_form)
    return targets


def _parse_sequences(
    manifest: dict[str, object],
    forms: dict[str, dict[str, object]],
    actions: dict[str, _Action],
    group_keys: set[str],
    bucket_signatures: dict[str, tuple[int, int, tuple[str, ...]]],
) -> None:
    raw = manifest.get("sequences", {})
    sequences = require_mapping(raw, "V4_SEQUENCES_INVALID", "v4 sequences are invalid")
    if len(sequences) > 16:
        raise PackageInputError("V4_SEQUENCES_INVALID", "v4 has too many sequences")
    for key, value in sequences.items():
        sequence_key = _key(key, "V4_SEQUENCES_INVALID", "v4 sequence id is invalid")
        entry = require_mapping(value, "V4_SEQUENCES_INVALID", f"sequences.{sequence_key} is invalid")
        required = {"label", "showInMenu", "steps"}
        if not required <= set(entry) or set(entry) - (required | {"autoplay"}):
            raise PackageInputError("V4_SEQUENCES_INVALID", f"sequences.{sequence_key} has invalid fields")
        _visible_text(entry.get("label"), "V4_SEQUENCES_INVALID", f"sequences.{sequence_key}.label is invalid")
        if not isinstance(entry.get("showInMenu"), bool):
            raise PackageInputError("V4_SEQUENCES_INVALID", f"sequences.{sequence_key}.showInMenu is invalid")
        steps = require_list(entry.get("steps"), "V4_SEQUENCES_INVALID", f"sequences.{sequence_key}.steps is invalid")
        if not 1 <= len(steps) <= 128:
            raise PackageInputError("V4_SEQUENCES_INVALID", f"sequences.{sequence_key}.steps is invalid")
        for index, item in enumerate(steps):
            prefix = f"sequences.{sequence_key}.steps[{index}]"
            step = require_mapping(item, "V4_SEQUENCES_INVALID", f"{prefix} is invalid")
            required_step = {"action", "repeatCount", "holdMs", "safeStopAfter"}
            if not required_step <= set(step) or set(step) - (required_step | {"formAfter"}):
                raise PackageInputError("V4_SEQUENCES_INVALID", f"{prefix} has invalid fields")
            action_id = step.get("action")
            form_after = step.get("formAfter")
            if not isinstance(action_id, str) or action_id not in actions:
                raise PackageInputError("V4_SEQUENCE_ACTION_UNKNOWN", f"{prefix} references an unknown action")
            if actions[action_id].loop:
                raise PackageInputError("V4_SEQUENCE_ACTION_INVALID", f"{prefix} requires a finite action")
            if form_after is not None and (not isinstance(form_after, str) or form_after not in forms):
                raise PackageInputError("V4_SEQUENCE_FORM_UNKNOWN", f"{prefix}.formAfter is invalid")
            if not is_integer(step.get("repeatCount"), 1, 20) or not is_integer(step.get("holdMs"), 0, 10_000) or not isinstance(step.get("safeStopAfter"), bool):
                raise PackageInputError("V4_SEQUENCES_INVALID", f"{prefix} timing is invalid")
        _parse_autoplay(entry.get("autoplay"), f"sequences.{sequence_key}.autoplay", group_keys, bucket_signatures)


def _validate_icon(manifest: dict[str, object], atlases: dict[str, _Atlas]) -> None:
    first_atlas = next(iter(atlases))
    icon = manifest.get("iconFrame", {"atlas": first_atlas, "row": 0, "column": 0})
    if not isinstance(icon, dict) or set(icon) != {"atlas", "row", "column"}:
        raise PackageInputError("V4_ICON_FRAME_INVALID", "v4 iconFrame is invalid")
    atlas_id = icon.get("atlas")
    atlas = atlases.get(atlas_id) if isinstance(atlas_id, str) else None
    if atlas is None or not grid_cell_visible(atlas.asset, atlas.cell_width, atlas.cell_height, icon.get("row"), icon.get("column")):
        raise PackageInputError("V4_ICON_FRAME_INVALID", "v4 iconFrame must select a visible atlas cell")


def validate(context: PackageContext) -> list[PackageCheck]:
    manifest = context.manifest
    unknown = set(manifest) - _ROOT_FIELDS
    if unknown:
        raise PackageInputError(
            "V4_ROOT_FIELDS_INVALID", "v4 manifest contains unknown fields", {"fields": sorted(unknown)}
        )
    package_id = _key(manifest.get("id"), "V4_ID_INVALID", "v4 id is invalid")
    _visible_text(manifest.get("displayName"), "V4_DISPLAY_NAME_INVALID", "v4 displayName is invalid")
    description = manifest.get("description", "")
    if not isinstance(description, str) or len(description) > 500 or any(ord(character) < 32 or ord(character) == 127 for character in description):
        raise PackageInputError("V4_DESCRIPTION_INVALID", "v4 description is invalid")
    atlases = _parse_atlases(context)
    actions = _parse_actions(manifest, atlases)
    _validate_icon(manifest, atlases)
    group_keys = _parse_cooldown_groups(manifest)
    forms, default_form = _parse_forms(manifest, actions)
    bucket_signatures: dict[str, tuple[int, int, tuple[str, ...]]] = {}
    targets = _parse_transformations(manifest, forms, default_form, actions, group_keys, bucket_signatures)
    for form_key in forms:
        if form_key != default_form and form_key not in targets:
            raise PackageInputError(
                "V4_FORM_EXIT_MISSING", "each non-default form requires a transformation exit"
            )
    _parse_sequences(manifest, forms, actions, group_keys, bucket_signatures)
    return [
        PackageCheck(
            "V4_PACKAGE_VALIDATION",
            "pass",
            "v4 layered, form, sequence, and scheduler checks passed",
            {"atlasCount": len(atlases), "actionCount": len(actions), "formCount": len(forms), "id": package_id},
        )
    ]
