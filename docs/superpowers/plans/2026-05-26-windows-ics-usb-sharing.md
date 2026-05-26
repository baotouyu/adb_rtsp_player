# Windows ICS USB Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Windows-only USB network sharing assistant that detects RNDIS/USB adapters, attempts ICS configuration with UAC, falls back to manual setup, and detects the board `usb0` IP for RTSP playback.

**Architecture:** Keep Windows network/ICS logic out of the Tkinter GUI in a new focused `rtsp_tool/windows_ics.py` module. Extend `ADBClient` with usb0 IP parsing/discovery methods. Wire the feature into `RTSPToolApp` with headless-friendly tests and clear manual fallback.

**Tech Stack:** Python 3 stdlib, Tkinter/ttk, `subprocess`, Windows PowerShell/HNetCfg COM via generated script, `unittest` with fakes/mocks.

---

## File Structure

- Create `rtsp_tool/windows_ics.py`
  - Owns Windows adapter models, RNDIS/internet adapter selection heuristics, PowerShell command generation, elevated ICS invocation, `ncpa.cpl` manual settings launcher, and result parsing.
  - Must not import Tkinter or ADB classes.
- Create `tests/test_windows_ics.py`
  - Unit tests for heuristics, command/script generation, non-Windows behavior, result parsing, and manual settings launcher command.
- Modify `rtsp_tool/adb_client.py`
  - Add `parse_usb0_ip`, `get_usb0_ip_addr_output`, `get_usb0_ifconfig_output`, `discover_usb0_ip`.
  - Keep existing `discover_ip` behavior unchanged.
- Modify `tests/test_adb_client.py`
  - Add tests for `usb0` IP parsing, fallback order, and invalid IP filtering.
- Modify `rtsp_tool/i18n.py`
  - Add labels for the USB sharing UI.
- Modify `rtsp_tool/gui.py`
  - Add `USB 网络共享` section, adapter selection comboboxes, detect/config/manual/detect-usb0 buttons, status text, and workflows.
  - Use existing `_run_background`, `_operation_in_progress`, `_ui`, and logging patterns.
- Modify `tests/test_gui_usb_sharing.py`
  - Add headless GUI tests for button state, adapter detection mapping, automatic config workflow, fallback workflow, non-Windows state, and usb0 IP detection.
- Modify `README.md`
  - Document Windows ICS/RNDIS setup and automatic/manual workflow.

---

### Task 1: Windows ICS Adapter Model and Selection Heuristics

**Files:**
- Create: `rtsp_tool/windows_ics.py`
- Test: `tests/test_windows_ics.py`

- [ ] **Step 1: Write failing tests for adapter selection**

Create `tests/test_windows_ics.py` with these tests:

```python
import unittest
from unittest.mock import patch

from rtsp_tool.windows_ics import (
    NetworkAdapter,
    adapter_choice_map,
    choose_single_internet_adapter,
    choose_single_usb_adapter,
    is_windows,
    select_internet_adapters,
    select_usb_adapters,
)


class WindowsIcsTests(unittest.TestCase):
    def test_select_usb_adapters_prefers_rndis_and_usb_ethernet_names(self):
        adapters = [
            NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status="Up", has_gateway=True),
            NetworkAdapter(name="Ethernet 2", description="Remote NDIS Compatible Device", status="Up", has_gateway=False),
            NetworkAdapter(name="以太网 3", description="USB Ethernet/RNDIS Gadget", status="Disconnected", has_gateway=False),
        ]

        selected = select_usb_adapters(adapters)

        self.assertEqual([adapter.name for adapter in selected], ["Ethernet 2", "以太网 3"])

    def test_select_internet_adapters_excludes_usb_candidates_and_requires_gateway(self):
        adapters = [
            NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status="Up", has_gateway=True),
            NetworkAdapter(name="Ethernet", description="Realtek PCIe", status="Disconnected", has_gateway=True),
            NetworkAdapter(name="USB RNDIS", description="Remote NDIS Compatible Device", status="Up", has_gateway=True),
            NetworkAdapter(name="vEthernet", description="Hyper-V Virtual Ethernet", status="Up", has_gateway=False),
        ]

        selected = select_internet_adapters(adapters)

        self.assertEqual([adapter.name for adapter in selected], ["Wi-Fi"])

    def test_choose_single_returns_adapter_only_when_exactly_one_candidate_exists(self):
        wifi = NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status="Up", has_gateway=True)
        ethernet = NetworkAdapter(name="Ethernet", description="Realtek", status="Up", has_gateway=True)
        rndis = NetworkAdapter(name="USB RNDIS", description="Remote NDIS", status="Up", has_gateway=False)

        self.assertIs(choose_single_internet_adapter([wifi]), wifi)
        self.assertIsNone(choose_single_internet_adapter([wifi, ethernet]))
        self.assertIs(choose_single_usb_adapter([rndis]), rndis)
        self.assertIsNone(choose_single_usb_adapter([]))

    def test_adapter_choice_map_uses_unique_labels(self):
        first = NetworkAdapter(name="Ethernet", description="Remote NDIS", status="Up", has_gateway=False)
        second = NetworkAdapter(name="Ethernet", description="USB Ethernet", status="Up", has_gateway=False)

        choices = adapter_choice_map([first, second])

        self.assertEqual(set(choices), {"Ethernet - Remote NDIS", "Ethernet - USB Ethernet"})
        self.assertIs(choices["Ethernet - Remote NDIS"], first)
        self.assertIs(choices["Ethernet - USB Ethernet"], second)

    def test_is_windows_uses_platform_system(self):
        with patch("rtsp_tool.windows_ics.platform.system", return_value="Windows"):
            self.assertTrue(is_windows())
        with patch("rtsp_tool.windows_ics.platform.system", return_value="Darwin"):
            self.assertFalse(is_windows())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m unittest tests.test_windows_ics -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'rtsp_tool.windows_ics'`.

