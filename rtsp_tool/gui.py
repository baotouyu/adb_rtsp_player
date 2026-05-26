from __future__ import annotations

from datetime import datetime
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, TypeVar

from .adb_client import ADBClient, ADBDevice, SERVICE_LOG, SERVICE_NAME
from .dependencies import DependencyStatus, check_dependencies
from .i18n import TEXT, device_state_text, state_text
from .player import PlayerController, build_rtsp_url


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
        self.root.geometry("920x680")
        self.root.minsize(760, 560)

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

        self._build_ui()
        self._render_dependency_status()
        self._update_button_states()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if self.dependencies["adb"].found:
            self.refresh_devices()
        else:
            self.log("未找到 adb。请安装 Android platform tools，或把 adb 加到 PATH。")

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(4, weight=1)

        dep_frame = ttk.LabelFrame(self.root, text=TEXT["dependencies"])
        dep_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        dep_frame.columnconfigure((0, 1, 2), weight=1)
        for index, name in enumerate(("adb", "ffplay", "tkinter")):
            self.dep_vars[name] = tk.StringVar(value=f"{name}: {state_text('checking')}")
            ttk.Label(dep_frame, textvariable=self.dep_vars[name]).grid(
                row=0, column=index, sticky="w", padx=10, pady=8
            )

        device_frame = ttk.LabelFrame(self.root, text=TEXT["devices"])
        device_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        device_frame.columnconfigure(0, weight=1)
        device_frame.rowconfigure(0, weight=1)

        self.device_tree = ttk.Treeview(
            device_frame,
            columns=("serial", "state"),
            show="headings",
            height=6,
            selectmode="browse",
        )
        self.device_tree.heading("serial", text=TEXT["serial"])
        self.device_tree.heading("state", text=TEXT["state"])
        self.device_tree.column("serial", width=520, anchor="w")
        self.device_tree.column("state", width=140, anchor="center")
        self.device_tree.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        self.device_tree.bind("<<TreeviewSelect>>", self.on_device_selected)

        device_scroll = ttk.Scrollbar(device_frame, orient="vertical", command=self.device_tree.yview)
        device_scroll.grid(row=0, column=1, sticky="ns", pady=8)
        self.device_tree.configure(yscrollcommand=device_scroll.set)

        device_buttons = ttk.Frame(device_frame)
        device_buttons.grid(row=0, column=2, sticky="ns", padx=8, pady=8)
        self.refresh_button = ttk.Button(
            device_buttons, text=TEXT["refresh_devices"], command=self.refresh_devices
        )
        self.refresh_button.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        stream_frame = ttk.LabelFrame(self.root, text=TEXT["stream"])
        stream_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        stream_frame.columnconfigure(1, weight=1)
        self._add_field(stream_frame, 0, TEXT["selected_device"], self.selected_serial)
        self._add_field(stream_frame, 1, TEXT["device_ip"], self.device_ip)
        self._add_field(stream_frame, 2, TEXT["rtsp_url"], self.rtsp_url)
        self._add_field(stream_frame, 3, TEXT["board_service"], self.service_status)

        controls = ttk.LabelFrame(self.root, text=TEXT["controls"])
        controls.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
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
        self.start_service_button.grid(row=0, column=0, sticky="ew", padx=6, pady=8)
        self.stop_service_button.grid(row=0, column=1, sticky="ew", padx=6, pady=8)
        self.start_playback_button.grid(row=0, column=2, sticky="ew", padx=6, pady=8)
        self.stop_playback_button.grid(row=0, column=3, sticky="ew", padx=6, pady=8)
        self.copy_button.grid(row=0, column=4, sticky="ew", padx=6, pady=8)

        log_frame = ttk.LabelFrame(self.root, text=TEXT["log"])
        log_frame.grid(row=4, column=0, sticky="nsew", padx=12, pady=(6, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(8, 4), pady=8)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns", pady=8)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        status_bar = ttk.Label(self.root, textvariable=self.status_text, anchor="w")
        status_bar.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 8))

    def _add_field(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=4)
        ttk.Label(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=10, pady=4)

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
        self.status_text.set(message)
        self.root.config(cursor="watch")

    def _clear_busy(self) -> None:
        self.status_text.set(state_text("ready"))
        self.root.config(cursor="")
        self._update_button_states()

    def _update_button_states(self) -> None:
        has_adb = self.dependencies["adb"].found
        has_ffplay = self.dependencies["ffplay"].found
        has_device = bool(self.selected_serial.get())
        has_url = bool(self.rtsp_url.get())

        self.refresh_button.configure(state="normal" if has_adb else "disabled")
        state_for_device = "normal" if has_adb and has_device else "disabled"
        self.start_service_button.configure(state=state_for_device)
        self.stop_service_button.configure(state=state_for_device)
        self.start_playback_button.configure(state="normal" if has_adb and has_ffplay and has_device else "disabled")
        self.stop_playback_button.configure(state="normal" if self.player.is_running() else "disabled")
        self.copy_button.configure(state="normal" if has_url else "disabled")

    def _run_background(self, message: str, work: Callable[[], T]) -> None:
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

    def _inspect_device(self, serial: str, start_if_needed: bool) -> str:
        self._ui(self.log, f"正在检查设备 {serial} 上的 {SERVICE_NAME}...")
        if not self.adb.command_exists(serial):
            message = f"板端 PATH 里找不到 {SERVICE_NAME}。请确认 /usr/bin/{SERVICE_NAME} 存在并可执行。"
            self._ui(self.service_status.set, state_text("missing"))
            raise RuntimeError(message)

        if self.adb.is_service_running(serial):
            self._ui(self.service_status.set, state_text("running"))
            self._ui(self.log, f"{SERVICE_NAME} 已经在运行。")
        elif start_if_needed:
            self._ui(self.service_status.set, state_text("starting"))
            self._ui(self.log, f"正在启动 {SERVICE_NAME}，设备：{serial}...")
            result = self.adb.start_service(serial)
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

        def work() -> None:
            self._inspect_device(device.serial, start_if_needed=True)

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

        def work() -> None:
            url = self._inspect_device(device.serial, start_if_needed=True)
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
