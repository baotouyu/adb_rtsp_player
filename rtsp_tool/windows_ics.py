"""Windows ICS network adapter selection helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import platform
import subprocess
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

    data = json.loads(output)
    if isinstance(data, dict):
        items = [data]
    else:
        items = data

    adapters: list[NetworkAdapter] = []
    for item in items:
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
    completed = runner(
        build_adapter_discovery_command(),
        text=True,
        capture_output=True,
        check=False,
    )
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
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return IcsConfigResult(ok=bool(data.get("ok")), message=str(data.get("message") or ""))


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