- [ ] **Step 3: Implement adapter model and heuristics**

Create `rtsp_tool/windows_ics.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import platform


USB_ADAPTER_KEYWORDS = (
    "rndis",
    "remote ndis",
    "usb ethernet",
    "usb ethernet/rndis gadget",
    "ethernet gadget",
)
INTERNET_ADAPTER_NAME_HINTS = ("wi-fi", "wifi", "wlan", "ethernet", "以太网")


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


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def _adapter_text(adapter: NetworkAdapter) -> str:
    return f"{adapter.name} {adapter.description}".lower()


def is_usb_adapter(adapter: NetworkAdapter) -> bool:
    text = _adapter_text(adapter)
    return any(keyword in text for keyword in USB_ADAPTER_KEYWORDS) or ("usb" in text and "ethernet" in text)


def select_usb_adapters(adapters: list[NetworkAdapter]) -> list[NetworkAdapter]:
    return [adapter for adapter in adapters if is_usb_adapter(adapter)]


def _is_connected(status: str) -> bool:
    return status.lower() in {"up", "connected", "已连接"}


def select_internet_adapters(adapters: list[NetworkAdapter]) -> list[NetworkAdapter]:
    candidates: list[NetworkAdapter] = []
    for adapter in adapters:
        if is_usb_adapter(adapter):
            continue
        if not adapter.has_gateway:
            continue
        if not _is_connected(adapter.status):
            continue
        text = _adapter_text(adapter)
        if any(hint in text for hint in INTERNET_ADAPTER_NAME_HINTS):
            candidates.append(adapter)
    return candidates


def choose_single_usb_adapter(candidates: list[NetworkAdapter]) -> NetworkAdapter | None:
    return candidates[0] if len(candidates) == 1 else None


def choose_single_internet_adapter(candidates: list[NetworkAdapter]) -> NetworkAdapter | None:
    return candidates[0] if len(candidates) == 1 else None


def adapter_choice_map(adapters: list[NetworkAdapter]) -> dict[str, NetworkAdapter]:
    labels: dict[str, int] = {}
    for adapter in adapters:
        labels[adapter.label] = labels.get(adapter.label, 0) + 1

    choices: dict[str, NetworkAdapter] = {}
    for index, adapter in enumerate(adapters, start=1):
        label = adapter.label
        if labels[label] > 1 or label in choices:
            label = f"{adapter.label} ({index})"
        choices[label] = adapter
    return choices
```

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
python3 -m unittest tests.test_windows_ics -v
```

Expected: all `WindowsIcsTests` pass.

- [ ] **Step 5: Commit**

```bash
git add rtsp_tool/windows_ics.py tests/test_windows_ics.py
git commit -m "feat: detect windows ics network adapters"
```

---

### Task 2: Windows Adapter Discovery and ICS Command Runner

**Files:**
- Modify: `rtsp_tool/windows_ics.py`
- Test: `tests/test_windows_ics.py`

- [ ] **Step 1: Add failing tests for PowerShell discovery/config/manual fallback**

Append to `tests/test_windows_ics.py`:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from rtsp_tool.windows_ics import (
    IcsConfigResult,
    build_adapter_discovery_command,
    build_elevated_ics_command,
    build_ics_script,
    load_ics_result,
    open_manual_network_settings,
    parse_adapter_json,
    run_adapter_discovery,
)


class WindowsIcsPowerShellTests(unittest.TestCase):
    def test_parse_adapter_json_returns_network_adapters(self):
        payload = """
        [
          {"Name":"Wi-Fi","InterfaceDescription":"Intel Wi-Fi","Status":"Up","IPv4DefaultGateway":{"NextHop":"192.168.1.1"}},
          {"Name":"Ethernet 2","InterfaceDescription":"Remote NDIS Compatible Device","Status":"Up","IPv4DefaultGateway":null}
        ]
        """

        adapters = parse_adapter_json(payload)

        self.assertEqual(adapters[0].name, "Wi-Fi")
        self.assertEqual(adapters[0].description, "Intel Wi-Fi")
        self.assertTrue(adapters[0].has_gateway)
        self.assertEqual(adapters[1].name, "Ethernet 2")
        self.assertFalse(adapters[1].has_gateway)

    def test_build_adapter_discovery_command_uses_powershell_json(self):
        command = build_adapter_discovery_command()

        self.assertEqual(command[0], "powershell")
        self.assertIn("Get-NetAdapter", command[-1])
        self.assertIn("ConvertTo-Json", command[-1])

    def test_run_adapter_discovery_returns_parsed_adapters(self):
        completed = Mock(returncode=0, stdout='[{"Name":"Wi-Fi","InterfaceDescription":"Intel","Status":"Up","IPv4DefaultGateway":{"NextHop":"192.168.1.1"}}]', stderr="")
        runner = Mock(return_value=completed)

        adapters = run_adapter_discovery(runner=runner)

        self.assertEqual([adapter.name for adapter in adapters], ["Wi-Fi"])
        runner.assert_called_once()

    def test_build_ics_script_contains_public_and_private_adapter_names(self):
        script = build_ics_script("Wi-Fi", "Ethernet 2", r"C:\Temp\ics-result.json")

        self.assertIn("Wi-Fi", script)
        self.assertIn("Ethernet 2", script)
        self.assertIn("HNetCfg.HNetShare", script)
        self.assertIn("EnableSharing(0)", script)
        self.assertIn("EnableSharing(1)", script)
        self.assertIn(r"C:\Temp\ics-result.json", script)

    def test_build_elevated_ics_command_runs_script_as_admin(self):
        command = build_elevated_ics_command(Path(r"C:\Temp\enable-ics.ps1"))

        self.assertEqual(command[0], "powershell")
        self.assertIn("Start-Process", command[-1])
        self.assertIn("-Verb RunAs", command[-1])
        self.assertIn("enable-ics.ps1", command[-1])

    def test_load_ics_result_reads_success_and_failure_json(self):
        with TemporaryDirectory() as tmpdir:
            result_path = Path(tmpdir) / "result.json"
            result_path.write_text('{"ok": true, "message": "done"}', encoding="utf-8")
            self.assertEqual(load_ics_result(result_path), IcsConfigResult(ok=True, message="done"))

            result_path.write_text('{"ok": false, "message": "failed"}', encoding="utf-8")
            self.assertEqual(load_ics_result(result_path), IcsConfigResult(ok=False, message="failed"))

    def test_open_manual_network_settings_launches_ncpa_cpl(self):
        runner = Mock(return_value=Mock(returncode=0))

        open_manual_network_settings(runner=runner)

        runner.assert_called_once_with(["control.exe", "ncpa.cpl"], check=False)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m unittest tests.test_windows_ics -v
```

