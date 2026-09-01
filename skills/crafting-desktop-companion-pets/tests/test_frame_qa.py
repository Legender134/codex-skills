from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from PIL import Image, ImageDraw


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import make_contact_sheet as contact_sheet_module
import render_timed_previews as preview_module
from contracts import evaluate_identity_gate, sha256_file, validate_visual_verdict
from inspect_frames import inspect_frames
from make_contact_sheet import make_contact_sheet
from render_timed_previews import render_timed_preview


HASH_A = "a" * 64
HASH_B = "b" * 64


def issue_codes(issues: list[object]) -> set[str]:
    return {getattr(issue, "code") for issue in issues}


def webp_durations(path: Path) -> list[int]:
    durations: list[int] = []
    with Image.open(path) as preview:
        for index in range(preview.n_frames):
            preview.seek(index)
            preview.load()
            duration = preview.info.get("duration")
            if not isinstance(duration, int):
                raise AssertionError(f"frame {index} did not expose an integer duration")
            durations.append(duration)
    return durations


def rgba_pixel_hash(image: Image.Image) -> str:
    return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def decoded_webp_hashes(path: Path) -> list[str]:
    hashes: list[str] = []
    with Image.open(path) as preview:
        for index in range(preview.n_frames):
            preview.seek(index)
            preview.load()
            hashes.append(rgba_pixel_hash(preview))
    return hashes


def write_png_header(path: Path, width: int, height: int) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")
    )


