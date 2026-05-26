from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys


_NATIVE_PATH_CLASS = type(Path())


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    found: bool
    path: str | None
    message: str
    source: str = "unknown"


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return _NATIVE_PATH_CLASS(sys.executable).resolve().parent
    return _NATIVE_PATH_CLASS(__file__).resolve().parents[1]


def _command_filename(name: str) -> str:
    if os.name == "nt":
        return f"{name}.exe"
    return name


def bundled_command_candidates(name: str, app_dir: Path | str | None = None) -> list[Path]:
    base_dir = _NATIVE_PATH_CLASS(app_dir) if app_dir is not None else get_app_dir()
    executable = _command_filename(name)
    if name == "adb":
        return [base_dir / "tools" / "adb" / executable]
    if name == "ffplay":
        return [base_dir / "tools" / "ffmpeg" / executable]
    return []


def _is_usable_command(path: Path) -> bool:
    if not path.is_file():
        return False
    if os.name == "nt":
        return True
    return os.access(path, os.X_OK)


def check_command(name: str, app_dir: Path | str | None = None) -> DependencyStatus:
    for candidate in bundled_command_candidates(name, app_dir=app_dir):
        if _is_usable_command(candidate):
            return DependencyStatus(
                name=name,
                found=True,
                path=str(candidate),
                message="found in bundled tools",
                source="bundled",
            )

    path = shutil.which(name)
    if path:
        return DependencyStatus(name=name, found=True, path=path, message="found in PATH", source="path")
    return DependencyStatus(
        name=name,
        found=False,
        path=None,
        message="not found in bundled tools or PATH",
        source="missing",
    )


def check_tkinter() -> DependencyStatus:
    try:
        import tkinter  # noqa: F401
    except Exception as exc:
        return DependencyStatus(name="tkinter", found=False, path=None, message=str(exc), source="stdlib")
    return DependencyStatus(name="tkinter", found=True, path="python stdlib", message="found", source="stdlib")


def check_dependencies(app_dir: Path | str | None = None) -> dict[str, DependencyStatus]:
    return {
        "adb": check_command("adb", app_dir=app_dir),
        "ffplay": check_command("ffplay", app_dir=app_dir),
        "tkinter": check_tkinter(),
    }