Expected: FAIL with import errors for the new functions/classes.

- [ ] **Step 3: Implement discovery/config/manual functions**

Extend `rtsp_tool/windows_ics.py`:

```python
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Callable, Sequence


Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class IcsConfigResult:
    ok: bool
    message: str


def build_adapter_discovery_command() -> list[str]:
    script = (
        "Get-NetAdapter | ForEach-Object { "
        "$gw = Get-NetIPConfiguration -InterfaceIndex $_.ifIndex | Select-Object -ExpandProperty IPv4DefaultGateway -ErrorAction SilentlyContinue; "
        "[PSCustomObject]@{Name=$_.Name; InterfaceDescription=$_.InterfaceDescription; Status=$_.Status; IPv4DefaultGateway=$gw} "
        "} | ConvertTo-Json -Depth 4"
    )
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]


def parse_adapter_json(output: str) -> list[NetworkAdapter]:
    if not output.strip():
        return []
    data = json.loads(output)
    if isinstance(data, dict):
        data = [data]
    adapters: list[NetworkAdapter] = []
    for item in data:
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


def run_adapter_discovery(runner: Runner = subprocess.run) -> list[NetworkAdapter]:
    completed = runner(build_adapter_discovery_command(), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "检测 Windows 网络适配器失败。")
    return parse_adapter_json(completed.stdout)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_ics_script(public_adapter_name: str, private_adapter_name: str, result_path: str) -> str:
    public_name = _ps_quote(public_adapter_name)
    private_name = _ps_quote(private_adapter_name)
    result = _ps_quote(result_path)
    return f"""
$ErrorActionPreference = 'Stop'
$resultPath = {result}
try {{
  $manager = New-Object -ComObject HNetCfg.HNetShare
  $connections = @($manager.EnumEveryConnection)
  $publicConfig = $null
  $privateConfig = $null
  foreach ($connection in $connections) {{
    $props = $manager.NetConnectionProps($connection)
    $config = $manager.INetSharingConfigurationForINetConnection($connection)
    if ($props.Name -eq {public_name}) {{ $publicConfig = $config }}
    if ($props.Name -eq {private_name}) {{ $privateConfig = $config }}
  }}
  if ($null -eq $publicConfig) {{ throw '未找到上网网卡：{public_adapter_name}' }}
  if ($null -eq $privateConfig) {{ throw '未找到板子 USB 网卡：{private_adapter_name}' }}
  foreach ($connection in $connections) {{
    $config = $manager.INetSharingConfigurationForINetConnection($connection)
    if ($config.SharingEnabled) {{ $config.DisableSharing() }}
  }}
  $publicConfig.EnableSharing(0)
  $privateConfig.EnableSharing(1)
  @{{ ok = $true; message = 'ICS 配置完成' }} | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $resultPath
}} catch {{
  @{{ ok = $false; message = $_.Exception.Message }} | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath $resultPath
  exit 1
}}
""".strip()


def build_elevated_ics_command(script_path: Path) -> list[str]:
    command = f"Start-Process powershell -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File {str(script_path)!r}'"
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]


def load_ics_result(path: Path) -> IcsConfigResult:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return IcsConfigResult(ok=bool(data.get("ok")), message=str(data.get("message") or ""))


def open_manual_network_settings(runner: Callable[..., object] = subprocess.run) -> None:
    runner(["control.exe", "ncpa.cpl"], check=False)
```

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
python3 -m unittest tests.test_windows_ics -v
```

Expected: all Windows ICS unit tests pass.

- [ ] **Step 5: Commit**

```bash
git add rtsp_tool/windows_ics.py tests/test_windows_ics.py
git commit -m "feat: build windows ics configuration helpers"
```

---

### Task 3: Elevated ICS Configure Orchestration

**Files:**
- Modify: `rtsp_tool/windows_ics.py`
- Test: `tests/test_windows_ics.py`

- [ ] **Step 1: Add failing tests for temporary script orchestration**

Append tests:

```python
from rtsp_tool.windows_ics import configure_ics


class WindowsIcsConfigureTests(unittest.TestCase):
    def test_configure_ics_writes_script_runs_elevated_and_reads_result(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            script_path = Path(command[-1].split("-File '", 1)[1].split("'", 1)[0])
            result_path = script_path.with_name("ics-result.json")
            result_path.write_text('{"ok": true, "message": "ICS 配置完成"}', encoding="utf-8")
            return Mock(returncode=0, stdout="", stderr="")

        with TemporaryDirectory() as tmpdir:
            result = configure_ics("Wi-Fi", "Ethernet 2", temp_dir=Path(tmpdir), runner=runner)

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "ICS 配置完成")
        self.assertTrue(calls)
        self.assertIn("Start-Process", calls[0][-1])

    def test_configure_ics_returns_failure_when_user_cancels_uac_or_no_result_file(self):
        with TemporaryDirectory() as tmpdir:
            result = configure_ics(
                "Wi-Fi",
                "Ethernet 2",
                temp_dir=Path(tmpdir),
                runner=Mock(return_value=Mock(returncode=1, stdout="", stderr="")),
            )

        self.assertFalse(result.ok)
        self.assertIn("管理员", result.message)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m unittest tests.test_windows_ics.WindowsIcsConfigureTests -v
