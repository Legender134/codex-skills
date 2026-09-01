"""Build the bounded synthetic bronze-moth input for the Task 12 dry run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys

from PIL import Image, ImageDraw


SKILL_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = SKILL_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from prepare_pet_run import prepare_pet_run


PROJECT_ID = "bronze-moth"
PACKAGE_ID = "bronzeMoth"
CANVAS = (192, 208)
RUNTIME_HEIGHT_TARGET = 84
BRIEF_RELATIVE_PATH = "evidence/bronze-moth-project-brief.md"
APPROVED_BRIEF_RELATIVE_PATH = "evidence/bronze-moth-approved-original-brief.json"
SOURCES_RELATIVE_PATH = "evidence/bronze-moth-sources.json"
LEDGER_RELATIVE_PATH = "evidence/bronze-moth-ledger.md"
IDENTITY_RELATIVE_PATH = "contracts/bronze-moth-identity.json"
ACTION_DIRECTORY_RELATIVE_PATH = "contracts/bronze-moth-actions"
PACKAGE_DIRECTORY_RELATIVE_PATH = f"package/{PACKAGE_ID}"
CHECKSUM_RELATIVE_PATHS = {
    "builder-stage": "evidence/generated-sha256.json",
    "final-pipeline": "evidence/final-pipeline-sha256.json",
}

_PREPARED_DIRECTORIES = (
    "evidence",
    "contracts",
    "contracts/actions",
    "references",
    "references/selected-sources",
    "frames",
    "package",
    "qa",
    "qa/identity",
    "qa/actions",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", 0) or 0
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
        os.path.abspath(str(right))
    )


def _relative_parts(relative: str) -> tuple[str, ...]:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"unsafe relative path: {relative}")
    return pure.parts


def _path_under_root(root: Path, relative: str) -> Path:
    return root.joinpath(*_relative_parts(relative))


def _unfollowed_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _assert_plain_directory(path: Path, label: str) -> Path:
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise ValueError(f"{label} must be an existing non-link directory: {path}") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or _is_reparse_point(metadata)
    ):
        raise ValueError(f"{label} must be an existing non-link directory: {path}")
    return path


def _assert_direct_directory(root: Path, relative: str) -> Path:
    candidate = _path_under_root(root, relative)
    _assert_plain_directory(candidate, f"prepared directory {relative}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"prepared directory cannot resolve: {relative}") from error
    if not _same_path(resolved, candidate):
        raise ValueError(f"prepared directory does not resolve directly under run root: {relative}")
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"prepared directory escapes run root: {relative}") from error
    return candidate


def _nearest_existing_parent(root: Path, path: Path) -> Path:
    current = path.parent
    while not _unfollowed_exists(current):
        if _same_path(current, root):
            break
        current = current.parent
    if _same_path(current, root):
        _assert_plain_directory(root, "output")
    else:
        try:
            relative = current.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError(f"new leaf escapes run root: {path}") from error
        _assert_direct_directory(root, relative)
    return current


def _assert_new_directory(root: Path, relative: str) -> Path:
    path = _path_under_root(root, relative)
    _nearest_existing_parent(root, path)
    if _unfollowed_exists(path):
        raise FileExistsError(f"synthetic directory already exists: {path}")
    return path


def _assert_new_leaf(root: Path, relative: str) -> Path:
    path = _path_under_root(root, relative)
    _nearest_existing_parent(root, path)
    if _unfollowed_exists(path):
        raise FileExistsError(f"synthetic leaf already exists: {path}")
    return path


def _assert_existing_regular_leaf(root: Path, relative: str) -> Path:
    path = _path_under_root(root, relative)
    _nearest_existing_parent(root, path)
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise ValueError(f"required synthetic leaf is unavailable: {path}") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or path.is_symlink()
        or _is_reparse_point(metadata)
        or metadata.st_nlink != 1
    ):
        raise ValueError(f"required synthetic leaf is not an exclusive regular file: {path}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"required synthetic leaf cannot resolve: {path}") from error
    if not _same_path(resolved, path):
        raise ValueError(f"required synthetic leaf does not resolve directly: {path}")
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"required synthetic leaf escapes run root: {path}") from error
    return path


def _write_new_text(path: Path, contents: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(contents)


def _write_new_json(path: Path, payload: dict[str, object]) -> None:
    _write_new_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )


def _save_new_png(path: Path, image: Image.Image) -> None:
    with path.open("xb") as destination:
        image.save(destination, format="PNG")


def _save_new_webp(path: Path, image: Image.Image) -> None:
    with path.open("xb") as destination:
        image.save(destination, format="WEBP", lossless=True, exact=True)


def _moth_image(wing_lift: int = 0, horizontal_shift: int = 0) -> Image.Image:
    """Return one transparent, original-brand moth pose on the fixed body canvas."""
    image = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    center_x = 96 + horizontal_shift
    wing_top = 89 + wing_lift
    bronze = (176, 105, 45, 255)
    copper = (220, 150, 68, 255)
    outline = (73, 42, 26, 255)
    glow = (255, 215, 126, 230)

    draw.polygon(
        [
            (center_x - 4, 106),
            (center_x - 37, wing_top),
            (center_x - 70, 118),
            (center_x - 37, 151),
            (center_x - 6, 136),
        ],
        fill=bronze,
        outline=outline,
    )
    draw.polygon(
        [
            (center_x + 4, 106),
            (center_x + 37, wing_top),
            (center_x + 70, 118),
            (center_x + 37, 151),
            (center_x + 6, 136),
        ],
        fill=bronze,
        outline=outline,
    )
    draw.polygon(
        [
            (center_x - 3, 117),
            (center_x - 31, 128),
            (center_x - 21, 159),
            (center_x - 3, 148),
        ],
        fill=copper,
        outline=outline,
    )
    draw.polygon(
        [
            (center_x + 3, 117),
            (center_x + 31, 128),
            (center_x + 21, 159),
            (center_x + 3, 148),
        ],
        fill=copper,
        outline=outline,
    )
    draw.ellipse((center_x - 9, 101, center_x + 9, 120), fill=outline)
    draw.ellipse((center_x - 7, 113, center_x + 7, 172), fill=bronze, outline=outline)
    draw.ellipse((center_x - 3, 105, center_x, 109), fill=glow)
    draw.ellipse((center_x + 1, 105, center_x + 4, 109), fill=glow)
    draw.line((center_x - 4, 104, center_x - 18, 91), fill=outline, width=2)
    draw.line((center_x + 4, 104, center_x + 18, 91), fill=outline, width=2)
    return image


def _glow_atlas() -> Image.Image:
    """Create one expanded effect cell that leaves the 192×208 body unchanged."""
    image = Image.new("RGBA", (384, 416), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 24, 372, 404), outline=(255, 196, 92, 140), width=8)
    draw.ellipse((50, 62, 334, 366), fill=(255, 174, 64, 38), outline=(255, 221, 132, 176), width=6)
    draw.ellipse((142, 164, 242, 264), fill=(255, 235, 160, 92))
    for offset in (-110, -55, 55, 110):
        draw.line((192, 214, 192 + offset, 102), fill=(255, 210, 110, 128), width=4)
        draw.line((192, 214, 192 + offset, 326), fill=(255, 210, 110, 128), width=4)
    return image


def _body_atlas(frames: list[Image.Image]) -> Image.Image:
    atlas = Image.new("RGBA", (CANVAS[0], CANVAS[1] * len(frames)), (0, 0, 0, 0))
    for row, frame in enumerate(frames):
        atlas.alpha_composite(frame, (0, row * CANVAS[1]))
    return atlas


def _action_contract(
    action_id: str,
    canonical_sha256: str,
    body_state: str,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "projectId": PROJECT_ID,
        "identityRoute": "original-brand",
        "formatRoute": "v4",
        "status": "draft",
        "selection": "candidate",
        "actionId": action_id,
        "family": "flying-pose",
        "riskClass": "fixture-pilot",
        "identitySha256": canonical_sha256,
        "desktopRole": "synthetic-flight-review",
        "phases": [
            {
                "id": "return",
                "bodyState": body_state,
                "faceState": "moth eye spots remain readable",
                "handState": "not-applicable to winged morphology",
                "hairGarmentState": "wing edges settle at the air anchor",
                "propEffectState": "absent or separated on the effect layer",
                "propLifecycleStage": None,
                "effectLifecycleStage": None,
                "anchor": "body",
                "durationMs": 100,
                "keyPose": True,
            }
        ],
        "worldMotionPhaseIds": [],
        "stableFeatures": ["bronze wings", "dark central body", "air anchor"],
        "allowedChanges": ["wing lift", "flight direction"],
        "forbiddenChanges": ["body scale", "canonical silhouette"],
        "interrupt": {"safePhaseIds": ["return"], "recoveryAction": "hoverIdle"},
        "behavior": {
            "manualEligible": True,
            "autoplayEligible": False,
            "pool": None,
            "weight": None,
            "cooldownMs": None,
            "sharedGroup": None,
            "repeatLimit": None,
            "priority": None,
            "environmentalConditions": [],
            "direction": None,
            "movement": None,
            "cooldownException": None,
        },
    }


def _manifest() -> dict[str, object]:
    body_layer = {
        "atlas": "body",
        "row": 0,
        "startColumn": 0,
        "anchorX": 96,
        "anchorY": 208,
        "hitTest": True,
    }
    return {
        "id": PACKAGE_ID,
        "displayName": "Bronze Moth",
        "description": "Synthetic original-brand flying fixture for a non-installing dry run.",
        "spriteVersionNumber": 4,
        "defaultForm": "defaultForm",
        "iconFrame": {"atlas": "body", "row": 0, "column": 0},
        "atlases": {
            "body": {"path": "body.webp", "cellWidth": 192, "cellHeight": 208},
            "glow": {"path": "glow.webp", "cellWidth": 384, "cellHeight": 416},
        },
        "cooldownGroups": {},
        "actions": {
            "hoverIdle": {
                "label": "Hover idle",
                "role": "idle",
                "frameCount": 1,
                "frameMs": 120,
                "loop": True,
                "layers": [body_layer],
            },
            "flyRight": {
                "label": "Right flight",
                "role": "move",
                "direction": "right",
                "frameCount": 1,
                "frameMs": 100,
                "loop": True,
                "layers": [{**body_layer, "row": 1}],
            },
            "flyLeft": {
                "label": "Left flight",
                "role": "move",
                "direction": "left",
                "frameCount": 1,
                "frameMs": 100,
                "loop": True,
                "layers": [{**body_layer, "row": 2}],
            },
            "glowPulse": {
                "label": "Expanded glow",
                "role": "interaction",
                "frameCount": 1,
                "frameMs": 120,
                "loop": False,
                "layers": [
                    {
                        "atlas": "glow",
                        "row": 0,
                        "startColumn": 0,
                        "anchorX": 192,
                        "anchorY": 416,
                    },
                    body_layer,
                ],
            },
        },
        "forms": {
            "defaultForm": {
                "label": "Bronze moth",
                "idleAction": "hoverIdle",
                "moveRightAction": "flyRight",
                "moveLeftAction": "flyLeft",
                "representativeAction": "hoverIdle",
                "interactionActions": ["glowPulse"],
            }
        },
        "transformations": {},
        "sequences": {},
    }


def _prepared_run_root(output: Path) -> Path:
    if not isinstance(output, Path):
        raise TypeError("output must be pathlib.Path")
    _assert_plain_directory(output, "output")
    try:
        root = output.resolve(strict=True)
    except OSError as error:
        raise ValueError("output must be an existing prepared run directory") from error
    _assert_plain_directory(root, "output")
    for relative in _PREPARED_DIRECTORIES:
        _assert_direct_directory(root, relative)
    return root


def _safe_tree_files(root: Path, self_excluded_path: Path) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    directories = [root]
    index = 0
    while index < len(directories):
        directory = directories[index]
        index += 1
        try:
            directory_relative = directory.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError(f"run directory escapes root: {directory}") from error
        if directory_relative == ".":
            directory_relative = "run root"
        try:
            with os.scandir(directory) as scan:
                entries = sorted(list(scan), key=lambda entry: entry.name)
        except OSError as error:
            raise ValueError(f"cannot scan run directory: {directory_relative}") from error
        for entry in entries:
            if not isinstance(entry.name, str) or entry.name in {"", ".", ".."}:
                raise ValueError(f"run directory has an unsafe entry name: {directory_relative}")
            path = directory / entry.name
            try:
                relative = path.relative_to(root).as_posix()
                metadata = os.lstat(path)
            except (OSError, ValueError) as error:
                raise ValueError(f"cannot stat run entry: {path}") from error
            if stat.S_ISLNK(metadata.st_mode) or _is_reparse_point(metadata):
                raise ValueError(f"run entry must not be a symlink or reparse point: {relative}")
            try:
                resolved = path.resolve(strict=True)
            except OSError as error:
                raise ValueError(f"run entry cannot resolve: {relative}") from error
            if not _same_path(resolved, path):
                raise ValueError(f"run entry does not resolve directly: {relative}")
            try:
                resolved.relative_to(root)
            except ValueError as error:
                raise ValueError(f"run entry escapes run root: {relative}") from error
            if stat.S_ISDIR(metadata.st_mode):
                directories.append(path)
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError(f"run entry must be an exclusive regular file: {relative}")
            if _same_path(path, self_excluded_path):
                continue
            try:
                digest = _sha256(path)
            except OSError as error:
                raise ValueError(f"cannot hash run entry: {relative}") from error
            files.append({"path": relative, "sha256": digest})
    return sorted(files, key=lambda record: record["path"])


def _preflight_existing_run_tree(root: Path) -> None:
    """Reject unsafe prepared entries before any synthetic leaf can be created."""
    _safe_tree_files(root, root / ".synthetic-preflight-never-created")


def write_checksum_manifest(output: Path, manifest_kind: str) -> Path:
    """Create one immutable checksum manifest for the current bounded run stage."""
    if manifest_kind not in CHECKSUM_RELATIVE_PATHS:
        raise ValueError("manifest_kind must be builder-stage or final-pipeline")
    root = _prepared_run_root(output)
    relative = CHECKSUM_RELATIVE_PATHS[manifest_kind]
    checksum_path = _assert_new_leaf(root, relative)
    files = _safe_tree_files(root, checksum_path)
    _write_new_json(
        checksum_path,
        {
            "schemaVersion": 1,
            "projectId": PROJECT_ID,
            "kind": manifest_kind,
            "selfExcludedPath": relative,
            "files": files,
        },
    )
    return checksum_path


def write_synthetic_action_contracts(output: Path) -> list[Path]:
    """Add fixture-only actions after the caller has observed the no-verdict stop."""
    root = _prepared_run_root(output)
    _preflight_existing_run_tree(root)
    identity_path = _assert_existing_regular_leaf(root, IDENTITY_RELATIVE_PATH)
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("synthetic identity contract cannot be read") from error
    canonical_sha256 = identity.get("canonicalSha256")
    if (
        not isinstance(canonical_sha256, str)
        or len(canonical_sha256) != 64
        or any(character not in "0123456789abcdef" for character in canonical_sha256.lower())
    ):
        raise ValueError("synthetic identity contract has no valid canonicalSha256")

    action_directory = _assert_new_directory(root, ACTION_DIRECTORY_RELATIVE_PATH)
    action_specs = [
        ("hoverIdle", "body remains readable at the air anchor"),
        ("flyRight", "wings lift for rightward flight"),
        ("flyLeft", "wings settle for leftward flight"),
        ("glowPulse", "body remains fixed while the glow expands on its own layer"),
    ]
    action_paths = [
        _assert_new_leaf(root, f"{ACTION_DIRECTORY_RELATIVE_PATH}/{action_id}.json")
        for action_id, _ in action_specs
    ]
    action_directory.mkdir()
    _assert_direct_directory(root, ACTION_DIRECTORY_RELATIVE_PATH)
    for path, (action_id, body_state) in zip(action_paths, action_specs, strict=True):
        _write_new_json(path, _action_contract(action_id, canonical_sha256, body_state))
    return action_paths


def build_synthetic_dry_run(output: Path) -> dict[str, object]:
    """Populate one already-prepared run without writing outside ``output``."""
    root = _prepared_run_root(output)
    _preflight_existing_run_tree(root)
    package_root = _assert_new_directory(root, PACKAGE_DIRECTORY_RELATIVE_PATH)
    leaf_paths = {
        relative: _assert_new_leaf(root, relative)
        for relative in (
            BRIEF_RELATIVE_PATH,
            APPROVED_BRIEF_RELATIVE_PATH,
            SOURCES_RELATIVE_PATH,
            LEDGER_RELATIVE_PATH,
            IDENTITY_RELATIVE_PATH,
            "references/selected-sources/approved-original-identity.png",
            "references/selected-sources/approved-original-proportion.png",
            "frames/canonical-identity.png",
            "frames/body-idle.png",
            "frames/body-flight-right.png",
            "frames/body-flight-left.png",
            f"{PACKAGE_DIRECTORY_RELATIVE_PATH}/body.webp",
            f"{PACKAGE_DIRECTORY_RELATIVE_PATH}/glow.webp",
            f"{PACKAGE_DIRECTORY_RELATIVE_PATH}/pet.json",
            f"{PACKAGE_DIRECTORY_RELATIVE_PATH}/source.json",
            CHECKSUM_RELATIVE_PATHS["builder-stage"],
        )
    }
    package_root.mkdir()
    _assert_direct_directory(root, PACKAGE_DIRECTORY_RELATIVE_PATH)

    brief_path = leaf_paths[BRIEF_RELATIVE_PATH]
    _write_new_text(
        brief_path,
        """# Bronze moth synthetic dry-run brief

