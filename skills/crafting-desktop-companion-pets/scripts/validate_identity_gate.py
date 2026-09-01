from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from contracts import evaluate_identity_gate


class InputError(Exception):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InputError(f"Cannot read JSON from {path}: {error}") from error


def _json_object(path: Path, label: str) -> dict[str, object]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise InputError(f"{label} must contain a JSON object: {path}")
    return payload


def _read_references(path: Path) -> list[dict[str, object]]:
    payload = _json_object(path, "references")
    sources = payload.get("sources")
    if not isinstance(sources, list) or not all(isinstance(source, dict) for source in sources):
        raise InputError(f"references.sources must be a list of objects: {path}")
    return sources


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _ArgumentParser(
        description="Evaluate the DesktopCompanion canonical identity gate."
    )
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--references", required=True, type=Path)
    parser.add_argument("--verdict", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        contract = _json_object(args.identity, "identity")
        references = _read_references(args.references)
        verdicts = [_json_object(path, "verdict") for path in args.verdict]
    except InputError as error:
        print(error, file=sys.stderr)
        return 1

    result = evaluate_identity_gate(contract, references, verdicts)
    try:
        args.output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError as error:
        print(f"Cannot write output to {args.output}: {error}", file=sys.stderr)
        return 1
    return 0 if result["status"] == "identity-selected" else 2


if __name__ == "__main__":
    raise SystemExit(main())