```

Expected: FAIL with `ImportError: cannot import name 'configure_ics'`.

- [ ] **Step 3: Implement `configure_ics`**

Extend `rtsp_tool/windows_ics.py`:

```python
import shutil
import tempfile


def configure_ics(
    public_adapter_name: str,
    private_adapter_name: str,
    temp_dir: Path | None = None,
    runner: Runner = subprocess.run,
) -> IcsConfigResult:
    created_temp_dir = temp_dir is None
    temp_root = Path(tempfile.mkdtemp(prefix="adb_rtsp_ics_")) if created_temp_dir else Path(temp_dir)
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
        script_path = temp_root / "enable-ics.ps1"
        result_path = temp_root / "ics-result.json"
        script_path.write_text(
            build_ics_script(public_adapter_name, private_adapter_name, str(result_path)),
            encoding="utf-8",
        )
        completed = runner(build_elevated_ics_command(script_path), text=True, capture_output=True, check=False)
        if result_path.exists():
            return load_ics_result(result_path)
        if completed.returncode != 0:
            return IcsConfigResult(ok=False, message="管理员授权被取消，或 Windows ICS 配置脚本未完成。")
        return IcsConfigResult(ok=False, message="Windows ICS 配置脚本没有返回结果。")
    finally:
        if created_temp_dir:
            shutil.rmtree(temp_root, ignore_errors=True)
```

Delete temporary script/result files when `configure_ics` creates its own temp directory. Do not delete `temp_dir` when it is provided by tests.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
python3 -m unittest tests.test_windows_ics -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add rtsp_tool/windows_ics.py tests/test_windows_ics.py
git commit -m "feat: run elevated windows ics configuration"
```

---

### Task 4: ADB usb0 IP Discovery

**Files:**
- Modify: `rtsp_tool/adb_client.py`
- Test: `tests/test_adb_client.py`

- [ ] **Step 1: Add failing tests for usb0 parsing and fallback**

Add to `tests/test_adb_client.py` imports:

```python
from rtsp_tool.adb_client import parse_usb0_ip
```

Add tests to `ADBClientTests`:

```python
    def test_parse_usb0_ip_accepts_ip_addr_output(self):
        output = """
3: usb0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    inet 192.168.137.22/24 brd 192.168.137.255 scope global usb0
"""

        self.assertEqual(parse_usb0_ip(output), "192.168.137.22")

    def test_parse_usb0_ip_accepts_ifconfig_output(self):
        output = """
usb0      Link encap:Ethernet  HWaddr 02:00:00:00:00:00
          inet addr:192.168.137.33  Bcast:192.168.137.255  Mask:255.255.255.0
"""

        self.assertEqual(parse_usb0_ip(output), "192.168.137.33")

    def test_parse_usb0_ip_rejects_loopback_zero_and_link_local(self):
        self.assertIsNone(parse_usb0_ip("inet 127.0.0.1/8 scope host lo"))
        self.assertIsNone(parse_usb0_ip("inet 0.0.0.0/24 scope global usb0"))
        self.assertIsNone(parse_usb0_ip("inet 169.254.3.4/16 scope link usb0"))

    def test_discover_usb0_ip_uses_ip_addr_then_ifconfig(self):
        client = ADBClient(adb_path="adb")
        ip_addr_result = type("Result", (), {"ok": True, "stdout": "", "stderr": ""})()
        ifconfig_result = type("Result", (), {"ok": True, "stdout": "inet addr:192.168.137.44", "stderr": ""})()

        with patch.object(client, "get_usb0_ip_addr_output", return_value=ip_addr_result) as ip_addr:
            with patch.object(client, "get_usb0_ifconfig_output", return_value=ifconfig_result) as ifconfig:
                self.assertEqual(client.discover_usb0_ip("abc123"), "192.168.137.44")

        ip_addr.assert_called_once_with("abc123")
        ifconfig.assert_called_once_with("abc123")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m unittest tests.test_adb_client -v
```

Expected: FAIL because `parse_usb0_ip` and new methods do not exist.

- [ ] **Step 3: Implement usb0 parsing and client methods**

Modify `rtsp_tool/adb_client.py`:

```python
def _valid_usb0_ip(ip: str) -> bool:
    return _valid_device_ip(ip) and not ip.startswith("169.254.")


def parse_usb0_ip(output: str) -> str | None:
    patterns = (
        r"\binet\s+(\d+\.\d+\.\d+\.\d+)(?:/\d+)?\b",
        r"\binet addr:(\d+\.\d+\.\d+\.\d+)\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, output):
            ip = match.group(1)
            if _valid_usb0_ip(ip):
                return ip
    return None
```

Add methods to `ADBClient` near existing network discovery methods:

