from __future__ import annotations

import re

from .base import (
    PackageCheck,
    PackageContext,
    PackageInputError,
    grid_cell_visible,
    is_integer,
    load_asset,
    require_mapping,
    require_text,
)


_V2_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ACTION_ROWS = (
    ("idle", 0, 7),
    ("moveRight", 1, 8),
    ("moveLeft", 2, 8),
    ("greet", 3, 4),
    ("jump", 4, 5),
    ("special", 5, 8),
    ("wait", 6, 6),
    ("observe", 7, 6),
    ("curious", 8, 6),
)
_USED_CELLS = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)


def _validate_metadata(manifest: dict[str, object]) -> None:
    actions = manifest.get("actions")
    if actions is None:
        return
    action_mapping = require_mapping(
        actions, "V2_ACTIONS_INVALID", "v2 actions must be an object"
    )
    expected = {key for key, _, _ in _ACTION_ROWS}
    if set(action_mapping) != expected:
        raise PackageInputError(
            "V2_ACTIONS_INVALID", "v2 actions must contain every fixed action slot"
        )
    any_in_place_weight = False
    for key, _, _ in _ACTION_ROWS:
        entry = require_mapping(
            action_mapping.get(key), "V2_ACTIONS_INVALID", f"v2 action {key} is invalid"
        )
        if set(entry) != {"label", "autoplayWeight"}:
            raise PackageInputError(
                "V2_ACTIONS_INVALID", f"v2 action {key} has unexpected fields"
            )
        label = entry.get("label")
        weight = entry.get("autoplayWeight")
        if (
            not isinstance(label, str)
            or not label.strip()
            or len(label.strip()) > 32
            or not all(character.isprintable() for character in label.strip())
        ):
            raise PackageInputError(
                "V2_ACTIONS_INVALID", f"v2 action {key} needs a printable label"
            )
        if not is_integer(weight, 0, 10):
            raise PackageInputError(
                "V2_ACTIONS_INVALID", f"v2 action {key} has an invalid autoplayWeight"
            )
        if key in {"idle", "moveRight", "moveLeft"} and weight != 0:
            raise PackageInputError(
                "V2_ACTIONS_INVALID", f"v2 moving action {key} must have autoplayWeight 0"
            )
        if key not in {"idle", "moveRight", "moveLeft"} and weight:
            any_in_place_weight = True
    if not any_in_place_weight:
        raise PackageInputError(
            "V2_ACTIONS_INVALID", "v2 actions need one in-place autoplay candidate"
        )


def validate(context: PackageContext) -> list[PackageCheck]:
    manifest = context.manifest
    if "states" in manifest:
        raise PackageInputError(
            "V2_STATES_UNSUPPORTED", "v2 packages do not support states"
        )
    package_id = require_text(
        manifest.get("id"), "V2_ID_INVALID", "v2 id must be text"
    )
    if _V2_ID.fullmatch(package_id) is None:
        raise PackageInputError("V2_ID_INVALID", "v2 id is not a supported package id")
    display_name = manifest.get("displayName")
    if (
        not isinstance(display_name, str)
        or not display_name.strip()
        or len(display_name.strip()) > 64
    ):
        raise PackageInputError("V2_DISPLAY_NAME_INVALID", "v2 displayName is invalid")
    spritesheet_path = manifest.get("spritesheetPath")
    atlas = load_asset(context, spritesheet_path, "spritesheetPath")
    if spritesheet_path != "spritesheet.webp":
        raise PackageInputError(
            "V2_SPRITESHEET_PATH", "v2 spritesheetPath must be spritesheet.webp"
        )
    if (atlas.width, atlas.height) != (1536, 2288):
        raise PackageInputError(
            "V2_ATLAS_DIMENSIONS",
            "v2 spritesheet must be exactly 1536x2288",
            {"actual": [atlas.width, atlas.height]},
        )
    for row, count in enumerate(_USED_CELLS):
        for column in range(8):
            visible = grid_cell_visible(atlas, 192, 208, row, column)
            if column < count and not visible:
                raise PackageInputError(
                    "V2_REQUIRED_CELL_EMPTY",
                    "v2 required atlas cell has no visible alpha",
                    {"row": row, "column": column},
                )
            if column >= count and visible:
                raise PackageInputError(
                    "V2_UNUSED_CELL_VISIBLE",
                    "v2 unused atlas cell must be fully transparent",
                    {"row": row, "column": column},
                )
    icon = manifest.get("iconFrame", {"row": 0, "column": 0})
    if not isinstance(icon, dict) or set(icon) != {"row", "column"}:
        raise PackageInputError("V2_ICON_FRAME_INVALID", "v2 iconFrame is invalid")
    row = icon.get("row")
    column = icon.get("column")
    if not is_integer(row, 0, 10) or not is_integer(column, 0, 7):
        raise PackageInputError("V2_ICON_FRAME_INVALID", "v2 iconFrame is outside the atlas")
    if not grid_cell_visible(atlas, 192, 208, row, column):
        raise PackageInputError(
            "V2_ICON_CELL_EMPTY", "v2 iconFrame must select a visible atlas cell"
        )
    _validate_metadata(manifest)
    return [
        PackageCheck(
            "V2_PACKAGE_VALIDATION",
            "pass",
            "v2 fixed atlas and metadata checks passed",
            {"grid": [8, 11], "cell": [192, 208], "id": package_id},
        )
    ]
