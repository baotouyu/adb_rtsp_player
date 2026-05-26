from types import SimpleNamespace
from contextlib import ExitStack
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from rtsp_tool.dependencies import DependencyStatus
from rtsp_tool.gui import RTSPToolApp
from rtsp_tool.i18n import TEXT
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


class FakeCombobox:
    def __init__(self):
        self.values = ()
        self.state = None

    def configure(self, **kwargs):
        if "values" in kwargs:
            self.values = tuple(kwargs["values"])
        if "state" in kwargs:
            self.state = kwargs["state"]


class FakeRoot:
    def __init__(self):
        self.row_configs = {}
        self.column_configs = {}
        self.cursor = ""
        self.protocols = {}

    def rowconfigure(self, row, **kwargs):
        self.row_configs[row] = kwargs

    def columnconfigure(self, column, **kwargs):
        self.column_configs[column] = kwargs

    def title(self, _title):
        pass

    def geometry(self, _geometry):
        pass

    def minsize(self, _width, _height):
        pass

    def protocol(self, name, callback):
        self.protocols[name] = callback

    def config(self, **kwargs):
        if "cursor" in kwargs:
            self.cursor = kwargs["cursor"]

    def after(self, _delay, callback):
        callback()


class FakeWidget:
    created = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.grid_kwargs = None
        self.bindings = {}
        self.configured = {}
        FakeWidget.created.append(self)

    def grid(self, **kwargs):
        self.grid_kwargs = kwargs

    def columnconfigure(self, *args, **kwargs):
        self.configured[("columnconfigure", args)] = kwargs

    def rowconfigure(self, *args, **kwargs):
        self.configured[("rowconfigure", args)] = kwargs

    def heading(self, *args, **kwargs):
        self.configured[("heading", args)] = kwargs

    def column(self, *args, **kwargs):
        self.configured[("column", args)] = kwargs

    def bind(self, event, callback):
        self.bindings[event] = callback

    def configure(self, **kwargs):
        self.configured.update(kwargs)

    def yview(self, *args):
        return None

    def set(self, *args):
        return None


def fake_widget_type(kind):
    return type(kind, (FakeWidget,), {"kind": kind})