```python
    def get_usb0_ip_addr_output(self, serial: str) -> CommandResult:
        return self.shell(serial, "ip addr show usb0")

    def get_usb0_ifconfig_output(self, serial: str) -> CommandResult:
        return self.shell(serial, "ifconfig usb0")

    def discover_usb0_ip(self, serial: str) -> str | None:
        ip_addr_result = self.get_usb0_ip_addr_output(serial)
        if ip_addr_result.ok:
            ip = parse_usb0_ip(ip_addr_result.stdout)
            if ip:
                return ip

        ifconfig_result = self.get_usb0_ifconfig_output(serial)
        if ifconfig_result.ok:
            return parse_usb0_ip(ifconfig_result.stdout)
        return None
```

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
python3 -m unittest tests.test_adb_client -v
```

Expected: all ADB tests pass.

- [ ] **Step 5: Commit**

```bash
git add rtsp_tool/adb_client.py tests/test_adb_client.py
git commit -m "feat: discover board usb0 ip over adb"
```

---

### Task 5: GUI Labels and Headless State for USB Sharing

**Files:**
- Modify: `rtsp_tool/i18n.py`
- Modify: `rtsp_tool/gui.py`
- Create: `tests/test_gui_usb_sharing.py`
- Modify: `tests/test_i18n.py`

- [ ] **Step 1: Add failing i18n and button-state tests**

Add to `tests/test_i18n.py`:

```python
    def test_usb_sharing_labels_are_chinese(self):
        self.assertEqual(TEXT["usb_sharing"], "USB 网络共享")
        self.assertEqual(TEXT["detect_network_adapters"], "检测网络适配器")
        self.assertEqual(TEXT["configure_usb_sharing"], "自动配置 USB 共享")
        self.assertEqual(TEXT["open_manual_network_settings"], "打开手动设置")
        self.assertEqual(TEXT["detect_usb0_ip"], "检测 usb0 IP")
        self.assertEqual(TEXT["internet_adapter"], "上网网卡")
        self.assertEqual(TEXT["usb_adapter"], "板子 USB 网卡")
```

Create `tests/test_gui_usb_sharing.py`:

```python
from types import SimpleNamespace
import unittest

from rtsp_tool.gui import RTSPToolApp
from rtsp_tool.i18n import state_text
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
    def make_app(self):
        app = object.__new__(RTSPToolApp)
        app.dependencies = {"adb": SimpleNamespace(found=True), "ffplay": SimpleNamespace(found=True)}
        app.selected_serial = FakeVar("abc")
        app.rtsp_url = FakeVar("")
        app.selected_yolo_package = FakeVar("")
        app.yolo_packages = {}
        app.devices = {"abc": SimpleNamespace(state="device")}
        app.player = SimpleNamespace(is_running=lambda: False)
        app._operation_in_progress = False
        app.internet_adapters = {}
        app.usb_adapters = {}
        app.selected_internet_adapter = FakeVar("")
        app.selected_usb_adapter = FakeVar("")
        app.usb_sharing_status = FakeVar(state_text("unknown"))
        for name in (
            "refresh_button", "start_service_button", "stop_service_button", "start_playback_button",
            "stop_playback_button", "copy_button", "update_yolo_button", "refresh_yolo_button",
            "detect_adapters_button", "configure_usb_sharing_button", "manual_network_settings_button",
            "detect_usb0_button",
        ):
            setattr(app, name, FakeButton())
        return app

    def test_usb_sharing_buttons_require_windows_and_selected_adapters(self):
        app = self.make_app()
        app._is_windows = lambda: True
        app.internet_adapters = {"Wi-Fi - Intel": NetworkAdapter("Wi-Fi", "Intel", "Up", True)}
        app.usb_adapters = {"Ethernet 2 - Remote NDIS": NetworkAdapter("Ethernet 2", "Remote NDIS", "Up", False)}
        app.selected_internet_adapter.set("Wi-Fi - Intel")
        app.selected_usb_adapter.set("Ethernet 2 - Remote NDIS")

        app._update_button_states()

        self.assertEqual(app.detect_adapters_button.state, "normal")
        self.assertEqual(app.configure_usb_sharing_button.state, "normal")
        self.assertEqual(app.manual_network_settings_button.state, "normal")
        self.assertEqual(app.detect_usb0_button.state, "normal")

    def test_configure_usb_sharing_disabled_without_selected_adapters(self):
        app = self.make_app()
        app._is_windows = lambda: True

        app._update_button_states()

        self.assertEqual(app.detect_adapters_button.state, "normal")
        self.assertEqual(app.configure_usb_sharing_button.state, "disabled")
        self.assertEqual(app.manual_network_settings_button.state, "normal")

    def test_usb_sharing_controls_disabled_on_non_windows_except_manual_help(self):
        app = self.make_app()
        app._is_windows = lambda: False

        app._update_button_states()

        self.assertEqual(app.detect_adapters_button.state, "disabled")
        self.assertEqual(app.configure_usb_sharing_button.state, "disabled")
        self.assertEqual(app.manual_network_settings_button.state, "disabled")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m unittest tests.test_i18n tests.test_gui_usb_sharing -v
```

Expected: FAIL with missing `TEXT` keys and missing GUI attributes/state logic.

- [ ] **Step 3: Add labels and state helpers**

Modify `rtsp_tool/i18n.py` `TEXT`:

```python
    "usb_sharing": "USB 网络共享",
    "detect_network_adapters": "检测网络适配器",
    "configure_usb_sharing": "自动配置 USB 共享",
    "open_manual_network_settings": "打开手动设置",
    "detect_usb0_ip": "检测 usb0 IP",
    "internet_adapter": "上网网卡",
    "usb_adapter": "板子 USB 网卡",
```

Modify `rtsp_tool/gui.py` imports:

```python
from .windows_ics import NetworkAdapter, adapter_choice_map, choose_single_internet_adapter, choose_single_usb_adapter, is_windows, select_internet_adapters, select_usb_adapters
```

In `__init__`, add state:

```python
        self.internet_adapters: dict[str, NetworkAdapter] = {}
        self.usb_adapters: dict[str, NetworkAdapter] = {}
        self.selected_internet_adapter = tk.StringVar(value="")
        self.selected_usb_adapter = tk.StringVar(value="")
        self.usb_sharing_status = tk.StringVar(value=state_text("unknown"))
```

Add methods:

```python
    def _is_windows(self) -> bool:
        return is_windows()

    def _selected_internet_adapter(self) -> NetworkAdapter | None:
        return self.internet_adapters.get(self.selected_internet_adapter.get())

    def _selected_usb_adapter(self) -> NetworkAdapter | None:
        return self.usb_adapters.get(self.selected_usb_adapter.get())
