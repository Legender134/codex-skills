from __future__ import annotations

import os
from pathlib import Path
import warnings

from PIL import Image

from contracts import _is_utf8_text, _validate_untrusted_image_canvas, sha256_file


def _coerce_input_path(value: object, field: str) -> Path:
    if isinstance(value, bytes) or not isinstance(value, (str, os.PathLike)):
        raise ValueError(f"{field} must be a filesystem path")
    if isinstance(value, str) and (not _is_utf8_text(value) or not value.strip()):
        raise ValueError(f"{field} must be non-empty UTF-8 text")
    try:
        path = Path(value)
        if not path.is_file():
            raise ValueError(f"{field} must name an existing file")
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


def _validate_expected_canvas(
    expected_canvas: tuple[int, int] | None,
) -> tuple[int, int] | None:
    if expected_canvas is None:
        return None
    if not isinstance(expected_canvas, (tuple, list)) or len(expected_canvas) != 2:
        raise ValueError("expected_canvas must contain exactly two positive integers")
    width, height = expected_canvas
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
        or width <= 0
        or height <= 0
    ):
        raise ValueError("expected_canvas must contain exactly two positive integers")
    return width, height


def _components(alpha: Image.Image) -> list[dict[str, object]]:
    width, height = alpha.size
    visible = [opacity != 0 for opacity in alpha.get_flattened_data()]
    visited = bytearray(width * height)
    components: list[dict[str, object]] = []
    for start_index, is_visible in enumerate(visible):
        if not is_visible or visited[start_index]:
            continue
        stack = [start_index]
        visited[start_index] = 1
        pixels = 0
        minimum_x = width
        minimum_y = height
        maximum_x = -1
        maximum_y = -1
        while stack:
            index = stack.pop()
            x = index % width
            y = index // width
            pixels += 1
            minimum_x = min(minimum_x, x)
            minimum_y = min(minimum_y, y)
            maximum_x = max(maximum_x, x)
            maximum_y = max(maximum_y, y)
            for neighbor_x, neighbor_y in (
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
            ):
                if not (0 <= neighbor_x < width and 0 <= neighbor_y < height):
                    continue
                neighbor_index = neighbor_y * width + neighbor_x
                if visible[neighbor_index] and not visited[neighbor_index]:
                    visited[neighbor_index] = 1
                    stack.append(neighbor_index)
        components.append(
            {
                "boundingBox": [
                    minimum_x,
                    minimum_y,
                    maximum_x + 1,
                    maximum_y + 1,
                ],
                "alphaPixels": pixels,
            }
        )
    components.sort(
        key=lambda component: (
            component["boundingBox"][1],
            component["boundingBox"][0],
            component["boundingBox"][3],
            component["boundingBox"][2],
        )
    )
    return [dict(component, index=index) for index, component in enumerate(components)]


def _anchor(bounding_box: tuple[int, int, int, int]) -> list[float]:
    left, _, right, bottom = bounding_box
    return [round((left + right - 1) / 2, 6), round(float(bottom - 1), 6)]


def inspect_frames(
    frame_paths: list[Path],
    expected_canvas: tuple[int, int] | None = None,
) -> dict[str, object]:
    """Return static alpha diagnostics without granting visual acceptance."""
    if not isinstance(frame_paths, list) or not frame_paths:
        raise ValueError("frame_paths must be a non-empty list")
    canvas_expectation = _validate_expected_canvas(expected_canvas)
    paths = [
        _coerce_input_path(value, f"frame_paths[{index}]")
        for index, value in enumerate(frame_paths)
    ]

    records: list[dict[str, object]] = []
    first_anchor: list[float] | None = None
    for index, path in enumerate(paths):
        image = _load_visible_rgba(path)
        width, height = image.size
        if canvas_expectation is not None and (width, height) != canvas_expectation:
            raise ValueError(
                f"frame_paths[{index}] has canvas {width}x{height}, expected "
                f"{canvas_expectation[0]}x{canvas_expectation[1]}"
            )
        alpha = image.getchannel("A")
        bounding_box = alpha.getbbox()
        if bounding_box is None:
            raise ValueError(f"frame_paths[{index}] has no visible alpha pixels")
        left, top, right, bottom = bounding_box
        anchor = _anchor(bounding_box)
        if first_anchor is None:
            first_anchor = list(anchor)
        components = _components(alpha)
        records.append(
            {
                "index": index,
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
                "canvas": [width, height],
                "mode": "RGBA",
                "alphaBoundingBox": [left, top, right, bottom],
                "alphaPixels": sum(1 for opacity in alpha.get_flattened_data() if opacity),
                "clippedLeft": left == 0,
                "clippedTop": top == 0,
                "clippedRight": right == width,
                "clippedBottom": bottom == height,
                "componentCount": len(components),
                "components": components,
                "bottomCenterAnchor": anchor,
                "anchorDriftFromFirst": [
                    round(anchor[0] - first_anchor[0], 6),
                    round(anchor[1] - first_anchor[1], 6),
                ],
            }
        )
    return {
        "schemaVersion": 1,
        "diagnosticOnly": True,
        "expectedCanvas": list(canvas_expectation) if canvas_expectation is not None else None,
        "frames": records,
    }
