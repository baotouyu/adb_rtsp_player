from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from rtsp_tool.adb_client import ADBDevice, CommandResult
from rtsp_tool.gui import RTSPToolApp
from rtsp_tool.i18n import state_text
from rtsp_tool.yolo_package import YoloPackage


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeCombobox:
    def __init__(self):
        self.values = ()
        self.state = None

    def configure(self, **kwargs):
        if "values" in kwargs:
            self.values = tuple(kwargs["values"])
        if "state" in kwargs:
            self.state = kwargs["state"]


class FakeButton:
    def __init__(self):
        self.state = None

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]


class FakeRoot:
    def __init__(self):
        self.cursor = ""

    def config(self, **kwargs):
        if "cursor" in kwargs:
            self.cursor = kwargs["cursor"]

    def after(self, _delay, callback):
        callback()


class FakeAdb:
    def __init__(self, result=None):
        self.result = result or CommandResult(["adb"], 0, "ok", "")
        self.installs = []

    def install_yolo_package(self, serial, app_path, model_path):
        self.installs.append((serial, app_path, model_path))
        return self.result


class FakePlayer:
    def __init__(self):
        self.started_urls = []

    def is_running(self):
        return bool(self.started_urls)

    def start(self, url):
        self.started_urls.append(url)
        return ["ffplay", url]


