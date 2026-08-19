from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any, Sequence
import uuid


IMAGE_SIZE = 256
MODEL_NAMES = ("isnet-anime", "u2net_human_seg")
ALPHA_CHANNEL_DESCRIPTIONS = {
    "rgba 4.0",
    "srgba 4.0",
    "graya 2.0",
    "cmyka 5.0",
}
COMMAND_TIMEOUT_SECONDS = 60
PREVIEW_DURATION_SECONDS = 0.4
PREVIEW_FRAME_INTERVAL_SECONDS = PREVIEW_DURATION_SECONDS / 4
PREVIEW_TIMING_TOLERANCE_SECONDS = 0.025
# FFprobe emits decimal strings; this only preserves inclusive boundaries after float conversion.
PREVIEW_FLOAT_COMPARISON_EPSILON_SECONDS = 1e-9
MAX_DIAGNOSTIC_CHARS = 320


class VerificationError(RuntimeError):
    pass


def load_dependencies() -> tuple[Any, Any, Any, Any, Any]:
    from PIL import Image, ImageDraw
    import cv2
    from rembg import new_session, remove

    return Image, ImageDraw, cv2, new_session, remove


def is_reparse_point(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(path.lstat().st_file_attributes & 0x400)
    except (AttributeError, OSError):
        return path.is_symlink()


def _resolved(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError as error:
        raise VerificationError(f"Could not resolve path: {path}") from error


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def is_reparse_stat(stat_result: os.stat_result) -> bool:
    return stat.S_ISLNK(stat_result.st_mode) or bool(
        getattr(stat_result, "st_file_attributes", 0) & 0x400
    )


def assert_lexical_regular_ancestors(path: Path, label: str) -> Path:
    lexical = lexical_absolute(path)
    current = lexical.parent
    lineage = [current]
    while current.parent != current:
        current = current.parent
        lineage.append(current)
    for ancestor in reversed(lineage):
        try:
            metadata = os.lstat(ancestor)
        except FileNotFoundError as error:
            raise VerificationError(f"{label} ancestor does not exist: {ancestor}") from error
        if is_reparse_stat(metadata):
            raise VerificationError(f"{label} has a reparse-point ancestor: {ancestor}")
        if not stat.S_ISDIR(metadata.st_mode):
            raise VerificationError(f"{label} ancestor is not a directory: {ancestor}")
    return lexical


def resolve_existing_directory(path_text: str, label: str) -> Path:
    lexical = assert_lexical_regular_ancestors(Path(path_text), label)
    path = _resolved(lexical)
    if not path.is_dir() or is_reparse_point(path):
        raise VerificationError(f"{label} is not an existing regular directory: {path}")
    return path


def resolve_contained_path(*, root: Path, candidate: Path, label: str, must_exist: bool) -> Path:
    root_full = _resolved(root)
    candidate_full = _resolved(candidate)
    try:
        candidate_full.relative_to(root_full)
    except ValueError as error:
        raise VerificationError(f"{label} escapes its permitted root") from error
    if must_exist and not candidate_full.exists():
        raise VerificationError(f"{label} does not exist: {candidate_full}")
    if candidate_full.exists() and is_reparse_point(candidate_full):
        raise VerificationError(f"{label} is a reparse point: {candidate_full}")
    return candidate_full


def resolve_regular_file(path_text: str, label: str) -> Path:
    lexical = lexical_absolute(Path(path_text))
    assert_lexical_regular_ancestors(lexical, label)
    path = _resolved(lexical)
    if not path.is_file() or is_reparse_point(path):
        raise VerificationError(f"{label} is not a regular file: {path}")
    return path


def create_private_work_directory(path_text: str) -> Path:
    work_dir = assert_lexical_regular_ancestors(Path(path_text), "work directory")
    try:
        existing = os.lstat(work_dir)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if is_reparse_stat(existing):
            raise VerificationError(f"work directory is a reparse point: {work_dir}")
        raise VerificationError(f"work directory must not already exist: {work_dir}")
    try:
        os.mkdir(work_dir)
    except FileExistsError as error:
        raise VerificationError(f"work directory must not already exist: {work_dir}") from error
    except OSError as error:
        raise VerificationError(f"could not create private work directory: {work_dir}") from error
    metadata = os.lstat(work_dir)
    if not stat.S_ISDIR(metadata.st_mode) or is_reparse_stat(metadata):
        raise VerificationError(f"private work directory is not a regular directory: {work_dir}")
    assert_lexical_regular_ancestors(work_dir, "work directory")
    return work_dir


def new_output_path(work_dir: Path, relative_name: str, label: str) -> Path:
    path = resolve_contained_path(
        root=work_dir,
        candidate=work_dir / relative_name,
        label=label,
        must_exist=False,
    )
    if path.parent != work_dir:
        raise VerificationError(f"{label} must be directly inside the work directory")
    if path.exists() or path.is_symlink():
        raise VerificationError(f"{label} must be a new path: {path}")
    return path


def bounded_text(value: object) -> str:
    text = "" if value is None else str(value)
    return text[:MAX_DIAGNOSTIC_CHARS]


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                shell=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
                capture_output=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        process.kill()


def run_external(arguments: list[str], *, timeout: int = COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            arguments,
            shell=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except OSError as error:
        raise VerificationError(f"Could not start external command: {arguments[0]}") from error
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        terminate_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = error.output, error.stderr
        raise VerificationError(
            f"External command timed out after {timeout} seconds: {arguments[0]}\n"
            f"stdout: {bounded_text(stdout)}\nstderr: {bounded_text(stderr)}"
        ) from None
    if process.returncode != 0:
        raise VerificationError(
            f"External command failed ({process.returncode}): {arguments[0]}\n"
            f"stdout: {bounded_text(stdout)}\nstderr: {bounded_text(stderr)}"
        )
    return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)


def alpha_summary(image: Any) -> dict[str, int]:
    if "A" not in image.getbands():
        raise VerificationError("Image does not have an alpha channel")
    alpha = image.getchannel("A")
    minimum, maximum = alpha.getextrema()
    histogram = alpha.histogram()
    transparent = int(histogram[0])
    opaque = int(histogram[255])
    minimum_pixels = math.ceil(image.width * image.height * 0.05)
    if minimum != 0 or maximum != 255:
        raise VerificationError("Image alpha extrema must be exactly 0 and 255")
    if transparent < minimum_pixels or opaque < minimum_pixels:
        raise VerificationError("Image alpha lacks meaningful transparent and opaque regions")
    return {
        "minimum": int(minimum),
        "maximum": int(maximum),
        "transparentPixels": transparent,
        "opaquePixels": opaque,
    }


def validate_and_normalize_model_alpha(image: Any) -> tuple[Any, dict[str, int]]:
    if "A" not in image.getbands():
        raise VerificationError("Model output does not have an alpha channel")
    alpha = image.getchannel("A")
    histogram = alpha.histogram()
    minimum_pixels = math.ceil(image.width * image.height * 0.05)
    if sum(histogram[:17]) < minimum_pixels:
        raise VerificationError("Model output alpha lacks meaningful low-alpha background region")
    if sum(histogram[128:]) < minimum_pixels:
        raise VerificationError("Model output alpha lacks meaningful high-alpha foreground region")
    normalized = image.convert("RGBA")
    normalized.putalpha(alpha.point([0] * 128 + [255] * 128))
    return normalized, alpha_summary(normalized)


def make_source_image(image_module: Any, image_draw: Any) -> Any:
    image = image_module.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), (250, 247, 240, 255))
    draw = image_draw.Draw(image)
    draw.ellipse((35, 22, 221, 274), fill=(49, 36, 65, 255))
    draw.ellipse((29, 178, 227, 314), fill=(54, 67, 116, 255))
    draw.ellipse((63, 51, 193, 205), fill=(251, 194, 144, 255))
    draw.ellipse((52, 112, 80, 160), fill=(242, 171, 127, 255))
    draw.ellipse((176, 112, 204, 160), fill=(242, 171, 127, 255))
    draw.polygon(
        ((61, 105), (76, 44), (112, 27), (153, 28), (190, 57), (196, 109), (171, 82), (128, 111), (89, 82)),
        fill=(49, 36, 65, 255),
    )
    draw.polygon(((57, 89), (82, 32), (111, 64), (93, 118)), fill=(49, 36, 65, 255))
    draw.polygon(((164, 66), (191, 31), (203, 95), (174, 119)), fill=(49, 36, 65, 255))
    draw.ellipse((84, 119, 108, 145), fill=(38, 29, 49, 255))
    draw.ellipse((148, 119, 172, 145), fill=(38, 29, 49, 255))
    draw.ellipse((92, 126, 99, 134), fill=(247, 245, 240, 255))
    draw.ellipse((156, 126, 163, 134), fill=(247, 245, 240, 255))
    draw.arc((102, 145, 154, 185), 0, 180, fill=(151, 50, 73, 255), width=5)
    draw.polygon(((82, 187), (174, 187), (200, 257), (56, 257)), fill=(199, 83, 111, 255))
    draw.polygon(((116, 187), (140, 187), (151, 222), (128, 239), (105, 222)), fill=(248, 231, 213, 255))
    return image


