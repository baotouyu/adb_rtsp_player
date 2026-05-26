from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PACKAGE_PREFIX = "yoloApp_"
REQUIRED_APP_FILENAME = "sample_smart_camera"
REQUIRED_MODEL_FILENAME = "network_binary.nb"


@dataclass(frozen=True)
class YoloPackage:
    name: str
    display_name: str
    path: Path
    app_path: Path
    model_path: Path


def yolo_apps_dir(app_dir: Path | str) -> Path:
    return Path(app_dir) / "yolo_apps"


def package_display_name(package_name: str) -> str:
    if package_name.startswith(PACKAGE_PREFIX):
        return package_name[len(PACKAGE_PREFIX) :] or package_name
    return package_name


def validate_yolo_package(package_dir: Path | str) -> YoloPackage:
    path = Path(package_dir)
    app_path = path / REQUIRED_APP_FILENAME
    model_path = path / REQUIRED_MODEL_FILENAME
    required_files = (
        (REQUIRED_APP_FILENAME, app_path),
        (REQUIRED_MODEL_FILENAME, model_path),
    )
    missing: list[str] = []
    for filename, file_path in required_files:
        if not file_path.is_file():
            missing.append(filename)
    if missing:
        raise ValueError(f"{path.name} 缺少必需文件：{', '.join(missing)}")
    return YoloPackage(
        name=path.name,
        display_name=package_display_name(path.name),
        path=path,
        app_path=app_path,
        model_path=model_path,
    )


def scan_yolo_packages(apps_dir: Path | str) -> list[YoloPackage]:
    root = Path(apps_dir)
    try:
        if not root.is_dir():
            return []
        candidates = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        return []

    packages: list[YoloPackage] = []
    for candidate in candidates:
        if not candidate.name.startswith(PACKAGE_PREFIX):
            continue
        try:
            if not candidate.is_dir():
                continue
            packages.append(validate_yolo_package(candidate))
        except (OSError, ValueError):
            continue
    return packages
