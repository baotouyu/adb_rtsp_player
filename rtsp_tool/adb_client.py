from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
import time
from typing import Sequence


SERVICE_NAME = "sample_smart_camera"
SERVICE_PATH = "/usr/bin/sample_smart_camera"
SERVICE_ARGS = "--rtsp-only"
SERVICE_LOG = "/tmp/sample_smart_camera.log"
YOLO_UPDATE_DIR = "/tmp/yolo_app_update"
YOLO_APP_REMOTE_PATH = SERVICE_PATH
YOLO_MODEL_REMOTE_PATH = "/network_binary.nb"
YOLO_INSTALL_TIMEOUT = 120.0


@dataclass(frozen=True)
class ADBDevice:
    serial: str
    state: str


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def parse_adb_devices(output: str) -> list[ADBDevice]:
    devices: list[ADBDevice] = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append(ADBDevice(serial=parts[0], state=parts[1]))
    return devices


def _valid_device_ip(ip: str) -> bool:
    return not (
        ip.startswith("127.")
        or ip.startswith("0.")
        or ip == "255.255.255.255"
        or ip == "0.0.0.0"
    )


def parse_ip_route_ip(output: str) -> str | None:
    for line in output.splitlines():
        if not line.strip().startswith("default "):
            continue
        match = re.search(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)\b", line)
        if match and _valid_device_ip(match.group(1)):
            return match.group(1)

    for match in re.finditer(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)\b", output):
        ip = match.group(1)
        if _valid_device_ip(ip):
            return ip
    return None


