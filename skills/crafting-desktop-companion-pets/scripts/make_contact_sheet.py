from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import warnings

from PIL import Image, ImageDraw, ImageFont

from contracts import (
    _is_utf8_text,
    _validate_untrusted_image_canvas,
    sha256_file,
    validate_json_structure,
)


_LIGHT_BACKGROUND = "#F2F2F2"
_DARK_BACKGROUND = "#20242A"
_CHECKER_LIGHT = "#FFFFFF"
_CHECKER_DARK = "#D4D4D4"
_CHECKER_TILE_SIZE = 8
_PADDING = 8
_GAP = 8
_BACKGROUND_NAMES = ("checker", "light", "dark")

# These intentionally conservative limits make all allocations predictable before
# any display resize or contact-board construction occurs.
_MAX_CONTACT_COLUMNS = 1024
_MAX_FRAME_RECORDS = 1024
_MAX_CONTACT_CELLS = _MAX_FRAME_RECORDS * len(_BACKGROUND_NAMES)
_MAX_LABEL_CODEPOINTS = 512
_MAX_CELL_DIMENSION = 8192
_MAX_CELL_PIXELS = 16 * 1024 * 1024
_MAX_BOARD_DIMENSION = 16384
_MAX_BOARD_PIXELS = 64 * 1024 * 1024
_MAX_DISPLAY_SCALE = 64.0

_CJK_FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\msyhbd.ttc"),
    Path(r"C:\Windows\Fonts\simhei.ttf"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJKsc-Regular.otf"),
)


def _nonempty_text(value: object) -> bool:
    return _is_utf8_text(value) and bool(value.strip())


def _normalized_path(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve(strict=False)))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("path could not be normalized safely") from error


def _paths_alias(left: Path, right: Path) -> bool:
    """Detect textual, symlink, and existing hard-link aliases without writes."""
    if _normalized_path(left) == _normalized_path(right):
        return True
    try:
        if not left.exists() or not right.exists():
            return False
        try:
            if left.samefile(right):
                return True
        except OSError:
            pass
        left_stat = left.stat()
        right_stat = right.stat()
        return (
            left_stat.st_dev == right_stat.st_dev
            and left_stat.st_ino != 0
            and left_stat.st_ino == right_stat.st_ino
        )
    except (OSError, UnicodeError, ValueError):
        return False