def compute_opencv_bounds(cv2: Any, source_path: Path) -> list[int]:
    image = cv2.imread(str(source_path), cv2.IMREAD_UNCHANGED)
    if image is None or getattr(image, "shape", ()) != (IMAGE_SIZE, IMAGE_SIZE, 4):
        raise VerificationError("OpenCV did not load a 256x256 four-channel image")
    _, _, _, alpha = cv2.split(image)
    points = cv2.findNonZero(alpha)
    if points is None:
        raise VerificationError("OpenCV found no opaque source pixels")
    x, y, width, height = cv2.boundingRect(points)
    if width <= 0 or height <= 0:
        raise VerificationError("OpenCV produced invalid non-empty bounds")
    return [int(x), int(y), int(width), int(height)]


def read_version(executable: Path) -> str:
    completed = run_external([str(executable), "-version"])
    output = (completed.stdout + "\n" + completed.stderr).strip()
    if not output:
        raise VerificationError(f"Version command produced no output: {executable}")
    return output.splitlines()[0]


def verify_identify(magick: Path, cutout: Path) -> None:
    completed = run_external([str(magick), "identify", "-format", "%w|%h|%[channels]|%[opaque]", str(cutout)])
    fields = [field.strip() for field in completed.stdout.split("|")]
    if (
        len(fields) != 4
        or not all(fields)
        or fields[0:2] != [str(IMAGE_SIZE), str(IMAGE_SIZE)]
    ):
        raise VerificationError(f"ImageMagick reported unexpected cutout dimensions: {completed.stdout!r}")
    if (
        fields[2].casefold() not in ALPHA_CHANNEL_DESCRIPTIONS
        or fields[3].casefold() != "false"
    ):
        raise VerificationError(f"ImageMagick did not preserve cutout alpha: {completed.stdout!r}")