- Project ID: `bronze-moth`
- Identity route: `original-brand`
- Morphology: `flying`
- Requested format: `v4`
- Runtime-height target: `84` pixels

## Approved original design

The approved original design is a small bronze moth with broad warm-metal wings,
a dark central body, pale eye spots, and a stable air anchor. Identity and
proportion are both governed by this approved brief. The wide glow is a separate
effect layer and must not reduce the body canvas or body occupancy.

## Authority

Installation, integration, commit, push, and publication authority are all `no`.
The next gate is an independent actual-size visual identity verdict.
""",
    )

    canonical = _moth_image()
    identity_reference = _moth_image(wing_lift=-2)
    proportion_reference = _moth_image(wing_lift=2)
    canonical_path = leaf_paths["frames/canonical-identity.png"]
    identity_reference_path = leaf_paths[
        "references/selected-sources/approved-original-identity.png"
    ]
    proportion_reference_path = leaf_paths[
        "references/selected-sources/approved-original-proportion.png"
    ]
    _save_new_png(canonical_path, canonical)
    _save_new_png(identity_reference_path, identity_reference)
    _save_new_png(proportion_reference_path, proportion_reference)

    brief_evidence_path = leaf_paths[APPROVED_BRIEF_RELATIVE_PATH]
    _write_new_json(
        brief_evidence_path,
        {
            "schemaVersion": 1,
            "projectId": PROJECT_ID,
            "approval": "approved-original-design",
            "identityRoute": "original-brand",
            "morphology": "flying",
            "runtimeHeightTarget": RUNTIME_HEIGHT_TARGET,
            "identityReferencePath": identity_reference_path.relative_to(root).as_posix(),
            "identityReferenceSha256": _sha256(identity_reference_path),
            "proportionReferencePath": proportion_reference_path.relative_to(root).as_posix(),
            "proportionReferenceSha256": _sha256(proportion_reference_path),
        },
    )
    source_record = {
        "id": "bronze-moth-approved-brief",
        "roles": ["identity", "proportion"],
        "allowedUses": ["canonical-identity", "canonical-proportion"],
        "evidenceClass": "approved-original-design",
        "approvedFor": ["identity", "proportion"],
        "artifactPath": brief_evidence_path.relative_to(root).as_posix(),
        "artifactSha256": _sha256(brief_evidence_path),
    }
    _write_new_json(
        leaf_paths[SOURCES_RELATIVE_PATH],
        {"schemaVersion": 1, "sources": [source_record]},
    )
    _write_new_text(
        leaf_paths[LEDGER_RELATIVE_PATH],
        """# Bronze moth evidence ledger

