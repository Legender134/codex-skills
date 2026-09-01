from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_ROOT))

from format_adapters.base import PackageCheck
from validate_package import detect_format, validate_package


FIXTURE_ROOT = Path(__file__).with_name("fixtures")
RUNTIME_COMMIT = "13222f9814cdac7d2f98b8005a2d601c4946e202"
_ABSOLUTE_WINDOWS_PATH = re.compile(r"(?i)\b[a-z]:[\\/]")
_FORBIDDEN_HOME_PATH = chr(67) + ":" + chr(92) + "Users" + chr(92)


def _environment_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def _runtime_root() -> Path:
    return _environment_path("DESKTOP_COMPANION_RUNTIME_REPO") or (
        Path.home() / "Documents" / "desktop-companion"
    )


def _candidate_runtime_pythons(runtime_root: Path) -> tuple[Path, ...]:
    configured = _environment_path("DESKTOP_COMPANION_RUNTIME_PYTHON")
    if configured is not None:
        return (configured,)
    relative_venvs = (
        (".venv", "Scripts", "python.exe"),
        (".venv", "bin", "python"),
        (".worktrees", "pet-toolchain", ".venv", "Scripts", "python.exe"),
        (".worktrees", "pet-toolchain", ".venv", "bin", "python"),
        (
            ".worktrees",
            "pet-toolchain",
            "work",
            "pet-media-proof",
            "Scripts",
            "python.exe",
        ),
        (
            ".worktrees",
            "pet-toolchain",
            "work",
            "pet-media-proof",
            "bin",
            "python",
        ),
    )
    return tuple(runtime_root.joinpath(*parts) for parts in relative_venvs)


