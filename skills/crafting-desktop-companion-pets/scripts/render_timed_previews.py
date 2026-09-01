from __future__ import annotations

import hashlib
from io import BytesIO
import os
from pathlib import Path
import shutil
import struct
import tempfile
import warnings

from PIL import Image

from contracts import _is_utf8_text, _validate_untrusted_image_canvas, sha256_file


_MAX_WEBP_DURATION_MS = 0xFFFFFF
_MAX_WEBP_LOOP_COUNT = 0xFFFF
_VP8X_ANIMATION_AND_ALPHA = 0x12
_ANMF_DISPOSE_TO_BACKGROUND_AND_NO_BLEND = 0x03


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


def _normalized_path(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve(strict=False)))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("path could not be normalized safely") from error


def _paths_alias(left: Path, right: Path) -> bool:
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
    if isinstance(value, str) and (not _is_utf8_text(value) or not value.strip()):
        raise ValueError("output_path must be non-empty UTF-8 text")
    try:
        path = Path(value)
        if not path.name or path.exists() and path.is_dir():
            raise ValueError("output_path must name a WebP file")
        if path.suffix.lower() != ".webp":
            raise ValueError("output_path must name a WebP file")
        _normalized_path(path)
        return path
    except (OSError, UnicodeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith("output_path"):
            raise
        raise ValueError("output_path must name a writable WebP file") from error


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


def _validate_frame_paths(frame_paths: object) -> list[Path]:
    if not isinstance(frame_paths, list) or not frame_paths:
        raise ValueError("frame_paths must be a non-empty list")
    return [
        _coerce_input_path(value, f"frame_paths[{index}]")
        for index, value in enumerate(frame_paths)
    ]


def _validate_durations(durations_ms: object, frame_count: int) -> list[int]:
    if not isinstance(durations_ms, list) or not durations_ms:
        raise ValueError("durations_ms must be a non-empty list of positive integers")
    if len(durations_ms) != frame_count:
        raise ValueError("durations_ms must have the same length as frame_paths")
    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= _MAX_WEBP_DURATION_MS
        for value in durations_ms
    ):
        raise ValueError(
            f"durations_ms must contain integers from 1 to {_MAX_WEBP_DURATION_MS}"
        )
    return list(durations_ms)


def _validate_loop(loop: object) -> int:
    if (
        not isinstance(loop, int)
        or isinstance(loop, bool)
        or not 0 <= loop <= _MAX_WEBP_LOOP_COUNT
    ):
        raise ValueError(f"loop must be an integer from 0 to {_MAX_WEBP_LOOP_COUNT}")
    return loop


def _temporary_path(directory: Path, stem: str) -> Path:
    with tempfile.NamedTemporaryFile(
        prefix=f".{stem}.", suffix=".tmp", dir=directory, delete=False
    ) as temporary:
        return Path(temporary.name)


def _uint24(value: int, field: str) -> bytes:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFF:
        raise ValueError(f"{field} must fit in an unsigned 24-bit integer")
    return value.to_bytes(3, "little")


def _riff_chunk(tag: bytes, payload: bytes) -> bytes:
    if len(tag) != 4:
        raise ValueError("RIFF chunk tags must contain exactly four bytes")
    return tag + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) % 2 else b"")


def _iter_riff_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("static WebP encoder did not produce a RIFF WEBP file")
    if struct.unpack("<I", data[4:8])[0] != len(data) - 8:
        raise ValueError("static WebP RIFF length is invalid")
    offset = 12
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("static WebP chunk header is truncated")
        tag = data[offset : offset + 4]
        size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        payload_start = offset + 8
        payload_end = payload_start + size
        if payload_end > len(data):
            raise ValueError("static WebP chunk is truncated")
        chunks.append((tag, data[payload_start:payload_end]))
        offset = payload_end + (size % 2)
    if offset != len(data):
        raise ValueError("static WebP chunk padding is invalid")
    return chunks


def _static_image_chunks(frame: Image.Image) -> bytes:
    encoded = BytesIO()
    frame.save(encoded, format="WEBP", lossless=True, exact=True)
    image_chunks: list[bytes] = []
    image_tags: list[bytes] = []
    for tag, payload in _iter_riff_chunks(encoded.getvalue()):
        if tag in {b"ALPH", b"VP8 ", b"VP8L"}:
            image_chunks.append(_riff_chunk(tag, payload))
            image_tags.append(tag)
    has_vp8l = b"VP8L" in image_tags
    has_vp8 = b"VP8 " in image_tags
    if has_vp8l == has_vp8:
        raise ValueError("static WebP must contain exactly one VP8L or VP8 image chunk")
    if has_vp8l and b"ALPH" in image_tags:
        raise ValueError("VP8L static WebP must not require a separate ALPH chunk")
    if has_vp8 and image_tags[-1] != b"VP8 ":
        raise ValueError("lossy static WebP image chunks must end with VP8")
    return b"".join(image_chunks)