`bronze-moth-approved-brief` is an approved original design source. It is the
only source authorized for the `identity` and `proportion` roles in this
synthetic fixture. No visual identity verdict has been recorded.
""",
    )

    canonical_sha256 = _sha256(canonical_path)
    identity_path = leaf_paths[IDENTITY_RELATIVE_PATH]
    _write_new_json(
        identity_path,
        {
            "schemaVersion": 1,
            "projectId": PROJECT_ID,
            "identityRoute": "original-brand",
            "formatRoute": "v4",
            "morphology": "flying",
            "status": "visual-candidate",
            "selection": "candidate",
            "canonicalPath": str(canonical_path),
            "canonicalSha256": canonical_sha256,
            "referenceIds": ["bronze-moth-approved-brief"],
            "features": {
                "runtimeHeightTarget": RUNTIME_HEIGHT_TARGET,
                "identity": "bronze moth with warm metal wings and dark body",
            },
            "measurements": [
                {
                    "feature": "runtime-height",
                    "referenceId": "bronze-moth-approved-brief",
                    "targetRange": [RUNTIME_HEIGHT_TARGET, RUNTIME_HEIGHT_TARGET],
                    "tolerance": 0,
                    "provenance": "APPROVED",
                    "selection": "candidate",
                }
            ],
            "uncertainties": [],
            "technicalStatus": "pass",
            "visualStatus": "not-reviewed",
            "visualVerdictIds": [],
            "identityGateStatus": "visual-candidate",
            "authority": {
                "identityUncertaintyApproved": False,
                "install": False,
                "integrate": False,
                "publish": False,
            },
        },
    )

    body_frames = [
        ("frames/body-idle.png", _moth_image()),
        ("frames/body-flight-right.png", _moth_image(wing_lift=-8, horizontal_shift=4)),
        ("frames/body-flight-left.png", _moth_image(wing_lift=3, horizontal_shift=-4)),
    ]
    body_frame_paths: list[Path] = []
    for relative, frame in body_frames:
        path = leaf_paths[relative]
        _save_new_png(path, frame)
        body_frame_paths.append(path)
    body_atlas = _body_atlas([frame for _, frame in body_frames])
    glow_atlas = _glow_atlas()
    body_atlas_path = leaf_paths[f"{PACKAGE_DIRECTORY_RELATIVE_PATH}/body.webp"]
    glow_atlas_path = leaf_paths[f"{PACKAGE_DIRECTORY_RELATIVE_PATH}/glow.webp"]
    _save_new_webp(body_atlas_path, body_atlas)
    _save_new_webp(glow_atlas_path, glow_atlas)

    _write_new_json(
        leaf_paths[f"{PACKAGE_DIRECTORY_RELATIVE_PATH}/pet.json"], _manifest()
    )
    fixture_source_path = SKILL_ROOT / "tests" / "fixtures" / "v4" / "pet.json"
    runtime_source_path = SKILL_ROOT / "tests" / "fixtures" / "v4" / "source.json"
    runtime_source = json.loads(runtime_source_path.read_text(encoding="utf-8"))
    _write_new_json(
        leaf_paths[f"{PACKAGE_DIRECTORY_RELATIVE_PATH}/source.json"],
        {
            "runtimeCommit": runtime_source["runtimeCommit"],
            "fixture": {
                "path": "tests/fixtures/v4/pet.json",
                "sha256": _sha256(fixture_source_path),
            },
            "schema": runtime_source["source"],
            "derivation": "Reduced body/effect/form/action shape for bronze-moth dry run.",
        },
    )

    checksum_path = write_checksum_manifest(root, "builder-stage")
    return {
        "runRoot": str(root),
        "briefPath": str(brief_path),
        "sourcesPath": str(leaf_paths[SOURCES_RELATIVE_PATH]),
        "ledgerPath": str(leaf_paths[LEDGER_RELATIVE_PATH]),
        "identityContractPath": str(identity_path),
        "canonicalPath": str(canonical_path),
        "identityReferencePath": str(identity_reference_path),
        "proportionReferencePath": str(proportion_reference_path),
        "bodyFramePaths": [str(path) for path in body_frame_paths],
        "bodyAtlasPath": str(body_atlas_path),
        "glowAtlasPath": str(glow_atlas_path),
        "packageRoot": str(package_root),
        "checksumPath": str(checksum_path),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output = args.output
    try:
        if output.name != PROJECT_ID:
            raise ValueError(f"--output must name the synthetic project directory: {PROJECT_ID}")
        if _unfollowed_exists(output):
            raise FileExistsError(f"--output already exists: {output}")
        _assert_plain_directory(output.parent, "--output parent")
        run = prepare_pet_run(output.parent, PROJECT_ID, "original-brand", "v4")
        result = build_synthetic_dry_run(run)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
