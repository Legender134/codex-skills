from __future__ import annotations

from pathlib import Path

from PIL import Image


def _alpha_weighted_centroid(alpha: Image.Image) -> list[float]:
    width, _ = alpha.size
    total_alpha = 0
    weighted_x = 0
    weighted_y = 0
    for index, opacity in enumerate(alpha.get_flattened_data()):
        if opacity:
            x = index % width
            y = index // width
            total_alpha += opacity
            weighted_x += x * opacity
            weighted_y += y * opacity
    return [round(weighted_x / total_alpha, 6), round(weighted_y / total_alpha, 6)]


def _width_profile(
    alpha: Image.Image, bounding_box: tuple[int, int, int, int], segments: int
) -> list[int]:
    _, top, _, bottom = bounding_box
    width, _ = alpha.size
    bounded_height = bottom - top
    profile: list[int] = []
    for segment in range(segments):
        segment_top = top + bounded_height * segment // segments
        segment_bottom = top + bounded_height * (segment + 1) // segments
        widest_row = 0
        for y in range(segment_top, segment_bottom):
            row_bounds = alpha.crop((0, y, width, y + 1)).getbbox()
            if row_bounds is not None:
                widest_row = max(widest_row, row_bounds[2] - row_bounds[0])
        profile.append(widest_row)
    return profile


def measure_alpha_geometry(
    image_path: Path, segments: int = 8
) -> dict[str, object]:
    """Measure visible-alpha geometry without making an aesthetic verdict."""
    if not isinstance(segments, int) or isinstance(segments, bool) or segments <= 0:
        raise ValueError("segments must be a positive integer")

    with Image.open(Path(image_path)) as source:
        image = source.convert("RGBA")
    alpha = image.getchannel("A")
    _, alpha_maximum = alpha.getextrema()
    bounding_box = alpha.getbbox()
    if alpha_maximum == 0 or bounding_box is None:
        raise ValueError("image has no visible pixels")

    width, height = image.size
    visible_height = max(1, bounding_box[3] - bounding_box[1])
    profile = _width_profile(alpha, bounding_box, min(segments, visible_height))
    maximum_width_segment = max(range(len(profile)), key=profile.__getitem__)
    alpha_pixels = sum(1 for opacity in alpha.get_flattened_data() if opacity)
    return {
        "canvas": [width, height],
        "alphaBoundingBox": list(bounding_box),
        "alphaPixels": alpha_pixels,
        "centroid": _alpha_weighted_centroid(alpha),
        "widthProfile": profile,
        "maximumWidthSegment": maximum_width_segment,
        "diagnosticOnly": True,
    }
