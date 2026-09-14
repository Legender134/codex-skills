"""Safe, byte-preserving access to checked-in routing templates."""

from pathlib import Path, PurePosixPath, PureWindowsPath

from .errors import RoutingConfigError


def _reject_unsafe_relative_path(relative_path: str) -> tuple[str, ...]:
    if not isinstance(relative_path, str) or not relative_path:
        raise RoutingConfigError("template path must be a non-empty relative string")

    normalized = relative_path.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(relative_path)
    if (
        Path(relative_path).is_absolute()
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
    ):
        raise RoutingConfigError("template path must be relative")

    components = tuple(part for part in normalized.split("/") if part not in ("", "."))
    if ".." in components:
        raise RoutingConfigError("template path may not contain '..'")
    return components


def _ensure_no_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise RoutingConfigError(f"template {label} may not be a symlink")


def load_template(source_root: Path, relative_path: str) -> bytes:
    """Return exact bytes for a regular template beneath ``source_root/templates``.

    The path is validated lexically and after resolution so traversal, absolute
    paths, symlink escapes, and non-regular files fail closed.
    """

    parts = _reject_unsafe_relative_path(relative_path)
    try:
        source_root = Path(source_root)
        templates_root = source_root / "templates"
        _ensure_no_symlink(templates_root, "root")
        resolved_root = templates_root.resolve(strict=True)
        if not resolved_root.is_dir():
            raise RoutingConfigError("template root is not a directory")

        candidate = templates_root.joinpath(*parts)
        current = templates_root
        _ensure_no_symlink(current, "root")
        for part in parts:
            current = current / part
            _ensure_no_symlink(current, "path component")

        resolved_candidate = candidate.resolve(strict=True)
        try:
            resolved_candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise RoutingConfigError("template path resolves outside the template root") from exc
        if not candidate.is_file() or candidate.is_symlink():
            raise RoutingConfigError("template path must name a regular non-symlink file")
        if not resolved_candidate.is_file():
            raise RoutingConfigError("template path must name a regular file")
        return candidate.read_bytes()
    except RoutingConfigError:
        raise
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        raise RoutingConfigError(f"unable to load template {relative_path!r}") from exc