```

Extend `_update_button_states` after existing buttons:

```python
        windows = self._is_windows()
        has_ics_selection = self._selected_internet_adapter() is not None and self._selected_usb_adapter() is not None
        self.detect_adapters_button.configure(state="normal" if windows and not busy else "disabled")
        self.configure_usb_sharing_button.configure(state="normal" if windows and has_ics_selection and not busy else "disabled")
        self.manual_network_settings_button.configure(state="normal" if windows and not busy else "disabled")
        self.detect_usb0_button.configure(state="normal" if has_adb and has_usable_device and not busy else "disabled")
```

Do not build visible UI yet in this task; create placeholder button attributes in tests only. The real UI comes in Task 6.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
python3 -m unittest tests.test_i18n tests.test_gui_usb_sharing -v
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add rtsp_tool/i18n.py rtsp_tool/gui.py tests/test_i18n.py tests/test_gui_usb_sharing.py
git commit -m "feat: add usb sharing gui state"
```

---

### Task 6: GUI USB Sharing Section and Adapter Detection Workflow

**Files:**
- Modify: `rtsp_tool/gui.py`
- Modify: `tests/test_gui_usb_sharing.py`

- [ ] **Step 1: Add failing tests for adapter detection mapping**

Append tests to `tests/test_gui_usb_sharing.py`:

```python
    def test_replace_network_adapters_selects_single_candidates(self):
        app = self.make_app()
        app.internet_adapter_combo = SimpleNamespace(values=(), configure=lambda **kwargs: setattr(app.internet_adapter_combo, "values", tuple(kwargs["values"])))
        app.usb_adapter_combo = SimpleNamespace(values=(), configure=lambda **kwargs: setattr(app.usb_adapter_combo, "values", tuple(kwargs["values"])))
        app.logged = []
        app.log = app.logged.append
        app._update_button_states = lambda: None
        adapters = [
            NetworkAdapter("Wi-Fi", "Intel Wi-Fi", "Up", True),
            NetworkAdapter("Ethernet 2", "Remote NDIS Compatible Device", "Up", False),
        ]

        app._replace_network_adapters(adapters)

        self.assertEqual(app.selected_internet_adapter.get(), "Wi-Fi - Intel Wi-Fi")
        self.assertEqual(app.selected_usb_adapter.get(), "Ethernet 2 - Remote NDIS Compatible Device")
        self.assertIn("检测到上网网卡", "\n".join(app.logged))
        self.assertIn("检测到板子 USB 网卡", "\n".join(app.logged))
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m unittest tests.test_gui_usb_sharing -v
```

Expected: FAIL with missing `_replace_network_adapters`.

- [ ] **Step 3: Build UI section and detection methods**

Modify `_build_ui` row layout:

- Keep dependencies row `0`, devices row `1`.
- Add USB sharing row `2`.
- Move stream row to `3`, YOLO row to `4`, controls row to `5`, log row to `6`, status row to `7`.
- Update `self.root.rowconfigure(6, weight=1)`.

Add UI after device frame:

```python
        usb_frame = ttk.LabelFrame(self.root, text=TEXT["usb_sharing"])
        usb_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        usb_frame.columnconfigure(1, weight=1)
        usb_frame.columnconfigure(3, weight=1)
        ttk.Label(usb_frame, text=TEXT["internet_adapter"]).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.internet_adapter_combo = ttk.Combobox(usb_frame, textvariable=self.selected_internet_adapter, state="readonly", values=())
        self.internet_adapter_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=(8, 4))
        ttk.Label(usb_frame, text=TEXT["usb_adapter"]).grid(row=0, column=2, sticky="w", padx=8, pady=(8, 4))
        self.usb_adapter_combo = ttk.Combobox(usb_frame, textvariable=self.selected_usb_adapter, state="readonly", values=())
        self.usb_adapter_combo.grid(row=0, column=3, sticky="ew", padx=6, pady=(8, 4))
        self.detect_adapters_button = ttk.Button(usb_frame, text=TEXT["detect_network_adapters"], command=self.detect_network_adapters)
        self.configure_usb_sharing_button = ttk.Button(usb_frame, text=TEXT["configure_usb_sharing"], command=self.configure_usb_sharing)
        self.manual_network_settings_button = ttk.Button(usb_frame, text=TEXT["open_manual_network_settings"], command=self.open_manual_network_settings)
        self.detect_usb0_button = ttk.Button(usb_frame, text=TEXT["detect_usb0_ip"], command=self.detect_usb0_ip)
        self.detect_adapters_button.grid(row=1, column=0, sticky="ew", padx=6, pady=(4, 8))
        self.configure_usb_sharing_button.grid(row=1, column=1, sticky="ew", padx=6, pady=(4, 8))
        self.manual_network_settings_button.grid(row=1, column=2, sticky="ew", padx=6, pady=(4, 8))
        self.detect_usb0_button.grid(row=1, column=3, sticky="ew", padx=6, pady=(4, 8))
        ttk.Label(usb_frame, textvariable=self.usb_sharing_status).grid(row=2, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 8))
```

Add methods:

```python
    def detect_network_adapters(self) -> None:
        if not self._is_windows():
            self.log("USB 网络共享自动配置仅适用于 Windows。")
            return

        def work() -> None:
            self._ui(self.log, "正在检测 Windows 网络适配器...")
            adapters = run_adapter_discovery()
            self._ui(self._replace_network_adapters, adapters)

        self._run_background("正在检测网络适配器...", work)

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
        self.selected_internet_adapter.set(internet_choice.label if internet_choice and internet_choice.label in self.internet_adapters else (internet_values[0] if len(internet_values) == 1 else ""))
        self.selected_usb_adapter.set(usb_choice.label if usb_choice and usb_choice.label in self.usb_adapters else (usb_values[0] if len(usb_values) == 1 else ""))
        if internet_values:
            self.log("检测到上网网卡：" + ", ".join(internet_values))
        else:
            self.log("没有检测到可用于共享的上网网卡。")
        if usb_values:
            self.log("检测到板子 USB 网卡：" + ", ".join(usb_values))
        else:
            self.log("没有检测到 RNDIS/USB 网卡。请检查 USB 连接或驱动。")
        self.usb_sharing_status.set("请选择网卡后配置 USB 网络共享。")
        self._update_button_states()
```