def _assemble_animation_webp(
    frames: list[Image.Image], durations: list[int], loop_count: int
) -> bytes:
    width, height = frames[0].size
    if width > 0xFFFFFF or height > 0xFFFFFF:
        raise ValueError("preview canvas exceeds WebP 24-bit dimensions")
    vp8x = bytes([_VP8X_ANIMATION_AND_ALPHA, 0, 0, 0]) + _uint24(
        width - 1, "canvas width"
    ) + _uint24(height - 1, "canvas height")
    chunks = [
        _riff_chunk(b"VP8X", vp8x),
        _riff_chunk(b"ANIM", b"\x00\x00\x00\x00" + struct.pack("<H", loop_count)),
    ]
    for frame, duration in zip(frames, durations, strict=True):
        anmf_header = (
            _uint24(0, "frame x")
            + _uint24(0, "frame y")
            + _uint24(width - 1, "frame width")
            + _uint24(height - 1, "frame height")
            + _uint24(duration, "frame duration")
            + bytes([_ANMF_DISPOSE_TO_BACKGROUND_AND_NO_BLEND])
        )
        chunks.append(_riff_chunk(b"ANMF", anmf_header + _static_image_chunks(frame)))
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _rgba_pixel_hash(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def _verify_preview(
    path: Path,
    expected_frames: list[Image.Image],
    expected_durations: list[int],
    expected_loop: int,
) -> None:
    expected_hashes = [_rgba_pixel_hash(frame) for frame in expected_frames]
    try:
        with Image.open(path) as preview:
            if preview.n_frames != len(expected_frames):
                raise ValueError("preview frame count changed during encoding")
            if preview.size != expected_frames[0].size:
                raise ValueError("preview canvas changed during encoding")
            if preview.info.get("loop") != expected_loop:
                raise ValueError("preview loop count changed during encoding")
            actual_durations: list[int] = []
            actual_hashes: list[str] = []
            for index in range(preview.n_frames):
                preview.seek(index)
                preview.load()
                duration = preview.info.get("duration")
                if isinstance(duration, bool) or not isinstance(duration, int):
                    raise ValueError("preview did not preserve integer frame durations")
                actual_durations.append(duration)
                actual_hashes.append(_rgba_pixel_hash(preview))
    except (OSError, SyntaxError, UnicodeError) as error:
        raise ValueError("preview could not be reopened for verification") from error
    if actual_durations != expected_durations:
        raise ValueError("preview did not preserve exact frame durations")
    if actual_hashes != expected_hashes:
        raise ValueError("preview did not preserve exact RGBA frame pixels")


def _backup_existing(path: Path) -> Path | None:
    if not path.exists():
        return None
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.stem}.", suffix=".bak", dir=path.parent, delete=False
    ) as temporary:
        backup = Path(temporary.name)
    try:
        shutil.copyfile(path, backup)
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def _publish_preview(temporary: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    backup = _backup_existing(output_path)
    try:
        try:
            os.replace(temporary, output_path)
        except OSError:
            try:
                if backup is None:
                    output_path.unlink(missing_ok=True)
                else:
                    shutil.copyfile(backup, output_path)
            except OSError as rollback_error:
                raise RuntimeError("preview publication rollback failed") from rollback_error
            raise
    finally:
        if backup is not None:
            backup.unlink(missing_ok=True)


def render_timed_preview(
    frame_paths: list[Path],
    durations_ms: list[int],
    output_path: Path,
    loop: int,
) -> dict[str, object]:
    """Encode a lossless, non-coalescing technical WebP preview."""
    paths = _validate_frame_paths(frame_paths)
    durations = _validate_durations(durations_ms, len(paths))
    loop_count = _validate_loop(loop)
    output = _coerce_output_path(output_path)
    if any(_paths_alias(output, path) for path in paths):
        raise ValueError("output_path must not match an input frame")

    frames = [_load_visible_rgba(path) for path in paths]
    canvas = frames[0].size
    if any(frame.size != canvas for frame in frames[1:]):
        raise ValueError("all preview frames must share one canvas")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(output.parent, output.stem)
    try:
        temporary.write_bytes(_assemble_animation_webp(frames, durations, loop_count))
        _verify_preview(temporary, frames, durations, loop_count)
        _publish_preview(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    return {
        "schemaVersion": 1,
        "technicalStatus": "pass",
        "outputPath": str(output.resolve()),
        "sha256": sha256_file(output),
        "frameCount": len(frames),
        "durationsMs": list(durations),
        "loop": loop_count,
        "lossless": True,
    }
