from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rtsp_tool.yolo_package import (
    REQUIRED_APP_FILENAME,
    REQUIRED_MODEL_FILENAME,
    YoloPackage,
    package_display_name,
    scan_yolo_packages,
    validate_yolo_package,
    yolo_apps_dir,
)


class YoloPackageTests(unittest.TestCase):
    def _write(self, path: Path, content: str = "x") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_yolo_apps_dir_is_next_to_app_dir(self):
        self.assertEqual(yolo_apps_dir(Path("/opt/tool")), Path("/opt/tool") / "yolo_apps")

    def test_package_display_name_strips_prefix_when_present(self):
        self.assertEqual(package_display_name("yoloApp_苹果"), "苹果")
        self.assertEqual(package_display_name("other"), "other")

    def test_package_display_name_keeps_empty_suffix_package_name(self):
        self.assertEqual(package_display_name("yoloApp_"), "yoloApp_")

    def test_validate_yolo_package_accepts_required_files(self):
        with TemporaryDirectory() as tmpdir:
            package_dir = Path(tmpdir) / "yoloApp_苹果"
            self._write(package_dir / REQUIRED_APP_FILENAME)
            self._write(package_dir / REQUIRED_MODEL_FILENAME)

            package = validate_yolo_package(package_dir)

        self.assertEqual(
            package,
            YoloPackage(
                name="yoloApp_苹果",
                display_name="苹果",
                path=package_dir,
                app_path=package_dir / REQUIRED_APP_FILENAME,
                model_path=package_dir / REQUIRED_MODEL_FILENAME,
            ),
        )

    def test_validate_yolo_package_reports_missing_required_files(self):
        with TemporaryDirectory() as tmpdir:
            package_dir = Path(tmpdir) / "yoloApp_苹果"
            package_dir.mkdir()

            with self.assertRaisesRegex(ValueError, "sample_smart_camera, network_binary.nb"):
                validate_yolo_package(package_dir)

    def test_scan_yolo_packages_returns_only_valid_yolo_app_directories_sorted(self):
        with TemporaryDirectory() as tmpdir:
            apps_dir = Path(tmpdir) / "yolo_apps"
            valid_banana = apps_dir / "yoloApp_香蕉"
            valid_apple = apps_dir / "yoloApp_苹果"
            invalid = apps_dir / "yoloApp_缺文件"
            ignored = apps_dir / "other_苹果"
            for package_dir in (valid_banana, valid_apple):
                self._write(package_dir / REQUIRED_APP_FILENAME)
                self._write(package_dir / REQUIRED_MODEL_FILENAME)
            self._write(invalid / REQUIRED_APP_FILENAME)
            self._write(ignored / REQUIRED_APP_FILENAME)
            self._write(ignored / REQUIRED_MODEL_FILENAME)

            packages = scan_yolo_packages(apps_dir)

        self.assertEqual([package.name for package in packages], ["yoloApp_苹果", "yoloApp_香蕉"])
        self.assertEqual([package.display_name for package in packages], ["苹果", "香蕉"])

    def test_scan_yolo_packages_returns_empty_when_directory_is_missing(self):
        with TemporaryDirectory() as tmpdir:
            self.assertEqual(scan_yolo_packages(Path(tmpdir) / "missing"), [])


if __name__ == "__main__":
    unittest.main()
