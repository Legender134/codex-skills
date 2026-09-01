from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from PIL import Image, ImageDraw, ImageFont

from measure_identity_geometry import measure_alpha_geometry


_LIGHT = "#F2F2F2"
_DARK = "#20242A"
_WHITE = "#FFFFFF"
_PANEL_PADDING = 12
_PANEL_GAP = 12
_REFERENCE_MAXIMUM_SIZE = (280, 220)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_rgba(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return source.convert("RGBA")


def _resize_to_height(image: Image.Image, height: int) -> Image.Image:
    source_width, source_height = image.size
    width = max(1, int(source_width * height / source_height))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _fit_reference(image: Image.Image) -> Image.Image:
    maximum_width, maximum_height = _REFERENCE_MAXIMUM_SIZE
    width, height = image.size
    scale = min(1.0, maximum_width / width, maximum_height / height)
    if scale == 1.0:
        return image.copy()
    return image.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))),
        Image.Resampling.LANCZOS,
    )


def _composite(image: Image.Image, background: str | Image.Image) -> Image.Image:
    if isinstance(background, Image.Image):
        canvas = background.copy()
    else:
        canvas = Image.new("RGBA", image.size, background)
    canvas.alpha_composite(image)
    return canvas


def _checkerboard(size: tuple[int, int]) -> Image.Image:
    checker = Image.new("RGBA", size, "#FFFFFF")
    draw = ImageDraw.Draw(checker)
    for y in range(0, size[1], 8):
        for x in range(0, size[0], 8):
            if (x // 8 + y // 8) % 2:
                draw.rectangle((x, y, x + 7, y + 7), fill="#D4D4D4")
    return checker


def _silhouette(image: Image.Image) -> Image.Image:
    result = Image.new("RGBA", image.size, "#4C6A84")
    result.putalpha(image.getchannel("A"))
    return result


def _geometry_text_panel(report: dict[str, object]) -> Image.Image:
    font = ImageFont.load_default()
    lines = [
        "Diagnostic geometry",
        f"canvas: {report['canvas'][0]} x {report['canvas'][1]}",
        f"alpha bbox: {report['alphaBoundingBox']}",
        f"alpha pixels: {report['alphaPixels']}",
        f"centroid: {report['centroid']}",
        f"width profile: {report['widthProfile']}",
        f"widest segment: {report['maximumWidthSegment']}",
        "diagnostic only; no visual verdict",
    ]
    text = "\n".join(lines)
    probe = Image.new("RGBA", (1, 1), _WHITE)
    probe_draw = ImageDraw.Draw(probe)
    bounds = probe_draw.multiline_textbbox((0, 0), text, font=font, spacing=3)
    content = Image.new(
        "RGBA",
        (bounds[2] - bounds[0] + _PANEL_PADDING * 2, bounds[3] - bounds[1] + _PANEL_PADDING * 2),
        _WHITE,
    )
    ImageDraw.Draw(content).multiline_text(
        (_PANEL_PADDING, _PANEL_PADDING),
        text,
        fill="#1D2730",
        font=font,
        spacing=3,
    )
    return content


def _metadata(
    name: str,
    source_path: Path,
    source_hash: str,
    rendered: Image.Image,
    background: str,
    role: str,
) -> dict[str, object]:
    return {
        "name": name,
        "source": str(source_path.resolve()),
        "sha256": source_hash,
        "renderedSize": list(rendered.size),
        "background": background,
        "role": role,
    }


def _tile_panel(metadata: dict[str, object], content: Image.Image) -> Image.Image:
    label = str(metadata["name"])
    font = ImageFont.load_default()
    probe = Image.new("RGBA", (1, 1), _WHITE)
    label_bounds = ImageDraw.Draw(probe).textbbox((0, 0), label, font=font)
    label_height = label_bounds[3] - label_bounds[1]
    tile_width = max(content.width, label_bounds[2] - label_bounds[0]) + _PANEL_PADDING * 2
    tile_height = content.height + label_height + _PANEL_PADDING * 3
    tile = Image.new("RGBA", (tile_width, tile_height), _WHITE)
    draw = ImageDraw.Draw(tile)
    draw.rectangle((0, 0, tile_width - 1, tile_height - 1), outline="#A9B0B7")
    draw.text((_PANEL_PADDING, _PANEL_PADDING), label, fill="#1D2730", font=font)
    x = (tile_width - content.width) // 2
    y = label_height + _PANEL_PADDING * 2
    tile.alpha_composite(content, (x, y))
    return tile


def _assemble_board(panels: list[tuple[dict[str, object], Image.Image]]) -> Image.Image:
    tiles = [_tile_panel(metadata, content) for metadata, content in panels]
    rows = [tiles[index : index + 3] for index in range(0, len(tiles), 3)]
    column_widths = [max(row[column].width for row in rows) for column in range(3)]
    row_heights = [max(tile.height for tile in row) for row in rows]
    board_width = sum(column_widths) + _PANEL_GAP * 4
    board_height = sum(row_heights) + _PANEL_GAP * 4
    board = Image.new("RGBA", (board_width, board_height), _WHITE)
    y = _PANEL_GAP
    for row_index, row in enumerate(rows):
        x = _PANEL_GAP
        for column_index, tile in enumerate(row):
            board.alpha_composite(tile, (x, y))
            x += column_widths[column_index] + _PANEL_GAP
        y += row_heights[row_index] + _PANEL_GAP
    return board


def _temporary_path(output_directory: Path, stem: str, suffix: str) -> Path:
    with tempfile.NamedTemporaryFile(
        prefix=f".{stem}.", suffix=suffix, dir=output_directory, delete=False
    ) as temporary:
        return Path(temporary.name)


def _normalized_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _validate_output_paths(
    output_path: Path, sidecar_path: Path, input_paths: tuple[Path, Path, Path]
) -> None:
    protected_paths = {_normalized_path(output_path), _normalized_path(sidecar_path)}
    if any(_normalized_path(path) in protected_paths for path in input_paths):
        raise ValueError("output path or sidecar must not match an input image")


def _backup_existing(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup_path = _temporary_path(path.parent, path.stem, ".bak")
    try:
        shutil.copyfile(path, backup_path)
    except BaseException:
        backup_path.unlink(missing_ok=True)
        raise
    return backup_path


def _restore_previous_pair(
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
    png_temporary_path = _temporary_path(output_path.parent, output_path.stem, ".tmp")
    sidecar_temporary_path = _temporary_path(
        sidecar_path.parent, sidecar_path.stem, ".tmp"
    )
    output_backup: Path | None = None
    sidecar_backup: Path | None = None
    try:
        board.save(png_temporary_path, format="PNG")
        sidecar_temporary_path.write_text(sidecar_text, encoding="utf-8")
        output_backup = _backup_existing(output_path)
        sidecar_backup = _backup_existing(sidecar_path)
        try:
            os.replace(png_temporary_path, output_path)
            os.replace(sidecar_temporary_path, sidecar_path)
        except OSError:
            try:
                _restore_previous_pair(
                    output_path,
                    sidecar_path,
                    output_backup,
                    sidecar_backup,
                )
            except OSError as rollback_error:
                raise RuntimeError("identity review output rollback failed") from rollback_error
            raise
    finally:
        for path in (
            png_temporary_path,
            sidecar_temporary_path,
            output_backup,
            sidecar_backup,
        ):
            if path is not None:
                path.unlink(missing_ok=True)


def build_identity_review_sheet(
    candidate_path: Path,
    identity_reference_path: Path,
    proportion_reference_path: Path,
    output_path: Path,
    runtime_height: int,
) -> dict[str, object]:
    """Build a fixed diagnostic board without determining visual acceptance."""
    if not isinstance(runtime_height, int) or isinstance(runtime_height, bool) or runtime_height <= 0:
        raise ValueError("runtime_height must be a positive integer")

    candidate_path = Path(candidate_path)
    identity_reference_path = Path(identity_reference_path)
    proportion_reference_path = Path(proportion_reference_path)
    output_path = Path(output_path)
    sidecar_path = output_path.with_suffix(output_path.suffix + ".json")
    _validate_output_paths(
        output_path,
        sidecar_path,
        (candidate_path, identity_reference_path, proportion_reference_path),
    )

    candidate = _load_rgba(candidate_path)
    identity_reference = _load_rgba(identity_reference_path)
    proportion_reference = _load_rgba(proportion_reference_path)
    candidate_hash = _sha256_file(candidate_path)
    identity_hash = _sha256_file(identity_reference_path)
    proportion_hash = _sha256_file(proportion_reference_path)
    geometry = measure_alpha_geometry(candidate_path)

    actual_size = _resize_to_height(candidate, runtime_height)
    identity_content = _composite(_fit_reference(identity_reference), _WHITE)
    proportion_content = _composite(_fit_reference(proportion_reference), _WHITE)
    candidate_original = _composite(candidate, _WHITE)
    candidate_actual = _composite(actual_size, _WHITE)
    light = _composite(actual_size, _LIGHT)
    dark = _composite(actual_size, _DARK)
    checker = _composite(actual_size, _checkerboard(actual_size.size))
    silhouette = _composite(_silhouette(actual_size), _LIGHT)
    geometry_content = _geometry_text_panel(geometry)

    panels: list[tuple[dict[str, object], Image.Image]] = [
        (
            _metadata(
                "identity-reference",
                identity_reference_path,
                identity_hash,
                identity_content,
                _WHITE,
                "identity-reference",
            ),
            identity_content,
        ),
        (
            _metadata(
                "proportion-reference",
                proportion_reference_path,
                proportion_hash,
                proportion_content,
                _WHITE,
                "proportion-reference",
            ),
            proportion_content,
        ),
        (
            _metadata(
                "candidate-original",
                candidate_path,
                candidate_hash,
                candidate_original,
                _WHITE,
                "candidate-original",
            ),
            candidate_original,
        ),
        (
            _metadata(
                "candidate-actual-size",
                candidate_path,
                candidate_hash,
                candidate_actual,
                _WHITE,
                "candidate-actual-size",
            ),
            candidate_actual,
        ),
        (
            _metadata(
                "light",
                candidate_path,
                candidate_hash,
                light,
                _LIGHT,
                "light-background",
            ),
            light,
        ),
        (
            _metadata(
                "dark",
                candidate_path,
                candidate_hash,
                dark,
                _DARK,
                "dark-background",
            ),
            dark,
        ),
        (
            _metadata(
                "checker",
                candidate_path,
                candidate_hash,
                checker,
                "checker-8px",
                "checker-background",
            ),
            checker,
        ),
        (
            _metadata(
                "silhouette",
                candidate_path,
                candidate_hash,
                silhouette,
                _LIGHT,
                "alpha-silhouette",
            ),
            silhouette,
        ),
        (
            _metadata(
                "geometry",
                candidate_path,
                candidate_hash,
                geometry_content,
                _WHITE,
                "diagnostic-geometry",
            ),
            geometry_content,
        ),
    ]
    sidecar = {
        "schemaVersion": 1,
        "runtimeHeight": runtime_height,
        "diagnosticOnly": True,
        "geometry": geometry,
        "panels": [metadata for metadata, _ in panels],
    }
    board = _assemble_board(panels)

    _publish_pair(
        output_path,
        sidecar_path,
        board,
        json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n",
    )
    return sidecar
