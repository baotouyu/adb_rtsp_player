import builtins
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rtsp_tool.dependencies import (
    DependencyStatus,
    bundled_command_candidates,
    check_command,
    check_dependencies,
    check_tkinter,
    get_app_dir,
)


class DependencyTests(unittest.TestCase):
    def _touch(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    def test_dependency_status_default_source_is_unknown(self):
        status = DependencyStatus(name="custom", found=False, path=None, message="missing")

        self.assertEqual(status.source, "unknown")

    def test_bundled_command_candidates_returns_empty_for_unknown_command(self):
        with TemporaryDirectory() as tmpdir:
            candidates = bundled_command_candidates("unknown", app_dir=Path(tmpdir))

        self.assertEqual(candidates, [])

    def test_check_command_prefers_bundled_windows_adb_over_path(self):
        with TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            bundled_adb = app_dir / "tools" / "adb" / "adb.exe"
            self._touch(bundled_adb)

            with patch("rtsp_tool.dependencies.os.name", "nt"):
                with patch("rtsp_tool.dependencies.shutil.which", return_value=r"C:\Android\platform-tools\adb.exe"):
                    status = check_command("adb", app_dir=app_dir)

        self.assertEqual(status.name, "adb")
        self.assertTrue(status.found)
        self.assertEqual(status.path, str(bundled_adb))
        self.assertEqual(status.message, "found in bundled tools")
        self.assertEqual(status.source, "bundled")

    def test_check_command_prefers_bundled_windows_ffplay_over_path(self):
        with TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            bundled_ffplay = app_dir / "tools" / "ffmpeg" / "ffplay.exe"
            self._touch(bundled_ffplay)

            with patch("rtsp_tool.dependencies.os.name", "nt"):
                with patch("rtsp_tool.dependencies.shutil.which", return_value=r"C:\ffmpeg\bin\ffplay.exe"):
                    status = check_command("ffplay", app_dir=app_dir)

        self.assertEqual(status.name, "ffplay")
        self.assertTrue(status.found)
        self.assertEqual(status.path, str(bundled_ffplay))
        self.assertEqual(status.message, "found in bundled tools")
        self.assertEqual(status.source, "bundled")

    def test_check_command_falls_back_to_path_when_bundled_tool_is_missing(self):
        with TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)

            with patch("rtsp_tool.dependencies.os.name", "nt"):
                with patch("rtsp_tool.dependencies.shutil.which", return_value=r"C:\ffmpeg\bin\ffplay.exe"):
                    status = check_command("ffplay", app_dir=app_dir)

        self.assertEqual(status.name, "ffplay")
        self.assertTrue(status.found)
        self.assertEqual(status.path, r"C:\ffmpeg\bin\ffplay.exe")
        self.assertEqual(status.message, "found in PATH")
        self.assertEqual(status.source, "path")

    def test_check_command_reports_missing_when_bundled_and_path_are_missing(self):
        with TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)

            with patch("rtsp_tool.dependencies.os.name", "nt"):
                with patch("rtsp_tool.dependencies.shutil.which", return_value=None):
                    status = check_command("adb", app_dir=app_dir)

        self.assertEqual(status.name, "adb")
        self.assertFalse(status.found)
        self.assertIsNone(status.path)
        self.assertEqual(status.message, "not found in bundled tools or PATH")
        self.assertEqual(status.source, "missing")

    def test_check_tkinter_reports_stdlib_source(self):
        status = check_tkinter()

        self.assertEqual(status.name, "tkinter")
        self.assertEqual(status.source, "stdlib")
        self.assertIn(status.found, (True, False))

    def test_check_tkinter_reports_stdlib_source_when_missing(self):
        original_import = builtins.__import__

        def import_without_tkinter(name, *args, **kwargs):
            if name == "tkinter":
                raise ImportError("no tkinter")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_tkinter):
            status = check_tkinter()

        self.assertEqual(status.name, "tkinter")
        self.assertFalse(status.found)
        self.assertIsNone(status.path)
        self.assertEqual(status.message, "no tkinter")
        self.assertEqual(status.source, "stdlib")

    def test_check_dependencies_accepts_explicit_app_dir(self):
        with TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            bundled_adb = app_dir / "tools" / "adb" / "adb.exe"
            bundled_ffplay = app_dir / "tools" / "ffmpeg" / "ffplay.exe"
            self._touch(bundled_adb)
            self._touch(bundled_ffplay)

            with patch("rtsp_tool.dependencies.os.name", "nt"):
                with patch("rtsp_tool.dependencies.shutil.which", return_value=None):
                    statuses = check_dependencies(app_dir=app_dir)

        self.assertEqual(statuses["adb"].path, str(bundled_adb))
        self.assertEqual(statuses["adb"].source, "bundled")
        self.assertEqual(statuses["ffplay"].path, str(bundled_ffplay))
        self.assertEqual(statuses["ffplay"].source, "bundled")
        self.assertEqual(statuses["tkinter"].source, "stdlib")

    def test_get_app_dir_points_at_project_root_in_normal_python(self):
        self.assertEqual(get_app_dir(), Path(__file__).resolve().parents[1])

    def test_get_app_dir_points_at_executable_parent_when_frozen(self):
        with TemporaryDirectory() as tmpdir:
            fake_executable = Path(tmpdir) / "ADB_RTSP_Player.exe"

            with patch("rtsp_tool.dependencies.sys.frozen", True, create=True):
                with patch("rtsp_tool.dependencies.sys.executable", str(fake_executable)):
                    self.assertEqual(get_app_dir(), fake_executable.resolve().parent)

    def test_check_command_ignores_non_executable_bundled_tool_on_posix(self):
        with TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            bundled_ffplay = app_dir / "tools" / "ffmpeg" / "ffplay"
            self._touch(bundled_ffplay)
            bundled_ffplay.chmod(0o644)

            with patch("rtsp_tool.dependencies.os.name", "posix"):
                with patch("rtsp_tool.dependencies.os.access", return_value=False):
                    with patch("rtsp_tool.dependencies.shutil.which", return_value="/usr/local/bin/ffplay"):
                        status = check_command("ffplay", app_dir=app_dir)

        self.assertEqual(status.name, "ffplay")
        self.assertTrue(status.found)
        self.assertEqual(status.path, "/usr/local/bin/ffplay")
        self.assertEqual(status.message, "found in PATH")
        self.assertEqual(status.source, "path")


if __name__ == "__main__":
    unittest.main()
