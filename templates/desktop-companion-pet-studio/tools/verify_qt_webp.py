from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Sequence


def emit_result(
    *,
    ok: bool,
    width: int = 0,
    height: int = 0,
    has_alpha: bool = False,
    alpha_min: int | None = None,
    alpha_max: int | None = None,
) -> None:
    print(
        json.dumps(
            {
                "ok": ok,
                "width": width,
                "height": height,
                "hasAlpha": has_alpha,
                "alphaMin": alpha_min,
                "alphaMax": alpha_max,
            },
            separators=(",", ":"),
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("Expected exactly one WebP path.", file=sys.stderr)
        emit_result(ok=False)
        return 1

    image_path = Path(arguments[0])
    if not image_path.is_file():
        print(f"WebP file does not exist: {image_path}", file=sys.stderr)
        emit_result(ok=False)
        return 1

    try:
        from PySide6.QtGui import QImage

        image = QImage(str(image_path))
        if image.isNull():
            print("Qt could not decode the WebP image.", file=sys.stderr)
            emit_result(ok=False)
            return 1
        width = image.width()
        height = image.height()
        rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
        if rgba.isNull():
            print("Qt could not normalize the decoded WebP image.", file=sys.stderr)
            emit_result(ok=False)
            return 1
        has_alpha = True
        alpha_values = [rgba.pixelColor(x, y).alpha() for y in range(height) for x in range(width)]
        alpha_min = min(alpha_values)
        alpha_max = max(alpha_values)
        result = {
            "ok": True,
            "width": width,
            "height": height,
            "hasAlpha": has_alpha,
            "alphaMin": alpha_min,
            "alphaMax": alpha_max,
        }
    except Exception as error:
        print(f"Qt WebP probe failed: {error}", file=sys.stderr)
        emit_result(ok=False)
        return 1

    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["ok"] and result["hasAlpha"] and result["alphaMin"] == 0 and result["alphaMax"] == 255 else 1


if __name__ == "__main__":
    raise SystemExit(main())
