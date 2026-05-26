"""Windows ICS network adapter selection helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from typing import Iterable


USB_KEYWORDS = (
    "rndis",
    "remote ndis",
    "usb ethernet/rndis gadget",
    "ethernet gadget",
)

INTERNET_HINTS = ("wi-fi", "wifi", "wlan", "ethernet", "以太网")
INTERNET_EXCLUDE_KEYWORDS = (
    "vethernet",
    "hyper-v",
    "wsl",
    "vmware",
    "virtualbox",
    "tap",
    "tunnel",
    "vpn",
    "host-only",
    "bridge",
)
CONNECTED_STATUSES = {"up", "connected", "已连接"}


@dataclass(frozen=True)
class NetworkAdapter:
    name: str
    description: str
    status: str
    has_gateway: bool = False

    @property
    def label(self) -> str:
        if self.description and self.description != self.name:
            return f"{self.name} - {self.description}"
        return self.name


@dataclass(frozen=True)
class IcsConfigResult:
    ok: bool
    message: str


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def _ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_adapter_discovery_command() -> list[str]:
    script = r"""
$adapters = Get-NetAdapter | ForEach-Object {
    $ipConfig = Get-NetIPConfiguration -InterfaceIndex $_.ifIndex
    [PSCustomObject]@{
        Name = $_.Name
        InterfaceDescription = $_.InterfaceDescription
        Status = $_.Status
        IPv4DefaultGateway = $ipConfig.IPv4DefaultGateway
    }
}
$adapters | ConvertTo-Json -Depth 5
""".strip()
    return ["powershell", "-NoProfile", "-Command", script]


def parse_adapter_json(output: str) -> list[NetworkAdapter]:
    if not output.strip():
        return []

    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("网卡信息 JSON 解析失败，请重新扫描网卡。") from exc

    if isinstance(data, dict):
        items = [data]
    elif isinstance(data, list):
        items = data
    else:
        raise RuntimeError("网卡信息 JSON 格式无效，请重新扫描网卡。")

    adapters: list[NetworkAdapter] = []
    for item in items:
        if not isinstance(item, dict):
            raise RuntimeError("网卡信息 JSON 格式无效，请重新扫描网卡。")
        gateway = item.get("IPv4DefaultGateway")
        adapters.append(
            NetworkAdapter(
                name=str(item.get("Name") or ""),
                description=str(item.get("InterfaceDescription") or ""),
                status=str(item.get("Status") or ""),
                has_gateway=bool(gateway),
            )
        )
    return adapters


def run_adapter_discovery(runner=subprocess.run) -> list[NetworkAdapter]:
    try:
        completed = runner(
            build_adapter_discovery_command(),
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"启动网卡发现命令失败: {exc}") from exc

    if completed.returncode != 0:
        message = (completed.stderr or "").strip() or "网卡发现失败"
        raise RuntimeError(message)
    return parse_adapter_json(completed.stdout)


def build_ics_script(public_adapter_name, private_adapter_name, result_path) -> str:
    public_name = _ps_single_quote(str(public_adapter_name))
    private_name = _ps_single_quote(str(private_adapter_name))
    result = _ps_single_quote(str(result_path))
    return f"""
$ErrorActionPreference = 'Stop'
$publicName = {public_name}
$privateName = {private_name}
$resultPath = {result}

function Write-IcsResult($ok, $message) {{
    @{{ ok = [bool]$ok; message = [string]$message }} |
        ConvertTo-Json -Compress |
        Set-Content -LiteralPath $resultPath -Encoding UTF8
}}

