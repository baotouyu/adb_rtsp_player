from __future__ import annotations

from datetime import datetime
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, TypeVar

from .adb_client import ADBClient, ADBDevice, SERVICE_LOG, SERVICE_NAME
from .dependencies import DependencyStatus, check_dependencies, get_app_dir
from .i18n import TEXT, device_state_text, state_text
from .player import PlayerController, build_rtsp_url
from . import windows_ics
from .windows_ics import (
    NetworkAdapter,
    adapter_choice_map,
    choose_single_internet_adapter,
    choose_single_usb_adapter,
    run_adapter_discovery,
    select_internet_adapters,
    select_usb_adapters,
)
from .yolo_package import YoloPackage, scan_yolo_packages, yolo_apps_dir


T = TypeVar("T")


def _found_dependency_location(status: DependencyStatus) -> str:
    return status.path or status.message or "未知位置"


def dependency_detail_text(status: DependencyStatus) -> str:
    if status.found:
        location = _found_dependency_location(status)
        if status.source == "bundled":
            return f"内置 {location}"
        if status.source == "path":
            return f"PATH {location}"
        return location
    if status.source == "missing":
        return "未找到内置工具，PATH 中也不存在"
    if status.message == "not found in PATH":
        return "不在 PATH 中"
    return status.message


def dependency_log_text(status: DependencyStatus) -> str:
    if status.found:
        location = _found_dependency_location(status)
        if status.source == "bundled":
            return f"{status.name} 已找到（内置）：{location}"
        if status.source == "path":
            return f"{status.name} 已找到（PATH）：{location}"
        return f"{status.name} 已找到：{location}"
    return f"{status.name} 缺失：{dependency_detail_text(status)}"


class RTSPToolApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(TEXT["app_title"])
        self.root.geometry("920x720")
        self.root.minsize(760, 640)

        self.dependencies = check_dependencies()
        adb_path = self.dependencies["adb"].path or "adb"
        ffplay_path = self.dependencies["ffplay"].path or "ffplay"
        self.adb = ADBClient(adb_path=adb_path)
        self.player = PlayerController(ffplay_path=ffplay_path)

        self.devices: dict[str, ADBDevice] = {}
        self.selected_serial = tk.StringVar(value="")
        self.device_ip = tk.StringVar(value="")
        self.rtsp_url = tk.StringVar(value="")
        self.service_status = tk.StringVar(value=state_text("unknown"))
        self.status_text = tk.StringVar(value=state_text("ready"))
        self.dep_vars: dict[str, tk.StringVar] = {}
        self.yolo_packages: dict[str, YoloPackage] = {}
        self.selected_yolo_package = tk.StringVar(value="")
        self.start_after_update = tk.BooleanVar(value=False)
        self.ai_stream_enabled = tk.BooleanVar(value=False)
        self.internet_adapters: dict[str, NetworkAdapter] = {}
        self.usb_adapters: dict[str, NetworkAdapter] = {}
        self.selected_internet_adapter = tk.StringVar(value="")
        self.selected_usb_adapter = tk.StringVar(value="")
        self.usb_sharing_status = tk.StringVar(value=state_text("unknown"))
        self.yolo_apps_path = yolo_apps_dir(get_app_dir())
        self._operation_in_progress = False

        self._build_ui()
        self._render_dependency_status()
        self.refresh_yolo_packages()
        self._update_button_states()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if self.dependencies["adb"].found:
            self.refresh_devices()
        else:
            self.log("未找到 adb。请安装 Android platform tools，或把 adb 加到 PATH。")

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(6, weight=1)

        dep_frame = ttk.LabelFrame(self.root, text=TEXT["dependencies"])
        dep_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        dep_frame.columnconfigure((0, 1, 2), weight=1)
        for index, name in enumerate(("adb", "ffplay", "tkinter")):
            self.dep_vars[name] = tk.StringVar(value=f"{name}: {state_text('checking')}")
            ttk.Label(dep_frame, textvariable=self.dep_vars[name]).grid(
                row=0, column=index, sticky="w", padx=10, pady=4
            )

        device_frame = ttk.LabelFrame(self.root, text=TEXT["devices"])
        device_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        device_frame.columnconfigure(0, weight=1)
        device_frame.rowconfigure(0, weight=1)

        self.device_tree = ttk.Treeview(
            device_frame,
            columns=("serial", "state"),
            show="headings",
            height=3,
            selectmode="browse",
        )
        self.device_tree.heading("serial", text=TEXT["serial"])
        self.device_tree.heading("state", text=TEXT["state"])
        self.device_tree.column("serial", width=520, anchor="w")
        self.device_tree.column("state", width=140, anchor="center")
        self.device_tree.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=4)
        self.device_tree.bind("<<TreeviewSelect>>", self.on_device_selected)

        device_scroll = ttk.Scrollbar(device_frame, orient="vertical", command=self.device_tree.yview)
        device_scroll.grid(row=0, column=1, sticky="ns", pady=4)
        self.device_tree.configure(yscrollcommand=device_scroll.set)

        device_buttons = ttk.Frame(device_frame)
        device_buttons.grid(row=0, column=2, sticky="ns", padx=8, pady=4)
        self.refresh_button = ttk.Button(
            device_buttons, text=TEXT["refresh_devices"], command=self.refresh_devices
        )
        self.refresh_button.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        usb_frame = ttk.LabelFrame(self.root, text=TEXT["usb_sharing"])
        usb_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        usb_frame.columnconfigure(1, weight=1)
        usb_frame.columnconfigure(3, weight=1)
        ttk.Label(usb_frame, text=TEXT["internet_adapter"]).grid(
            row=0, column=0, sticky="w", padx=(10, 6), pady=(4, 2)
        )
        self.internet_adapter_combo = ttk.Combobox(
            usb_frame,
            textvariable=self.selected_internet_adapter,
            state="readonly",
            values=(),
        )
        self.internet_adapter_combo.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(4, 2))
        self.internet_adapter_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_button_states())
        ttk.Label(usb_frame, text=TEXT["usb_adapter"]).grid(
            row=0, column=2, sticky="w", padx=(10, 6), pady=(4, 2)
        )
        self.usb_adapter_combo = ttk.Combobox(
            usb_frame,
            textvariable=self.selected_usb_adapter,
            state="readonly",
            values=(),
        )
        self.usb_adapter_combo.grid(row=0, column=3, sticky="ew", padx=(0, 10), pady=(4, 2))
        self.usb_adapter_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_button_states())

        self.detect_adapters_button = ttk.Button(
            usb_frame, text=TEXT["detect_network_adapters"], command=self.detect_network_adapters
        )
        self.configure_usb_sharing_button = ttk.Button(
            usb_frame, text=TEXT["configure_usb_sharing"], command=self.configure_usb_sharing
        )
        self.manual_network_settings_button = ttk.Button(
            usb_frame, text=TEXT["open_manual_network_settings"], command=self.open_manual_network_settings
        )
        self.detect_usb0_button = ttk.Button(
            usb_frame, text=TEXT["detect_usb0_ip"], command=self.detect_usb0_ip
        )
        self.detect_adapters_button.grid(row=1, column=0, sticky="ew", padx=(10, 6), pady=2)
        self.configure_usb_sharing_button.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        self.manual_network_settings_button.grid(row=1, column=2, sticky="ew", padx=6, pady=2)
        self.detect_usb0_button.grid(row=1, column=3, sticky="ew", padx=(6, 10), pady=2)
        ttk.Label(usb_frame, textvariable=self.usb_sharing_status, anchor="w").grid(
            row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=(2, 4)
        )

        stream_frame = ttk.LabelFrame(self.root, text=TEXT["stream"])
        stream_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=4)
        stream_frame.columnconfigure(1, weight=1)
        stream_frame.columnconfigure(3, weight=1)
        self._add_compact_field(stream_frame, 0, 0, TEXT["selected_device"], self.selected_serial)
        self._add_compact_field(stream_frame, 0, 2, TEXT["device_ip"], self.device_ip)
        ttk.Label(stream_frame, text=TEXT["rtsp_url"]).grid(row=1, column=0, sticky="w", padx=10, pady=2)
        ttk.Label(stream_frame, textvariable=self.rtsp_url).grid(
            row=1, column=1, columnspan=3, sticky="ew", padx=10, pady=2
        )
        self._add_compact_field(stream_frame, 2, 0, TEXT["board_service"], self.service_status)
        self.ai_stream_check = ttk.Checkbutton(
            stream_frame,
            text=TEXT["enable_ai_detection"],
            variable=self.ai_stream_enabled,
        )
        self.ai_stream_check.grid(row=2, column=2, columnspan=2, sticky="w", padx=10, pady=2)

        yolo_frame = ttk.LabelFrame(self.root, text=TEXT["yolo_package"])
        yolo_frame.grid(row=4, column=0, sticky="ew", padx=12, pady=4)
        yolo_frame.columnconfigure(0, weight=1)
        self.yolo_package_combo = ttk.Combobox(
            yolo_frame,
            textvariable=self.selected_yolo_package,
            state="readonly",
            values=(),
        )
        self.yolo_package_combo.grid(row=0, column=0, sticky="ew", padx=(8, 6), pady=4)
        self.yolo_package_combo.bind("<<ComboboxSelected>>", lambda _event: self._update_button_states())
        self.refresh_yolo_button = ttk.Button(
            yolo_frame, text=TEXT["refresh_yolo_packages"], command=self.refresh_yolo_packages
        )
        self.update_yolo_button = ttk.Button(
            yolo_frame, text=TEXT["update_yolo_package"], command=self.update_yolo_package
        )
        self.start_after_update_check = ttk.Checkbutton(
            yolo_frame, text=TEXT["start_after_update"], variable=self.start_after_update
        )
        self.refresh_yolo_button.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        self.update_yolo_button.grid(row=0, column=2, sticky="ew", padx=6, pady=4)
        self.start_after_update_check.grid(row=0, column=3, sticky="w", padx=(6, 8), pady=4)

        controls = ttk.LabelFrame(self.root, text=TEXT["controls"])
        controls.grid(row=5, column=0, sticky="ew", padx=12, pady=4)
        for col in range(5):
            controls.columnconfigure(col, weight=1)
        self.start_service_button = ttk.Button(
            controls, text=TEXT["start_board_stream"], command=self.start_board_service
        )
        self.stop_service_button = ttk.Button(
            controls, text=TEXT["stop_board_stream"], command=self.stop_board_service
        )
        self.start_playback_button = ttk.Button(
            controls, text=TEXT["start_playback"], command=self.start_playback
        )
        self.stop_playback_button = ttk.Button(
            controls, text=TEXT["stop_playback"], command=self.stop_playback
        )
        self.copy_button = ttk.Button(controls, text=TEXT["copy_rtsp_url"], command=self.copy_rtsp_url)
        self.start_service_button.grid(row=0, column=0, sticky="ew", padx=6, pady=4)
        self.stop_service_button.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        self.start_playback_button.grid(row=0, column=2, sticky="ew", padx=6, pady=4)
        self.stop_playback_button.grid(row=0, column=3, sticky="ew", padx=6, pady=4)
        self.copy_button.grid(row=0, column=4, sticky="ew", padx=6, pady=4)

        log_frame = ttk.LabelFrame(self.root, text=TEXT["log"])
        log_frame.grid(row=6, column=0, sticky="nsew", padx=12, pady=(4, 6))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=4)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns", pady=4)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        status_bar = ttk.Label(self.root, textvariable=self.status_text, anchor="w")
        status_bar.grid(row=7, column=0, sticky="ew", padx=12, pady=(0, 8))

    def _add_compact_field(
        self, parent: ttk.Frame, row: int, column: int, label: str, variable: tk.StringVar
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=10, pady=2)
        ttk.Label(parent, textvariable=variable).grid(
            row=row, column=column + 1, sticky="ew", padx=10, pady=2
        )

    def _render_dependency_status(self) -> None:
        for name, status in self.dependencies.items():
            marker = "正常" if status.found else "缺失"
            self.dep_vars[name].set(f"{name}: {marker} ({dependency_detail_text(status)})")
        self.log("依赖检测完成。")
        for status in self.dependencies.values():
            self.log(self._format_dependency(status))

    def _format_dependency(self, status: DependencyStatus) -> str:
        return dependency_log_text(status)

    def _set_busy(self, message: str) -> None:
        self._operation_in_progress = True
        self.status_text.set(message)
        self.root.config(cursor="watch")
        self._update_button_states()

    def _clear_busy(self) -> None:
        self._operation_in_progress = False
        self.status_text.set(state_text("ready"))
        self.root.config(cursor="")
        self._update_button_states()

    def _update_button_states(self) -> None:
        has_adb = self.dependencies["adb"].found
        has_ffplay = self.dependencies["ffplay"].found
        has_device = bool(self.selected_serial.get())
        device = self.devices.get(self.selected_serial.get())
        has_usable_device = bool(device and device.state == "device")
        has_url = bool(self.rtsp_url.get())
        has_yolo_package = self._selected_yolo_package() is not None
        busy = getattr(self, "_operation_in_progress", False)

        self.refresh_button.configure(state="normal" if has_adb and not busy else "disabled")
        state_for_device = "normal" if has_adb and has_device and not busy else "disabled"
        self.start_service_button.configure(state=state_for_device)
        self.stop_service_button.configure(state=state_for_device)
        self.start_playback_button.configure(
            state="normal" if has_adb and has_ffplay and has_device and not busy else "disabled"
        )
        self.stop_playback_button.configure(state="normal" if self.player.is_running() and not busy else "disabled")
        self.copy_button.configure(state="normal" if has_url else "disabled")
        self.refresh_yolo_button.configure(state="normal")
        self.update_yolo_button.configure(
            state="normal" if has_adb and has_usable_device and has_yolo_package and not busy else "disabled"
        )
        checkbox_state = "disabled" if busy else "normal"
        self.start_after_update_check.configure(state=checkbox_state)
        self.ai_stream_check.configure(state=checkbox_state)

        is_windows = self._is_windows()
        has_selected_adapters = bool(self._selected_internet_adapter() and self._selected_usb_adapter())
        windows_ready = is_windows and not busy
        self._configure_optional_button(
            "detect_adapters_button", "normal" if windows_ready else "disabled"
        )
        self._configure_optional_button(
            "configure_usb_sharing_button",
            "normal" if windows_ready and has_selected_adapters else "disabled",
        )
        self._configure_optional_button(
            "manual_network_settings_button", "normal" if windows_ready else "disabled"
        )
        self._configure_optional_button(
            "detect_usb0_button", "normal" if has_adb and has_usable_device and not busy else "disabled"
        )

    def _configure_optional_button(self, attribute_name: str, state: str) -> None:
        button = getattr(self, attribute_name, None)
        if button is not None:
            button.configure(state=state)

    def _is_windows(self) -> bool:
        return windows_ics.is_windows()

    def _selected_internet_adapter(self) -> NetworkAdapter | None:
        selected_var = getattr(self, "selected_internet_adapter", None)
        if selected_var is None:
            return None
        return getattr(self, "internet_adapters", {}).get(selected_var.get())

    def _selected_usb_adapter(self) -> NetworkAdapter | None:
        selected_var = getattr(self, "selected_usb_adapter", None)
        if selected_var is None:
            return None
        return getattr(self, "usb_adapters", {}).get(selected_var.get())

    def detect_network_adapters(self) -> None:
        if not self._is_windows():
            self.log("USB 网络共享自动配置仅适用于 Windows。")
            return

        def work() -> None:
            self._ui(self.log, "正在检测 Windows 网络适配器...")
            adapters = run_adapter_discovery()
            self._ui(self._replace_network_adapters, adapters)

        self._run_background("正在检测 Windows 网络适配器...", work)

    def _replace_network_adapters(self, adapters: list[NetworkAdapter]) -> None:
        internet_candidates = select_internet_adapters(adapters)
        usb_candidates = select_usb_adapters(adapters)

        self.internet_adapters = adapter_choice_map(internet_candidates)
        self.usb_adapters = adapter_choice_map(usb_candidates)
        internet_values = tuple(self.internet_adapters)
        usb_values = tuple(self.usb_adapters)
        self.internet_adapter_combo.configure(values=internet_values)
        self.usb_adapter_combo.configure(values=usb_values)

        internet_choice = choose_single_internet_adapter(internet_candidates)
        usb_choice = choose_single_usb_adapter(usb_candidates)
        self.selected_internet_adapter.set(self._adapter_label_for_choice(self.internet_adapters, internet_choice))
        self.selected_usb_adapter.set(self._adapter_label_for_choice(self.usb_adapters, usb_choice))

        if internet_values:
            self.log("检测到上网网卡：" + "、".join(internet_values))
        else:
            self.log("未检测到可用于上网的 Windows 网卡。")
        if usb_values:
            self.log("检测到板子 USB 网卡：" + "、".join(usb_values))
        else:
            self.log("未检测到板子 USB 网卡。请确认 USB 网络/RNDIS 已连接。")

        if internet_values or usb_values:
            self.usb_sharing_status.set("请选择网卡后配置 USB 网络共享。")
        else:
            self.usb_sharing_status.set("未检测到可用网卡。请检查网络和 USB/RNDIS 连接后重新检测。")
        self._update_button_states()

    def _adapter_label_for_choice(
        self, choices: dict[str, NetworkAdapter], choice: NetworkAdapter | None
    ) -> str:
        if choice is None:
            return ""
        for label, adapter in choices.items():
            if adapter is choice or adapter == choice:
                return label
        return ""

    def configure_usb_sharing(self) -> None:
        self._show_usb_sharing_placeholder("自动配置 USB 网络共享")

    def open_manual_network_settings(self) -> None:
        self._show_usb_sharing_placeholder("打开手动网络设置")

    def detect_usb0_ip(self) -> None:
        self._show_usb_sharing_placeholder("检测 usb0 IP")

    def _show_usb_sharing_placeholder(self, action: str) -> None:
        message = f"{action}功能尚未执行，将在后续步骤实现；当前不会修改系统或设备。"
        self.usb_sharing_status.set(message)
        self.log(message)

    def _run_background(self, message: str, work: Callable[[], T]) -> None:
        if getattr(self, "_operation_in_progress", False):
            self.log("已有操作正在执行，请稍候。")
            return
        self._set_busy(message)

        def target() -> None:
            try:
                work()
            except Exception as exc:  # Keep the GUI alive and show actionable detail.
                self._ui(self.log, f"错误：{exc}")
                self._ui(messagebox.showerror, "操作失败", str(exc))
            finally:
                self._ui(self._clear_busy)

        threading.Thread(target=target, daemon=True).start()

    def _ui(self, func: Callable[..., T], *args: object) -> None:
        self.root.after(0, lambda: func(*args))

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def refresh_yolo_packages(self) -> None:
        current_selection = self.selected_yolo_package.get()
        packages = scan_yolo_packages(self.yolo_apps_path)
        choices = self._build_yolo_package_choices(packages)
        self.yolo_packages = choices
        values = tuple(choices)
        self.yolo_package_combo.configure(values=values)

        if current_selection in choices:
            self.selected_yolo_package.set(current_selection)
        elif values:
            self.selected_yolo_package.set(values[0])
        else:
            self.selected_yolo_package.set("")

        if packages:
            self.log(f"找到 {len(packages)} 个 YOLO 组合包：{self.yolo_apps_path}")
        else:
            self.log(f"没有找到 YOLO 组合包。请放到 {self._yolo_package_example_path()}")
        self._update_button_states()

    def _yolo_package_example_path(self) -> str:
        return str(self.yolo_apps_path / "yoloApp_xxx")

    def _build_yolo_package_choices(self, packages: list[YoloPackage]) -> dict[str, YoloPackage]:
        display_counts: dict[str, int] = {}
        for package in packages:
            display_counts[package.display_name] = display_counts.get(package.display_name, 0) + 1

        choices: dict[str, YoloPackage] = {}
        for package in packages:
            label = package.display_name
            if display_counts[label] > 1 or label in choices:
                label = f"{package.display_name} ({package.name})"
            choices[label] = package
        return choices

    def _selected_yolo_package(self) -> YoloPackage | None:
        return self.yolo_packages.get(self.selected_yolo_package.get())

    def update_yolo_package(self) -> None:
        device = self._require_selected_device()
        if not device:
            return
        package = self._selected_yolo_package()
        if not package:
            messagebox.showwarning(
                "未选择组合包",
                f"请把组合包放到 {self._yolo_package_example_path()}，然后选择一个模型/App 组合。",
            )
            return

        confirmed = messagebox.askyesno(
            "确认更新组合包",
            "这会覆盖板端 /usr/bin/sample_smart_camera 和 /network_binary.nb。\n"
            f"确定更新为 {package.display_name} 吗？",
        )
        if not confirmed:
            return

        start_after_update = self.start_after_update.get()
        ai_enabled = self.ai_stream_enabled.get()

        def work() -> None:
            self._ui(self.log, f"正在更新 YOLO 组合包 {package.display_name} 到设备 {device.serial}...")
            result = self.adb.install_yolo_package(device.serial, str(package.app_path), str(package.model_path))
            if not result.ok:
                detail = result.stderr.strip() or result.stdout.strip() or "组合包更新命令返回非 0 状态。"
                raise RuntimeError(detail)

            self._ui(self.log, f"已更新 YOLO 组合包：{package.display_name}")
            self._ui(self.service_status.set, state_text("stopped"))
            if start_after_update:
                url = self._inspect_device(device.serial, start_if_needed=True, ai_enabled=ai_enabled)
                command = self.player.start(url)
                self._ui(self.log, "已启动 ffplay：" + " ".join(command))
                self._ui(self._update_button_states)

        self._run_background("正在更新 YOLO 组合包...", work)

    def refresh_devices(self) -> None:
        def work() -> None:
            self._ui(self.log, "正在执行 adb devices...")
            devices = self.adb.list_devices()
            self._ui(self._replace_devices, devices)
            if devices:
                self._ui(self.log, f"找到 {len(devices)} 个 ADB 设备。")
            else:
                self._ui(self.log, "没有找到 ADB 设备。")

        self._run_background("正在刷新 ADB 设备...", work)

    def _replace_devices(self, devices: list[ADBDevice]) -> None:
        self.devices = {device.serial: device for device in devices}
        for item in self.device_tree.get_children():
            self.device_tree.delete(item)
        for device in devices:
            self.device_tree.insert(
                "", "end", iid=device.serial, values=(device.serial, device_state_text(device.state))
            )
        self.selected_serial.set("")
        self.device_ip.set("")
        self.rtsp_url.set("")
        self.service_status.set(state_text("unknown"))
        self._update_button_states()

    def on_device_selected(self, _event: object | None = None) -> None:
        selection = self.device_tree.selection()
        if not selection:
            return
        serial = str(selection[0])
        device = self.devices.get(serial)
        self.selected_serial.set(serial)
        self.device_ip.set("")
        self.rtsp_url.set("")
        self.service_status.set(state_text("unknown"))
        self._update_button_states()
        if not device:
            return
        self.log(f"已选择设备 {device.serial}（{device_state_text(device.state)}）。")
        if device.state != "device":
            self._explain_unusable_device(device.state)
            return
        self.inspect_selected_device()

    def _explain_unusable_device(self, state: str) -> None:
        if state == "unauthorized":
            self.log("设备未授权。请在板端确认 USB 调试授权提示。")
        elif state == "offline":
            self.log("设备离线。请重插 USB，或执行 adb kill-server && adb start-server。")
        else:
            self.log(f"设备状态是 {state}；只有已连接状态才能播放。")

    def _require_selected_device(self) -> ADBDevice | None:
        serial = self.selected_serial.get()
        if not serial:
            messagebox.showwarning("未选择设备", "请先选择一个 ADB 设备。")
            return None
        device = self.devices.get(serial)
        if not device:
            messagebox.showwarning("未找到设备", "请刷新设备列表，然后重新选择板子。")
            return None
        if device.state != "device":
            self._explain_unusable_device(device.state)
            messagebox.showwarning("设备未就绪", f"设备状态是 {device_state_text(device.state)}。")
            return None
        return device

    def inspect_selected_device(self) -> None:
        device = self._require_selected_device()
        if not device:
            return

        def work() -> None:
            self._inspect_device(device.serial, start_if_needed=False)

        self._run_background("正在检查所选设备...", work)

    def _inspect_device(self, serial: str, start_if_needed: bool, ai_enabled: bool = False) -> str:
        self._ui(self.log, f"正在检查设备 {serial} 上的 {SERVICE_NAME}...")
        if not self.adb.command_exists(serial):
            message = f"板端 PATH 里找不到 {SERVICE_NAME}。请确认 /usr/bin/{SERVICE_NAME} 存在并可执行。"
            self._ui(self.service_status.set, state_text("missing"))
            raise RuntimeError(message)

        if self.adb.is_service_running(serial):
            self._ui(self.service_status.set, state_text("running"))
            self._ui(self.log, f"{SERVICE_NAME} 已经在运行。")
            self._ui(self.log, "服务已运行，不会因为当前勾选框切换模式；如需切换，请先停止再启动。")
        elif start_if_needed:
            self._ui(self.service_status.set, state_text("starting"))
            mode_text = "AI 检测 + 推流" if ai_enabled else "仅推流"
            self._ui(self.log, f"正在以{mode_text}模式启动 {SERVICE_NAME}，设备：{serial}...")
            result = self.adb.start_service(serial, ai_enabled=ai_enabled)
            if not result.ok:
                self._ui(self.service_status.set, state_text("start failed"))
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "板端推流服务启动失败。")
            if not self.adb.wait_for_service(serial, timeout=8.0, interval=0.5):
                self._ui(self.service_status.set, state_text("start failed"))
                raise RuntimeError(f"推流服务启动后没有保持运行。请在板端查看 {SERVICE_LOG}。")
            self._ui(self.service_status.set, state_text("running"))
            self._ui(self.log, f"{SERVICE_NAME} 已启动。")
        else:
            self._ui(self.service_status.set, state_text("stopped"))
            self._ui(self.log, f"{SERVICE_NAME} 当前未运行。")

        ip = self.adb.discover_ip(serial)
        if not ip:
            raise RuntimeError("无法通过 ip route 或 ifconfig 获取板端 IP。")
        url = build_rtsp_url(ip)
        self._ui(self.device_ip.set, ip)
        self._ui(self.rtsp_url.set, url)
        self._ui(self.log, f"RTSP 地址：{url}")
        return url

    def start_board_service(self) -> None:
        device = self._require_selected_device()
        if not device:
            return
        ai_enabled = self.ai_stream_enabled.get()

        def work() -> None:
            self._inspect_device(device.serial, start_if_needed=True, ai_enabled=ai_enabled)

        self._run_background("正在启动板端推流服务...", work)

    def stop_board_service(self) -> None:
        device = self._require_selected_device()
        if not device:
            return

        def work() -> None:
            self._ui(self.log, f"正在停止设备 {device.serial} 上的 {SERVICE_NAME}...")
            result = self.adb.stop_service(device.serial)
            if not result.ok:
                self._ui(self.log, result.stderr.strip() or result.stdout.strip() or "停止命令返回非 0 状态。")
            time.sleep(0.5)
            running = self.adb.is_service_running(device.serial)
            self._ui(self.service_status.set, state_text("running") if running else state_text("stopped"))
            self._ui(self.log, "板端推流服务仍在运行。" if running else "板端推流服务已停止。")

        self._run_background("正在停止板端推流服务...", work)

    def start_playback(self) -> None:
        device = self._require_selected_device()
        if not device:
            return
        ai_enabled = self.ai_stream_enabled.get()

        def work() -> None:
            url = self._inspect_device(device.serial, start_if_needed=True, ai_enabled=ai_enabled)
            command = self.player.start(url)
            self._ui(self.log, "已启动 ffplay：" + " ".join(command))
            self._ui(self._update_button_states)

        self._run_background("正在开始播放...", work)

    def stop_playback(self) -> None:
        self.player.stop()
        self.log("已停止 ffplay 播放。")
        self._update_button_states()

    def copy_rtsp_url(self) -> None:
        url = self.rtsp_url.get()
        if not url:
            messagebox.showinfo("没有 RTSP 地址", "当前还没有可用的 RTSP 地址。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.log(f"已复制 RTSP 地址：{url}")

    def on_close(self) -> None:
        self.player.stop()
        self.adb.stop_all_local_service_processes()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = RTSPToolApp(root)
    app.log("就绪。请选择设备，然后开始播放。")
    root.mainloop()