Import `run_adapter_discovery` from `.windows_ics`.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
python3 -m unittest tests.test_gui_usb_sharing tests.test_gui_yolo_package -v
```

Expected: GUI tests pass after updating row assumptions if any exist.

- [ ] **Step 5: Commit**

```bash
git add rtsp_tool/gui.py tests/test_gui_usb_sharing.py
git commit -m "feat: add usb sharing adapter detection ui"
```

---

### Task 7: GUI ICS Configure, Manual Fallback, and usb0 IP Workflows

**Files:**
- Modify: `rtsp_tool/gui.py`
- Modify: `tests/test_gui_usb_sharing.py`

- [ ] **Step 1: Add failing tests for workflows**

Append tests:

```python
from rtsp_tool.windows_ics import IcsConfigResult


class FakeRoot:
    def after(self, _delay, callback):
        callback()
    def config(self, **_kwargs):
        pass


def make_sync_background(app):
    def run_sync(_message, work):
        try:
            work()
        except Exception as exc:
            app.log(f"错误：{exc}")
    return run_sync
```

Add methods to `GuiUsbSharingTests`:

```python
    def test_configure_usb_sharing_cancel_does_not_run_ics(self):
        app = self.make_app()
        app.root = FakeRoot()
        app.log = Mock()
        app._run_background = make_sync_background(app)
        app._selected_internet_adapter = lambda: NetworkAdapter("Wi-Fi", "Intel", "Up", True)
        app._selected_usb_adapter = lambda: NetworkAdapter("Ethernet 2", "Remote NDIS", "Up", False)

        with patch("rtsp_tool.gui.messagebox.askyesno", return_value=False):
            with patch("rtsp_tool.gui.configure_ics") as configure:
                app.configure_usb_sharing()

        configure.assert_not_called()

    def test_configure_usb_sharing_success_updates_status(self):
        app = self.make_app()
        app.root = FakeRoot()
        app.logged = []
        app.log = app.logged.append
        app._run_background = make_sync_background(app)
        app._selected_internet_adapter = lambda: NetworkAdapter("Wi-Fi", "Intel", "Up", True)
        app._selected_usb_adapter = lambda: NetworkAdapter("Ethernet 2", "Remote NDIS", "Up", False)

        with patch("rtsp_tool.gui.messagebox.askyesno", return_value=True):
            with patch("rtsp_tool.gui.configure_ics", return_value=IcsConfigResult(True, "ICS 配置完成")):
                app.configure_usb_sharing()

        self.assertEqual(app.usb_sharing_status.get(), "ICS 配置完成")
        self.assertIn("请等待板端 usb0", "\n".join(app.logged))

    def test_configure_usb_sharing_failure_opens_manual_settings(self):
        app = self.make_app()
        app.root = FakeRoot()
        app.logged = []
        app.log = app.logged.append
        app._run_background = make_sync_background(app)
        app._selected_internet_adapter = lambda: NetworkAdapter("Wi-Fi", "Intel", "Up", True)
        app._selected_usb_adapter = lambda: NetworkAdapter("Ethernet 2", "Remote NDIS", "Up", False)

        with patch("rtsp_tool.gui.messagebox.askyesno", return_value=True):
            with patch("rtsp_tool.gui.configure_ics", return_value=IcsConfigResult(False, "失败")):
                with patch.object(app, "open_manual_network_settings") as manual:
                    app.configure_usb_sharing()

        manual.assert_called_once()
        self.assertIn("失败", app.usb_sharing_status.get())

    def test_detect_usb0_ip_updates_rtsp_url(self):
        app = self.make_app()
        app.root = FakeRoot()
        app.logged = []
        app.log = app.logged.append
        app._run_background = make_sync_background(app)
        app.device_ip = FakeVar("")
        app.rtsp_url = FakeVar("")
        app.adb = SimpleNamespace(discover_usb0_ip=lambda serial: "192.168.137.22")
        app._require_selected_device = lambda: SimpleNamespace(serial="abc", state="device")

        app.detect_usb0_ip()

        self.assertEqual(app.device_ip.get(), "192.168.137.22")
        self.assertEqual(app.rtsp_url.get(), "rtsp://192.168.137.22:8554/ch0")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
python3 -m unittest tests.test_gui_usb_sharing -v
```

Expected: FAIL with missing `configure_usb_sharing`, `open_manual_network_settings`, and `detect_usb0_ip`.

- [ ] **Step 3: Implement workflows**

Modify `rtsp_tool/gui.py` imports:

```python
from .windows_ics import IcsConfigResult, configure_ics, open_manual_network_settings as open_windows_network_settings
```

Add method:

```python
    def _manual_ics_steps(self) -> str:
        return (
            "手动设置步骤：右键上网网卡 -> 属性 -> 共享 -> 勾选允许共享 -> "
            "家庭网络连接选择板子 RNDIS/USB 网卡。"
        )
