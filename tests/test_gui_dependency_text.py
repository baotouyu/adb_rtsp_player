import unittest

from rtsp_tool.dependencies import DependencyStatus
from rtsp_tool.gui import dependency_detail_text, dependency_log_text


class GuiDependencyTextTests(unittest.TestCase):
    def test_bundled_dependency_text_names_bundled_source(self):
        status = DependencyStatus(
            name="adb",
            found=True,
            path=r"C:\App\tools\adb\adb.exe",
            message="found in bundled tools",
            source="bundled",
        )

        self.assertEqual(dependency_detail_text(status), r"内置 C:\App\tools\adb\adb.exe")
        self.assertEqual(dependency_log_text(status), r"adb 已找到（内置）：C:\App\tools\adb\adb.exe")

    def test_path_dependency_text_names_path_source(self):
        status = DependencyStatus(
            name="ffplay",
            found=True,
            path=r"C:\ffmpeg\bin\ffplay.exe",
            message="found in PATH",
            source="path",
        )

        self.assertEqual(dependency_detail_text(status), r"PATH C:\ffmpeg\bin\ffplay.exe")
        self.assertEqual(dependency_log_text(status), r"ffplay 已找到（PATH）：C:\ffmpeg\bin\ffplay.exe")

    def test_stdlib_dependency_text_uses_python_stdlib(self):
        status = DependencyStatus(
            name="tkinter",
            found=True,
            path="python stdlib",
            message="found",
            source="stdlib",
        )

        self.assertEqual(dependency_detail_text(status), "python stdlib")
        self.assertEqual(dependency_log_text(status), "tkinter 已找到：python stdlib")

    def test_missing_dependency_text_explains_bundle_and_path_lookup(self):
        status = DependencyStatus(
            name="adb",
            found=False,
            path=None,
            message="not found in bundled tools or PATH",
            source="missing",
        )

        self.assertEqual(dependency_detail_text(status), "未找到内置工具，PATH 中也不存在")
        self.assertEqual(dependency_log_text(status), "adb 缺失：未找到内置工具，PATH 中也不存在")

    def test_bundled_dependency_without_path_uses_message(self):
        status = DependencyStatus(
            name="adb",
            found=True,
            path=None,
            message="found in bundled tools",
            source="bundled",
        )

        self.assertEqual(dependency_detail_text(status), "内置 found in bundled tools")
        self.assertEqual(dependency_log_text(status), "adb 已找到（内置）：found in bundled tools")

    def test_custom_dependency_without_path_uses_message(self):
        status = DependencyStatus(
            name="tool",
            found=True,
            path=None,
            message="custom location",
            source="custom",
        )

        self.assertEqual(dependency_detail_text(status), "custom location")
        self.assertEqual(dependency_log_text(status), "tool 已找到：custom location")

    def test_found_dependency_without_path_or_message_uses_unknown_location(self):
        status = DependencyStatus(
            name="tool",
            found=True,
            path=None,
            message="",
            source="custom",
        )

        self.assertEqual(dependency_detail_text(status), "未知位置")
        self.assertEqual(dependency_log_text(status), "tool 已找到：未知位置")


if __name__ == "__main__":
    unittest.main()