class FrameQualityAssuranceTest(unittest.TestCase):
    def _write_frame(self, path: Path, left: int, *, right_edge: bool = False) -> None:
        image = Image.new("RGBA", (64, 80), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        right = 63 if right_edge else left + 19
        draw.rectangle((left, 32, right, 71), fill=(40, 120, 220, 255))
        image.save(path, format="PNG")

    def _write_three_frames(self, root: Path) -> list[Path]:
        frame_1 = root / "frame-1.png"
        frame_2 = root / "frame-2.png"
        frame_3 = root / "frame-3.png"
        self._write_frame(frame_1, 20)
        self._write_frame(frame_2, 22)
        self._write_frame(frame_3, 44, right_edge=True)
        return [frame_1, frame_2, frame_3]

    def _contact_records(self, paths: list[Path]) -> list[dict[str, object]]:
        return [
            {"label": "frame-2 | preparation", "path": str(paths[1])},
            {"label": "frame-1 | entry", "path": str(paths[0])},
            {"label": "frame-3 | recovery", "path": str(paths[2])},
        ]

    def _assert_untrusted_png_header_rejected_without_artifacts(
        self, root: Path, name: str, width: int, height: int
    ) -> None:
        existing_names = {path.name for path in root.iterdir()}
        source = root / f"{name}.png"
        write_png_header(source, width, height)
        source_bytes = source.read_bytes()
        contact_output = root / f"{name}-contact.png"
        preview_output = root / f"{name}-preview.webp"
        original_pillow_limit = Image.MAX_IMAGE_PIXELS

        with self.assertRaisesRegex(ValueError, "unsafe canvas"):
            inspect_frames([source])
        with self.assertRaisesRegex(ValueError, "unsafe canvas"):
            make_contact_sheet(
                [{"label": name, "path": str(source)}],
                contact_output,
                columns=1,
                display_scale=1.0,
            )
        with self.assertRaisesRegex(ValueError, "unsafe canvas"):
            render_timed_preview([source], [80], preview_output, loop=0)

        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual(Image.MAX_IMAGE_PIXELS, original_pillow_limit)
        self.assertFalse(contact_output.exists())
        self.assertFalse(contact_output.with_suffix(contact_output.suffix + ".json").exists())
        self.assertFalse(preview_output.exists())
        self.assertEqual(
            {path.name for path in root.iterdir()}, existing_names | {source.name}
        )

    def _assert_pair_restored_after_second_publication_failure(
        self, has_prior_pair: bool
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = self._write_three_frames(root)
            output = root / "contact-sheet.png"
            sidecar = output.with_suffix(output.suffix + ".json")
            prior_png = b"prior contact PNG\n"
            prior_sidecar = b'{"prior": true}\n'
            if has_prior_pair:
                output.write_bytes(prior_png)
                sidecar.write_bytes(prior_sidecar)

            real_replace = contact_sheet_module.os.replace
            publish_count = 0

            def fail_second_publication(source: object, destination: object) -> object:
                nonlocal publish_count
                if Path(destination).resolve() in {output.resolve(), sidecar.resolve()}:
                    publish_count += 1
                    if publish_count == 2:
                        raise OSError("injected second contact publication failure")
                return real_replace(source, destination)

            with patch.object(
                contact_sheet_module.os,
                "replace",
                side_effect=fail_second_publication,
            ):
                with self.assertRaisesRegex(
                    OSError, "injected second contact publication failure"
                ):
                    make_contact_sheet(
                        self._contact_records(paths),
                        output,
                        columns=2,
                        display_scale=1.25,
                    )

            if has_prior_pair:
                self.assertEqual(output.read_bytes(), prior_png)
                self.assertEqual(sidecar.read_bytes(), prior_sidecar)
            else:
                self.assertFalse(output.exists())
                self.assertFalse(sidecar.exists())
            self.assertFalse(any(path.name.startswith(".") for path in root.iterdir()))

    def test_inspect_frames_reports_ordered_alpha_clipping_components_and_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            paths = self._write_three_frames(Path(raw))

            report = inspect_frames(paths, expected_canvas=(64, 80))

            self.assertTrue(report["diagnosticOnly"])
            self.assertNotIn("decision", report)
            self.assertNotIn("pass", report)
            self.assertEqual(report["expectedCanvas"], [64, 80])
            records = report["frames"]
            self.assertEqual(len(records), 3)
            self.assertEqual([record["index"] for record in records], [0, 1, 2])
            self.assertEqual(
                [Path(str(record["path"])).resolve() for record in records],
                [path.resolve() for path in paths],
            )
            self.assertEqual(records[0]["canvas"], [64, 80])
            self.assertEqual(records[0]["mode"], "RGBA")
            self.assertEqual(records[0]["alphaBoundingBox"], [20, 32, 40, 72])
            self.assertEqual(records[1]["alphaBoundingBox"], [22, 32, 42, 72])
            self.assertEqual(records[0]["alphaPixels"], 800)
            self.assertEqual(records[2]["clippedRight"], True)
            self.assertEqual(records[2]["clippedLeft"], False)
            self.assertEqual(records[2]["clippedTop"], False)
            self.assertEqual(records[2]["clippedBottom"], False)
            self.assertEqual(records[0]["componentCount"], 1)
            self.assertEqual(
                records[0]["components"],
                [{"index": 0, "boundingBox": [20, 32, 40, 72], "alphaPixels": 800}],
            )
            self.assertEqual(records[0]["bottomCenterAnchor"], [29.5, 71.0])
            self.assertEqual(records[1]["anchorDriftFromFirst"], [2.0, 0.0])

    def test_inspect_frames_rejects_invalid_inputs_and_uses_iterative_components(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            empty = root / "empty.png"
            Image.new("RGBA", (64, 80), (0, 0, 0, 0)).save(empty, format="PNG")
            corrupt = root / "corrupt.png"
            corrupt.write_bytes(b"not an image")
            tall = root / "tall.png"
            Image.new("RGBA", (1, 4096), (180, 80, 40, 255)).save(tall, format="PNG")

            with self.assertRaisesRegex(ValueError, "non-empty"):
                inspect_frames([], expected_canvas=(64, 80))
            with self.assertRaisesRegex(ValueError, "expected_canvas"):
                inspect_frames([tall], expected_canvas=(True, 80))
            with self.assertRaisesRegex(ValueError, "visible"):
                inspect_frames([empty])
            with self.assertRaisesRegex(ValueError, "RGBA"):
                inspect_frames([corrupt])

            report = inspect_frames([tall], expected_canvas=(1, 4096))
            self.assertEqual(report["frames"][0]["componentCount"], 1)
            self.assertEqual(report["frames"][0]["components"][0]["alphaPixels"], 4096)

    def test_untrusted_png_headers_fail_before_decode_without_artifact_residue(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with self.subTest(case="pillow-bomb"):
                self._assert_untrusted_png_header_rejected_without_artifacts(
                    root, "pillow-bomb", 1_000_000, 1_000_000
                )
            with self.subTest(case="skill-cap-below-pillow-threshold"):
                self._assert_untrusted_png_header_rejected_without_artifacts(
                    root, "skill-cap", 4097, 4097
                )

    def test_contact_sheet_preserves_manifest_order_hashes_parameters_and_backgrounds(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = self._write_three_frames(root)
            records = self._contact_records(paths)
            output = root / "contact-sheet.png"

            result = make_contact_sheet(records, output, columns=2, display_scale=1.25)

            sidecar_path = output.with_suffix(output.suffix + ".json")
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            self.assertTrue(output.is_file())
            self.assertEqual(result, sidecar)
            self.assertTrue(sidecar["diagnosticOnly"])
            self.assertNotIn("decision", sidecar)
            self.assertEqual(sidecar["columns"], 2)
            self.assertEqual(sidecar["displayScale"], 1.25)
            self.assertEqual(sidecar["backgrounds"], ["checker", "light", "dark"])
            self.assertEqual(
                [record["label"] for record in sidecar["frames"]],
                ["frame-2 | preparation", "frame-1 | entry", "frame-3 | recovery"],
            )
            self.assertEqual(
                [Path(str(record["path"])).resolve() for record in sidecar["frames"]],
                [paths[1].resolve(), paths[0].resolve(), paths[2].resolve()],
            )
            self.assertEqual(
                [record["sha256"] for record in sidecar["frames"]],
                [
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in [paths[1], paths[0], paths[2]]
                ],
            )
            self.assertEqual(
                [record["displayCanvas"] for record in sidecar["frames"]],
                [[80, 100], [80, 100], [80, 100]],
            )

    def test_contact_sheet_rejects_invalid_metadata_and_input_aliases_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = self._write_three_frames(root)
            output = root / "contact-sheet.png"
            source_bytes = {path: path.read_bytes() for path in paths}

            invalid_cases: list[tuple[object, int, float]] = [
                ([], 2, 1.0),
                ([{"label": "", "path": str(paths[0])}], 2, 1.0),
                ([{"label": "\ud800", "path": str(paths[0])}], 2, 1.0),
                (self._contact_records(paths), True, 1.0),
                (self._contact_records(paths), 2, float("nan")),
            ]
            for frames, columns, display_scale in invalid_cases:
                with self.subTest(frames=repr(frames), columns=columns, display_scale=display_scale):
                    with self.assertRaises(ValueError):
                        make_contact_sheet(frames, output, columns, display_scale)
                    self.assertFalse(output.exists())
                    self.assertFalse(output.with_suffix(output.suffix + ".json").exists())

            sidecar_input = output.with_suffix(output.suffix + ".json")
            self._write_frame(sidecar_input, 20)
            sidecar_source_bytes = sidecar_input.read_bytes()
            aliased_records = [{"label": "sidecar input", "path": str(sidecar_input)}]
            with self.assertRaisesRegex(ValueError, "match an input"):
                make_contact_sheet(aliased_records, output, columns=1, display_scale=1.0)
            self.assertEqual(sidecar_input.read_bytes(), sidecar_source_bytes)
            self.assertFalse(output.exists())

            output_alias = Path(str(root) + "\\nested\\..\\frame-1.png")
            with self.assertRaisesRegex(ValueError, "match an input"):
                make_contact_sheet(
                    [{"label": "output input", "path": str(paths[0])}],
                    output_alias,
                    columns=1,
                    display_scale=1.0,
                )
            self.assertEqual(
                {path: path.read_bytes() for path in source_bytes}, source_bytes
            )

    def test_frame_qa_json_boundary_rejects_nonfinite_extension_values_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = self._write_three_frames(root)
            output = root / "contact-sheet.png"
            frames = [
                {
                    "label": "frame-1",
                    "path": str(paths[0]),
                    "extension": {"untrusted": float("nan")},
                }
            ]

            with self.assertRaisesRegex(ValueError, "JSON-compatible"):
                make_contact_sheet(frames, output, columns=1, display_scale=1.0)

            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(output.suffix + ".json").exists())

        verdict = {
            "verdictId": "review-1",
            "gate": "identity",
            "decision": "pass",
            "artifactSha256": HASH_A,
            "reviewScale": "actual-runtime-size",
            "reviewer": {"type": "user", "id": "person-1"},
            "observations": ["Actual-size silhouette is readable."],
            "blockingObservations": [],
            "extension": {"untrusted": float("inf")},
        }
        self.assertIn(
            "JSON_STRUCTURE_NUMBER_INVALID",
            issue_codes(validate_visual_verdict(verdict)),
        )

    def test_contact_sheet_restores_pair_on_second_publication_failure(self) -> None:
        self._assert_pair_restored_after_second_publication_failure(has_prior_pair=False)
        self._assert_pair_restored_after_second_publication_failure(has_prior_pair=True)

    def test_timed_preview_preserves_exact_durations_and_reports_technical_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = self._write_three_frames(root)
            output = root / "preview.webp"

            result = render_timed_preview(paths, [80, 240, 120], output, loop=2)

            self.assertTrue(output.is_file())
            with Image.open(output) as preview:
                self.assertEqual(preview.n_frames, 3)
                self.assertEqual(preview.info.get("loop"), 2)
            self.assertEqual(webp_durations(output), [80, 240, 120])
            self.assertEqual(result["technicalStatus"], "pass")
            self.assertEqual(result["frameCount"], 3)
            self.assertEqual(result["durationsMs"], [80, 240, 120])
            self.assertNotIn("decision", result)
            self.assertNotIn("visualStatus", result)

    def test_timed_preview_rejects_bad_timing_and_aliases_and_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = self._write_three_frames(root)
            output = root / "preview.webp"
            original = b"existing preview bytes\n"
            output.write_bytes(original)
            source_bytes = {path: path.read_bytes() for path in paths}

            invalid_cases = [
                ([], [], output, 0),
                ([paths[0]], [80, 240], output, 0),
                ([paths[0]], [True], output, 0),
                ([paths[0]], [0], output, 0),
                ([paths[0]], [80], output, True),
                ([paths[0]], [80], output, -1),
                ([paths[0]], [80], Path(str(root) + "\\nested\\..\\frame-1.png"), 0),
            ]
            for frame_paths, durations, selected_output, loop in invalid_cases:
                with self.subTest(
                    frame_paths=repr(frame_paths),
                    durations=durations,
                    output=str(selected_output),
                    loop=loop,
                ):
                    with self.assertRaises(ValueError):
                        render_timed_preview(frame_paths, durations, selected_output, loop)
                    self.assertEqual(output.read_bytes(), original)
                    self.assertEqual(
                        {path: path.read_bytes() for path in source_bytes}, source_bytes
                    )

            real_replace = preview_module.os.replace

            def fail_publication(source: object, destination: object) -> object:
                if Path(destination).resolve() == output.resolve():
                    raise OSError("injected preview publication failure")
                return real_replace(source, destination)

            with patch.object(preview_module.os, "replace", side_effect=fail_publication):
                with self.assertRaisesRegex(OSError, "injected preview publication failure"):
                    render_timed_preview(paths, [80, 240, 120], output, loop=0)
            self.assertEqual(output.read_bytes(), original)
            self.assertFalse(any(path.name.startswith(".") for path in root.iterdir()))

    def test_timed_preview_retains_single_identical_and_alpha_frames_losslessly(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            single = root / "single.png"
            self._write_frame(single, 20)

            identical_paths: list[Path] = []
            for index in range(3):
                path = root / f"identical-{index}.png"
                self._write_frame(path, 20)
                identical_paths.append(path)

            opaque = root / "opaque.png"
            transparent = root / "transparent.png"
            opaque_image = Image.new("RGBA", (64, 80), (210, 40, 20, 0))
            ImageDraw.Draw(opaque_image).rectangle(
                (20, 32, 39, 71), fill=(20, 120, 220, 255)
            )
            opaque_image.save(opaque, format="PNG")
            transparent_image = Image.new("RGBA", (64, 80), (40, 210, 20, 0))
            ImageDraw.Draw(transparent_image).rectangle(
                (20, 32, 39, 71), fill=(20, 120, 220, 128)
            )
            transparent_image.save(transparent, format="PNG")

            cases = [
                ("single", [single], [73], 1),
                ("two-identical", identical_paths[:2], [80, 240], 2),
                ("three-identical", identical_paths, [80, 240, 120], 0),
                ("alpha", [opaque, transparent], [110, 130], 7),
            ]
            for label, paths, durations, loop in cases:
                with self.subTest(label=label):
                    output = root / f"{label}.webp"
                    result = render_timed_preview(paths, durations, output, loop)
                    with Image.open(output) as preview:
                        self.assertEqual(preview.n_frames, len(paths))
                        self.assertEqual(preview.size, (64, 80))
                        self.assertEqual(preview.info.get("loop"), loop)
                    self.assertEqual(webp_durations(output), durations)
                    expected_hashes = []
                    for path in paths:
                        with Image.open(path) as source:
                            source.load()
                            expected_hashes.append(rgba_pixel_hash(source))
                    self.assertEqual(decoded_webp_hashes(output), expected_hashes)
                    self.assertEqual(result["frameCount"], len(paths))

    def test_contact_and_preview_reject_hard_link_aliases_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source.png"
            self._write_frame(source, 20)
            source_bytes = source.read_bytes()

            output_alias = root / "output-alias.png"
            os.link(source, output_alias)
            with self.assertRaisesRegex(ValueError, "match an input"):
                make_contact_sheet(
                    [{"label": "source", "path": str(source)}],
                    output_alias,
                    columns=1,
                    display_scale=1.0,
                )
            self.assertEqual(source.read_bytes(), source_bytes)

            sidecar_output = root / "sidecar-output.png"
            sidecar_alias = sidecar_output.with_suffix(sidecar_output.suffix + ".json")
            os.link(source, sidecar_alias)
            with self.assertRaisesRegex(ValueError, "match an input"):
                make_contact_sheet(
                    [{"label": "source", "path": str(source)}],
                    sidecar_output,
                    columns=1,
                    display_scale=1.0,
                )
            self.assertEqual(source.read_bytes(), source_bytes)

            webp_source = root / "source.webp"
            with Image.open(source) as image:
                image.save(webp_source, format="WEBP", lossless=True, exact=True)
            preview_alias = root / "preview-alias.webp"
            os.link(webp_source, preview_alias)
            preview_source_bytes = webp_source.read_bytes()
            with self.assertRaisesRegex(ValueError, "match an input"):
                render_timed_preview([webp_source], [80], preview_alias, loop=0)
            self.assertEqual(webp_source.read_bytes(), preview_source_bytes)

    def test_contact_sheet_cleans_up_when_either_temporary_creation_fails(self) -> None:
        for failure_number in (1, 2):
            with self.subTest(failure_number=failure_number), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                source = root / "source.png"
                output = root / "contact-sheet.png"
                self._write_frame(source, 20)
                source_bytes = source.read_bytes()
                real_temporary_path = contact_sheet_module._temporary_path
                calls = 0

                def fail_selected_temporary(*args: object, **kwargs: object) -> Path:
                    nonlocal calls
                    calls += 1
                    if calls == failure_number:
                        raise OSError("injected temporary creation failure")
                    return real_temporary_path(*args, **kwargs)

                with patch.object(
                    contact_sheet_module,
                    "_temporary_path",
                    side_effect=fail_selected_temporary,
                ):
                    with self.assertRaisesRegex(OSError, "injected temporary creation failure"):
                        make_contact_sheet(
                            [{"label": "source", "path": str(source)}],
                            output,
                            columns=1,
                            display_scale=1.0,
                        )

                self.assertEqual(source.read_bytes(), source_bytes)
                self.assertFalse(output.exists())
                self.assertFalse(output.with_suffix(output.suffix + ".json").exists())
                self.assertFalse(any(path.name.startswith(".") for path in root.iterdir()))

    def test_contact_sheet_uses_traceable_cjk_label_evidence_and_distinct_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source.png"
            self._write_frame(source, 20)
            png_bytes: list[bytes] = []
            for label, codepoint in (("陈", "U+9648"), ("巧", "U+5DE7"), ("倩", "U+5029")):
                with self.subTest(label=label):
                    output = root / f"{codepoint}.png"
                    result = make_contact_sheet(
                        [{"label": label, "path": str(source)}],
                        output,
                        columns=1,
                        display_scale=1.0,
                    )
                    self.assertEqual(
                        result["frames"][0]["labelEvidence"], f"{label} [{codepoint}]"
                    )
                    self.assertEqual(
                        result["labelRendering"]["nonAsciiFallback"],
                        "unicode-codepoint-ascii",
                    )
                    self.assertIn(
                        result["labelRendering"]["route"],
                        {"cjk-system-font", "pillow-default-fallback"},
                    )
                    png_bytes.append(output.read_bytes())
            self.assertEqual(len(set(png_bytes)), 3)

    def test_contact_and_preview_reject_resource_bound_excesses_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source.png"
            self._write_frame(source, 20)
            contact_output = root / "contact-sheet.png"
            preview_output = root / "preview.webp"
            records = [{"label": "source", "path": str(source)}]

            for columns, display_scale in ((1025, 1.0), (1, 1e308), (1, 10**1000)):
                with self.subTest(columns=columns, display_scale=repr(display_scale)):
                    with self.assertRaises(ValueError):
                        make_contact_sheet(records, contact_output, columns, display_scale)
                    self.assertFalse(contact_output.exists())
                    self.assertFalse(contact_output.with_suffix(contact_output.suffix + ".json").exists())

            for durations, loop in (([0x1000000], 0), ([80], 0x10000)):
                with self.subTest(durations=durations, loop=loop):
                    with self.assertRaises(ValueError):
                        render_timed_preview([source], durations, preview_output, loop)
                    self.assertFalse(preview_output.exists())

    def test_contact_sheet_and_preview_reject_empty_alpha_without_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            empty = root / "empty.png"
            Image.new("RGBA", (64, 80), (0, 0, 0, 0)).save(empty, format="PNG")
            contact_output = root / "contact-sheet.png"
            preview_output = root / "preview.webp"

            with self.assertRaisesRegex(ValueError, "visible"):
                make_contact_sheet(
                    [{"label": "empty", "path": str(empty)}],
                    contact_output,
                    columns=1,
                    display_scale=1.0,
                )
            with self.assertRaisesRegex(ValueError, "visible"):
                render_timed_preview([empty], [80], preview_output, loop=0)

            self.assertFalse(contact_output.exists())
            self.assertFalse(contact_output.with_suffix(contact_output.suffix + ".json").exists())
            self.assertFalse(preview_output.exists())

    def test_visual_verdict_enforces_actual_size_hash_authority_and_nonpassing_review(self) -> None:
        verdict = {
            "verdictId": "identity-review-1",
            "gate": "identity",
            "decision": "pass",
            "artifactSha256": HASH_A,
            "reviewedArtifactSha256": HASH_A,
            "canonicalSubjectSha256": HASH_A,
            "reviewScale": "actual-runtime-size",
            "reviewer": {"type": "independent", "id": "reviewer-1"},
            "observations": ["Adult silhouette and costume blocks remain readable."],
            "blockingObservations": [],
        }
        self.assertEqual(validate_visual_verdict(verdict), [])

        enlarged_only = dict(verdict, reviewScale="enlarged-only")
        self.assertIn(
            "IDENTITY_PASS_REQUIRES_ACTUAL_RUNTIME_SIZE",
            issue_codes(validate_visual_verdict(enlarged_only)),
        )

        mismatched_hash = dict(verdict, canonicalSubjectSha256=HASH_B)
        self.assertIn(
            "VERDICT_ARTIFACT_HASH_MISMATCH",
            issue_codes(validate_visual_verdict(mismatched_hash)),
        )

        technical_script = dict(
            verdict,
            reviewer={"type": "technical-script", "id": "frame-checker"},
        )
        self.assertIn(
            "VISUAL_PASS_REVIEWER_UNAUTHORIZED",
            issue_codes(validate_visual_verdict(technical_script)),
        )

        needs_review = dict(
            verdict,
            decision="needs-review",
            reviewer={"type": "unassigned", "id": None},
            observations=[],
        )
        self.assertEqual(validate_visual_verdict(needs_review), [])

        with tempfile.TemporaryDirectory() as raw:
            canonical = Path(raw) / "canonical.png"
            canonical.write_bytes(b"canonical identity")
            canonical_hash = sha256_file(canonical)
            needs_review["artifactSha256"] = canonical_hash
            needs_review["reviewedArtifactSha256"] = canonical_hash
            needs_review["canonicalSubjectSha256"] = canonical_hash
            result = evaluate_identity_gate(
                {
                    "identityRoute": "source-faithful",
                    "referenceIds": ["identity", "proportion"],
                    "canonicalPath": str(canonical),
                    "canonicalSha256": canonical_hash,
                    "technicalStatus": "pass",
                    "authority": {"identityUncertaintyApproved": False},
                },
                [
                    {
                        "id": "identity",
                        "roles": ["identity"],
                        "allowedUses": ["canonical-identity"],
                        "evidenceClass": "current-official",
                    },
                    {
                        "id": "proportion",
                        "roles": ["proportion"],
                        "allowedUses": ["canonical-identity"],
                        "evidenceClass": "same-character-current",
                    },
                ],
                [needs_review],
            )
            self.assertEqual(result["status"], "visual-candidate")
            self.assertEqual(result["acceptedVerdictIds"], [])

    def test_visual_terminal_gate_scale_mapping_rejects_unreviewed_scales(self) -> None:
        base = {
            "verdictId": "review-1",
            "decision": "pass",
            "artifactSha256": HASH_A,
            "reviewScale": "not-reviewed",
            "reviewer": {"type": "independent", "id": "reviewer-1"},
            "observations": ["Reviewed at the declared scale."],
            "blockingObservations": [],
        }
        for gate in ("motion", "action", "visual"):
            with self.subTest(gate=gate):
                self.assertIn(
                    "VISUAL_TERMINAL_REVIEW_SCALE_INVALID",
                    issue_codes(validate_visual_verdict({**base, "gate": gate})),
                )
        failed_action = {
            **base,
            "gate": "action",
            "decision": "fail",
            "blockingObservations": ["The hand pose is not readable."],
        }
        self.assertIn(
            "VISUAL_TERMINAL_REVIEW_SCALE_INVALID",
            issue_codes(validate_visual_verdict(failed_action)),
        )
        self.assertEqual(
            validate_visual_verdict(
                {**base, "gate": "motion", "reviewScale": "actual-runtime-size-plus-detail"}
            ),
            [],
        )
        self.assertIn(
            "VISUAL_PASS_REQUIRES_ACTUAL_RUNTIME_OR_DETAIL",
            issue_codes(
                validate_visual_verdict(
                    {**base, "gate": "motion", "reviewScale": "enlarged-only"}
                )
            ),
        )
        self.assertEqual(
            validate_visual_verdict(
                {
                    **base,
                    "gate": "action",
                    "decision": "fail",
                    "reviewScale": "enlarged-only",
                    "blockingObservations": ["The hand pose is not readable."],
                }
            ),
            [],
        )

    def test_visual_verdict_requires_notes_for_terminal_decisions_and_handles_invalid_json_values(self) -> None:
        pass_without_notes = {
            "verdictId": "identity-review-1",
            "gate": "visual",
            "decision": "pass",
            "artifactSha256": HASH_A,
            "reviewScale": "actual-runtime-size",
            "reviewer": {"type": "user", "id": "person-1"},
            "observations": [],
            "blockingObservations": [],
        }
        self.assertIn(
            "VERDICT_EVIDENCE_NOTES_REQUIRED",
            issue_codes(validate_visual_verdict(pass_without_notes)),
        )
        omitted_observations = dict(pass_without_notes)
        omitted_observations.pop("observations")
        self.assertIn(
            "VERDICT_EVIDENCE_NOTES_REQUIRED",
            issue_codes(validate_visual_verdict(omitted_observations)),
        )

        with tempfile.TemporaryDirectory() as raw:
            canonical = Path(raw) / "canonical.png"
            canonical.write_bytes(b"canonical identity")
            canonical_hash = sha256_file(canonical)
            without_notes = dict(omitted_observations, artifactSha256=canonical_hash)
            result = evaluate_identity_gate(
                {
                    "identityRoute": "source-faithful",
                    "referenceIds": ["identity", "proportion"],
                    "canonicalPath": str(canonical),
                    "canonicalSha256": canonical_hash,
                    "technicalStatus": "pass",
                    "authority": {"identityUncertaintyApproved": False},
                },
                [
                    {
                        "id": "identity",
                        "roles": ["identity"],
                        "allowedUses": ["canonical-identity"],
                        "evidenceClass": "current-official",
                    },
                    {
                        "id": "proportion",
                        "roles": ["proportion"],
                        "allowedUses": ["canonical-identity"],
                        "evidenceClass": "same-character-current",
                    },
                ],
                [without_notes],
            )
            self.assertNotEqual(result["status"], "identity-selected")

        fail_without_blocker = dict(
            pass_without_notes,
            decision="fail",
            observations=["Hands are not readable at actual size."],
        )
        self.assertIn(
            "VERDICT_BLOCKING_OBSERVATIONS_REQUIRED",
            issue_codes(validate_visual_verdict(fail_without_blocker)),
        )

        malformed = dict(pass_without_notes, artifactSha256=True)
        self.assertIn(
            "VERDICT_ARTIFACT_SHA256_INVALID",
            issue_codes(validate_visual_verdict(malformed)),
        )
        unicode_invalid = dict(pass_without_notes, observations=["\ud800"])
        self.assertIn(
            "JSON_STRUCTURE_TEXT_INVALID",
            issue_codes(validate_visual_verdict(unicode_invalid)),
        )


if __name__ == "__main__":
    unittest.main()