```

Add workflow methods:

```python
    def configure_usb_sharing(self) -> None:
        internet_adapter = self._selected_internet_adapter()
        usb_adapter = self._selected_usb_adapter()
        if not internet_adapter or not usb_adapter:
            messagebox.showwarning("未选择网卡", "请先检测并选择上网网卡和板子 USB 网卡。")
            return
        confirmed = messagebox.askyesno(
            "确认配置 USB 网络共享",
            "这会修改 Windows 网络共享设置，并可能弹出管理员权限确认。是否继续？",
        )
        if not confirmed:
            return

        def work() -> None:
            self._ui(self.log, "正在请求管理员权限配置 Windows 网络共享...")
            result = configure_ics(internet_adapter.name, usb_adapter.name)
            self._ui(self.usb_sharing_status.set, result.message)
            if result.ok:
                self._ui(self.log, "ICS 配置完成。请等待板端 usb0 通过 DHCP 获取 IP。")
                return
            self._ui(self.log, f"未能自动配置 ICS：{result.message}")
            self._ui(self.open_manual_network_settings)

        self._run_background("正在配置 USB 网络共享...", work)

    def open_manual_network_settings(self) -> None:
        try:
            open_windows_network_settings()
        except Exception as exc:
            self.log(f"打开 Windows 网络连接页面失败：{exc}")
        self.usb_sharing_status.set(self._manual_ics_steps())
        self.log(self._manual_ics_steps())

    def detect_usb0_ip(self) -> None:
        device = self._require_selected_device()
        if not device:
            return

        def work() -> None:
            self._ui(self.log, f"正在检测设备 {device.serial} 的 usb0 IP...")
            ip = self.adb.discover_usb0_ip(device.serial)
            if not ip:
                raise RuntimeError("没有检测到 usb0 IP。请确认 Windows ICS 已启用，并等待板端 DHCP 获取地址。")
            url = build_rtsp_url(ip)
            self._ui(self.device_ip.set, ip)
            self._ui(self.rtsp_url.set, url)
            self._ui(self.usb_sharing_status.set, f"板端 usb0 IP：{ip}")
            self._ui(self.log, f"板端 usb0 IP：{ip}")
            self._ui(self.log, f"RTSP 地址：{url}")

        self._run_background("正在检测 usb0 IP...", work)
```

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
python3 -m unittest tests.test_gui_usb_sharing -v
python3 -m unittest discover -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add rtsp_tool/gui.py tests/test_gui_usb_sharing.py
git commit -m "feat: configure windows usb network sharing from gui"
```

---

### Task 8: Startup Detection, Non-Windows Status, and README

**Files:**
- Modify: `rtsp_tool/gui.py`
- Modify: `README.md`
- Test: existing tests only unless a regression is found

- [ ] **Step 1: Add startup status behavior**

Modify `RTSPToolApp.__init__` after `_render_dependency_status()` to avoid overlapping startup background jobs with `refresh_devices()`:

```python
        if self._is_windows():
            self.usb_sharing_status.set("点击“检测网络适配器”开始配置 USB 网络共享。")
        else:
            self.usb_sharing_status.set("USB 网络共享自动配置仅适用于 Windows。")
```

Users start adapter detection with the visible `检测网络适配器` button.

- [ ] **Step 2: Update README**

Add section after `## Windows 免安装使用` or near `## YOLO App 和模型包更新`:

```markdown
## Windows USB 网络共享（ICS）

如果板子通过 USB/RNDIS 暴露 `usb0`，Windows 端需要启用 Internet Connection Sharing (ICS)，让板端通过 DHCP 获取 IP。

在 app 里可以使用“USB 网络共享”区域：

1. 点击“检测网络适配器”。
2. 确认“上网网卡”是 Wi-Fi/以太网。
3. 确认“板子 USB 网卡”是 Remote NDIS/USB Ethernet/RNDIS Gadget。
4. 点击“自动配置 USB 共享”。Windows 可能弹出管理员权限确认。
5. 配置完成后，点击“检测 usb0 IP”，或在板端执行 `ifconfig usb0` 查看 DHCP 地址。

如果自动配置失败，app 会打开 Windows 网络连接页面。手动设置方法：右键上网网卡 -> 属性 -> 共享 -> 勾选允许共享 -> 家庭网络连接选择板子 RNDIS/USB 网卡。
```

- [ ] **Step 3: Run verification**

Run:

```bash
python3 -m unittest discover -v
python3 -m py_compile app.py rtsp_tool/*.py
rg -n "USB 网络共享|ICS|RNDIS|usb0|自动配置 USB 共享" README.md rtsp_tool tests
```

Expected: tests and compile pass; `rg` shows docs/UI/test coverage.

- [ ] **Step 4: Commit**

```bash
git add rtsp_tool/gui.py README.md
git commit -m "docs: explain windows usb network sharing"
```

---

### Task 9: Final Verification and Push

**Files:**
- No code changes expected.

- [ ] **Step 1: Run full local verification**

Run:

```bash
python3 -m unittest discover -v
python3 -m py_compile app.py rtsp_tool/*.py
git status --short --branch
```

Expected:

- `unittest` passes.
- `py_compile` exits 0.
- `git status` shows clean branch ahead of `origin/main` by the new commits.

- [ ] **Step 2: Check Windows packaging triggers**

Run:

```bash
rg -n "rtsp_tool/\*\*|tests/\*\*|README.md" .github/workflows/windows-build.yml
```

Expected: workflow triggers on code/tests changes. README alone may not trigger a build, but code/tests changes from Tasks 1-8 will trigger.

- [ ] **Step 3: Push**

Run:

```bash
git push
```

Expected: push succeeds and GitHub Actions starts a new Windows Portable Build.

- [ ] **Step 4: Report manual Windows validation steps**

Tell the user to test on Windows:

```text
1. Download latest ADB_RTSP_Player_Windows artifact.
2. Connect board USB/RNDIS.
3. Open app -> USB 网络共享 -> 检测网络适配器.
4. Confirm Wi-Fi/以太网 and RNDIS selections.
5. Click 自动配置 USB 共享 and accept UAC.
6. Click 检测 usb0 IP.
7. Start playback.
```