class GuiYoloPackageTests(unittest.TestCase):
    def make_app(self, apps_path: Path):
        app = object.__new__(RTSPToolApp)
        app.yolo_apps_path = apps_path
        app.yolo_packages = {}
        app.selected_yolo_package = FakeVar("")
        app.yolo_package_combo = FakeCombobox()
        app.logged = []
        app.log = app.logged.append
        app._update_button_states = lambda: None
        return app

    def create_package(self, root: Path, folder: str):
        package_dir = root / folder
        package_dir.mkdir(parents=True)
        (package_dir / "sample_smart_camera").write_text("app", encoding="utf-8")
        (package_dir / "network_binary.nb").write_text("model", encoding="utf-8")
        return package_dir

    def package(self, name="yoloApp_pkg", display_name="pkg"):
        path = Path("/tmp") / name
        return YoloPackage(name, display_name, path, path / "sample_smart_camera", path / "network_binary.nb")

    def make_workflow_app(self, package_selected=True, confirm=True, install_result=None, start_after_update=False):
        app = object.__new__(RTSPToolApp)
        app.root = FakeRoot()
        app.status_text = FakeVar(state_text("ready"))
        app.service_status = FakeVar(state_text("unknown"))
        app.dependencies = {"adb": SimpleNamespace(found=True), "ffplay": SimpleNamespace(found=True)}
        app.devices = {"abc": ADBDevice("abc", "device")}
        app.selected_serial = FakeVar("abc")
        app.rtsp_url = FakeVar("")
        app.selected_yolo_package = FakeVar("pkg" if package_selected else "missing")
        package = self.package()
        app.yolo_packages = {"pkg": package} if package_selected else {}
        app.yolo_apps_path = Path("/tmp/yolo_apps")
        app.start_after_update = FakeVar(start_after_update)
        app.adb = FakeAdb(install_result)
        app.player = FakePlayer()
        app.logged = []
        app.log = app.logged.append
        app._inspect_device = lambda serial, start_if_needed: "rtsp://192.168.1.10:8554/ch0"
        self.messages = []
        self.confirm = confirm

        def showwarning(title, message):
            self.messages.append(("warning", title, message))

        def showerror(title, message):
            self.messages.append(("error", title, message))

        def askyesno(title, message):
            self.messages.append(("confirm", title, message))
            return self.confirm

        app._ui = lambda func, *args: func(*args)
        app._update_button_states = lambda: None

        def run_sync(message, work):
            app._set_busy(message)
            try:
                work()
            except Exception as exc:
                app.log(f"错误：{exc}")
                showerror("操作失败", str(exc))
            finally:
                app._clear_busy()

        app._run_background = run_sync
        return app, package, showwarning, showerror, askyesno

    def test_refresh_yolo_packages_selects_first_and_logs_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_path = Path(temp_dir) / "yolo_apps"
            self.create_package(apps_path, "yoloApp_alpha")
            self.create_package(apps_path, "yoloApp_beta")
            app = self.make_app(apps_path)

            app.refresh_yolo_packages()

            self.assertEqual(app.yolo_package_combo.values, ("alpha", "beta"))
            self.assertEqual(app.selected_yolo_package.get(), "alpha")
            self.assertEqual(app._selected_yolo_package().name, "yoloApp_alpha")
            self.assertIn(str(apps_path), "\n".join(app.logged))
            self.assertIn("找到 2 个", "\n".join(app.logged))

    def test_refresh_yolo_packages_uses_windows_path_separator_in_example_path(self):
        apps_path = PureWindowsPath(r"C:\Users\yuwei\Desktop\ADB_RTSP_Player\yolo_apps")
        app = self.make_app(apps_path)

        app.refresh_yolo_packages()

        log_text = "\n".join(app.logged)
        self.assertIn(r"yolo_apps\yoloApp_xxx", log_text)
        self.assertNotIn("yolo_apps/yoloApp_xxx", log_text)

    def test_refresh_yolo_packages_keeps_selection_when_new_distinct_package_is_added(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            apps_path = Path(temp_dir) / "yolo_apps"
            self.create_package(apps_path, "yoloApp_camera")
            app = self.make_app(apps_path)
            app.refresh_yolo_packages()
            app.selected_yolo_package.set("camera")

            self.create_package(apps_path, "yoloApp_camera_extra")
            app.refresh_yolo_packages()

            self.assertIn("camera", app.yolo_package_combo.values)
            self.assertIn("camera_extra", app.yolo_package_combo.values)
            self.assertEqual(app.selected_yolo_package.get(), "camera")

    def test_yolo_package_choices_disambiguates_duplicate_display_names(self):
        app = self.make_app(Path("/tmp/yolo_apps"))
        first = self.package("yoloApp_one", "camera")
        second = self.package("yoloApp_two", "camera")

        choices = app._build_yolo_package_choices([first, second])

        self.assertEqual(set(choices), {"camera (yoloApp_one)", "camera (yoloApp_two)"})
        self.assertIs(choices["camera (yoloApp_one)"], first)
        self.assertIs(choices["camera (yoloApp_two)"], second)

    def make_button_state_app(self):
        app = object.__new__(RTSPToolApp)
        app.dependencies = {"adb": SimpleNamespace(found=True), "ffplay": SimpleNamespace(found=True)}
        app.selected_serial = FakeVar("abc")
        app.rtsp_url = FakeVar("")
        app.selected_yolo_package = FakeVar("pkg")
        app.yolo_packages = {"pkg": self.package()}
        app.devices = {"abc": SimpleNamespace(state="device")}
        app.player = SimpleNamespace(is_running=lambda: False)
        app._operation_in_progress = False
        buttons = {}
        for name in (
            "refresh_button",
            "start_service_button",
            "stop_service_button",
            "start_playback_button",
            "stop_playback_button",
            "copy_button",
            "update_yolo_button",
            "refresh_yolo_button",
        ):
            buttons[name] = FakeButton()
            setattr(app, name, buttons[name])
        return app

    def test_update_button_requires_adb_usable_device_and_selected_package(self):
        app = self.make_button_state_app()

        app._update_button_states()
        self.assertEqual(app.update_yolo_button.state, "normal")
        self.assertEqual(app.refresh_yolo_button.state, "normal")

        app.selected_yolo_package.set("")
        app._update_button_states()
        self.assertEqual(app.update_yolo_button.state, "disabled")
        self.assertEqual(app.refresh_yolo_button.state, "normal")

    def test_background_operation_disables_destructive_controls_until_cleared(self):
        app = self.make_button_state_app()
        app.root = FakeRoot()
        app.status_text = FakeVar(state_text("ready"))

        app._set_busy("working")
        app._update_button_states()

        self.assertEqual(app.update_yolo_button.state, "disabled")
        self.assertEqual(app.start_service_button.state, "disabled")
        self.assertEqual(app.stop_service_button.state, "disabled")
        self.assertEqual(app.start_playback_button.state, "disabled")
        self.assertEqual(app.refresh_yolo_button.state, "normal")

        app._clear_busy()
        self.assertEqual(app.update_yolo_button.state, "normal")

    def test_run_background_ignores_new_work_while_operation_is_in_progress(self):
        app = self.make_button_state_app()
        app.root = FakeRoot()
        app.status_text = FakeVar(state_text("ready"))
        app.logged = []
        app.log = app.logged.append
        app._ui = lambda func, *args: func(*args)
        ran = []
        app._operation_in_progress = True

        app._run_background("second", lambda: ran.append("ran"))

        self.assertEqual(ran, [])
        self.assertTrue(app._operation_in_progress)
        self.assertIn("已有操作正在执行", "\n".join(app.logged))

    def test_update_yolo_package_cancel_does_not_install(self):
        app, _package, showwarning, showerror, askyesno = self.make_workflow_app(confirm=False)
        with patch("rtsp_tool.gui.messagebox.showwarning", showwarning), patch(
            "rtsp_tool.gui.messagebox.showerror", showerror
        ), patch("rtsp_tool.gui.messagebox.askyesno", askyesno):
            app.update_yolo_package()

        self.assertEqual(len(app.adb.installs), 0)
        self.assertEqual(self.messages[0][0], "confirm")

    def test_update_yolo_package_missing_package_warns(self):
        app, _package, showwarning, showerror, askyesno = self.make_workflow_app(package_selected=False)
        app.yolo_apps_path = PureWindowsPath(r"C:\Users\yuwei\Desktop\ADB_RTSP_Player\yolo_apps")
        with patch("rtsp_tool.gui.messagebox.showwarning", showwarning), patch(
            "rtsp_tool.gui.messagebox.showerror", showerror
        ), patch("rtsp_tool.gui.messagebox.askyesno", askyesno):
            app.update_yolo_package()

        self.assertEqual(len(app.adb.installs), 0)
        self.assertEqual(self.messages[0][0], "warning")
        self.assertIn("yoloApp_xxx", self.messages[0][2])
        self.assertIn(r"yolo_apps\yoloApp_xxx", self.messages[0][2])
        self.assertNotIn("yolo_apps/yoloApp_xxx", self.messages[0][2])

    def test_update_yolo_package_install_failure_is_logged_and_shown(self):
        failed = CommandResult(["adb"], 1, "", "push failed")
        app, _package, showwarning, showerror, askyesno = self.make_workflow_app(install_result=failed)
        with patch("rtsp_tool.gui.messagebox.showwarning", showwarning), patch(
            "rtsp_tool.gui.messagebox.showerror", showerror
        ), patch("rtsp_tool.gui.messagebox.askyesno", askyesno):
            app.update_yolo_package()

        self.assertEqual(self.messages[-1], ("error", "操作失败", "push failed"))
        self.assertIn("错误：push failed", app.logged)

    def test_update_yolo_package_success_sets_service_stopped(self):
        app, package, showwarning, showerror, askyesno = self.make_workflow_app()
        with patch("rtsp_tool.gui.messagebox.showwarning", showwarning), patch(
            "rtsp_tool.gui.messagebox.showerror", showerror
        ), patch("rtsp_tool.gui.messagebox.askyesno", askyesno):
            app.update_yolo_package()

        self.assertEqual(app.adb.installs, [("abc", str(package.app_path), str(package.model_path))])
        self.assertEqual(app.service_status.get(), state_text("stopped"))
        self.assertIn("已更新 YOLO 组合包：pkg", app.logged)

    def test_update_yolo_package_start_after_update_starts_playback_and_logs_command(self):
        app, _package, showwarning, showerror, askyesno = self.make_workflow_app(start_after_update=True)
        with patch("rtsp_tool.gui.messagebox.showwarning", showwarning), patch(
            "rtsp_tool.gui.messagebox.showerror", showerror
        ), patch("rtsp_tool.gui.messagebox.askyesno", askyesno):
            app.update_yolo_package()

        self.assertEqual(app.player.started_urls, ["rtsp://192.168.1.10:8554/ch0"])
        self.assertIn("已启动 ffplay：ffplay rtsp://192.168.1.10:8554/ch0", app.logged)


if __name__ == "__main__":
    unittest.main()