def verify_webp(image_module: Any, cwebp: Path, cutout: Path, output_path: Path) -> dict[str, Any]:
    run_external([str(cwebp), "-lossless", "-exact", str(cutout), "-o", str(output_path)])
    if not output_path.is_file() or is_reparse_point(output_path):
        raise VerificationError("cwebp did not create a regular WebP output")
    with image_module.open(output_path) as image:
        image.load()
        if image.size != (IMAGE_SIZE, IMAGE_SIZE):
            raise VerificationError("Pillow loaded WebP with unexpected dimensions")
        summary = alpha_summary(image.convert("RGBA"))
    return {
        "relativePath": output_path.name,
        "width": IMAGE_SIZE,
        "height": IMAGE_SIZE,
        "hasAlpha": True,
        "alphaMin": summary["minimum"],
        "alphaMax": summary["maximum"],
    }


def frame_fingerprint(image: Any) -> str:
    return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def verify_preview(image_module: Any, image_draw: Any, ffmpeg: Path, ffprobe: Path, cutout: Path, work_dir: Path) -> dict[str, Any]:
    frame_inputs = [new_output_path(work_dir, f"preview-input-{number:02d}.png", "preview input") for number in range(1, 5)]
    with image_module.open(cutout) as source:
        for number, frame_path in enumerate(frame_inputs, start=1):
            frame = source.convert("RGBA")
            draw = image_draw.Draw(frame)
            draw.rectangle((8, 8, 40, 40), fill=(number * 40, 255 - number * 40, 80 + number * 20, 255))
            frame.save(frame_path, format="PNG")
            if not frame_path.is_file() or is_reparse_point(frame_path):
                raise VerificationError("Could not create a regular distinct preview input")
    preview_path = new_output_path(work_dir, "preview.webp", "animated preview")
    run_external(
        [
            str(ffmpeg), "-y", "-framerate", "10", "-start_number", "1", "-i",
            str(work_dir / "preview-input-%02d.png"), "-frames:v", "4", "-c:v", "libwebp",
            "-lossless", "1", "-loop", "0", str(preview_path),
        ]
    )
    if not preview_path.is_file() or is_reparse_point(preview_path):
        raise VerificationError("FFmpeg did not create the animated preview")
    with image_module.open(preview_path) as preview:
        if getattr(preview, "n_frames", 1) != 4:
            raise VerificationError("Pillow did not find exactly four animated preview frames")
        preview_fingerprints: set[str] = set()
        for frame_number in range(4):
            preview.seek(frame_number)
            if preview.size != (IMAGE_SIZE, IMAGE_SIZE):
                raise VerificationError("Animated preview frame has unexpected dimensions")
            preview_fingerprints.add(frame_fingerprint(preview.copy()))
        if len(preview_fingerprints) != 4:
            raise VerificationError("Animated preview frames are not visually distinct")
    extracted_paths = [new_output_path(work_dir, f"preview-extract-{number:02d}.png", "extracted preview") for number in range(1, 5)]
    run_external([str(ffmpeg), "-y", "-i", str(preview_path), "-frames:v", "4", str(work_dir / "preview-extract-%02d.png")])
    extracted_fingerprints: set[str] = set()
    for frame_path in extracted_paths:
        if not frame_path.is_file() or is_reparse_point(frame_path):
            raise VerificationError("FFmpeg did not extract all four regular preview frames")
        with image_module.open(frame_path) as frame:
            if frame.size != (IMAGE_SIZE, IMAGE_SIZE):
                raise VerificationError("Extracted preview frame has unexpected dimensions")
            extracted_fingerprints.add(frame_fingerprint(frame))
    if len(extracted_fingerprints) != 4:
        raise VerificationError("Extracted preview frames are not visually distinct")
    probe = run_external(
        [
            str(ffprobe),
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type,width,height,nb_read_frames:frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(preview_path),
        ]
    )
    try:
        probe_data = json.loads(probe.stdout)
        if type(probe_data) is not dict:
            raise TypeError("ffprobe root must be an object")
        streams = probe_data["streams"]
        frames = probe_data["frames"]
        if type(streams) is not list or type(frames) is not list:
            raise TypeError("ffprobe streams and frames must be arrays")
        if any(type(stream) is not dict for stream in streams):
            raise TypeError("ffprobe stream entries must be objects")
        if any(type(frame) is not dict for frame in frames):
            raise TypeError("ffprobe frame entries must be objects")
        timestamps = [float(frame["best_effort_timestamp_time"]) for frame in frames]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise VerificationError(f"ffprobe returned invalid preview metadata: {bounded_text(probe.stdout)!r}") from error
    matching_streams = [
        stream
        for stream in streams
        if stream.get("codec_type") == "video"
        and stream.get("width") == IMAGE_SIZE
        and stream.get("height") == IMAGE_SIZE
        and str(stream.get("nb_read_frames")) == "4"
    ]
    intervals = [later - earlier for earlier, later in zip(timestamps, timestamps[1:])]
    timing_is_valid = (
        len(timestamps) == 4
        and all(math.isfinite(timestamp) for timestamp in timestamps)
        and abs(timestamps[0])
        <= PREVIEW_TIMING_TOLERANCE_SECONDS + PREVIEW_FLOAT_COMPARISON_EPSILON_SECONDS
        and len(intervals) == 3
        and all(
            abs(interval - PREVIEW_FRAME_INTERVAL_SECONDS)
            <= PREVIEW_TIMING_TOLERANCE_SECONDS + PREVIEW_FLOAT_COMPARISON_EPSILON_SECONDS
            for interval in intervals
        )
    )
    if len(matching_streams) != 1 or not timing_is_valid:
        raise VerificationError("ffprobe did not report four preview frames near 0.4 seconds")
    duration = round(timestamps[-1] - timestamps[0] + PREVIEW_FRAME_INTERVAL_SECONDS, 6)
    return {"frames": 4, "durationSeconds": duration}


