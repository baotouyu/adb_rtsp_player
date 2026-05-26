from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rtsp_tool.gui import RTSPToolApp
from rtsp_tool.windows_ics import NetworkAdapter


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeButton:
    def __init__(self):
        self.state = None

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.state = kwargs["state"]


class GuiUsbSharingTests(unittest.TestCase):
    def make_app(self, *, windows=True, selected_adapters=True, usable_device=True, busy=False):
        app = object.__new__(RTSPToolApp)
        app.dependencies = {"adb": SimpleNamespace(found=True), "ffplay": SimpleNamespace(found=True)}
        app.devices = {"abc": SimpleNamespace(state="device" if usable_device else "offline")}
        app.selected_serial = FakeVar("abc")
        app.rtsp_url = FakeVar("")
        app.player = SimpleNamespace(is_running=lambda: False)
        app.selected_yolo_package = FakeVar("")
        app.yolo_packages = {}
        app._operation_in_progress = busy
        app._is_windows = lambda: windows

        internet = NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status="Up", has_gateway=True)
        usb = NetworkAdapter(name="USB RNDIS", description="Remote NDIS", status="Up")
        app.internet_adapters = {"wifi": internet}
        app.usb_adapters = {"usb": usb}
        app.selected_internet_adapter = FakeVar("wifi" if selected_adapters else "")
        app.selected_usb_adapter = FakeVar("usb" if selected_adapters else "")

        for name in (
            "refresh_button",
            "start_service_button",
            "stop_service_button",
            "start_playback_button",
            "stop_playback_button",
            "copy_button",
            "update_yolo_button",
            "refresh_yolo_button",
            "start_after_update_check",
            "ai_stream_check",
            "detect_adapters_button",
            "configure_usb_sharing_button",
            "manual_network_settings_button",
            "detect_usb0_button",
        ):
            setattr(app, name, FakeButton())
        return app

    def test_windows_with_selected_adapters_and_usable_device_enables_usb_sharing_buttons(self):
        app = self.make_app(windows=True, selected_adapters=True, usable_device=True)

        app._update_button_states()

        self.assertEqual(app.detect_adapters_button.state, "normal")
        self.assertEqual(app.configure_usb_sharing_button.state, "normal")
        self.assertEqual(app.manual_network_settings_button.state, "normal")
        self.assertEqual(app.detect_usb0_button.state, "normal")

    def test_windows_without_selected_adapters_disables_configure_only(self):
        app = self.make_app(windows=True, selected_adapters=False, usable_device=True)

        app._update_button_states()

        self.assertEqual(app.detect_adapters_button.state, "normal")
        self.assertEqual(app.configure_usb_sharing_button.state, "disabled")
        self.assertEqual(app.manual_network_settings_button.state, "normal")
        self.assertEqual(app.detect_usb0_button.state, "normal")

    def test_non_windows_disables_windows_actions_but_keeps_usb0_detection_available(self):
        app = self.make_app(windows=False, selected_adapters=True, usable_device=True)

        app._update_button_states()

        self.assertEqual(app.detect_adapters_button.state, "disabled")
        self.assertEqual(app.configure_usb_sharing_button.state, "disabled")
        self.assertEqual(app.manual_network_settings_button.state, "disabled")
        self.assertEqual(app.detect_usb0_button.state, "normal")

    def test_busy_disables_usb_sharing_buttons(self):
        app = self.make_app(windows=True, selected_adapters=True, usable_device=True, busy=True)

        app._update_button_states()

        self.assertEqual(app.detect_adapters_button.state, "disabled")
        self.assertEqual(app.configure_usb_sharing_button.state, "disabled")
        self.assertEqual(app.manual_network_settings_button.state, "disabled")
        self.assertEqual(app.detect_usb0_button.state, "disabled")

    def test_selected_adapter_helpers_return_matching_adapter_or_none(self):
        app = self.make_app(windows=True, selected_adapters=True)

        self.assertEqual(app._selected_internet_adapter(), app.internet_adapters["wifi"])
        self.assertEqual(app._selected_usb_adapter(), app.usb_adapters["usb"])

        app.selected_internet_adapter.set("missing")
        app.selected_usb_adapter.set("")
        self.assertIsNone(app._selected_internet_adapter())
        self.assertIsNone(app._selected_usb_adapter())

    def test_is_windows_delegates_to_windows_ics(self):
        app = object.__new__(RTSPToolApp)

        with patch("rtsp_tool.windows_ics.is_windows", return_value=True):
            self.assertTrue(app._is_windows())
        with patch("rtsp_tool.windows_ics.is_windows", return_value=False):
            self.assertFalse(app._is_windows())


if __name__ == "__main__":
    unittest.main()