def parse_ifconfig_ip(output: str) -> str | None:
    patterns = (
        r"\binet addr:(\d+\.\d+\.\d+\.\d+)\b",
        r"\binet\s+(?:addr:)?(\d+\.\d+\.\d+\.\d+)\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, output):
            ip = match.group(1)
            if _valid_device_ip(ip):
                return ip
    return None


def build_shell_command(adb_path: str, serial: str, shell_command: str) -> list[str]:
    return [adb_path, "-s", serial, "shell", shell_command]


class ADBClient:
    def __init__(self, adb_path: str = "adb", timeout: float = 8.0):
        self.adb_path = adb_path
        self.timeout = timeout
        self._service_processes: dict[str, subprocess.Popen[str]] = {}

    def run(self, args: Sequence[str], timeout: float | None = None) -> CommandResult:
        command = [self.adb_path, *args]
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=self.timeout if timeout is None else timeout,
                check=False,
            )
            return CommandResult(command, completed.returncode, completed.stdout, completed.stderr)
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command,
                124,
                exc.stdout or "",
                exc.stderr or f"Command timed out after {exc.timeout} seconds",
            )
        except OSError as exc:
            return CommandResult(command, 127, "", str(exc))

    def shell(self, serial: str, shell_command: str, timeout: float | None = None) -> CommandResult:
        return self.run(["-s", serial, "shell", shell_command], timeout=timeout)

    def list_devices(self) -> list[ADBDevice]:
        result = self.run(["devices"])
        if not result.ok:
            return []
        return parse_adb_devices(result.stdout)

    def command_exists_command(self, serial: str) -> list[str]:
        return build_shell_command(self.adb_path, serial, f"test -x {SERVICE_PATH}")

    def service_status_command(self, serial: str) -> list[str]:
        return build_shell_command(self.adb_path, serial, f"pidof {SERVICE_NAME}")

    def start_service_command(self, serial: str) -> list[str]:
        shell_command = f"cd /tmp && {SERVICE_PATH} {SERVICE_ARGS} >{SERVICE_LOG} 2>&1"
        return build_shell_command(self.adb_path, serial, shell_command)

    def stop_service_command(self, serial: str, ignore_missing: bool = False) -> list[str]:
        shell_command = f"pkill {SERVICE_NAME}"
        if ignore_missing:
            shell_command = f"{shell_command} || true"
        return build_shell_command(self.adb_path, serial, shell_command)

    def prepare_yolo_update_command(self, serial: str) -> list[str]:
        return build_shell_command(self.adb_path, serial, f"rm -rf {YOLO_UPDATE_DIR} && mkdir -p {YOLO_UPDATE_DIR}")

    def push_yolo_file_command(self, serial: str, local_path: str, remote_path: str) -> list[str]:
        return [self.adb_path, "-s", serial, "push", local_path, remote_path]

    def install_yolo_update_command(self, serial: str) -> list[str]:
        shell_command = (
            f"app={YOLO_APP_REMOTE_PATH}; model={YOLO_MODEL_REMOTE_PATH}; dir={YOLO_UPDATE_DIR}; "
            "backup_app=$dir/sample_smart_camera.previous; backup_model=$dir/network_binary.nb.previous; "
            "if cp $app $backup_app && cp $model $backup_model && "
            "cp $dir/sample_smart_camera $app && cp $dir/network_binary.nb $model && chmod +x $app && sync; "
            "then rm -rf $dir; "
            "else cp $backup_app $app; cp $backup_model $model; chmod +x $app; sync; rm -rf $dir; false; fi"
        )
        return build_shell_command(self.adb_path, serial, shell_command)

    def command_exists(self, serial: str) -> bool:
        result = self.shell(serial, f"test -x {SERVICE_PATH}")
        return result.ok

    def service_pid(self, serial: str) -> str | None:
        result = self.shell(serial, f"pidof {SERVICE_NAME}")
        if result.ok and result.stdout.strip():
            return result.stdout.strip().split()[0]
        return None

    def is_service_running(self, serial: str) -> bool:
        return self.service_pid(serial) is not None

    def wait_for_service(self, serial: str, timeout: float = 8.0, interval: float = 0.5) -> bool:
        attempts = max(1, int(timeout / interval))
        for _ in range(attempts):
            if self.is_service_running(serial):
                return True
            time.sleep(interval)
        return self.is_service_running(serial)

    def start_service(self, serial: str) -> CommandResult:
        command = self.start_service_command(serial)
        existing = self._service_processes.get(serial)
        if existing and existing.poll() is None:
            return CommandResult(command, 0, "started", "")
        try:
            self._service_processes[serial] = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return CommandResult(command, 0, "started", "")
        except OSError as exc:
            return CommandResult(command, 127, "", str(exc))

    def stop_service(self, serial: str, ignore_missing: bool = False) -> CommandResult:
        result = self.run(self.stop_service_command(serial, ignore_missing=ignore_missing)[1:])
        self.stop_local_service_process(serial)
        return result

    def install_yolo_package(self, serial: str, app_path: str, model_path: str) -> CommandResult:
        last_result = self.stop_service(serial, ignore_missing=True)
        if not last_result.ok:
            return last_result

        steps = [
            (self.prepare_yolo_update_command(serial)[1:], None),
            (self.push_yolo_file_command(serial, app_path, f"{YOLO_UPDATE_DIR}/sample_smart_camera")[1:], YOLO_INSTALL_TIMEOUT),
            (self.push_yolo_file_command(serial, model_path, f"{YOLO_UPDATE_DIR}/network_binary.nb")[1:], YOLO_INSTALL_TIMEOUT),
            (self.install_yolo_update_command(serial)[1:], YOLO_INSTALL_TIMEOUT),
        ]
        for step, timeout in steps:
            last_result = self.run(step, timeout=timeout)
            if not last_result.ok:
                return last_result
        return last_result

    def stop_local_service_process(self, serial: str) -> None:
        process = self._service_processes.pop(serial, None)
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def stop_all_local_service_processes(self) -> None:
        for serial in list(self._service_processes):
            self.stop_local_service_process(serial)

    def get_ip_route_output(self, serial: str) -> CommandResult:
        return self.shell(serial, "ip route")

    def get_ifconfig_output(self, serial: str) -> CommandResult:
        return self.shell(serial, "ifconfig")

    def discover_ip(self, serial: str) -> str | None:
        route_result = self.get_ip_route_output(serial)
        if route_result.ok:
            ip = parse_ip_route_ip(route_result.stdout)
            if ip:
                return ip

        ifconfig_result = self.get_ifconfig_output(serial)
        if ifconfig_result.ok:
            return parse_ifconfig_ip(ifconfig_result.stdout)
        return None