def write_result_atomically(result_path: Path, work_dir: Path, result: dict[str, Any]) -> None:
    if result_path.exists() or result_path.is_symlink():
        raise VerificationError("result JSON path must be new")
    temporary = new_output_path(work_dir, f"{result_path.name}.tmp-{uuid.uuid4().hex}", "result JSON temporary path")
    encoded = (json.dumps(result, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if result_path.exists() or result_path.is_symlink():
            raise VerificationError("result JSON path was unexpectedly created")
        os.replace(temporary, result_path)
        if not result_path.is_file() or is_reparse_point(result_path):
            raise VerificationError("result JSON was not published as a regular file")
    finally:
        if temporary.exists() and not is_reparse_point(temporary):
            temporary.unlink()


def verify_media(arguments: argparse.Namespace) -> dict[str, Any]:
    requested_work_dir = assert_lexical_regular_ancestors(
        Path(arguments.work_dir), "work directory"
    )
    result_path = lexical_absolute(Path(arguments.result_json))
    try:
        result_path.relative_to(requested_work_dir)
    except ValueError as error:
        raise VerificationError("result JSON path escapes its permitted root") from error
    if result_path.parent != requested_work_dir:
        raise VerificationError("result JSON path must be directly inside the work directory")
    try:
        result_metadata = os.lstat(result_path)
    except FileNotFoundError:
        result_metadata = None
    if result_metadata is not None:
        if is_reparse_stat(result_metadata):
            raise VerificationError("result JSON path is a reparse point")
        raise VerificationError("result JSON path must be new")
    models_root = resolve_existing_directory(arguments.models_root, "models root")
    work_dir = create_private_work_directory(arguments.work_dir)
    result_path = resolve_contained_path(
        root=work_dir,
        candidate=result_path,
        label="result JSON path",
        must_exist=False,
    )
    model_paths = {
        model_name: resolve_contained_path(
            root=models_root,
            candidate=models_root / f"{model_name}.onnx",
            label=f"model {model_name}",
            must_exist=True,
        )
        for model_name in MODEL_NAMES
    }
    if not all(path.is_file() and not is_reparse_point(path) for path in model_paths.values()):
        raise VerificationError("One or more rembg model files are not regular files")
    ffmpeg = resolve_regular_file(arguments.ffmpeg, "FFmpeg executable")
    ffprobe = resolve_regular_file(arguments.ffprobe, "ffprobe executable")
    magick = resolve_regular_file(arguments.magick, "ImageMagick executable")
    cwebp = resolve_regular_file(arguments.cwebp, "cwebp executable")
    os.environ["U2NET_HOME"] = str(models_root)
    if arguments.numba_cache_dir is None:
        numba_cache_root = work_dir
        numba_cache_candidate = work_dir / "numba-cache"
    else:
        numba_cache_root = resolve_existing_directory(
            work_dir.parent, "verification workspace"
        )
        numba_cache_candidate = lexical_absolute(Path(arguments.numba_cache_dir))
        if (
            numba_cache_candidate.parent != numba_cache_root
            or numba_cache_candidate.name != "n"
        ):
            raise VerificationError(
                "Explicit Numba cache must be the owned workspace sibling"
            )
    numba_cache = resolve_contained_path(
        root=numba_cache_root,
        candidate=numba_cache_candidate,
        label="Numba cache directory",
        must_exist=False,
    )
    if numba_cache.exists():
        raise VerificationError("Numba cache directory must be new")
    os.environ["NUMBA_CACHE_DIR"] = str(numba_cache)

    image_module, image_draw, cv2, new_session, remove = load_dependencies()
    source_path = new_output_path(work_dir, "source.png", "source image")
    source = make_source_image(image_module, image_draw)
    source.save(source_path, format="PNG")
    if not source_path.is_file() or is_reparse_point(source_path):
        raise VerificationError("Could not create the source image inside the work directory")
    bounds = compute_opencv_bounds(cv2, source_path)
    model_results: dict[str, dict[str, Any]] = {}
    cutout_paths: dict[str, Path] = {}
    for model_name in MODEL_NAMES:
        session = new_session(model_name)
        cutout = remove(source, session=session)
        cutout, summary = validate_and_normalize_model_alpha(cutout)
        cutout_path = new_output_path(work_dir, f"cutout-{model_name}.png", f"cutout {model_name}")
        cutout.save(cutout_path, format="PNG")
        if not cutout_path.is_file() or is_reparse_point(cutout_path):
            raise VerificationError(f"rembg did not create a regular cutout: {model_name}")
        cutout_paths[model_name] = cutout_path
        model_results[model_name] = {"relativePath": cutout_path.name, "alpha": summary}
    primary_cutout = cutout_paths["isnet-anime"]
    verify_identify(magick, primary_cutout)
    webp_result = verify_webp(image_module, cwebp, primary_cutout, new_output_path(work_dir, "cutout-isnet-anime.webp", "cutout WebP"))
    preview_result = verify_preview(image_module, image_draw, ffmpeg, ffprobe, primary_cutout, work_dir)
    result = {
        "schemaVersion": 1,
        "tools": {
            "ffmpeg": read_version(ffmpeg), "ffprobe": read_version(ffprobe),
            "magick": read_version(magick), "cwebp": read_version(cwebp),
        },
        "source": {"width": IMAGE_SIZE, "height": IMAGE_SIZE, "opencvBounds": bounds},
        "models": model_results, "webp": webp_result, "preview": preview_result,
    }
    write_result_atomically(result_path, work_dir, result)
    return result


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the isolated pet-media toolchain.")
    parser.add_argument("--models-root", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffprobe", required=True)
    parser.add_argument("--magick", required=True)
    parser.add_argument("--cwebp", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--numba-cache-dir")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = verify_media(parse_arguments(argv))
    except Exception as error:
        print(f"Pet media verification failed: {bounded_text(error)}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
