"""Read-only validation entry point for DesktopCompanion pet packages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from format_adapters import v2, v3, v4
from format_adapters.base import (
    CheckCollector,
    PackageCheck,
    PackageContext,
    PackageInputError,
    authoritative_schema_check,
    close_assets,
    detect_format,
    load_manifest,
    report_for,
    stable_manifest,
    validate_package_identity,
)


_ADAPTERS = {2: v2.validate, 3: v3.validate, 4: v4.validate}


def _validate_arguments(
    package_root: Path,
    runtime_repo: Path | None,
    runtime_python: Path | None,
) -> None:
    if not isinstance(package_root, Path):
        raise TypeError("package_root must be pathlib.Path")
    if runtime_repo is not None and not isinstance(runtime_repo, Path):
        raise TypeError("runtime_repo must be pathlib.Path or None")
    if runtime_python is not None and not isinstance(runtime_python, Path):
        raise TypeError("runtime_python must be pathlib.Path or None")


def validate_package(
    package_root: Path,
    runtime_repo: Path | None,
    runtime_python: Path | None,
) -> dict[str, object]:
    """Validate one package without installing, importing, or modifying it.

    The local package route is always evaluated first.  Runtime schema authority
    is explicitly optional and cannot turn an unverifiable package into a pass.
    """

    _validate_arguments(package_root, runtime_repo, runtime_python)
    collector = CheckCollector()
    manifest_data = None
    context = None
    format_version: int | None = None
    input_changed_recorded = False
    try:
        manifest_data = load_manifest(package_root)
        collector.add(
            PackageCheck(
                "PACKAGE_ROOT",
                "pass",
                "package root and manifest were read without mutation",
                {"manifest": "pet.json"},
            )
        )
        collector.add(
            PackageCheck(
                "MANIFEST_JSON",
                "pass",
                "pet.json passed bounded JSON input checks",
                {"sha256": manifest_data.manifest_sha256},
            )
        )
        context = PackageContext(
            manifest_data.root, manifest_data.manifest_path, manifest_data.manifest, []
        )
        try:
            format_version = detect_format(manifest_data.manifest)
        except ValueError as error:
            raise PackageInputError(
                "FORMAT_VERSION_INVALID", "spriteVersionNumber is invalid"
            ) from error
        collector.add(
            PackageCheck(
                "FORMAT_ROUTE",
                "pass",
                "format route was selected from spriteVersionNumber",
                {"formatVersion": format_version},
            )
        )
        package_id = validate_package_identity(context)
        collector.add(
            PackageCheck(
                "PACKAGE_ID",
                "pass",
                "manifest id matches package directory",
                {"id": package_id},
            )
        )
        for check in _ADAPTERS[format_version](context):
            collector.add(check)
    except PackageInputError as error:
        collector.blocked(error)
    except Exception as error:
        # A malformed package must never expose an implementation exception.
        collector.add(
            PackageCheck(
                "VALIDATION_INTERNAL_ERROR",
                "blocked",
                "package validation could not safely interpret package data",
                {"exception": type(error).__name__},
            )
        )
    finally:
        if context is not None:
            close_assets(context)

    if manifest_data is not None:
        if not stable_manifest(manifest_data):
            collector.add(
                PackageCheck(
                    "PACKAGE_INPUT_CHANGED",
                    "blocked",
                    "pet.json changed while it was being validated",
                    {},
                )
            )
            input_changed_recorded = True
        if format_version is not None:
            try:
                schema_check = authoritative_schema_check(
                    manifest_data, format_version, runtime_repo, runtime_python
                )
            except Exception as error:
                schema_check = PackageCheck(
                    "SCHEMA_VALIDATION",
                    "unverified",
                    "runtime schema authority could not be verified",
                    {"exception": type(error).__name__},
                )
            collector.add(schema_check)
        else:
            collector.add(
                PackageCheck(
                    "SCHEMA_VALIDATION",
                    "unverified",
                    "runtime schema route could not be selected",
                    {},
                )
            )
        if not input_changed_recorded and not stable_manifest(manifest_data):
            collector.add(
                PackageCheck(
                    "PACKAGE_INPUT_CHANGED",
                    "blocked",
                    "pet.json changed while it was being validated",
                    {},
                )
            )
    else:
        collector.add(
            PackageCheck(
                "SCHEMA_VALIDATION",
                "unverified",
                "runtime schema was not reached because manifest input was invalid",
                {},
            )
        )
    return report_for(collector.checks, format_version)


def _main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--runtime-repo", type=Path)
    parser.add_argument("--runtime-python", type=Path)
    parsed = parser.parse_args(arguments)
    report = validate_package(parsed.package_root, parsed.runtime_repo, parsed.runtime_python)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
