from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = SKILL_ROOT / "scripts"
FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"
V4_FIXTURE_ROOT = FIXTURES_ROOT / "v4"
BUILDER_CHECKSUM_RELATIVE_PATH = "evidence/generated-sha256.json"
FINAL_CHECKSUM_RELATIVE_PATH = "evidence/final-pipeline-sha256.json"
sys.path.insert(0, str(SCRIPTS_ROOT))
sys.path.insert(0, str(FIXTURES_ROOT))

import build_synthetic_dry_run as synthetic_builder
from build_synthetic_dry_run import (
    build_synthetic_dry_run,
    write_checksum_manifest,
    write_synthetic_action_contracts,
)
from contracts import evaluate_identity_gate, validate_action_contract
from inspect_frames import inspect_frames
from make_contact_sheet import make_contact_sheet
from make_identity_review_sheet import build_identity_review_sheet
from make_run_summary import build_run_summary
from measure_identity_geometry import measure_alpha_geometry
from prepare_generation_jobs import SelectionError, build_generation_jobs
from prepare_pet_run import prepare_pet_run
from render_timed_previews import render_timed_preview
from validate_package import validate_package


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot[relative] = "directory"
        elif path.is_file():
            snapshot[relative] = f"file:{_sha256(path)}"
        else:
            snapshot[relative] = "other"
    return snapshot


def _changed_paths(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_checksum_complete(
    test: unittest.TestCase,
    root: Path,
    checksum_path: Path,
    self_excluded_path: str,
) -> None:
    checksum = json.loads(checksum_path.read_text(encoding="utf-8"))
    test.assertEqual(checksum["selfExcludedPath"], self_excluded_path)
    recorded = {record["path"]: record["sha256"] for record in checksum["files"]}
    test.assertEqual(len(recorded), len(checksum["files"]))
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != checksum_path
    }
    test.assertEqual(set(recorded), actual)
    for relative, digest in recorded.items():
        test.assertEqual(digest, _sha256(root / relative))


def _write_unfinished_summary_draft(run: Path, identity_status: str) -> None:
    keep_paths = sorted(
        path.relative_to(run).as_posix()
        for path in run.rglob("*")
        if path.is_file()
    )
    _write_json(
        run / "run-summary.json",
        {
            "schemaVersion": 1,
            "projectId": "bronze-moth",
            "identityRoute": "original-brand",
            "formatRoute": "v4",
            "status": "draft",
            "selection": "candidate",
            "identityGateStatus": identity_status,
            "formalGates": "needs-review",
            "technicalStatus": "partial",
            "visualStatus": "not-reviewed",
            "packageStatus": "local-candidate",
            "runtimeStatus": "unverified",
            "installedStatus": "not-authorized",
            "runtimeEvidence": [],
            "installationEvidence": [],
            "requiredSoakMinutes": None,
            "observedSoakMinutes": 0,
            "soakVerdict": "not-run",
            "completedJobIds": [],
            "visualVerdictIds": [],
            "unresolvedItems": [
                "An independent actual-size visual verdict is required before identity selection."
            ],
            "userAcceptance": [],
            "installAuthority": False,
            "integrationAuthority": False,
            "commitAuthority": False,
            "pushAuthority": False,
            "publicationAuthority": False,
            "verifiedArtifacts": [],
            "localState": {
                "keep": keep_paths,
                "archiveCandidate": [],
                "cleanupCandidate": [],
                "uncertainUserOwned": [],
            },
        },
    )