def _coerce_output_path(value: object) -> Path:
    if isinstance(value, bytes) or not isinstance(value, (str, os.PathLike)):
        raise ValueError("output_path must be a filesystem path")
    if isinstance(value, str) and not _nonempty_text(value):
        raise ValueError("output_path must be non-empty UTF-8 text")
    try:
        path = Path(value)
        if not path.name or path.exists() and path.is_dir():
            raise ValueError("output_path must name a PNG file")
        if path.suffix.lower() != ".png":
            raise ValueError("output_path must name a PNG file")
        _normalized_path(path)
        return path
    except (OSError, UnicodeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("output_path"):
            raise
        raise ValueError("output_path must name a writable PNG file") from error


def _coerce_input_path(value: object, field: str) -> Path:
    if not _nonempty_text(value):
        raise ValueError(f"{field} must be non-empty UTF-8 text")
    try:
        path = Path(value)
        if not path.is_file():
            raise ValueError(f"{field} must name an existing file")
        _normalized_path(path)
        return path
    except (OSError, UnicodeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith(field):
            raise
        raise ValueError(f"{field} must name an existing readable file") from error


def _load_visible_rgba(path: Path) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                _validate_untrusted_image_canvas(*source.size)
                source.load()
                image = source.convert("RGBA")
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise ValueError(f"{path} has an unsafe canvas") from error
    except (OSError, SyntaxError, UnicodeError, ValueError) as error:
        if isinstance(error, ValueError) and "unsafe canvas" in str(error):
            raise
        raise ValueError(f"{path} is not RGBA-decodable") from error
    if image.getchannel("A").getbbox() is None:
        raise ValueError(f"{path} has no visible alpha pixels")
    return image


def _validate_frames(frames: object) -> list[tuple[str, Path]]:
    structural_issues = validate_json_structure(frames, "frames")
    if structural_issues:
        raise ValueError("frames must be a UTF-8 JSON-compatible list of records")
    if not isinstance(frames, list) or not frames:
        raise ValueError("frames must be a non-empty list")
    if len(frames) > _MAX_FRAME_RECORDS:
        raise ValueError(f"frames may contain at most {_MAX_FRAME_RECORDS} records")
    records: list[tuple[str, Path]] = []
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise ValueError(f"frames[{index}] must be an object")
        label = frame.get("label")
        if not _nonempty_text(label):
            raise ValueError(f"frames[{index}].label must be non-empty UTF-8 text")
        if len(label) > _MAX_LABEL_CODEPOINTS:
            raise ValueError(
                f"frames[{index}].label exceeds {_MAX_LABEL_CODEPOINTS} code points"
            )
        records.append(
            (label, _coerce_input_path(frame.get("path"), f"frames[{index}].path"))
        )
    return records


def _validate_columns(columns: object) -> int:
    if (
        not isinstance(columns, int)
        or isinstance(columns, bool)
        or not 1 <= columns <= _MAX_CONTACT_COLUMNS
    ):
        raise ValueError(
            f"columns must be an integer from 1 to {_MAX_CONTACT_COLUMNS}"
        )
    return columns


def _validate_display_scale(display_scale: object) -> float:
    if isinstance(display_scale, bool) or not isinstance(display_scale, (int, float)):
        raise ValueError("display_scale must be a finite positive number")
    if isinstance(display_scale, int):
        if not 0 < display_scale <= _MAX_DISPLAY_SCALE:
            raise ValueError(
                f"display_scale must be at most {_MAX_DISPLAY_SCALE:g}"
            )
        return float(display_scale)
    if (
        not math.isfinite(display_scale)
        or not 0 < display_scale <= _MAX_DISPLAY_SCALE
    ):
        raise ValueError(
            f"display_scale must be finite and at most {_MAX_DISPLAY_SCALE:g}"
        )
    return display_scale


def _checkerboard(size: tuple[int, int]) -> Image.Image:
    checker = Image.new("RGBA", size, _CHECKER_LIGHT)
    draw = ImageDraw.Draw(checker)
    for y in range(0, size[1], _CHECKER_TILE_SIZE):
        for x in range(0, size[0], _CHECKER_TILE_SIZE):
            if (x // _CHECKER_TILE_SIZE + y // _CHECKER_TILE_SIZE) % 2:
                draw.rectangle(
                    (
                        x,
                        y,
                        min(size[0] - 1, x + _CHECKER_TILE_SIZE - 1),
                        min(size[1] - 1, y + _CHECKER_TILE_SIZE - 1),
                    ),
                    fill=_CHECKER_DARK,
                )
    return checker


def _background(name: str, size: tuple[int, int]) -> Image.Image:
    if name == "checker":
        return _checkerboard(size)
    if name == "light":
        return Image.new("RGBA", size, _LIGHT_BACKGROUND)
    if name == "dark":
        return Image.new("RGBA", size, _DARK_BACKGROUND)
    raise ValueError("unknown contact-sheet background")


def _label_evidence(label: str) -> str:
    non_ascii = [
        f"U+{ord(character):04X}" for character in label if ord(character) > 127
    ]
    return f"{label} [{' '.join(non_ascii)}]" if non_ascii else label


def _ascii_label_fallback(label: str) -> str:
    ascii_characters = "".join(character for character in label if ord(character) < 128)
    codepoints = " ".join(
        f"U+{ord(character):04X}" for character in label if ord(character) > 127
    )
    if codepoints:
        return f"{ascii_characters} [{codepoints}]".strip()
    return ascii_characters


def _load_label_font() -> tuple[ImageFont.ImageFont, dict[str, object]]:
    for candidate in _CJK_FONT_CANDIDATES:
        try:
            if candidate.is_file():
                return (
                    ImageFont.truetype(str(candidate), 14),
                    {
                        "route": "cjk-system-font",
                        "fontPath": str(candidate),
                        "nonAsciiFallback": "unicode-codepoint-ascii",
                    },
                )
        except (OSError, UnicodeError, ValueError):
            continue
    return (
        ImageFont.load_default(),
        {
            "route": "pillow-default-fallback",
            "fontPath": None,
            "nonAsciiFallback": "unicode-codepoint-ascii",
        },
    )


def _display_label(
    label: str, label_evidence: str, label_rendering: dict[str, object]
) -> str:
    if label_rendering["route"] == "cjk-system-font":
        return label_evidence
    return _ascii_label_fallback(label)


def _text_size(rendered_label: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    probe = Image.new("RGBA", (1, 1), _CHECKER_LIGHT)
    try:
        bounds = ImageDraw.Draw(probe).textbbox((0, 0), rendered_label, font=font)
    except (UnicodeError, ValueError, OSError) as error:
        raise ValueError("frame label could not be rendered") from error
    return (bounds[2] - bounds[0], bounds[3] - bounds[1])


def _scaled_size(image: Image.Image, scale: float) -> tuple[int, int]:
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    if (
        width > _MAX_CELL_DIMENSION
        or height > _MAX_CELL_DIMENSION
        or width * height > _MAX_CELL_PIXELS
    ):
        raise ValueError("display scale projects an unsafe contact-sheet cell")
    return (width, height)


def _cell_size(
    display_size: tuple[int, int], rendered_label: str, font: ImageFont.ImageFont
) -> tuple[int, int]:
    label_width, label_height = _text_size(rendered_label, font)
    width = max(display_size[0], label_width) + _PADDING * 2
    height = display_size[1] + label_height + _PADDING * 3
    if (
        width > _MAX_CELL_DIMENSION
        or height > _MAX_CELL_DIMENSION
        or width * height > _MAX_CELL_PIXELS
    ):
        raise ValueError("label projects an unsafe contact-sheet cell")
    return (width, height)


def _board_size(cell_sizes: list[tuple[int, int]], columns: int) -> tuple[int, int]:
    if not cell_sizes or len(cell_sizes) > _MAX_CONTACT_CELLS:
        raise ValueError("contact sheet has an unsafe number of cells")
    effective_columns = min(columns, len(cell_sizes))
    row_count = (len(cell_sizes) + effective_columns - 1) // effective_columns
    column_widths = [0] * effective_columns
    row_heights = [0] * row_count
    for index, (width, height) in enumerate(cell_sizes):
        column = index % effective_columns
        row = index // effective_columns
        column_widths[column] = max(column_widths[column], width)
        row_heights[row] = max(row_heights[row], height)
    board_width = sum(column_widths) + _GAP * (effective_columns + 1)
    board_height = sum(row_heights) + _GAP * (row_count + 1)
    if (
        board_width > _MAX_BOARD_DIMENSION
        or board_height > _MAX_BOARD_DIMENSION
        or board_width * board_height > _MAX_BOARD_PIXELS
    ):
        raise ValueError("contact sheet projects an unsafe board size")
    return (board_width, board_height)


def _resized(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return image.resize(size, Image.Resampling.LANCZOS)


def _labeled_cell(
    image: Image.Image,
    rendered_label: str,
    background_name: str,
    font: ImageFont.ImageFont,
    expected_size: tuple[int, int],
) -> Image.Image:
    cell = Image.new("RGBA", expected_size, _CHECKER_LIGHT)
    draw = ImageDraw.Draw(cell)
    draw.text((_PADDING, _PADDING), rendered_label, fill="#1D2730", font=font)
    canvas = _background(background_name, image.size)
    canvas.alpha_composite(image)
    label_height = _text_size(rendered_label, font)[1]
    cell.alpha_composite(canvas, (_PADDING, label_height + _PADDING * 2))
    return cell


def _assemble_cells(
    cells: list[Image.Image], columns: int, expected_board_size: tuple[int, int]
) -> Image.Image:
    effective_columns = min(columns, len(cells))
    rows = [
        cells[index : index + effective_columns]
        for index in range(0, len(cells), effective_columns)
    ]
    column_widths = [
        max(row[column].width for row in rows if column < len(row))
        for column in range(effective_columns)
    ]
    row_heights = [max(cell.height for cell in row) for row in rows]
    board = Image.new("RGBA", expected_board_size, _CHECKER_LIGHT)
    y = _GAP
    for row, row_height in zip(rows, row_heights, strict=True):
        x = _GAP
        for column, cell in enumerate(row):
            board.alpha_composite(cell, (x, y))
            x += column_widths[column] + _GAP
        y += row_height + _GAP
    return board


def _temporary_path(directory: Path, stem: str, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(
        prefix=f".{stem}.", suffix=suffix, dir=directory, delete=False
    ) as temporary:
        return Path(temporary.name)


def _backup_existing(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = _temporary_path(path.parent, path.stem, ".bak")
    try:
        shutil.copyfile(path, backup)
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _restore_pair(
    output_path: Path,
    sidecar_path: Path,
    output_backup: Path | None,
    sidecar_backup: Path | None,
) -> None:
    for path, backup in (
        (output_path, output_backup),
        (sidecar_path, sidecar_backup),
    ):
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            os.replace(backup, path)


def _publish_pair(
    output_path: Path, sidecar_path: Path, board: Image.Image, sidecar_text: str
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image_temporary: Path | None = None
    sidecar_temporary: Path | None = None
    output_backup: Path | None = None
    sidecar_backup: Path | None = None
    try:
        image_temporary = _temporary_path(output_path.parent, output_path.stem, ".tmp")
        sidecar_temporary = _temporary_path(
            sidecar_path.parent, sidecar_path.stem, ".tmp"
        )
        board.save(image_temporary, format="PNG")
        sidecar_temporary.write_text(sidecar_text, encoding="utf-8")
        output_backup = _backup_existing(output_path)
        sidecar_backup = _backup_existing(sidecar_path)
        try:
            os.replace(image_temporary, output_path)
            os.replace(sidecar_temporary, sidecar_path)
        except OSError:
            try:
                _restore_pair(
                    output_path,
                    sidecar_path,
                    output_backup,
                    sidecar_backup,
                )
            except OSError as rollback_error:
                raise RuntimeError("contact-sheet publication rollback failed") from rollback_error
            raise
    finally:
        for path in (
            image_temporary,
            sidecar_temporary,
            output_backup,
            sidecar_backup,
        ):
            if path is not None:
                path.unlink(missing_ok=True)


def make_contact_sheet(
    frames: list[dict[str, object]],
    output_path: Path,
    columns: int,
    display_scale: float,
) -> dict[str, object]:
    """Publish ordered technical review artifacts without a visual verdict."""
    ordered_records = _validate_frames(frames)
    validated_columns = _validate_columns(columns)
    validated_scale = _validate_display_scale(display_scale)
    output = _coerce_output_path(output_path)
    sidecar_path = output.with_suffix(output.suffix + ".json")
    if any(
        _paths_alias(candidate, path)
        for candidate in (output, sidecar_path)
        for _, path in ordered_records
    ):
        raise ValueError("output path or sidecar must not match an input frame")

    font, label_rendering = _load_label_font()
    frame_metadata: list[dict[str, object]] = []
    source_images: list[Image.Image] = []
    display_sizes: list[tuple[int, int]] = []
    rendered_labels: list[str] = []
    cell_plans: list[tuple[int, str, tuple[int, int], tuple[int, int]]] = []
    for index, (label, path) in enumerate(ordered_records):
        image = _load_visible_rgba(path)
        source_images.append(image)
        display_size = _scaled_size(image, validated_scale)
        label_evidence = _label_evidence(label)
        rendered_label = _display_label(label, label_evidence, label_rendering)
        display_sizes.append(display_size)
        rendered_labels.append(rendered_label)
        frame_metadata.append(
            {
                "index": index,
                "label": label,
                "labelEvidence": label_evidence,
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
                "sourceCanvas": [image.width, image.height],
                "displayCanvas": [display_size[0], display_size[1]],
                "mode": "RGBA",
            }
        )
        for background_name in _BACKGROUND_NAMES:
            cell_plans.append(
                (
                    index,
                    background_name,
                    display_size,
                    _cell_size(display_size, rendered_label, font),
                )
            )

    board_size = _board_size(
        [cell_size for _, _, _, cell_size in cell_plans], validated_columns
    )
    displays = [
        _resized(source_image, display_size)
        for source_image, display_size in zip(source_images, display_sizes, strict=True)
    ]
    cells = [
        _labeled_cell(
            displays[index],
            rendered_labels[index],
            background_name,
            font,
            cell_size,
        )
        for index, background_name, _, cell_size in cell_plans
    ]
    effective_columns = min(validated_columns, len(cells))
    sidecar: dict[str, object] = {
        "schemaVersion": 1,
        "diagnosticOnly": True,
        "columns": validated_columns,
        "effectiveColumns": effective_columns,
        "displayScale": validated_scale,
        "backgrounds": list(_BACKGROUND_NAMES),
        "backgroundParameters": {
            "checker": {
                "tileSize": _CHECKER_TILE_SIZE,
                "light": _CHECKER_LIGHT,
                "dark": _CHECKER_DARK,
            },
            "light": {"color": _LIGHT_BACKGROUND},
            "dark": {"color": _DARK_BACKGROUND},
        },
        "labelRendering": label_rendering,
        "frames": frame_metadata,
    }
    _publish_pair(
        output,
        sidecar_path,
        _assemble_cells(cells, effective_columns, board_size),
        json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n",
    )
    return sidecar
