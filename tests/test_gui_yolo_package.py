from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from rtsp_tool.gui import RTSPToolApp
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

    def test_refresh_yolo_packages_disambiguates_duplicate_display_names_and_keeps_selection(self):
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

    def test_update_button_requires_adb_usable_device_and_selected_package(self):
        app = object.__new__(RTSPToolApp)
        app.dependencies = {"adb": SimpleNamespace(found=True), "ffplay": SimpleNamespace(found=True)}
        app.selected_serial = FakeVar("abc")
        app.rtsp_url = FakeVar("")
        app.selected_yolo_package = FakeVar("pkg")
        app.yolo_packages = {"pkg": YoloPackage("yoloApp_pkg", "pkg", Path("/tmp/pkg"), Path("/tmp/pkg/sample_smart_camera"), Path("/tmp/pkg/network_binary.nb"))}
        app.devices = {"abc": SimpleNamespace(state="device")}
        app.player = SimpleNamespace(is_running=lambda: False)
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
            buttons[name] = SimpleNamespace(configure=lambda n=name, **kwargs: setattr(buttons[n], "state", kwargs["state"]))
            setattr(app, name, buttons[name])

        app._update_button_states()
        self.assertEqual(app.update_yolo_button.state, "normal")
        self.assertEqual(app.refresh_yolo_button.state, "normal")

        app.selected_yolo_package.set("")
        app._update_button_states()
        self.assertEqual(app.update_yolo_button.state, "disabled")
        self.assertEqual(app.refresh_yolo_button.state, "normal")