class EndToEndDryRunTest(unittest.TestCase):
    def test_no_verdict_dry_run_stops_at_visual_candidate_without_escaping_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            run_parent = workspace / "runs"
            run_parent.mkdir()
            sentinel = workspace / "outside" / "user-owned.txt"
            sentinel.parent.mkdir()
            sentinel.write_text("preserve", encoding="utf-8")
            before = _tree_snapshot(workspace)

            run = prepare_pet_run(run_parent, "bronze-moth", "original-brand", "v4")
            fixture = build_synthetic_dry_run(run)

            self.assertEqual(Path(str(fixture["runRoot"])), run)
            self.assertNotIn("actionContractPaths", fixture)
            self.assertFalse((run / "contracts" / "bronze-moth-actions").exists())
            self.assertIn(
                "bronze-moth",
                Path(str(fixture["briefPath"])).read_text(encoding="utf-8"),
            )
            sources = json.loads(
                Path(str(fixture["sourcesPath"])).read_text(encoding="utf-8")
            )
            self.assertEqual(sources["sources"][0]["evidenceClass"], "approved-original-design")
            self.assertEqual(set(sources["sources"][0]["roles"]), {"identity", "proportion"})

            canonical = Path(str(fixture["canonicalPath"]))
            with Image.open(canonical) as candidate:
                self.assertEqual(candidate.size, (192, 208))
                self.assertIsNotNone(candidate.getchannel("A").getbbox())
            with Image.open(Path(str(fixture["bodyAtlasPath"]))) as body_atlas:
                self.assertEqual(body_atlas.size, (192, 624))
            with Image.open(Path(str(fixture["glowAtlasPath"]))) as glow_atlas:
                self.assertEqual(glow_atlas.size, (384, 416))
            geometry = measure_alpha_geometry(canonical)
            self.assertEqual(geometry["canvas"], [192, 208])
            self.assertTrue(geometry["diagnosticOnly"])
            _write_json(run / "qa" / "identity" / "geometry.json", geometry)

            review = build_identity_review_sheet(
                canonical,
                Path(str(fixture["identityReferencePath"])),
                Path(str(fixture["proportionReferencePath"])),
                run / "qa" / "identity" / "review-board.png",
                runtime_height=84,
            )
            self.assertEqual(review["runtimeHeight"], 84)
            self.assertEqual(len(review["panels"]), 9)

            identity_path = Path(str(fixture["identityContractPath"]))
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
            self.assertEqual(identity["formatRoute"], "v4")
            self.assertEqual(identity["features"]["runtimeHeightTarget"], 84)
            identity_result = evaluate_identity_gate(identity, sources["sources"], [])
            self.assertEqual(identity_result["status"], "visual-candidate")
            self.assertEqual(identity_result["acceptedVerdictIds"], [])
            self.assertEqual(identity_result["canonicalSha256"], _sha256(canonical))
            _write_json(run / "qa" / "identity" / "gate-without-verdict.json", identity_result)
            identity.update(
                {
                    "identityGateStatus": identity_result["status"],
                    "selection": "candidate",
                    "visualStatus": "not-reviewed",
                    "visualVerdictIds": [],
                }
            )
            _write_json(identity_path, identity)
            self.assertNotEqual(identity["identityGateStatus"], "identity-selected")

            action_paths = write_synthetic_action_contracts(run)
            action_contracts = [
                json.loads(Path(str(path)).read_text(encoding="utf-8"))
                for path in action_paths
            ]
            self.assertTrue(action_contracts)
            for action in action_contracts:
                self.assertEqual(validate_action_contract(action), [])
            with self.assertRaisesRegex(SelectionError, "identityGateStatus"):
                build_generation_jobs(identity, action_contracts)
            selected_for_route_assertion = copy.deepcopy(identity)
            selected_for_route_assertion.update(
                {
                    "identityGateStatus": "identity-selected",
                    "selection": "selected",
                    "visualVerdictIds": ["synthetic-route-only-selection"],
                }
            )
            selected_jobs = build_generation_jobs(
                selected_for_route_assertion, action_contracts
            )
            self.assertEqual(selected_jobs["formatRoute"], "v4")
            self.assertEqual(identity["identityGateStatus"], "visual-candidate")

            body_frames = [Path(str(path)) for path in fixture["bodyFramePaths"]]
            frame_report = inspect_frames(body_frames, expected_canvas=(192, 208))
            self.assertTrue(frame_report["diagnosticOnly"])
            self.assertEqual(len(frame_report["frames"]), 3)
            _write_json(run / "qa" / "actions" / "frame-inspection.json", frame_report)

            contact = make_contact_sheet(
                [
                    {"label": "idle | air anchor", "path": str(body_frames[0])},
                    {"label": "flight-right | air travel", "path": str(body_frames[1])},
                    {"label": "flight-left | air travel", "path": str(body_frames[2])},
                ],
                run / "qa" / "actions" / "contact-sheet.png",
                columns=3,
                display_scale=1.0,
            )
            self.assertTrue(contact["diagnosticOnly"])

            preview = render_timed_preview(
                body_frames,
                [100, 100, 100],
                run / "qa" / "actions" / "flight-preview.webp",
                loop=0,
            )
            self.assertEqual(preview["technicalStatus"], "pass")

            package = validate_package(Path(str(fixture["packageRoot"])), None, None)
            package_root = Path(str(fixture["packageRoot"]))
            manifest = json.loads((package_root / "pet.json").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["atlases"]["body"],
                {"path": "body.webp", "cellWidth": 192, "cellHeight": 208},
            )
            self.assertEqual(
                manifest["atlases"]["glow"],
                {"path": "glow.webp", "cellWidth": 384, "cellHeight": 416},
            )
            for action_id in ("hoverIdle", "flyRight", "flyLeft"):
                layers = manifest["actions"][action_id]["layers"]
                self.assertEqual(len(layers), 1)
                body_layer = layers[0]
                self.assertEqual(body_layer["atlas"], "body")
                self.assertEqual((body_layer["anchorX"], body_layer["anchorY"]), (96, 208))
                self.assertTrue(body_layer["hitTest"])
                self.assertNotIn("scalePercent", body_layer)
                self.assertEqual(body_layer.get("scalePercent", 100), 100)
            glow_layers = manifest["actions"]["glowPulse"]["layers"]
            self.assertEqual([layer["atlas"] for layer in glow_layers], ["glow", "body"])
            self.assertEqual(
                (glow_layers[0]["anchorX"], glow_layers[0]["anchorY"]), (192, 416)
            )
            self.assertFalse(glow_layers[0].get("hitTest", False))
            self.assertEqual(
                (glow_layers[1]["anchorX"], glow_layers[1]["anchorY"]), (96, 208)
            )
            self.assertTrue(glow_layers[1]["hitTest"])
            self.assertNotIn("scalePercent", glow_layers[1])
            source_record = json.loads(
                (package_root / "source.json").read_text(encoding="utf-8")
            )
            retained_v4_source = json.loads(
                (V4_FIXTURE_ROOT / "source.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                _sha256(V4_FIXTURE_ROOT / "pet.json"),
                retained_v4_source["fixture"]["sha256"],
            )
            self.assertEqual(
                _sha256(V4_FIXTURE_ROOT / "pet.json"),
                retained_v4_source["source"]["manifestSha256"],
            )
            self.assertEqual(source_record["runtimeCommit"], retained_v4_source["runtimeCommit"])
            self.assertEqual(source_record["fixture"], retained_v4_source["fixture"])
            self.assertEqual(source_record["schema"], retained_v4_source["source"])
            checks = {check["code"]: check for check in package["checks"]}
            self.assertEqual(package["formatVersion"], 4)
            self.assertEqual(checks["V4_PACKAGE_VALIDATION"]["status"], "pass")
            self.assertEqual(package["packageStatus"], "local-candidate")
            self.assertEqual(package["runtimeStatus"], "unverified")
            self.assertEqual(package["installedStatus"], "not-authorized")
            _write_json(run / "qa" / "package-validation.json", package)

            _write_unfinished_summary_draft(run, str(identity_result["status"]))
            summary = build_run_summary(run)
            self.assertEqual(summary["packageStatus"], "local-candidate")
            self.assertEqual(summary["runtimeStatus"], "unverified")
            self.assertEqual(summary["installedStatus"], "not-authorized")
            self.assertEqual(summary["visualStatus"], "not-reviewed")
            self.assertFalse(summary["finalSummary"])

            final_checksum_path = write_checksum_manifest(run, "final-pipeline")
            _assert_checksum_complete(
                self,
                run,
                final_checksum_path,
                FINAL_CHECKSUM_RELATIVE_PATH,
            )

            after = _tree_snapshot(workspace)
            changed = _changed_paths(before, after)
            run_prefix = run.relative_to(workspace).as_posix()
            self.assertTrue(changed)
            self.assertTrue(
                all(path == run_prefix or path.startswith(f"{run_prefix}/") for path in changed),
                sorted(changed),
            )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_builder_cli_writes_only_beneath_explicit_output_and_hashes_every_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            output_parent = workspace / "explicit-output"
            output_parent.mkdir()
            output = output_parent / "bronze-moth"
            sentinel = workspace / "outside" / "user-owned.txt"
            sentinel.parent.mkdir()
            sentinel.write_text("preserve", encoding="utf-8")
            before = _tree_snapshot(workspace)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(FIXTURES_ROOT / "build_synthetic_dry_run.py"),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            checksum_path = output / "evidence" / "generated-sha256.json"
            _assert_checksum_complete(
                self,
                output,
                checksum_path,
                BUILDER_CHECKSUM_RELATIVE_PATH,
            )
            self.assertFalse((output / "contracts" / "bronze-moth-actions").exists())

            after = _tree_snapshot(workspace)
            changed = _changed_paths(before, after)
            output_prefix = output.relative_to(workspace).as_posix()
            self.assertTrue(changed)
            self.assertTrue(
                all(
                    path == output_prefix or path.startswith(f"{output_prefix}/")
                    for path in changed
                ),
                sorted(changed),
            )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_builder_rejects_a_preexisting_hardlinked_leaf_without_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            run_parent = workspace / "runs"
            run_parent.mkdir()
            sentinel = workspace / "outside" / "user-owned.txt"
            sentinel.parent.mkdir()
            sentinel.write_text("preserve", encoding="utf-8")
            run = prepare_pet_run(run_parent, "bronze-moth", "original-brand", "v4")
            hardlinked_leaf = run / "frames" / "canonical-identity.png"
            os.link(sentinel, hardlinked_leaf)
            before = _tree_snapshot(workspace)

            with self.assertRaises(ValueError):
                build_synthetic_dry_run(run)

            self.assertEqual(_tree_snapshot(workspace), before)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_builder_preflights_a_hardlinked_template_leaf_before_synthetic_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            run_parent = workspace / "runs"
            run_parent.mkdir()
            sentinel = workspace / "outside" / "user-owned.txt"
            sentinel.parent.mkdir()
            sentinel.write_bytes(b"preserve")
            run = prepare_pet_run(run_parent, "bronze-moth", "original-brand", "v4")
            template_leaf = run / "run-summary.json"
            template_leaf.unlink()
            os.link(sentinel, template_leaf)
            before = _tree_snapshot(workspace)

            with self.assertRaises(ValueError):
                build_synthetic_dry_run(run)

            self.assertEqual(_tree_snapshot(workspace), before)
            self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_builder_rejects_an_unreadable_subtree_before_synthetic_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            run_parent = workspace / "runs"
            run_parent.mkdir()
            sentinel = workspace / "outside" / "user-owned.txt"
            sentinel.parent.mkdir()
            sentinel.write_bytes(b"preserve")
            run = prepare_pet_run(run_parent, "bronze-moth", "original-brand", "v4")
            denied_subtree = run / "decoded"
            before = _tree_snapshot(workspace)
            original_scandir = os.scandir

            def deny_decoded_scan(path: object):
                if Path(path).resolve() == denied_subtree.resolve():
                    raise PermissionError("synthetic decoded subtree denial")
                return original_scandir(path)

            error: Exception | None = None
            with patch.object(synthetic_builder.os, "scandir", side_effect=deny_decoded_scan):
                try:
                    build_synthetic_dry_run(run)
                except (PermissionError, ValueError) as caught:
                    error = caught

            self.assertEqual(_tree_snapshot(workspace), before)
            self.assertEqual(sentinel.read_bytes(), b"preserve")
            self.assertIsInstance(error, ValueError)
            self.assertIn("cannot scan run directory: decoded", str(error))

    def test_action_helper_rejects_a_post_builder_hardlink_without_action_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            run_parent = workspace / "runs"
            run_parent.mkdir()
            sentinel = workspace / "outside" / "user-owned.txt"
            sentinel.parent.mkdir()
            sentinel.write_bytes(b"preserve")
            run = prepare_pet_run(run_parent, "bronze-moth", "original-brand", "v4")
            fixture = build_synthetic_dry_run(run)
            action_directory = run / "contracts" / "bronze-moth-actions"
            self.assertFalse(action_directory.exists())
            body_leaf = Path(str(fixture["bodyFramePaths"][0]))
            body_leaf.unlink()
            os.link(sentinel, body_leaf)
            before = _tree_snapshot(workspace)

            with self.assertRaisesRegex(ValueError, "exclusive regular file"):
                write_synthetic_action_contracts(run)

            self.assertEqual(_tree_snapshot(workspace), before)
            self.assertEqual(sentinel.read_bytes(), b"preserve")
            self.assertFalse(action_directory.exists())

    def test_builder_preflights_an_omitted_prepared_directory_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            run_parent = workspace / "runs"
            run_parent.mkdir()
            sentinel = workspace / "outside" / "user-owned.txt"
            sentinel.parent.mkdir()
            sentinel.write_bytes(b"preserve")
            external_directory = sentinel.parent / "decoded-target"
            external_directory.mkdir()
            run = prepare_pet_run(run_parent, "bronze-moth", "original-brand", "v4")
            omitted_directory = run / "decoded"
            omitted_directory.rmdir()
            try:
                omitted_directory.symlink_to(external_directory, target_is_directory=True)
            except OSError as error:
                if getattr(error, "winerror", None) == 1314:
                    self.skipTest("Windows policy does not permit the symlink probe")
                raise
            before = _tree_snapshot(workspace)

            with self.assertRaises(ValueError):
                build_synthetic_dry_run(run)

            self.assertEqual(_tree_snapshot(workspace), before)
            self.assertEqual(sentinel.read_bytes(), b"preserve")

    def test_builder_rejects_a_preexisting_symlink_leaf_without_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            run_parent = workspace / "runs"
            run_parent.mkdir()
            sentinel = workspace / "outside" / "user-owned.txt"
            sentinel.parent.mkdir()
            sentinel.write_text("preserve", encoding="utf-8")
            run = prepare_pet_run(run_parent, "bronze-moth", "original-brand", "v4")
            symlinked_leaf = run / "frames" / "canonical-identity.png"
            try:
                symlinked_leaf.symlink_to(sentinel)
            except OSError as error:
                if getattr(error, "winerror", None) == 1314:
                    self.skipTest("Windows policy does not permit the symlink probe")
                raise
            before = _tree_snapshot(workspace)

            with self.assertRaisesRegex(ValueError, "symlink or reparse point"):
                build_synthetic_dry_run(run)

            self.assertEqual(_tree_snapshot(workspace), before)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