class GuiUsbSharingTests(unittest.TestCase):
    def skip_windows_ci_real_tk_layout(self):
        if os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true":
            self.skipTest("Windows CI desktop/DPI metrics make real Tk layout dimensions unstable")

    def make_missing_dependencies(self):
        return {
            "adb": DependencyStatus(
                name="adb",
                found=False,
                path=None,
                message="not found in bundled tools or PATH",
                source="missing",
            ),
            "ffplay": DependencyStatus(
                name="ffplay",
                found=False,
                path=None,
                message="not found in bundled tools or PATH",
                source="missing",
            ),
            "tkinter": DependencyStatus(
                name="tkinter",
                found=True,
                path="python stdlib",
                message="found",
                source="stdlib",
            ),
        }

    def make_app(self, *, windows=True, selected_adapters=True, usable_device=True, busy=False):
        app = object.__new__(RTSPToolApp)
        app.root = FakeRoot()
        app.status_text = FakeVar("")
        app.dependencies = {"adb": SimpleNamespace(found=True), "ffplay": SimpleNamespace(found=True)}
        app.devices = {"abc": SimpleNamespace(serial="abc", state="device" if usable_device else "offline")}
        app.selected_serial = FakeVar("abc")
        app.device_ip = FakeVar("")
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
        app.usb_sharing_status = FakeVar("")
        app.internet_adapter_combo = FakeCombobox()
        app.usb_adapter_combo = FakeCombobox()
        app.logged = []
        app.log = app.logged.append
        app._ui = lambda func, *args: func(*args)
        app.adb = SimpleNamespace(discover_usb0_ip=lambda _serial: None)

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

    def use_sync_background(self, app, showerror=None):
        background_messages = []

        def run_background(message, work):
            background_messages.append(message)
            app._set_busy(message)
            try:
                work()
            except Exception as exc:
                app.log(f"错误：{exc}")
                if showerror is not None:
                    showerror("操作失败", str(exc))
            finally:
                app._clear_busy()

        app._run_background = run_background
        return background_messages

    def make_real_app(self, root):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("rtsp_tool.gui.check_dependencies", return_value=self.make_missing_dependencies()):
                with patch("rtsp_tool.gui.get_app_dir", return_value=temp_dir):
                    return RTSPToolApp(root)

    def make_minimal_init_app(self, *, windows):
        with tempfile.TemporaryDirectory() as temp_dir:
            with ExitStack() as stack:
                stack.enter_context(
                    patch("rtsp_tool.gui.check_dependencies", return_value=self.make_missing_dependencies())
                )
                stack.enter_context(patch("rtsp_tool.gui.get_app_dir", return_value=temp_dir))
                stack.enter_context(patch("rtsp_tool.gui.tk.StringVar", FakeVar))
                stack.enter_context(patch("rtsp_tool.gui.tk.BooleanVar", FakeVar))
                stack.enter_context(patch.object(RTSPToolApp, "_build_ui"))
                stack.enter_context(patch.object(RTSPToolApp, "_render_dependency_status"))
                stack.enter_context(patch.object(RTSPToolApp, "refresh_yolo_packages"))
                stack.enter_context(patch.object(RTSPToolApp, "_update_button_states"))
                stack.enter_context(patch.object(RTSPToolApp, "_is_windows", return_value=windows))
                stack.enter_context(patch.object(RTSPToolApp, "log"))
                return RTSPToolApp(FakeRoot())

    def test_windows_startup_prompts_user_to_detect_adapters(self):
        app = self.make_minimal_init_app(windows=True)

        self.assertEqual(app.usb_sharing_status.get(), "点击“检测网络适配器”开始配置 USB 网络共享。")

    def test_non_windows_startup_explains_auto_usb_sharing_is_windows_only(self):
        app = self.make_minimal_init_app(windows=False)

        self.assertEqual(app.usb_sharing_status.get(), "USB 网络共享自动配置仅适用于 Windows。")

    def assert_bottom_rows_visible(self, root, app, *, min_log_text_height):
        root.update_idletasks()

        root_height = root.winfo_height()
        controls = root.grid_slaves(row=5, column=0)[0]
        log_frame = root.grid_slaves(row=6, column=0)[0]
        status_bar = root.grid_slaves(row=7, column=0)[0]

        for widget in (controls, log_frame, status_bar):
            self.assertLessEqual(widget.winfo_y() + widget.winfo_height(), root_height)
        self.assertGreaterEqual(app.log_text.winfo_height(), min_log_text_height)

    def test_laptop_geometry_keeps_bottom_rows_visible(self):
        self.skip_windows_ci_real_tk_layout()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")

        self.addCleanup(root.destroy)
        app = self.make_real_app(root)

        root.geometry("920x720")
        root.update_idletasks()
        root.withdraw()
        root.update_idletasks()

        self.assertLessEqual(root.winfo_height(), 720)
        self.assert_bottom_rows_visible(root, app, min_log_text_height=80)

    def test_minimum_geometry_keeps_controls_status_and_some_log_visible(self):
        self.skip_windows_ci_real_tk_layout()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")

        self.addCleanup(root.destroy)
        app = self.make_real_app(root)

        root.geometry("760x640")
        root.update_idletasks()
        root.withdraw()
        root.update_idletasks()

        self.assertLessEqual(root.winfo_height(), 640)
        root_height = root.winfo_height()
        controls = root.grid_slaves(row=5, column=0)[0]
        log_frame = root.grid_slaves(row=6, column=0)[0]
        status_bar = root.grid_slaves(row=7, column=0)[0]

        self.assertLessEqual(controls.winfo_y() + controls.winfo_height(), root_height)
        self.assertGreater(log_frame.winfo_height(), 0)
        self.assertLessEqual(status_bar.winfo_y() + status_bar.winfo_height(), root_height)
        self.assertGreater(app.log_text.winfo_height(), 0)

    def test_default_geometry_keeps_bottom_rows_visible(self):
        self.skip_windows_ci_real_tk_layout()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")

        self.addCleanup(root.destroy)
        app = self.make_real_app(root)

        root.update_idletasks()
        root.withdraw()
        root.update_idletasks()

        self.assertLessEqual(root.winfo_height(), 720)
        self.assert_bottom_rows_visible(root, app, min_log_text_height=80)

    def test_build_ui_adds_usb_sharing_section_and_expected_rows(self):
        app = object.__new__(RTSPToolApp)
        app.root = FakeRoot()
        app.dep_vars = {}
        app.selected_serial = FakeVar("")
        app.device_ip = FakeVar("")
        app.rtsp_url = FakeVar("")
        app.service_status = FakeVar("")
        app.status_text = FakeVar("")
        app.selected_yolo_package = FakeVar("")
        app.start_after_update = FakeVar(False)
        app.ai_stream_enabled = FakeVar(False)
        app.selected_internet_adapter = FakeVar("")
        app.selected_usb_adapter = FakeVar("")
        app.usb_sharing_status = FakeVar("")
        FakeWidget.created = []

        widget_patches = {
            "rtsp_tool.gui.ttk.LabelFrame": fake_widget_type("LabelFrame"),
            "rtsp_tool.gui.ttk.Label": fake_widget_type("Label"),
            "rtsp_tool.gui.ttk.Treeview": fake_widget_type("Treeview"),
            "rtsp_tool.gui.ttk.Scrollbar": fake_widget_type("Scrollbar"),
            "rtsp_tool.gui.ttk.Frame": fake_widget_type("Frame"),
            "rtsp_tool.gui.ttk.Button": fake_widget_type("Button"),
            "rtsp_tool.gui.ttk.Combobox": fake_widget_type("Combobox"),
            "rtsp_tool.gui.ttk.Checkbutton": fake_widget_type("Checkbutton"),
            "rtsp_tool.gui.tk.Text": fake_widget_type("Text"),
            "rtsp_tool.gui.tk.StringVar": FakeVar,
        }
        with ExitStack() as stack:
            for target, replacement in widget_patches.items():
                stack.enter_context(patch(target, replacement))
            app._build_ui()

        frames = [widget for widget in FakeWidget.created if widget.kind == "LabelFrame"]
        rows_by_text = {widget.kwargs["text"]: widget.grid_kwargs["row"] for widget in frames}
        self.assertEqual(rows_by_text[TEXT["dependencies"]], 0)
        self.assertEqual(rows_by_text[TEXT["devices"]], 1)
        self.assertEqual(rows_by_text[TEXT["usb_sharing"]], 2)
        self.assertEqual(rows_by_text[TEXT["stream"]], 3)
        self.assertEqual(rows_by_text[TEXT["yolo_package"]], 4)
        self.assertEqual(rows_by_text[TEXT["controls"]], 5)
        self.assertEqual(rows_by_text[TEXT["log"]], 6)
        self.assertEqual(app.root.row_configs[6]["weight"], 1)

        self.assertIs(app.internet_adapter_combo.kwargs["textvariable"], app.selected_internet_adapter)
        self.assertEqual(app.internet_adapter_combo.kwargs["state"], "readonly")
        self.assertIn("<<ComboboxSelected>>", app.internet_adapter_combo.bindings)
        self.assertIs(app.usb_adapter_combo.kwargs["textvariable"], app.selected_usb_adapter)
        self.assertEqual(app.usb_adapter_combo.kwargs["state"], "readonly")
        self.assertIn("<<ComboboxSelected>>", app.usb_adapter_combo.bindings)

        self.assertEqual(app.detect_adapters_button.kwargs["text"], TEXT["detect_network_adapters"])
        self.assertEqual(app.detect_adapters_button.kwargs["command"], app.detect_network_adapters)
        self.assertEqual(app.configure_usb_sharing_button.kwargs["text"], TEXT["configure_usb_sharing"])
        self.assertEqual(app.configure_usb_sharing_button.kwargs["command"], app.configure_usb_sharing)
        self.assertEqual(app.manual_network_settings_button.kwargs["text"], TEXT["open_manual_network_settings"])
        self.assertEqual(app.manual_network_settings_button.kwargs["command"], app.open_manual_network_settings)
        self.assertEqual(app.detect_usb0_button.kwargs["text"], TEXT["detect_usb0_ip"])
        self.assertEqual(app.detect_usb0_button.kwargs["command"], app.detect_usb0_ip)
        self.assertTrue(
            any(
                widget.kind == "Label" and widget.kwargs.get("textvariable") is app.usb_sharing_status
                for widget in FakeWidget.created
            )
        )

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

    def test_unusable_device_disables_usb0_detection_only(self):
        app = self.make_app(windows=True, selected_adapters=True, usable_device=False)

        app._update_button_states()

        self.assertEqual(app.detect_adapters_button.state, "normal")
        self.assertEqual(app.configure_usb_sharing_button.state, "normal")
        self.assertEqual(app.manual_network_settings_button.state, "normal")
        self.assertEqual(app.detect_usb0_button.state, "disabled")

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

    def test_replace_network_adapters_selects_single_candidates(self):
        app = self.make_app(windows=True, selected_adapters=False)
        internet = NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status="Up", has_gateway=True)
        usb = NetworkAdapter(name="Ethernet 2", description="Remote NDIS Compatible Device", status="Up")

        app._replace_network_adapters([internet, usb])

        self.assertEqual(app.internet_adapter_combo.values, ("Wi-Fi - Intel Wi-Fi",))
        self.assertEqual(app.usb_adapter_combo.values, ("Ethernet 2 - Remote NDIS Compatible Device",))
        self.assertEqual(app.selected_internet_adapter.get(), "Wi-Fi - Intel Wi-Fi")
        self.assertEqual(app.selected_usb_adapter.get(), "Ethernet 2 - Remote NDIS Compatible Device")
        self.assertIs(app._selected_internet_adapter(), internet)
        self.assertIs(app._selected_usb_adapter(), usb)
        self.assertIn("检测到上网网卡", "\n".join(app.logged))
        self.assertIn("检测到板子 USB 网卡", "\n".join(app.logged))
        self.assertEqual(app.usb_sharing_status.get(), "请选择网卡后配置 USB 网络共享。")
        self.assertEqual(app.configure_usb_sharing_button.state, "normal")

    def test_replace_network_adapters_does_not_select_when_multiple_candidates(self):
        app = self.make_app(windows=True, selected_adapters=True)
        adapters = [
            NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status="Up", has_gateway=True),
            NetworkAdapter(name="Ethernet", description="Realtek PCIe", status="Up", has_gateway=True),
            NetworkAdapter(name="Ethernet 2", description="Remote NDIS Compatible Device", status="Up"),
            NetworkAdapter(name="USB Ethernet Gadget", description="Board link", status="Up"),
        ]

        app._replace_network_adapters(adapters)

        self.assertEqual(
            app.internet_adapter_combo.values,
            ("Wi-Fi - Intel Wi-Fi", "Ethernet - Realtek PCIe"),
        )
        self.assertEqual(
            app.usb_adapter_combo.values,
            ("Ethernet 2 - Remote NDIS Compatible Device", "USB Ethernet Gadget - Board link"),
        )
        self.assertEqual(app.selected_internet_adapter.get(), "")
        self.assertEqual(app.selected_usb_adapter.get(), "")
        self.assertEqual(app.configure_usb_sharing_button.state, "disabled")

    def test_replace_network_adapters_without_candidates_clears_stale_selection(self):
        app = self.make_app(windows=True, selected_adapters=True)

        app._replace_network_adapters([])

        self.assertEqual(app.internet_adapter_combo.values, ())
        self.assertEqual(app.usb_adapter_combo.values, ())
        self.assertEqual(app.selected_internet_adapter.get(), "")
        self.assertEqual(app.selected_usb_adapter.get(), "")
        self.assertIsNone(app._selected_internet_adapter())
        self.assertIsNone(app._selected_usb_adapter())
        self.assertIn("未检测到可用于上网的 Windows 网卡。", "\n".join(app.logged))
        self.assertIn("未检测到板子 USB 网卡。请确认 USB 网络/RNDIS 已连接。", "\n".join(app.logged))
        self.assertEqual(app.usb_sharing_status.get(), "未检测到可用网卡。请检查网络和 USB/RNDIS 连接后重新检测。")
        self.assertEqual(app.configure_usb_sharing_button.state, "disabled")

    def test_configure_usb_sharing_cancel_does_not_run_ics(self):
        app = self.make_app(windows=True, selected_adapters=True)

        def fail_run_background(message, work):
            self.fail("_run_background should not be called when the user cancels ICS configuration")

        app._run_background = fail_run_background
        with patch("rtsp_tool.gui.messagebox.askyesno", return_value=False) as askyesno, patch(
            "rtsp_tool.gui.configure_ics"
        ) as configure_ics:
            app.configure_usb_sharing()

        askyesno.assert_called_once_with(
            "确认配置 USB 网络共享",
            "这会修改 Windows 网络共享设置，并可能弹出管理员权限确认。是否继续？",
        )
        configure_ics.assert_not_called()

    def test_configure_usb_sharing_skips_direct_call_on_non_windows(self):
        app = self.make_app(windows=False, selected_adapters=True)

        def fail_run_background(message, work):
            self.fail("_run_background should not be called on non-Windows hosts")

        app._run_background = fail_run_background
        with patch("rtsp_tool.gui.messagebox.askyesno") as askyesno, patch(
            "rtsp_tool.gui.configure_ics"
        ) as configure_ics:
            app.configure_usb_sharing()

        self.assertEqual(app.usb_sharing_status.get(), "USB 网络共享自动配置仅适用于 Windows。")
        self.assertIn("USB 网络共享自动配置仅适用于 Windows。", app.logged)
        askyesno.assert_not_called()
        configure_ics.assert_not_called()

    def test_configure_usb_sharing_warns_without_selected_adapters(self):
        app = self.make_app(windows=True, selected_adapters=False)

        def fail_run_background(message, work):
            self.fail("_run_background should not be called without both selected adapters")

        app._run_background = fail_run_background
        with patch("rtsp_tool.gui.messagebox.showwarning") as showwarning, patch(
            "rtsp_tool.gui.messagebox.askyesno"
        ) as askyesno, patch("rtsp_tool.gui.configure_ics") as configure_ics:
            app.configure_usb_sharing()

        showwarning.assert_called_once_with(
            "未选择网卡",
            "请先检测并选择上网网卡和板子 USB 网卡。",
        )
        askyesno.assert_not_called()
        configure_ics.assert_not_called()

    def test_configure_usb_sharing_success_updates_status(self):
        app = self.make_app(windows=True, selected_adapters=True)
        background_messages = []

        def run_background(message, work):
            background_messages.append(message)
            work()

        app._run_background = run_background
        result = SimpleNamespace(ok=True, message="ICS 配置成功")
        with patch("rtsp_tool.gui.messagebox.askyesno", return_value=True), patch(
            "rtsp_tool.gui.configure_ics", return_value=result
        ) as configure_ics:
            app.configure_usb_sharing()

        configure_ics.assert_called_once_with("Wi-Fi", "USB RNDIS")
        self.assertEqual(background_messages, ["正在配置 USB 网络共享..."])
        self.assertEqual(app.usb_sharing_status.get(), "ICS 配置成功")
        log_text = "\n".join(app.logged)
        self.assertIn("正在请求管理员权限配置 Windows 网络共享...", log_text)
        self.assertIn("ICS 配置完成。请等待板端 usb0 通过 DHCP 获取 IP。", log_text)

    def test_configure_usb_sharing_failure_opens_manual_settings(self):
        app = self.make_app(windows=True, selected_adapters=True)
        app._run_background = lambda _message, work: work()
        manual_calls = []
        app.open_manual_network_settings = lambda: manual_calls.append("opened")
        result = SimpleNamespace(ok=False, message="管理员授权被取消")

        with patch("rtsp_tool.gui.messagebox.askyesno", return_value=True), patch(
            "rtsp_tool.gui.configure_ics", return_value=result
        ) as configure_ics:
            app.configure_usb_sharing()

        configure_ics.assert_called_once_with("Wi-Fi", "USB RNDIS")
        self.assertEqual(app.usb_sharing_status.get(), "管理员授权被取消")
        self.assertEqual(manual_calls, ["opened"])
        self.assertIn("未能自动配置 ICS：管理员授权被取消", "\n".join(app.logged))

    def test_configure_usb_sharing_failure_schedules_manual_settings_on_ui_thread(self):
        app = self.make_app(windows=True, selected_adapters=True)
        queued_ui = []
        manual_calls = []

        def manual_settings():
            manual_calls.append("opened")

        app.open_manual_network_settings = manual_settings
        app._run_background = lambda _message, work: work()
        app._ui = lambda func, *args: queued_ui.append((func, args))
        result = SimpleNamespace(ok=False, message="管理员授权被取消")

        with patch("rtsp_tool.gui.messagebox.askyesno", return_value=True), patch(
            "rtsp_tool.gui.configure_ics", return_value=result
        ):
            app.configure_usb_sharing()

        self.assertIn((app.open_manual_network_settings, ()), queued_ui)
        self.assertEqual(manual_calls, [])

        for func, args in queued_ui:
            func(*args)

        self.assertEqual(manual_calls, ["opened"])

    def test_configure_usb_sharing_ics_exception_is_logged_by_background(self):
        app = self.make_app(windows=True, selected_adapters=True)
        messages = []
        self.use_sync_background(app, showerror=lambda title, message: messages.append((title, message)))

        with patch("rtsp_tool.gui.messagebox.askyesno", return_value=True), patch(
            "rtsp_tool.gui.configure_ics", side_effect=RuntimeError("boom")
        ):
            app.configure_usb_sharing()

        self.assertIn("错误：boom", app.logged)
        self.assertEqual(messages, [("操作失败", "boom")])
        self.assertFalse(app._operation_in_progress)
        self.assertEqual(app.root.cursor, "")

    def test_open_manual_network_settings_logs_steps_and_handles_open_failure(self):
        app = self.make_app(windows=True, selected_adapters=True)

        with patch(
            "rtsp_tool.gui.open_windows_network_settings",
            side_effect=OSError("control panel unavailable"),
        ) as open_settings:
            app.open_manual_network_settings()

        open_settings.assert_called_once_with()
        self.assertIn("打开 Windows 网络连接页面失败：control panel unavailable", "\n".join(app.logged))
        manual_steps = (
            "手动设置步骤：右键上网网卡 -> 属性 -> 共享 -> 勾选允许共享 -> "
            "家庭网络连接选择板子 RNDIS/USB 网卡。"
        )
        self.assertEqual(app.usb_sharing_status.get(), manual_steps)
        self.assertIn(manual_steps, "\n".join(app.logged))

    def test_open_manual_network_settings_skips_direct_call_on_non_windows(self):
        app = self.make_app(windows=False, selected_adapters=True)

        with patch("rtsp_tool.gui.open_windows_network_settings") as open_settings:
            app.open_manual_network_settings()

        self.assertEqual(app.usb_sharing_status.get(), "USB 网络共享自动配置仅适用于 Windows。")
        self.assertIn("USB 网络共享自动配置仅适用于 Windows。", app.logged)
        open_settings.assert_not_called()

    def test_detect_usb0_ip_updates_rtsp_url(self):
        app = self.make_app(windows=True, selected_adapters=True)
        background_messages = []
        update_calls = []
        discover_usb0_ip = Mock(return_value="192.168.137.33")

        def run_background(message, work):
            background_messages.append(message)
            work()

        app._run_background = run_background
        app._update_button_states = lambda: update_calls.append("updated")
        app.adb = SimpleNamespace(discover_usb0_ip=discover_usb0_ip)

        app.detect_usb0_ip()

        discover_usb0_ip.assert_called_once_with("abc")
        self.assertEqual(background_messages, ["正在检测 usb0 IP..."])
        self.assertEqual(app.device_ip.get(), "192.168.137.33")
        self.assertEqual(app.rtsp_url.get(), "rtsp://192.168.137.33:8554/ch0")
        self.assertEqual(app.usb_sharing_status.get(), "板端 usb0 IP：192.168.137.33")
        self.assertEqual(update_calls, ["updated"])
        log_text = "\n".join(app.logged)
        self.assertIn("正在检测设备 abc 的 usb0 IP...", log_text)
        self.assertIn("板端 usb0 IP：192.168.137.33", log_text)
        self.assertIn("RTSP 地址：rtsp://192.168.137.33:8554/ch0", log_text)

    def test_detect_usb0_ip_missing_ip_is_logged_by_background(self):
        app = self.make_app(windows=True, selected_adapters=True)
        messages = []
        app.adb = SimpleNamespace(discover_usb0_ip=lambda serial: None)
        self.use_sync_background(app, showerror=lambda title, message: messages.append((title, message)))

        app.detect_usb0_ip()

        expected = "没有检测到 usb0 IP。请确认 Windows ICS 已启用，并等待板端 DHCP 获取地址。"
        self.assertEqual(messages, [("操作失败", expected)])
        self.assertIn(f"错误：{expected}", app.logged)
        self.assertEqual(app.device_ip.get(), "")
        self.assertEqual(app.rtsp_url.get(), "")

    def test_detect_network_adapters_skips_on_non_windows(self):
        app = self.make_app(windows=False)

        def fail_run_background(message, work):
            self.fail("_run_background should not be called on non-Windows hosts")

        app._run_background = fail_run_background
        with patch("rtsp_tool.gui.run_adapter_discovery") as discovery:
            app.detect_network_adapters()

        discovery.assert_not_called()
        self.assertIn("USB 网络共享自动配置仅适用于 Windows。", app.logged)

    def test_detect_network_adapters_runs_discovery_in_background(self):
        app = self.make_app(windows=True, selected_adapters=False)
        adapters = [
            NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status="Up", has_gateway=True),
            NetworkAdapter(name="Ethernet 2", description="Remote NDIS Compatible Device", status="Up"),
        ]
        background_messages = []

        def run_background(message, work):
            background_messages.append(message)
            work()

        app._run_background = run_background
        with patch("rtsp_tool.gui.run_adapter_discovery", return_value=adapters) as discovery:
            app.detect_network_adapters()

        discovery.assert_called_once_with()
        self.assertEqual(background_messages, ["正在检测 Windows 网络适配器..."])
        self.assertEqual(app.selected_internet_adapter.get(), "Wi-Fi - Intel Wi-Fi")
        self.assertEqual(app.selected_usb_adapter.get(), "Ethernet 2 - Remote NDIS Compatible Device")
        self.assertIn("正在检测 Windows 网络适配器...", app.logged)


if __name__ == "__main__":
    unittest.main()