def _find_runtime_schema_python(runtime_root: Path) -> Path | None:
    for candidate in _candidate_runtime_pythons(runtime_root):
        try:
            interpreter = candidate.resolve(strict=True)
            if not interpreter.is_file():
                continue
            completed = subprocess.run(
                [str(interpreter), "-B", "-c", "import jsonschema"],
                shell=False,
                timeout=10,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        if completed.returncode == 0:
            return interpreter
    return None


RUNTIME_ROOT = _runtime_root()
RUNTIME_SCHEMA_PYTHON = _find_runtime_schema_python(RUNTIME_ROOT)
MOCK_RUNTIME_PYTHON = Path(sys.executable).resolve()


def check_codes(report: dict[str, object]) -> set[str]:
    return {
        str(check["code"])
        for check in report["checks"]
        if isinstance(check, dict) and isinstance(check.get("code"), str)
    }


def check_by_code(report: dict[str, object], code: str) -> dict[str, object]:
    for check in report["checks"]:
        if isinstance(check, dict) and check.get("code") == code:
            return check
    raise AssertionError(f"check {code} was not present: {report!r}")


def write_rgba_atlas(path: Path, size: tuple[int, int], cells: list[tuple[int, int, int, int]]) -> None:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    painter = ImageDraw.Draw(image)
    for left, top, right, bottom in cells:
        painter.rectangle(
            (left + 1, top + 1, right - 2, bottom - 2), fill=(29, 122, 211, 255)
        )
    image.save(path, format="WEBP", lossless=True, exact=True)


def manifest_from_fixture(version: int) -> dict[str, object]:
    return json.loads(
        (FIXTURE_ROOT / f"v{version}" / "pet.json").read_text(encoding="utf-8")
    )


def write_manifest(path: Path, manifest: dict[str, object]) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class PackageRouteTest(unittest.TestCase):
    maxDiff = None

    def _create_package(self, raw: Path, version: int) -> Path:
        manifest_bytes = (FIXTURE_ROOT / f"v{version}" / "pet.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        package = raw / str(manifest["id"])
        package.mkdir(parents=True)
        (package / "pet.json").write_bytes(manifest_bytes)
        if version == 2:
            used = (7, 8, 8, 4, 5, 8, 6, 6, 6, 8, 8)
            cells = [
                (column * 192, row * 208, (column + 1) * 192, (row + 1) * 208)
                for row, count in enumerate(used)
                for column in range(count)
            ]
            write_rgba_atlas(package / "spritesheet.webp", (1536, 2288), cells)
        elif version == 3:
            cells = [
                (column * 192, row * 208, (column + 1) * 192, (row + 1) * 208)
                for row, count in ((0, 4), (1, 8), (2, 6), (3, 8))
                for column in range(count)
            ]
            write_rgba_atlas(package / "spritesheet.webp", (1536, 832), cells)
        else:
            character_cells = [
                (column * 192, row * 208, (column + 1) * 192, (row + 1) * 208)
                for row in range(12)
                for column in range(8)
            ]
            effect_cells = [
                (column * 384, 0, (column + 1) * 384, 208)
                for column in range(3)
            ]
            write_rgba_atlas(package / "character.webp", (1536, 2496), character_cells)
            write_rgba_atlas(package / "effects.webp", (1152, 208), effect_cells)
        return package

    def _validate_local(self, package: Path) -> dict[str, object]:
        return validate_package(package, runtime_repo=None, runtime_python=None)

    def _assert_local_candidate(self, report: dict[str, object]) -> None:
        self.assertEqual(report["packageStatus"], "local-candidate")
        self.assertEqual(report["runtimeStatus"], "unverified")
        self.assertEqual(report["installedStatus"], "not-authorized")
        self.assertIs(report["releaseAuthority"], False)

    def _assert_blocked(self, report: dict[str, object], code: str) -> None:
        self.assertEqual(report["status"], "blocked", report)
        self.assertEqual(check_by_code(report, code)["status"], "blocked", report)
        self._assert_local_candidate(report)

    def _assert_runtime_schema_and_registry_accepts(self, package: Path) -> dict[str, object]:
        """Prove a compatibility probe is accepted by both runtime authorities."""

        if RUNTIME_SCHEMA_PYTHON is None:
            self.skipTest("no caller-supplied or repository-relative jsonschema interpreter")
        report = validate_package(
            package,
            runtime_repo=RUNTIME_ROOT,
            runtime_python=RUNTIME_SCHEMA_PYTHON,
        )
        self.assertEqual(
            check_by_code(report, "SCHEMA_VALIDATION")["status"], "pass", report
        )
        registry_program = (
            "import sys;"
            "from pathlib import Path;"
            "sys.path.insert(0,sys.argv[1]);"
            "from shiyi_desktop_pet.pet_registry import PetRegistry;"
            "PetRegistry._load_definition(Path(sys.argv[2]),is_bundled=True)"
        )
        completed = subprocess.run(
            [
                str(RUNTIME_SCHEMA_PYTHON),
                "-B",
                "-c",
                registry_program,
                str(RUNTIME_ROOT / "src"),
                str(package),
            ],
            shell=False,
            timeout=10,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return report

    def _wait_for_child_pid(self, pid_path: Path) -> int:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if pid_path.is_file():
                return int(pid_path.read_text(encoding="ascii"))
            time.sleep(0.01)
        self.fail(f"child did not record a pid at {pid_path}")

    def _windows_pid_is_live(self, pid: int) -> bool:
        if os.name != "nt":
            raise RuntimeError("Windows liveness probe was requested on another platform")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        process = kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not process:
            error = ctypes.get_last_error()
            if error == 87:
                return False
            raise OSError(error, "OpenProcess")
        try:
            wait_result = kernel32.WaitForSingleObject(process, 0)
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                raise OSError(ctypes.get_last_error(), "GetExitCodeProcess")
            if wait_result == 258:
                # The process can exit between the zero-time wait and the exit-code
                # query.  That race is still a confirmed exit, never evidence that
                # a descendant survived.
                return exit_code.value == 259
            if wait_result == 0:
                return False
            raise OSError(ctypes.get_last_error(), "WaitForSingleObject")
        finally:
            kernel32.CloseHandle(process)

    def _windows_handle_count(self) -> int:
        if os.name != "nt":
            raise RuntimeError("Windows handle probe was requested on another platform")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetProcessHandleCount.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.GetProcessHandleCount.restype = wintypes.BOOL
        count = wintypes.DWORD()
        if not kernel32.GetProcessHandleCount(
            kernel32.GetCurrentProcess(), ctypes.byref(count)
        ):
            raise OSError(ctypes.get_last_error(), "GetProcessHandleCount")
        return int(count.value)

    def _assert_pid_stops(self, pid: int, *, timeout_seconds: float = 2) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if os.name == "nt":
                if not self._windows_pid_is_live(pid):
                    return
            else:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return
                except PermissionError:
                    break
                except OSError:
                    return
            time.sleep(0.01)
        self.fail(f"runner left descendant process {pid} alive")

    def test_detect_format_routes_only_exact_integer_versions(self) -> None:
        self.assertEqual(detect_format({"spriteVersionNumber": 2}), 2)
        self.assertEqual(detect_format({"spriteVersionNumber": 3}), 3)
        self.assertEqual(detect_format({"spriteVersionNumber": 4}), 4)
        with self.assertRaisesRegex(ValueError, "spriteVersionNumber"):
            detect_format({"spriteVersionNumber": True})
        with self.assertRaisesRegex(ValueError, "spriteVersionNumber"):
            detect_format({"spriteVersionNumber": 2.0})
        with self.assertRaisesRegex(ValueError, "spriteVersionNumber"):
            detect_format({"spriteVersionNumber": 5})

    def test_fixture_manifests_are_byte_identical_runtime_records(self) -> None:
        expected = {
            2: (
                "src/shiyi_desktop_pet/resources/pets/ziling/pet.json",
                "0d1f144406e4210b3a1687c24ce53de64fa99640328700eb5004430caf441363",
                "schemas/pet-pack-v2.schema.json",
                "2f7de59531f9c689455cfa1ca4a20b417ca8de67c3c8d24700a66ccc13086135",
            ),
            3: (
                "examples/pet-pack-template/pet.json",
                "d15a17227a1b7f227a9a87f2120747fed88ff501540f24d77952d1873a900522",
                "schemas/pet-pack-v3.schema.json",
                "f264b9d02fba4a8033d876d0da98e02467dca07e48bb83a96b4d2399320e1ed8",
            ),
            4: (
                "tests/fixtures/pets/multiformV4/pet.json",
                "b8962a78b5c7e72eda72a1b83469ef197c8b1aa440a09b7067096f8c011e681b",
                "schemas/pet-pack-v4.schema.json",
                "b57647e6a2e489fe6d23ccefad7dc248f314cbedc81023b8f215bf322c942457",
            ),
        }
        for version, (manifest_path, manifest_hash, schema_path, schema_hash) in expected.items():
            with self.subTest(version=version):
                record = json.loads(
                    (FIXTURE_ROOT / f"v{version}" / "source.json").read_text(
                        encoding="utf-8"
                    )
                )
                fixture = FIXTURE_ROOT / f"v{version}" / "pet.json"
                self.assertEqual(record["runtimeCommit"], RUNTIME_COMMIT)
                self.assertEqual(record["source"]["manifestPath"], manifest_path)
                self.assertEqual(record["source"]["manifestSha256"], manifest_hash)
                self.assertEqual(record["source"]["schemaPath"], schema_path)
                self.assertEqual(record["source"]["schemaSha256"], schema_hash)
                self.assertEqual(record["fixture"]["path"], f"tests/fixtures/v{version}/pet.json")
                self.assertEqual(record["fixture"]["sha256"], manifest_hash)
                self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), manifest_hash)
                runtime_manifest = RUNTIME_ROOT / manifest_path
                self.assertEqual(
                    runtime_manifest.read_bytes(), fixture.read_bytes(),
                    "fixture must retain byte-for-byte runtime provenance",
                )
                self.assertEqual(
                    hashlib.sha256(runtime_manifest.read_bytes()).hexdigest(), manifest_hash
                )
                self.assertNotIn(
                    _FORBIDDEN_HOME_PATH, json.dumps(record, ensure_ascii=False)
                )

    def test_task7_text_does_not_persist_machine_specific_paths(self) -> None:
        paths = (
            SCRIPT_ROOT / "format_adapters" / "__init__.py",
            SCRIPT_ROOT / "format_adapters" / "base.py",
            SCRIPT_ROOT / "format_adapters" / "v2.py",
            SCRIPT_ROOT / "format_adapters" / "v3.py",
            SCRIPT_ROOT / "format_adapters" / "v4.py",
            SCRIPT_ROOT / "validate_package.py",
            Path(__file__),
            *(FIXTURE_ROOT / f"v{version}" / filename
              for version in (2, 3, 4)
              for filename in ("pet.json", "source.json")),
        )
        for path in paths:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn(_FORBIDDEN_HOME_PATH, text)
                self.assertIsNone(_ABSOLUTE_WINDOWS_PATH.search(text))

    def test_local_v2_v3_and_v4_routes_pass_deterministic_checks_without_cross_route_errors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            reports = {
                version: self._validate_local(self._create_package(root, version))
                for version in (2, 3, 4)
            }
        for version, report in reports.items():
            with self.subTest(version=version):
                self.assertEqual(report["formatVersion"], version, report)
                self.assertEqual(report["status"], "unverified", report)
                self._assert_local_candidate(report)
                self.assertTrue(
                    all(
                        check["status"] in {"pass", "unverified"}
                        for check in report["checks"]
                        if isinstance(check, dict)
                    ),
                    report,
                )
        self.assertFalse(any(code.startswith("V2_") for code in check_codes(reports[3])))
        self.assertFalse(any(code.startswith("V2_") for code in check_codes(reports[4])))
        self.assertFalse(any(code.startswith("V4_") for code in check_codes(reports[2])))
        self.assertFalse(any(code.startswith("V4_") for code in check_codes(reports[3])))

    def test_v2_wrong_fixed_atlas_is_blocked_without_affecting_v3_route(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            v2 = self._create_package(root, 2)
            write_rgba_atlas(v2 / "spritesheet.webp", (192, 208), [(0, 0, 192, 208)])
            blocked = self._validate_local(v2)
            self._assert_blocked(blocked, "V2_ATLAS_DIMENSIONS")

    def test_authority_absence_is_unverified_and_cannot_grant_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = self._validate_local(self._create_package(Path(raw), 2))
        schema = check_by_code(report, "SCHEMA_VALIDATION")
        self.assertEqual(schema["status"], "unverified", report)
        self.assertEqual(report["status"], "unverified", report)

    def test_authoritative_schema_records_runtime_commit_and_schema_provenance(self) -> None:
        if RUNTIME_SCHEMA_PYTHON is None:
            self.skipTest("no caller-supplied or repository-relative jsonschema interpreter")
        before = subprocess.run(
            ["git", "-C", str(RUNTIME_ROOT), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        with tempfile.TemporaryDirectory() as raw:
            reports = {
                version: validate_package(
                    self._create_package(Path(raw), version),
                    runtime_repo=RUNTIME_ROOT,
                    runtime_python=RUNTIME_SCHEMA_PYTHON,
                )
                for version in (2, 3, 4)
            }
        after = subprocess.run(
            ["git", "-C", str(RUNTIME_ROOT), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(before, after)
        for version, report in reports.items():
            with self.subTest(version=version):
                self.assertEqual(report["status"], "pass", report)
                schema = check_by_code(report, "SCHEMA_VALIDATION")
                self.assertEqual(schema["status"], "pass", report)
                self.assertEqual(
                    schema["evidence"]["schemaPath"],
                    f"schemas/pet-pack-v{version}.schema.json",
                )
                self.assertEqual(schema["evidence"]["runtimeCommit"], RUNTIME_COMMIT)
                self._assert_local_candidate(report)

    def test_package_check_is_frozen_and_reports_are_mutation_safe(self) -> None:
        check = PackageCheck("CHECK", "pass", "ok", {"nested": ["value"]})
        with self.assertRaises(FrozenInstanceError):
            check.status = "blocked"  # type: ignore[misc]
        serialized = check.to_dict()
        serialized["evidence"]["nested"].append("changed")
        self.assertEqual(check.to_dict()["evidence"], {"nested": ["value"]})
        with tempfile.TemporaryDirectory() as raw:
            package = self._create_package(Path(raw), 3)
            first = self._validate_local(package)
            first["checks"][0]["evidence"]["mutated"] = True
            second = self._validate_local(package)
        self.assertNotIn("mutated", second["checks"][0]["evidence"])

    def test_untrusted_manifest_syntax_and_structure_become_blocked_checks(self) -> None:
        cases = {
            "duplicate": (
                b'{"id":"ziling","id":"other","displayName":"x",'
                b'"spriteVersionNumber":2,"spritesheetPath":"spritesheet.webp"}',
                "MANIFEST_JSON_DUPLICATE_KEY",
            ),
            "constant": (
                b'{"id":"ziling","displayName":"x",'
                b'"spriteVersionNumber":NaN,"spritesheetPath":"spritesheet.webp"}',
                "MANIFEST_JSON_NONSTANDARD_NUMBER",
            ),
            "unicode": (
                b'{"id":"\xed\xa0\x80","displayName":"x",'
                b'"spriteVersionNumber":2,"spritesheetPath":"spritesheet.webp"}',
                "MANIFEST_JSON_INVALID_UNICODE",
            ),
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for name, (payload, code) in cases.items():
                with self.subTest(name=name):
                    package = self._create_package(root / name, 2)
                    (package / "pet.json").write_bytes(payload)
                    self._assert_blocked(self._validate_local(package), code)
            package = self._create_package(root / "nested", 2)
            deeply_nested: object = "leaf"
            for _ in range(130):
                deeply_nested = [deeply_nested]
            payload = {
                "id": "ziling",
                "displayName": "x",
                "spriteVersionNumber": 2,
                "spritesheetPath": "spritesheet.webp",
                "unexpected": deeply_nested,
            }
            write_manifest(package / "pet.json", payload)
            self._assert_blocked(
                self._validate_local(package), "MANIFEST_JSON_STRUCTURE_INVALID"
            )

    def test_duplicate_invalid_unicode_key_is_a_blocked_check_not_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self._create_package(Path(raw), 2)
            (package / "pet.json").write_bytes(
                b'{"\\ud800":1,"\\ud800":2}'
            )
            self._assert_blocked(
                self._validate_local(package), "MANIFEST_JSON_DUPLICATE_KEY"
            )

    def test_referenced_paths_cannot_escape_or_link_outside_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            package = self._create_package(root, 3)
            manifest = manifest_from_fixture(3)
            manifest["spritesheetPath"] = "../outside.webp"
            write_manifest(package / "pet.json", manifest)
            self._assert_blocked(self._validate_local(package), "PACKAGE_PATH_INVALID")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            package = self._create_package(root, 3)
            manifest = manifest_from_fixture(3)
            manifest["spritesheetPath"] = "spritesheet.webp:alternate"
            write_manifest(package / "pet.json", manifest)
            self._assert_blocked(self._validate_local(package), "PACKAGE_PATH_INVALID")

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            package = self._create_package(root, 3)
            outside = root / "outside.webp"
            write_rgba_atlas(outside, (192, 208), [(0, 0, 192, 208)])
            (package / "spritesheet.webp").unlink()
            try:
                (package / "spritesheet.webp").symlink_to(outside)
            except OSError:
                self.skipTest("host does not permit symlink fixtures")
            self._assert_blocked(self._validate_local(package), "PACKAGE_PATH_INVALID")

    def test_missing_empty_alpha_oversized_and_out_of_bounds_images_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            missing = self._create_package(root / "missing", 3)
            (missing / "spritesheet.webp").unlink()
            self._assert_blocked(self._validate_local(missing), "PACKAGE_FILE_MISSING")

            empty = self._create_package(root / "empty", 3)
            write_rgba_atlas(empty / "spritesheet.webp", (1536, 832), [])
            self._assert_blocked(self._validate_local(empty), "PACKAGE_IMAGE_EMPTY_ALPHA")

            oversized = self._create_package(root / "oversized", 3)
            write_rgba_atlas(oversized / "spritesheet.webp", (4097, 4097), [])
            self._assert_blocked(
                self._validate_local(oversized), "PACKAGE_IMAGE_PIXELS_LIMIT"
            )

            out_of_bounds = self._create_package(root / "out-of-bounds", 3)
            manifest = manifest_from_fixture(3)
            manifest["actions"]["idle"]["row"] = 4
            write_manifest(out_of_bounds / "pet.json", manifest)
            self._assert_blocked(
                self._validate_local(out_of_bounds), "V3_CELL_OUT_OF_BOUNDS"
            )

    def test_v2_checks_id_required_cells_and_fixed_only_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            id_mismatch = self._create_package(root / "id", 2)
            manifest = manifest_from_fixture(2)
            manifest["id"] = "different"
            write_manifest(id_mismatch / "pet.json", manifest)
            self._assert_blocked(self._validate_local(id_mismatch), "PACKAGE_ID_MISMATCH")

            missing_cell = self._create_package(root / "cell", 2)
            write_rgba_atlas(
                missing_cell / "spritesheet.webp", (1536, 2288), [(0, 0, 192, 208)]
            )
            self._assert_blocked(
                self._validate_local(missing_cell), "V2_REQUIRED_CELL_EMPTY"
            )

    def test_v2_states_are_rejected_even_when_authoritative_schema_accepts_them(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self._create_package(Path(raw), 2)
            manifest = manifest_from_fixture(2)
            manifest["states"] = {}
            write_manifest(package / "pet.json", manifest)

            self._assert_blocked(self._validate_local(package), "V2_STATES_UNSUPPORTED")

            if RUNTIME_SCHEMA_PYTHON is None:
                self.skipTest("no caller-supplied or repository-relative jsonschema interpreter")
            authoritative = validate_package(
                package,
                runtime_repo=RUNTIME_ROOT,
                runtime_python=RUNTIME_SCHEMA_PYTHON,
            )

        self.assertEqual(
            check_by_code(authoritative, "SCHEMA_VALIDATION")["status"], "pass", authoritative
        )
        self._assert_blocked(authoritative, "V2_STATES_UNSUPPORTED")

    def test_v3_checks_capabilities_mirroring_and_dynamic_mapping_without_v2_grid_rules(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            no_interaction = self._create_package(root / "no-interaction", 3)
            manifest = manifest_from_fixture(3)
            del manifest["actions"]["greet"]
            write_manifest(no_interaction / "pet.json", manifest)
            report = self._validate_local(no_interaction)
            self._assert_blocked(report, "V3_INTERACTION_REQUIRED")
            self.assertFalse(any(code.startswith("V2_") for code in check_codes(report)))

            invalid_mirror = self._create_package(root / "mirror", 3)
            manifest = manifest_from_fixture(3)
            manifest["actions"]["moveLeft"]["mirrorOf"] = "moveLeft"
            write_manifest(invalid_mirror / "pet.json", manifest)
            self._assert_blocked(
                self._validate_local(invalid_mirror), "V3_MIRROR_INVALID"
            )

            bad_durations = self._create_package(root / "durations", 3)
            manifest = manifest_from_fixture(3)
            action = manifest["actions"]["idle"]
            del action["frameMs"]
            action["frameDurations"] = [120]
            write_manifest(bad_durations / "pet.json", manifest)
            self._assert_blocked(
                self._validate_local(bad_durations), "V3_FRAME_DURATIONS_INVALID"
            )

    def test_v3_and_v4_allow_nondirectional_direct_interaction_mirrors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            v3 = self._create_package(root / "v3", 3)
            v3_manifest = manifest_from_fixture(3)
            v3_manifest["actions"]["greetMirror"] = {
                "label": "Mirrored greeting",
                "role": "interaction",
                "mirrorOf": "greet",
            }
            write_manifest(v3 / "pet.json", v3_manifest)
            v3_report = self._assert_runtime_schema_and_registry_accepts(v3)

            v4 = self._create_package(root / "v4", 4)
            v4_manifest = manifest_from_fixture(4)
            v4_manifest["actions"]["wideSpellMirror"] = {
                **v4_manifest["actions"]["wideSpell"],
                "label": "Mirrored wide spell",
                "mirrorOf": "wideSpell",
            }
            write_manifest(v4 / "pet.json", v4_manifest)
            v4_report = self._assert_runtime_schema_and_registry_accepts(v4)

        self.assertEqual(v3_report["status"], "pass", v3_report)
        self.assertEqual(v4_report["status"], "pass", v4_report)

    def test_v3_and_v4_reject_mixed_same_chained_missing_and_cross_role_mirrors(self) -> None:
        def v3_manifest_with_mirror(entry: dict[str, object]) -> dict[str, object]:
            manifest = manifest_from_fixture(3)
            manifest["actions"]["probeMirror"] = entry
            return manifest

        def v4_manifest_with_mirror(entry: dict[str, object]) -> dict[str, object]:
            manifest = manifest_from_fixture(4)
            manifest["actions"]["probeMirror"] = entry
            return manifest

        v3_cases = {
            "mixed": v3_manifest_with_mirror(
                {
                    "label": "Mixed mirror",
                    "role": "interaction",
                    "direction": "left",
                    "mirrorOf": "greet",
                }
            ),
            "same": v3_manifest_with_mirror(
                {
                    "label": "Same-direction mirror",
                    "role": "move",
                    "direction": "right",
                    "mirrorOf": "moveRight",
                }
            ),
            "missing": v3_manifest_with_mirror(
                {
                    "label": "Missing mirror",
                    "role": "interaction",
                    "mirrorOf": "noSuchAction",
                }
            ),
            "cross-role": v3_manifest_with_mirror(
                {
                    "label": "Cross-role mirror",
                    "role": "gaze",
                    "mirrorOf": "greet",
                }
            ),
        }
        v3_chain = manifest_from_fixture(3)
        v3_chain["actions"]["firstMirror"] = {
            "label": "First mirror",
            "role": "interaction",
            "mirrorOf": "greet",
        }
        v3_chain["actions"]["secondMirror"] = {
            "label": "Second mirror",
            "role": "interaction",
            "mirrorOf": "firstMirror",
        }
        v3_cases["chain"] = v3_chain

        wide_spell = manifest_from_fixture(4)["actions"]["wideSpell"]
        v4_cases = {
            "mixed": v4_manifest_with_mirror(
                {**wide_spell, "label": "Mixed mirror", "direction": "left", "mirrorOf": "wideSpell"}
            ),
            "same": v4_manifest_with_mirror(
                {
                    **manifest_from_fixture(4)["actions"]["humanMoveRight"],
                    "label": "Same-direction mirror",
                    "mirrorOf": "humanMoveRight",
                }
            ),
            "missing": v4_manifest_with_mirror(
                {**wide_spell, "label": "Missing mirror", "mirrorOf": "noSuchAction"}
            ),
            "cross-role": v4_manifest_with_mirror(
                {
                    **manifest_from_fixture(4)["actions"]["humanIdle"],
                    "label": "Cross-role mirror",
                    "role": "interaction",
                    "loop": False,
                    "mirrorOf": "humanIdle",
                }
            ),
        }
        v4_chain = manifest_from_fixture(4)
        v4_chain["actions"]["firstMirror"] = {
            **wide_spell,
            "label": "First mirror",
            "mirrorOf": "wideSpell",
        }
        v4_chain["actions"]["secondMirror"] = {
            **wide_spell,
            "label": "Second mirror",
            "mirrorOf": "firstMirror",
        }
        v4_cases["chain"] = v4_chain

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for route, cases, version in (("v3", v3_cases, 3), ("v4", v4_cases, 4)):
                for name, manifest in cases.items():
                    with self.subTest(route=route, name=name):
                        package = self._create_package(root / route / name, version)
                        write_manifest(package / "pet.json", manifest)
                        expected = (
                            "V3_ACTION_INVALID"
                            if route == "v3" and name == "mixed"
                            else "V4_ACTIONS_INVALID"
                            if route == "v4" and name == "mixed"
                            else f"V{version}_MIRROR_INVALID"
                        )
                        self._assert_blocked(self._validate_local(package), expected)

    def test_v3_and_v4_omitted_burst_end_uses_explicit_start(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            v3 = self._create_package(root / "v3", 3)
            v3_manifest = manifest_from_fixture(3)
            v3_manifest["actions"]["dashRight"]["travelStartFrame"] = 6
            del v3_manifest["actions"]["dashRight"]["travelEndFrame"]
            write_manifest(v3 / "pet.json", v3_manifest)
            v3_report = self._validate_local(v3)

            v4 = self._create_package(root / "v4", 4)
            v4_manifest = manifest_from_fixture(4)
            v4_manifest["actions"]["humanBurstRight"] = {
                "label": "Burst right",
                "role": "burstMove",
                "direction": "right",
                "frameCount": 8,
                "frameMs": 90,
                "repeatCount": 1,
                "travelStartFrame": 6,
                "layers": [
                    {
                        "atlas": "character",
                        "row": 3,
                        "startColumn": 0,
                        "anchorX": 96,
                        "anchorY": 208,
                        "hitTest": True,
                    }
                ],
            }
            write_manifest(v4 / "pet.json", v4_manifest)
            v4_report = self._validate_local(v4)

            invalid_v3 = self._create_package(root / "invalid-v3", 3)
            invalid_v3_manifest = manifest_from_fixture(3)
            invalid_v3_manifest["actions"]["dashRight"]["travelStartFrame"] = 6
            invalid_v3_manifest["actions"]["dashRight"]["travelEndFrame"] = 6
            write_manifest(invalid_v3 / "pet.json", invalid_v3_manifest)
            invalid_v3_report = self._validate_local(invalid_v3)

            invalid_v4 = self._create_package(root / "invalid-v4", 4)
            invalid_v4_manifest = manifest_from_fixture(4)
            invalid_v4_manifest["actions"]["humanBurstRight"] = {
                "label": "Burst right",
                "role": "burstMove",
                "direction": "right",
                "frameCount": 8,
                "frameMs": 90,
                "repeatCount": 1,
                "travelStartFrame": 6,
                "travelEndFrame": 6,
                "layers": [
                    {
                        "atlas": "character",
                        "row": 3,
                        "startColumn": 0,
                        "anchorX": 96,
                        "anchorY": 208,
                        "hitTest": True,
                    }
                ],
            }
            write_manifest(invalid_v4 / "pet.json", invalid_v4_manifest)
            invalid_v4_report = self._validate_local(invalid_v4)

        for version, report, blocked_code in (
            (3, v3_report, "V3_ACTION_INVALID"),
            (4, v4_report, "V4_ACTIONS_INVALID"),
        ):
            with self.subTest(version=version):
                self.assertNotIn(blocked_code, check_codes(report), report)
                self.assertEqual(report["status"], "unverified", report)
                self._assert_local_candidate(report)
        self._assert_blocked(invalid_v3_report, "V3_ACTION_INVALID")
        self._assert_blocked(invalid_v4_report, "V4_ACTIONS_INVALID")

    def test_v3_state_action_visibility_and_autoplay_match_runtime_rules(self) -> None:
        def state_manifest() -> dict[str, object]:
            manifest = manifest_from_fixture(3)
            actions = manifest["actions"]
            actions.update(
                {
                    "stateEnter": {
                        "label": "State enter",
                        "role": "interaction",
                        "row": 3,
                        "startColumn": 0,
                        "frameCount": 1,
                        "frameMs": 100,
                        "showInMenu": True,
                        "autoplayWeight": 0,
                    },
                    "stateResidentOne": {
                        "label": "State resident one",
                        "role": "interaction",
                        "row": 3,
                        "startColumn": 1,
                        "frameCount": 1,
                        "frameMs": 100,
                        "showInMenu": False,
                        "autoplayWeight": 0,
                    },
                    "stateResidentTwo": {
                        "label": "State resident two",
                        "role": "interaction",
                        "row": 3,
                        "startColumn": 2,
                        "frameCount": 1,
                        "frameMs": 100,
                        "showInMenu": False,
                        "autoplayWeight": 0,
                    },
                    "stateExit": {
                        "label": "State exit",
                        "role": "interaction",
                        "row": 3,
                        "startColumn": 3,
                        "frameCount": 1,
                        "frameMs": 100,
                        "showInMenu": False,
                        "autoplayWeight": 0,
                    },
                }
            )
            manifest["states"] = {
                "focused": {
                    "label": "Focused",
                    "enterAction": "stateEnter",
                    "residentActions": [
                        {"action": "stateResidentOne", "weight": 50},
                        {"action": "stateResidentTwo", "weight": 50},
                    ],
                    "exitAction": "stateExit",
                    "minDurationMs": 5000,
                    "rampDurationMs": 0,
                    "maxDurationMs": 10000,
                    "exitChanceAfterMin": 0,
                    "exitChanceAfterRamp": 100,
                }
            }
            return manifest

        cases = (
            ("resident-visible", "stateResidentOne", "showInMenu", True),
            ("resident-autoplay", "stateResidentOne", "autoplayWeight", 1),
            ("exit-visible", "stateExit", "showInMenu", True),
            ("exit-autoplay", "stateExit", "autoplayWeight", 1),
            ("enter-hidden-inert", "stateEnter", "showInMenu", False),
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            valid = self._create_package(root / "valid", 3)
            write_manifest(valid / "pet.json", state_manifest())
            valid_report = self._validate_local(valid)
            self.assertEqual(valid_report["status"], "unverified", valid_report)
            for case, action, field, value in cases:
                with self.subTest(case=case):
                    package = self._create_package(root / case, 3)
                    manifest = state_manifest()
                    manifest["actions"][action][field] = value
                    if case == "enter-hidden-inert":
                        manifest["actions"][action]["autoplayWeight"] = 0
                    write_manifest(package / "pet.json", manifest)
                    self._assert_blocked(
                        self._validate_local(package), "V3_STATES_INVALID"
                    )
            for action in ("stateEnter", "stateResidentOne", "stateExit"):
                with self.subTest(non_interaction_role=action):
                    package = self._create_package(root / f"role-{action}", 3)
                    manifest = state_manifest()
                    manifest["actions"][action]["role"] = "move"
                    manifest["actions"][action]["direction"] = "right"
                    write_manifest(package / "pet.json", manifest)
                    self._assert_blocked(
                        self._validate_local(package), "V3_STATES_INVALID"
                    )

    def test_asset_snapshot_rejects_replacement_between_metadata_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self._create_package(Path(raw), 3)
            asset_path = package / "spritesheet.webp"
            replacement = package / "replacement.webp"
            cells = [
                (column * 192, row * 208, (column + 1) * 192, (row + 1) * 208)
                for row, count in ((0, 4), (1, 8), (2, 6), (3, 8))
                for column in range(count)
            ]
            write_rgba_atlas(replacement, (1536, 832), cells)
            original_open = Path.open
            swapped = False

            def swap_before_open(path: Path, *args: object, **kwargs: object):
                nonlocal swapped
                if path == asset_path and args and args[0] == "rb" and not swapped:
                    swapped = True
                    os.replace(replacement, asset_path)
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", new=swap_before_open):
                report = self._validate_local(package)

        self.assertTrue(swapped)
        self._assert_blocked(report, "PACKAGE_FILE_CHANGED")

    def test_v4_preflight_rejects_aggregate_before_any_full_decode(self) -> None:
        import format_adapters.v4 as v4_adapter

        with tempfile.TemporaryDirectory() as raw:
            package = self._create_package(Path(raw), 4)
            manifest = manifest_from_fixture(4)
            for atlas_key in ("extraOne", "extraTwo"):
                manifest["atlases"][atlas_key] = {
                    "path": f"{atlas_key}.webp",
                    "cellWidth": 192,
                    "cellHeight": 208,
                }
                write_rgba_atlas(package / f"{atlas_key}.webp", (192, 208), [(0, 0, 192, 208)])
            write_manifest(package / "pet.json", manifest)
            ordinal = 0

            def oversized_snapshot(*args: object, **kwargs: object):
                nonlocal ordinal
                ordinal += 1
                return type(
                    "Snapshot",
                    (),
                    {
                        "path": package / f"snapshot-{ordinal}.webp",
                        "identity": (ordinal, ordinal, 1, 1),
                        "encoded": b"x",
                        "sha256": str(ordinal),
                        "width": 4224,
                        "height": 3120,
                    },
                )()

            with patch.object(v4_adapter, "snapshot_webp", side_effect=oversized_snapshot), patch.object(
                v4_adapter,
                "decode_snapshot_rgba",
                side_effect=AssertionError("aggregate preflight decoded an atlas"),
            ) as decode:
                report = self._validate_local(package)

        self._assert_blocked(report, "V4_ATLAS_PIXELS_LIMIT")
        self.assertEqual(decode.call_count, 0)

    def test_v4_rejects_hard_linked_atlas_identities(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self._create_package(Path(raw), 4)
            effects = package / "effects.webp"
            effects.unlink()
            try:
                os.link(package / "character.webp", effects)
            except OSError as error:
                self.fail(f"host must support the required hard-link regression: {error}")
            report = self._validate_local(package)
        self._assert_blocked(report, "V4_ATLAS_PATH")

    def test_windows_liveness_probe_rejects_legacy_os_kill_zero_false_exit(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-specific process liveness contract")
        probe = subprocess.Popen(
            [str(MOCK_RUNTIME_PYTHON), "-B", "-c", "import time; time.sleep(30)"],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid = probe.pid
        try:
            self.assertTrue(self._windows_pid_is_live(pid))
            # The former helper treated every non-PermissionError OSError from
            # os.kill(pid, 0) as an exited process.  Some supported Windows Python
            # builds return normally here, so exercise that old broad-error branch
            # deterministically while the native probe proves this exact PID lives.
            def legacy_os_kill_liveness(target_pid: int) -> bool:
                try:
                    os.kill(target_pid, 0)
                except ProcessLookupError:
                    return False
                except PermissionError:
                    return True
                except OSError:
                    return False
                return True

            with patch("os.kill", side_effect=OSError(87, "legacy probe failure")):
                self.assertFalse(legacy_os_kill_liveness(pid))
            with self.assertRaisesRegex(AssertionError, "left descendant process"):
                self._assert_pid_stops(pid, timeout_seconds=0.05)
        finally:
            if probe.poll() is None:
                probe.terminate()
            try:
                probe.wait(timeout=2)
            except subprocess.TimeoutExpired:
                probe.kill()
                probe.wait(timeout=2)
        self.assertFalse(self._windows_pid_is_live(pid))

    def test_windows_suspended_job_ownership_runs_only_after_resume(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-specific suspended Job ownership contract")
        import format_adapters.base as adapter_base

        runner = getattr(adapter_base, "_run_bounded_process")
        original_resume = getattr(adapter_base, "_resume_suspended_windows_process", None)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sentinel = root / "command-ran"
            child_pid = root / "child.pid"
            observed_before_resume: list[tuple[bool, bool]] = []

            def observe_resume(process: object) -> bool:
                observed_before_resume.append((sentinel.exists(), child_pid.exists()))
                return bool(original_resume and original_resume(process))

            with patch(
                "format_adapters.base._resume_suspended_windows_process",
                create=True,
                side_effect=observe_resume,
            ):
                result = runner(
                    [
                        str(MOCK_RUNTIME_PYTHON),
                        "-B",
                        "-c",
                        "from pathlib import Path;import sys;Path(sys.argv[1]).write_text('owned',encoding='ascii')",
                        str(sentinel),
                    ],
                    timeout_seconds=2,
                    output_limit=4096,
                )

            self.assertEqual(observed_before_resume, [(False, False)])
            self.assertEqual(result.returncode, 0)
            self.assertFalse(result.spawn_failed)
            self.assertTrue(sentinel.is_file())
            self.assertFalse(child_pid.exists())

    def test_windows_suspended_assignment_failure_never_runs_parent_or_child(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-specific suspended Job ownership contract")
        import format_adapters.base as adapter_base

        runner = getattr(adapter_base, "_run_bounded_process")
        real_popen = adapter_base.subprocess.Popen
        created: list[subprocess.Popen[bytes]] = []

        def capture_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
            process = real_popen(*args, **kwargs)
            created.append(process)
            return process

        child_program = (
            "from pathlib import Path\n"
            "import os,sys,time\n"
            "Path(sys.argv[1]).write_text(str(os.getpid()),encoding='ascii')\n"
            "while not Path(sys.argv[2]).exists():\n"
            "    time.sleep(0.01)\n"
        )
        parent_program = (
            "from pathlib import Path\n"
            "import subprocess,sys,time\n"
            "sentinel=Path(sys.argv[1])\n"
            "pid_path=Path(sys.argv[2])\n"
            "stop_path=Path(sys.argv[3])\n"
            "sentinel.write_text('ran',encoding='ascii')\n"
            "subprocess.Popen([sys.executable,'-B','-c',sys.argv[4],str(pid_path),str(stop_path)],stdout=sys.stdout,stderr=sys.stderr)\n"
            "while not stop_path.exists():\n"
            "    time.sleep(0.01)\n"
        )
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sentinel = root / "command-ran"
            pid_path = root / "child.pid"
            stop_path = root / "stop"

            def delayed_assignment_failure(_process: object) -> None:
                deadline = time.monotonic() + 0.75
                while time.monotonic() < deadline:
                    if sentinel.is_file() and pid_path.is_file():
                        break
                    time.sleep(0.01)
                return None

            try:
                with patch(
                    "format_adapters.base.subprocess.Popen",
                    side_effect=capture_popen,
                ), patch(
                    "format_adapters.base._assign_windows_job",
                    side_effect=delayed_assignment_failure,
                ):
                    result = runner(
                        [
                            str(MOCK_RUNTIME_PYTHON),
                            "-B",
                            "-c",
                            parent_program,
                            str(sentinel),
                            str(pid_path),
                            str(stop_path),
                            child_program,
                        ],
                        timeout_seconds=2,
                        output_limit=4096,
                    )
            finally:
                stop_path.write_text("stop", encoding="ascii")
                if pid_path.is_file():
                    self._assert_pid_stops(
                        int(pid_path.read_text(encoding="ascii"))
                    )

            self.assertTrue(result.spawn_failed)
            self.assertFalse(sentinel.exists())
            self.assertFalse(pid_path.exists())
            self.assertEqual(len(created), 1)
            self.assertFalse(self._windows_pid_is_live(created[0].pid))

    def test_windows_suspended_resume_failure_reaps_owned_process(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-specific suspended Job ownership contract")
        import format_adapters.base as adapter_base

        runner = getattr(adapter_base, "_run_bounded_process")
        real_popen = adapter_base.subprocess.Popen
        original_terminate_job = adapter_base._terminate_windows_job
        created: list[subprocess.Popen[bytes]] = []
        terminated_jobs: list[int] = []

        def capture_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
            process = real_popen(*args, **kwargs)
            created.append(process)
            return process

        def record_terminate_job(job_handle: int) -> bool:
            terminated_jobs.append(job_handle)
            return original_terminate_job(job_handle)

        with tempfile.TemporaryDirectory() as raw:
            sentinel = Path(raw) / "command-ran"
            with patch(
                "format_adapters.base.subprocess.Popen",
                side_effect=capture_popen,
            ), patch(
                "format_adapters.base._resume_suspended_windows_process",
                create=True,
                return_value=False,
            ), patch(
                "format_adapters.base._terminate_windows_job",
                side_effect=record_terminate_job,
            ):
                result = runner(
                    [
                        str(MOCK_RUNTIME_PYTHON),
                        "-B",
                        "-c",
                        "from pathlib import Path;import sys;Path(sys.argv[1]).write_text('ran',encoding='ascii')",
                        str(sentinel),
                    ],
                    timeout_seconds=2,
                    output_limit=4096,
                )

            self.assertTrue(result.spawn_failed)
            self.assertFalse(sentinel.exists())
            self.assertEqual(len(created), 1)
            self.assertFalse(self._windows_pid_is_live(created[0].pid))
            self.assertEqual(len(terminated_jobs), 1)

    def test_windows_suspended_thread_discovery_failure_reaps_without_running(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-specific suspended Job ownership contract")
        import format_adapters.base as adapter_base

        runner = getattr(adapter_base, "_run_bounded_process")
        real_popen = adapter_base.subprocess.Popen
        original_terminate_job = adapter_base._terminate_windows_job
        created: list[subprocess.Popen[bytes]] = []
        terminated_jobs: list[int] = []

        def capture_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
            process = real_popen(*args, **kwargs)
            created.append(process)
            return process

        def record_terminate_job(job_handle: int) -> bool:
            terminated_jobs.append(job_handle)
            return original_terminate_job(job_handle)

        with tempfile.TemporaryDirectory() as raw:
            sentinel = Path(raw) / "command-ran"
            with patch(
                "format_adapters.base.subprocess.Popen",
                side_effect=capture_popen,
            ), patch(
                "format_adapters.base._find_initial_windows_thread_id",
                create=True,
                return_value=None,
            ), patch(
                "format_adapters.base._terminate_windows_job",
                side_effect=record_terminate_job,
            ):
                result = runner(
                    [
                        str(MOCK_RUNTIME_PYTHON),
                        "-B",
                        "-c",
                        "from pathlib import Path;import sys;Path(sys.argv[1]).write_text('ran',encoding='ascii')",
                        str(sentinel),
                    ],
                    timeout_seconds=2,
                    output_limit=4096,
                )

            self.assertTrue(result.spawn_failed)
            self.assertFalse(sentinel.exists())
            self.assertEqual(len(created), 1)
            self.assertFalse(self._windows_pid_is_live(created[0].pid))
            self.assertEqual(len(terminated_jobs), 1)

    def test_windows_runner_releases_handles_and_reader_threads(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-specific process resource contract")
        import format_adapters.base as adapter_base

        runner = getattr(adapter_base, "_run_bounded_process")
        real_popen = adapter_base.subprocess.Popen
        created_pids: list[int] = []
        handles_before = self._windows_handle_count()
        reader_threads_before = {
            thread.ident
            for thread in threading.enumerate()
            if "drain" in thread.name
        }

        def capture_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
            process = real_popen(*args, **kwargs)
            created_pids.append(process.pid)
            return process

        with patch("format_adapters.base.subprocess.Popen", side_effect=capture_popen):
            for _ in range(8):
                result = runner(
                    [str(MOCK_RUNTIME_PYTHON), "-B", "-c", "raise SystemExit(0)"],
                    timeout_seconds=2,
                    output_limit=4096,
                )
                self.assertEqual(result.returncode, 0)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            remaining_readers = {
                thread.ident
                for thread in threading.enumerate()
                if "drain" in thread.name
            } - reader_threads_before
            if not remaining_readers:
                break
            time.sleep(0.01)
        self.assertFalse(remaining_readers)
        self.assertLessEqual(self._windows_handle_count(), handles_before + 2)
        self.assertEqual(len(created_pids), 8)
        for pid in created_pids:
            self.assertFalse(self._windows_pid_is_live(pid))

    def test_bounded_process_runner_caps_held_pipes_reaps_trees_and_classifies_failures(self) -> None:
        import format_adapters.base as adapter_base

        runner = getattr(adapter_base, "_run_bounded_process")

        child_program = (
            "from pathlib import Path\n"
            "import os,sys,time\n"
            "pid_path=Path(sys.argv[1])\n"
            "stop_path=Path(sys.argv[2])\n"
            "pid_path.write_text(str(os.getpid()),encoding='ascii')\n"
            "sys.stdout.write('x'*int(sys.argv[3]))\n"
            "sys.stdout.flush()\n"
            "while not stop_path.exists():\n"
            "    time.sleep(0.01)\n"
        )
        parent_program = (
            "from pathlib import Path\n"
            "import subprocess,sys,time\n"
            "subprocess.Popen([sys.executable,'-B','-c',sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]],stdout=sys.stdout,stderr=sys.stderr)\n"
            "deadline=time.monotonic()+2\n"
            "while not Path(sys.argv[2]).exists() and time.monotonic()<deadline:\n"
            "    time.sleep(0.01)\n"
            "time.sleep(float(sys.argv[5]))\n"
        )

        def run_held_tree(
            payload: int, *, parent_lifetime: float, timeout: float
        ) -> tuple[object, float]:
            with tempfile.TemporaryDirectory() as raw:
                raw_root = Path(raw)
                pid_path = raw_root / "child.pid"
                stop_path = raw_root / "stop"
                started = time.monotonic()
                watchdog = threading.Timer(
                    1.5, lambda: stop_path.write_text("stop", encoding="ascii")
                )
                watchdog.daemon = True
                watchdog.start()
                try:
                    result = runner(
                        [
                            str(MOCK_RUNTIME_PYTHON),
                            "-B",
                            "-c",
                            parent_program,
                            child_program,
                            str(pid_path),
                            str(stop_path),
                            str(payload),
                            str(parent_lifetime),
                        ],
                        timeout_seconds=timeout,
                        output_limit=4096,
                    )
                finally:
                    watchdog.cancel()
                elapsed = time.monotonic() - started
                pid = self._wait_for_child_pid(pid_path)
                try:
                    self._assert_pid_stops(pid)
                finally:
                    stop_path.write_text("stop", encoding="ascii")
                    self._assert_pid_stops(pid)
                return result, elapsed

        exact_cap, exact_elapsed = run_held_tree(
            4096, parent_lifetime=30, timeout=0.3
        )
        self.assertLess(exact_elapsed, 1.0, exact_elapsed)
        self.assertFalse(exact_cap.overflow)
        self.assertTrue(exact_cap.timed_out)
        self.assertEqual(len(exact_cap.stdout), 4096)

        cap_plus_one, cap_plus_one_elapsed = run_held_tree(
            4097, parent_lifetime=30, timeout=0.5
        )
        self.assertLess(cap_plus_one_elapsed, 1.0, cap_plus_one_elapsed)
        self.assertTrue(cap_plus_one.overflow)
        self.assertFalse(cap_plus_one.timed_out)
        self.assertEqual(len(cap_plus_one.stdout), 4096)

        silent_timeout, silent_elapsed = run_held_tree(
            0, parent_lifetime=30, timeout=0.3
        )
        self.assertLess(silent_elapsed, 1.0, silent_elapsed)
        self.assertFalse(silent_timeout.overflow)
        self.assertTrue(silent_timeout.timed_out)

        parent_exits_first, parent_exit_elapsed = run_held_tree(
            0, parent_lifetime=0, timeout=2
        )
        self.assertLess(parent_exit_elapsed, 1.0, parent_exit_elapsed)
        self.assertFalse(parent_exits_first.overflow)
        self.assertFalse(parent_exits_first.timed_out)

        noisy = (
            "import sys,threading;"
            "a=threading.Thread(target=lambda:sys.stdout.write('x'*3000000));"
            "b=threading.Thread(target=lambda:sys.stderr.write('y'*3000000));"
            "a.start();b.start();a.join();b.join()"
        )
        overflow = runner(
            [str(MOCK_RUNTIME_PYTHON), "-B", "-c", noisy],
            timeout_seconds=10,
            output_limit=4096,
        )
        self.assertTrue(overflow.overflow)
        self.assertFalse(overflow.timed_out)
        self.assertFalse(overflow.spawn_failed)
        self.assertFalse(overflow.read_failed)
        self.assertIsNotNone(overflow.returncode)
        self.assertLessEqual(len(overflow.stdout), 4096)
        self.assertLessEqual(len(overflow.stderr), 4096)

        timed_out = runner(
            [str(MOCK_RUNTIME_PYTHON), "-B", "-c", "import time; time.sleep(30)"],
            timeout_seconds=0.1,
            output_limit=4096,
        )
        self.assertTrue(timed_out.timed_out)
        self.assertIsNotNone(timed_out.returncode)

        for exit_code in (0, 1, 2):
            with self.subTest(exit_code=exit_code):
                completed = runner(
                    [str(MOCK_RUNTIME_PYTHON), "-B", "-c", f"raise SystemExit({exit_code})"],
                    timeout_seconds=10,
                    output_limit=4096,
                )
                self.assertEqual(completed.returncode, exit_code)
                self.assertFalse(completed.overflow)
                self.assertFalse(completed.timed_out)

        with patch("format_adapters.base.subprocess.Popen", side_effect=OSError("spawn")):
            spawn_failed = runner(["missing"], timeout_seconds=1, output_limit=4096)
        self.assertTrue(spawn_failed.spawn_failed)
        self.assertIsNotNone(spawn_failed.returncode)

        with patch(
            "format_adapters.base._establish_process_tree",
            create=True,
            return_value=None,
        ):
            ownership_failed = runner(
                [str(MOCK_RUNTIME_PYTHON), "-B", "-c", "import time; time.sleep(30)"],
                timeout_seconds=1,
                output_limit=4096,
            )
        self.assertTrue(ownership_failed.spawn_failed)
        self.assertIsNotNone(ownership_failed.returncode)

        class BrokenReader:
            def read1(self, _size: int) -> bytes:
                raise OSError("read")

            def close(self) -> None:
                return None

        class BrokenProcess:
            stdout = BrokenReader()
            stderr = BrokenReader()
            returncode = 0
            pid = 0

            def poll(self) -> int:
                return 0

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def terminate(self) -> None:
                return None

            def kill(self) -> None:
                return None

        broken_process = BrokenProcess()
        owned_process = type(
            "OwnedProcess",
            (),
            {
                "process": broken_process,
                "job_handle": None,
                "process_group_id": None,
                "closed": False,
            },
        )()
        with patch("format_adapters.base.subprocess.Popen", return_value=broken_process), patch(
            "format_adapters.base._establish_process_tree",
            create=True,
            return_value=owned_process,
        ), patch(
            "format_adapters.base._resume_suspended_windows_process",
            return_value=True,
        ):
            read_failed = runner(["ignored"], timeout_seconds=1, output_limit=4096)
        self.assertTrue(read_failed.read_failed)
        self.assertIsNotNone(read_failed.returncode)

    def test_huge_integers_are_route_specific_validation_errors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            v3 = self._create_package(root / "v3", 3)
            v3_manifest = manifest_from_fixture(3)
            v3_manifest["actions"]["greet"]["travelDistanceRatio"] = 10**400
            write_manifest(v3 / "pet.json", v3_manifest)
            self._assert_blocked(self._validate_local(v3), "V3_ACTION_INVALID")

            v4 = self._create_package(root / "v4", 4)
            v4_manifest = manifest_from_fixture(4)
            v4_manifest["actions"]["wideSpell"]["travelDistanceRatio"] = 10**400
            write_manifest(v4 / "pet.json", v4_manifest)
            self._assert_blocked(self._validate_local(v4), "V4_ACTIONS_INVALID")

    def test_v4_checks_layers_forms_sequences_cooldowns_and_quality_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            no_body = self._create_package(root / "no-body", 4)
            manifest = manifest_from_fixture(4)
            manifest["actions"]["humanIdle"]["layers"][0]["hitTest"] = False
            write_manifest(no_body / "pet.json", manifest)
            self._assert_blocked(self._validate_local(no_body), "V4_HIT_TEST_LAYER")

            forbidden_gaze = self._create_package(root / "gaze", 4)
            manifest = manifest_from_fixture(4)
            manifest["forms"]["smallAnimal"]["gazeAction"] = "humanGaze"
            write_manifest(forbidden_gaze / "pet.json", manifest)
            self._assert_blocked(
                self._validate_local(forbidden_gaze), "V4_GAZE_DEFAULT_ONLY"
            )

            no_exit = self._create_package(root / "exit", 4)
            manifest = manifest_from_fixture(4)
            del manifest["transformations"]
            write_manifest(no_exit / "pet.json", manifest)
            self._assert_blocked(self._validate_local(no_exit), "V4_FORM_EXIT_MISSING")

            empty_simplified = self._create_package(root / "quality", 4)
            manifest = manifest_from_fixture(4)
            manifest["actions"]["humanIdle"]["layers"][0]["optionalInSimplified"] = True
            write_manifest(empty_simplified / "pet.json", manifest)
            self._assert_blocked(
                self._validate_local(empty_simplified), "V4_SIMPLIFIED_FRAME_EMPTY"
            )

            unknown_group = self._create_package(root / "cooldown", 4)
            manifest = manifest_from_fixture(4)
            manifest["transformations"]["becomeAnimal"]["autoplay"]["cooldownGroups"] = [
                "unknownGroup"
            ]
            write_manifest(unknown_group / "pet.json", manifest)
            self._assert_blocked(
                self._validate_local(unknown_group), "V4_COOLDOWN_GROUP_UNKNOWN"
            )

            unknown_form = self._create_package(root / "sequence", 4)
            manifest = manifest_from_fixture(4)
            manifest["sequences"]["shapeBurst"]["steps"][0]["formAfter"] = "unknownForm"
            write_manifest(unknown_form / "pet.json", manifest)
            self._assert_blocked(
                self._validate_local(unknown_form), "V4_SEQUENCE_FORM_UNKNOWN"
            )

    def test_v4_allows_transparent_body_frame_with_other_visible_layers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self._create_package(Path(raw), 4)
            manifest = manifest_from_fixture(4)
            wide_spell = manifest["actions"]["wideSpell"]
            wide_spell["layers"][1]["frameMap"] = [0, None, 2]
            wide_spell["layers"].append(
                {
                    "atlas": "character",
                    "row": 5,
                    "startColumn": 0,
                    "anchorX": 96,
                    "anchorY": 208,
                    "frameMap": [0, 1, 2],
                }
            )
            write_manifest(package / "pet.json", manifest)
            report = self._assert_runtime_schema_and_registry_accepts(package)

        self.assertEqual(report["status"], "pass", report)

    def test_v4_allows_natural_sequence_completion_but_validates_safe_stop_field(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            natural = self._create_package(root / "natural", 4)
            natural_manifest = manifest_from_fixture(4)
            for step in natural_manifest["sequences"]["shapeBurst"]["steps"]:
                step["safeStopAfter"] = False
            write_manifest(natural / "pet.json", natural_manifest)
            natural_report = self._assert_runtime_schema_and_registry_accepts(natural)

            invalid = self._create_package(root / "invalid", 4)
            invalid_manifest = manifest_from_fixture(4)
            invalid_manifest["sequences"]["shapeBurst"]["steps"][0]["safeStopAfter"] = "false"
            write_manifest(invalid / "pet.json", invalid_manifest)
            self._assert_blocked(
                self._validate_local(invalid), "V4_SEQUENCES_INVALID"
            )

        self.assertEqual(natural_report["status"], "pass", natural_report)

    def test_v4_rejects_unhashable_cross_references_and_invalid_action_hold(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            invalid_hold = self._create_package(root / "hold", 4)
            manifest = manifest_from_fixture(4)
            manifest["actions"]["humanIdle"]["holdMs"] = True
            write_manifest(invalid_hold / "pet.json", manifest)
            self._assert_blocked(
                self._validate_local(invalid_hold), "V4_ACTIONS_INVALID"
            )

            bad_form = self._create_package(root / "form", 4)
            manifest = manifest_from_fixture(4)
            manifest["forms"]["defaultHuman"]["interactionActions"] = [["wideSpell"]]
            write_manifest(bad_form / "pet.json", manifest)
            self._assert_blocked(
                self._validate_local(bad_form), "V4_FORMS_INVALID"
            )

            bad_transformation = self._create_package(root / "transformation", 4)
            manifest = manifest_from_fixture(4)
            manifest["transformations"]["becomeAnimal"]["residentActions"] = [
                {"action": ["animalResident"], "weight": 100}
            ]
            write_manifest(bad_transformation / "pet.json", manifest)
            self._assert_blocked(
                self._validate_local(bad_transformation),
                "V4_TRANSFORMATIONS_INVALID",
            )

    def test_v4_valid_layered_fixture_never_receives_v2_fixed_atlas_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = self._validate_local(self._create_package(Path(raw), 4))
        self.assertFalse(any(code.startswith("V2_") for code in check_codes(report)))
        self.assertFalse(any(code.startswith("V3_") for code in check_codes(report)))

    def _mock_authority_process(
        self,
        schema_result: subprocess.CompletedProcess[str] | BaseException,
        *,
        statuses: list[str] | None = None,
        heads: list[str] | None = None,
    ):
        status_values = iter(statuses or ["", ""])
        head_values = iter(heads or [RUNTIME_COMMIT, RUNTIME_COMMIT])

        def result(
            returncode: int,
            stdout: str = "",
            stderr: str = "",
            *,
            timed_out: bool = False,
            spawn_failed: bool = False,
            read_failed: bool = False,
        ) -> object:
            return type(
                "BoundedProcessResult",
                (),
                {
                    "returncode": returncode,
                    "stdout": stdout.encode("utf-8"),
                    "stderr": stderr.encode("utf-8"),
                    "overflow": False,
                    "timed_out": timed_out,
                    "spawn_failed": spawn_failed,
                    "read_failed": read_failed,
                },
            )()

        def fake_process(command: list[str], *args: object, **kwargs: object) -> object:
            command_strings = [str(item) for item in command]
            if command_strings[0] == "git":
                if command_strings[-2:] == ["rev-parse", "HEAD"]:
                    return result(0, next(head_values) + "\n")
                if "status" in command_strings:
                    return result(0, next(status_values))
                if "ls-files" in command_strings:
                    return result(0, command_strings[-1] + "\n")
                raise AssertionError(f"unexpected git invocation: {command_strings!r}")
            if command_strings[0] == str(MOCK_RUNTIME_PYTHON):
                if isinstance(schema_result, subprocess.TimeoutExpired):
                    return result(-1, timed_out=True)
                if isinstance(schema_result, BaseException):
                    return result(-1, spawn_failed=True)
                return result(
                    schema_result.returncode,
                    schema_result.stdout or "",
                    schema_result.stderr or "",
                )
            raise AssertionError(f"unexpected subprocess invocation: {command_strings!r}")

        return fake_process

    def test_authority_process_timeout_malformed_output_and_exit_matrix_fail_closed(self) -> None:
        cases: list[tuple[str, subprocess.CompletedProcess[str] | BaseException, str, str]] = [
            (
                "timeout",
                subprocess.TimeoutExpired([str(MOCK_RUNTIME_PYTHON)], 30),
                "unverified",
                "unverified",
            ),
            (
                "malformed",
                subprocess.CompletedProcess([str(MOCK_RUNTIME_PYTHON)], 0, "not-json", ""),
                "unverified",
                "unverified",
            ),
            (
                "wrong-exit",
                subprocess.CompletedProcess([str(MOCK_RUNTIME_PYTHON)], 2, "[]", ""),
                "unverified",
                "unverified",
            ),
            (
                "schema-error",
                subprocess.CompletedProcess(
                    [str(MOCK_RUNTIME_PYTHON)],
                    1,
                    '[{"path":["id"],"message":"invalid id"}]',
                    "",
                ),
                "blocked",
                "blocked",
            ),
        ]
        with tempfile.TemporaryDirectory() as raw:
            package = self._create_package(Path(raw), 2)
            for name, process_result, expected_schema, expected_overall in cases:
                with self.subTest(name=name):
                    with patch(
                        "format_adapters.base._run_bounded_process",
                        side_effect=self._mock_authority_process(process_result),
                    ):
                        report = validate_package(package, RUNTIME_ROOT, MOCK_RUNTIME_PYTHON)
                    self.assertEqual(
                        check_by_code(report, "SCHEMA_VALIDATION")["status"],
                        expected_schema,
                        report,
                    )
                    self.assertEqual(report["status"], expected_overall, report)

    def test_dirty_or_moving_runtime_authority_is_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = self._create_package(Path(raw), 2)
            with patch(
                "format_adapters.base._run_bounded_process",
                side_effect=self._mock_authority_process(
                    subprocess.CompletedProcess([str(MOCK_RUNTIME_PYTHON)], 0, "[]", ""),
                    statuses=[" M schemas/pet-pack-v2.schema.json\n"],
                ),
            ):
                dirty = validate_package(package, RUNTIME_ROOT, MOCK_RUNTIME_PYTHON)
            self.assertEqual(dirty["status"], "unverified", dirty)
            self.assertEqual(
                check_by_code(dirty, "SCHEMA_VALIDATION")["status"], "unverified"
            )

            with patch(
                "format_adapters.base._run_bounded_process",
                side_effect=self._mock_authority_process(
                    subprocess.CompletedProcess([str(MOCK_RUNTIME_PYTHON)], 0, "[]", ""),
                    heads=[RUNTIME_COMMIT, "f" * 40],
                ),
            ):
                moving = validate_package(package, RUNTIME_ROOT, MOCK_RUNTIME_PYTHON)
            self.assertEqual(moving["status"], "unverified", moving)
            self.assertEqual(
                check_by_code(moving, "SCHEMA_VALIDATION")["status"], "unverified"
            )

    def test_public_argument_misuse_is_controlled(self) -> None:
        with self.assertRaises(TypeError):
            validate_package(None, None, None)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            validate_package(Path("."), True, None)  # type: ignore[arg-type]

    def test_validation_does_not_mutate_package_source_installed_sentinel_or_pillow_globals(self) -> None:
        original_pixel_limit = Image.MAX_IMAGE_PIXELS
        before_source = subprocess.run(
            ["git", "-C", str(RUNTIME_ROOT), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            package = self._create_package(root / "package", 4)
            sentinel = root / "installed-pets" / "untouched.pet"
            sentinel.parent.mkdir()
            sentinel.write_bytes(b"pre-existing installed pet sentinel")
            before_sentinel = (sentinel.read_bytes(), sentinel.stat().st_mtime_ns)
            before_package = {
                path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in package.rglob("*")
                if path.is_file()
            }
            report = self._validate_local(package)
            after_package = {
                path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in package.rglob("*")
                if path.is_file()
            }
            self.assertEqual(report["status"], "unverified", report)
            self.assertEqual((sentinel.read_bytes(), sentinel.stat().st_mtime_ns), before_sentinel)
            self.assertEqual(before_package, after_package)
        after_source = subprocess.run(
            ["git", "-C", str(RUNTIME_ROOT), "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertEqual(before_source, after_source)
        self.assertEqual(Image.MAX_IMAGE_PIXELS, original_pixel_limit)