try {{
    $share = New-Object -ComObject HNetCfg.HNetShare
    $connections = @($share.EnumEveryConnection)

    function Find-ConnectionByName($name) {{
        foreach ($connection in $connections) {{
            $props = $share.NetConnectionProps($connection)
            if ($props.Name -eq $name) {{
                return $connection
            }}
        }}
        return $null
    }}

    $publicConnection = Find-ConnectionByName $publicName
    $privateConnection = Find-ConnectionByName $privateName

    if ($null -eq $publicConnection) {{
        throw "未找到公网网卡: $publicName"
    }}
    if ($null -eq $privateConnection) {{
        throw "未找到专用网卡: $privateName"
    }}

    foreach ($connection in $connections) {{
        $config = $share.INetSharingConfigurationForINetConnection($connection)
        if ($config.SharingEnabled) {{
            $config.DisableSharing()
        }}
    }}

    $publicConfig = $share.INetSharingConfigurationForINetConnection($publicConnection)
    $privateConfig = $share.INetSharingConfigurationForINetConnection($privateConnection)
    $publicConfig.EnableSharing(0)
    $privateConfig.EnableSharing(1)

    Write-IcsResult $true 'ICS 配置成功'
}} catch {{
    Write-IcsResult $false $_.Exception.Message
}}
""".strip()


def build_elevated_ics_command(script_path: Path) -> list[str]:
    quoted_script = _ps_single_quote(subprocess.list2cmdline([str(script_path)]))
    script = (
        "$arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "
        f"{quoted_script}); Start-Process powershell -Verb RunAs -Wait -ArgumentList $arguments"
    )
    return ["powershell", "-NoProfile", "-Command", script]


def load_ics_result(path: Path) -> IcsConfigResult:
    try:
        output = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise RuntimeError(f"读取 ICS 结果失败: {exc}") from exc

    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ICS 结果 JSON 解析失败，请重试 ICS 配置。") from exc

    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool) or not isinstance(data.get("message"), str):
        raise RuntimeError("ICS 结果 JSON 格式无效，请重试 ICS 配置。")

    return IcsConfigResult(ok=data["ok"], message=data["message"])


def configure_ics(public_adapter_name, private_adapter_name, temp_dir=None, runner=subprocess.run) -> IcsConfigResult:
    owns_temp_dir = temp_dir is None
    work_dir = Path(tempfile.mkdtemp(prefix="rtsp-ics-")) if owns_temp_dir else Path(temp_dir)
    script_path = work_dir / "enable-ics.ps1"
    result_path = work_dir / "ics-result.json"

    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        script_path.write_text(
            build_ics_script(public_adapter_name, private_adapter_name, result_path),
            encoding="utf-8",
        )

        try:
            completed = runner(
                build_elevated_ics_command(script_path),
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            return IcsConfigResult(ok=False, message=f"启动 ICS 配置脚本失败: {exc}")

        if result_path.exists():
            return load_ics_result(result_path)
        if completed.returncode != 0:
            return IcsConfigResult(ok=False, message="管理员授权被取消，或 Windows ICS 配置脚本未完成。")
        return IcsConfigResult(ok=False, message="Windows ICS 配置脚本没有返回结果。")
    finally:
        if owns_temp_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


def open_manual_network_settings(runner=subprocess.run) -> None:
    runner(["control.exe", "ncpa.cpl"], check=False)


def _adapter_text(adapter: NetworkAdapter) -> str:
    return f"{adapter.name} {adapter.description}".lower()


def is_usb_adapter(adapter: NetworkAdapter) -> bool:
    text = _adapter_text(adapter)
    return any(keyword in text for keyword in USB_KEYWORDS) or (
        "usb" in text and "ethernet" in text and not adapter.has_gateway
    )


def select_usb_adapters(adapters: Iterable[NetworkAdapter]) -> list[NetworkAdapter]:
    return [adapter for adapter in adapters if is_usb_adapter(adapter)]


def _is_connected(adapter: NetworkAdapter) -> bool:
    return adapter.status.strip().lower() in CONNECTED_STATUSES


def _has_internet_hint(adapter: NetworkAdapter) -> bool:
    text = _adapter_text(adapter)
    return any(hint in text for hint in INTERNET_HINTS)


def _is_excluded_internet_adapter(adapter: NetworkAdapter) -> bool:
    text = _adapter_text(adapter)
    return any(keyword in text for keyword in INTERNET_EXCLUDE_KEYWORDS)


def select_internet_adapters(adapters: Iterable[NetworkAdapter]) -> list[NetworkAdapter]:
    return [
        adapter
        for adapter in adapters
        if _is_connected(adapter)
        and adapter.has_gateway
        and not is_usb_adapter(adapter)
        and _has_internet_hint(adapter)
        and not _is_excluded_internet_adapter(adapter)
    ]


def choose_single_usb_adapter(candidates: list[NetworkAdapter]) -> NetworkAdapter | None:
    return candidates[0] if len(candidates) == 1 else None


def choose_single_internet_adapter(candidates: list[NetworkAdapter]) -> NetworkAdapter | None:
    return candidates[0] if len(candidates) == 1 else None


def adapter_choice_map(adapters: Iterable[NetworkAdapter]) -> dict[str, NetworkAdapter]:
    adapters = list(adapters)
    labels = [adapter.label for adapter in adapters]
    counts = Counter(labels)
    reserved_labels = {label for label, count in counts.items() if count == 1}
    suffixes: dict[str, int] = defaultdict(int)
    choices: dict[str, NetworkAdapter] = {}

    for adapter, label in zip(adapters, labels):
        if counts[label] > 1:
            suffixes[label] += 1
            candidate = f"{label} ({suffixes[label]})"
            while candidate in choices or candidate in reserved_labels:
                suffixes[label] += 1
                candidate = f"{label} ({suffixes[label]})"
            label = candidate
        choices[label] = adapter

    return choices
