import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rtsp_tool.windows_ics import (
    build_adapter_discovery_command,
    build_elevated_ics_command,
    build_ics_script,
    load_ics_result,
    NetworkAdapter,
    open_manual_network_settings,
    parse_adapter_json,
    run_adapter_discovery,
    adapter_choice_map,
    choose_single_internet_adapter,
    choose_single_usb_adapter,
    is_windows,
    select_internet_adapters,
    select_usb_adapters,
)


class WindowsIcsTests(unittest.TestCase):
    def test_network_adapter_label_handles_empty_same_and_different_descriptions(self):
        empty_description = NetworkAdapter(name="Ethernet", description="", status="Up")
        same_description = NetworkAdapter(name="Wi-Fi", description="Wi-Fi", status="Up")
        different_description = NetworkAdapter(name="以太网", description="Realtek PCIe", status="Up")

        self.assertEqual(empty_description.label, "Ethernet")
        self.assertEqual(same_description.label, "Wi-Fi")
        self.assertEqual(different_description.label, "以太网 - Realtek PCIe")

    def test_select_usb_adapters_prefers_rndis_and_usb_ethernet_names(self):
        adapters = [
            NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status="Up", has_gateway=True),
            NetworkAdapter(name="Ethernet 2", description="Remote NDIS Compatible Device", status="Up", has_gateway=False),
            NetworkAdapter(name="以太网 3", description="USB Ethernet/RNDIS Gadget", status="Disconnected", has_gateway=False),
        ]

        selected = select_usb_adapters(adapters)

        self.assertEqual([adapter.name for adapter in selected], ["Ethernet 2", "以太网 3"])

    def test_select_usb_adapters_matches_ethernet_gadget_and_generic_usb_ethernet_text(self):
        adapters = [
            NetworkAdapter(name="Board LAN", description="Ethernet Gadget", status="Up"),
            NetworkAdapter(name="Lab USB Link", description="ACME Ethernet Controller", status="Up"),
            NetworkAdapter(name="Bluetooth", description="Personal Area Network", status="Up"),
        ]

        selected = select_usb_adapters(adapters)

        self.assertEqual([adapter.name for adapter in selected], ["Board LAN", "Lab USB Link"])

    def test_select_usb_adapters_excludes_upstream_usb_ethernet_with_gateway(self):
        adapters = [
            NetworkAdapter(name="USB-C Ethernet Adapter", description="Realtek USB GbE", status="Up", has_gateway=True),
            NetworkAdapter(name="USB Ethernet Gadget", description="Board link", status="Up", has_gateway=False),
        ]

        selected = select_usb_adapters(adapters)

        self.assertEqual([adapter.name for adapter in selected], ["USB Ethernet Gadget"])

    def test_select_internet_adapters_excludes_usb_candidates_and_requires_gateway(self):
        adapters = [
            NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status="Up", has_gateway=True),
            NetworkAdapter(name="Ethernet", description="Realtek PCIe", status="Disconnected", has_gateway=True),
            NetworkAdapter(name="USB RNDIS", description="Remote NDIS Compatible Device", status="Up", has_gateway=True),
            NetworkAdapter(name="vEthernet", description="Hyper-V Virtual Ethernet", status="Up", has_gateway=False),
        ]

        selected = select_internet_adapters(adapters)

        self.assertEqual([adapter.name for adapter in selected], ["Wi-Fi"])

    def test_select_internet_adapters_excludes_gateway_adapters_without_internet_hints(self):
        adapters = [
            NetworkAdapter(name="Bluetooth Network", description="Personal Area Network", status="Up", has_gateway=True),
            NetworkAdapter(name="VPN", description="WireGuard Tunnel", status="Connected", has_gateway=True),
            NetworkAdapter(name="WLAN", description="Intel Wireless", status="Connected", has_gateway=True),
            NetworkAdapter(name="以太网", description="Realtek PCIe", status="Up", has_gateway=True),
        ]

        selected = select_internet_adapters(adapters)

        self.assertEqual([adapter.name for adapter in selected], ["WLAN", "以太网"])

    def test_select_internet_adapters_excludes_virtual_tunnel_and_bridge_adapters(self):
        adapters = [
            NetworkAdapter(name="vEthernet (WSL)", description="Hyper-V Virtual Ethernet", status="Up", has_gateway=True),
            NetworkAdapter(name="VPN Ethernet", description="WireGuard Tunnel", status="Connected", has_gateway=True),
            NetworkAdapter(name="VMware Network", description="VMware Virtual Ethernet Adapter", status="Up", has_gateway=True),
            NetworkAdapter(name="VirtualBox Host-Only Ethernet", description="VirtualBox Host-Only", status="Up", has_gateway=True),
            NetworkAdapter(name="Network Bridge", description="Ethernet Bridge", status="Up", has_gateway=True),
            NetworkAdapter(name="Ethernet", description="Realtek PCIe", status="Up", has_gateway=True),
        ]

        selected = select_internet_adapters(adapters)

        self.assertEqual([adapter.name for adapter in selected], ["Ethernet"])

    def test_select_internet_adapters_accepts_trimmed_and_chinese_connected_status(self):
        adapters = [
            NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status=" 已连接 ", has_gateway=True),
            NetworkAdapter(name="Ethernet", description="Realtek PCIe", status=" connected ", has_gateway=True),
        ]

        selected = select_internet_adapters(adapters)

        self.assertEqual([adapter.name for adapter in selected], ["Wi-Fi", "Ethernet"])

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

    def test_adapter_choice_map_disambiguates_duplicate_labels_with_indexes(self):
        first = NetworkAdapter(name="Ethernet", description="", status="Up", has_gateway=False)
        second = NetworkAdapter(name="Ethernet", description="Ethernet", status="Up", has_gateway=False)
        third = NetworkAdapter(name="Wi-Fi", description="Intel Wi-Fi", status="Up", has_gateway=True)

        choices = adapter_choice_map([first, second, third])

        self.assertEqual(set(choices), {"Ethernet (1)", "Ethernet (2)", "Wi-Fi - Intel Wi-Fi"})
        self.assertIs(choices["Ethernet (1)"], first)
        self.assertIs(choices["Ethernet (2)"], second)
        self.assertIs(choices["Wi-Fi - Intel Wi-Fi"], third)

    def test_adapter_choice_map_disambiguates_without_colliding_with_existing_labels(self):
        first = NetworkAdapter(name="Ethernet", description="", status="Up", has_gateway=False)
        second = NetworkAdapter(name="Ethernet", description="Ethernet", status="Up", has_gateway=False)
        existing = NetworkAdapter(name="Ethernet (1)", description="", status="Up", has_gateway=False)

        choices = adapter_choice_map([first, second, existing])

        self.assertEqual(set(choices), {"Ethernet (1)", "Ethernet (2)", "Ethernet (3)"})
        self.assertIs(choices["Ethernet (1)"], existing)
        self.assertIs(choices["Ethernet (2)"], first)
        self.assertIs(choices["Ethernet (3)"], second)

    def test_is_windows_uses_platform_system(self):
        with patch("rtsp_tool.windows_ics.platform.system", return_value="Windows"):
            self.assertTrue(is_windows())
        with patch("rtsp_tool.windows_ics.platform.system", return_value="Darwin"):
            self.assertFalse(is_windows())

    def test_parse_adapter_json_returns_adapters_from_array_and_gateway_flag(self):
        output = """
        [
            {
                "Name": "Wi-Fi",
                "InterfaceDescription": "Intel Wireless",
                "Status": "Up",
                "IPv4DefaultGateway": {"NextHop": "192.168.1.1"}
            },
            {
                "Name": "USB RNDIS",
                "InterfaceDescription": "Remote NDIS",
                "Status": "Disconnected",
                "IPv4DefaultGateway": null
            }
        ]
        """

        adapters = parse_adapter_json(output)

        self.assertEqual(
            adapters,
            [
                NetworkAdapter(name="Wi-Fi", description="Intel Wireless", status="Up", has_gateway=True),
                NetworkAdapter(name="USB RNDIS", description="Remote NDIS", status="Disconnected", has_gateway=False),
            ],
        )

    def test_parse_adapter_json_handles_single_json_object(self):
        output = """
        {
            "Name": "Ethernet",
            "InterfaceDescription": "Realtek PCIe",
            "Status": "Up",
            "IPv4DefaultGateway": "192.168.1.1"
        }
        """

        adapters = parse_adapter_json(output)

        self.assertEqual(adapters, [NetworkAdapter(name="Ethernet", description="Realtek PCIe", status="Up", has_gateway=True)])

    def test_build_adapter_discovery_command_contains_expected_powershell(self):
        command = build_adapter_discovery_command()
        command_text = " ".join(command)

        self.assertIn("powershell", command_text.lower())
        self.assertIn("Get-NetAdapter", command_text)
        self.assertIn("Get-NetIPConfiguration", command_text)
        self.assertIn("ConvertTo-Json", command_text)

    def test_run_adapter_discovery_parses_output_and_passes_subprocess_options(self):
        calls = []

        class Completed:
            returncode = 0
            stdout = """
            {
                "Name": "Wi-Fi",
                "InterfaceDescription": "Intel Wireless",
                "Status": "Up",
                "IPv4DefaultGateway": {"NextHop": "192.168.1.1"}
            }
            """
            stderr = ""

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()

        adapters = run_adapter_discovery(runner=runner)

        self.assertEqual(adapters, [NetworkAdapter(name="Wi-Fi", description="Intel Wireless", status="Up", has_gateway=True)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], {"text": True, "capture_output": True, "check": False})
        self.assertIn("Get-NetAdapter", " ".join(calls[0][0]))

    def test_run_adapter_discovery_raises_runtime_error_with_stderr_on_failure(self):
        class Completed:
            returncode = 1
            stdout = ""
            stderr = "access denied"

        with self.assertRaisesRegex(RuntimeError, "access denied"):
            run_adapter_discovery(runner=lambda command, **kwargs: Completed())

    def test_run_adapter_discovery_raises_runtime_error_with_chinese_fallback_on_failure(self):
        class Completed:
            returncode = 1
            stdout = ""
            stderr = ""

        with self.assertRaisesRegex(RuntimeError, "网卡发现失败"):
            run_adapter_discovery(runner=lambda command, **kwargs: Completed())

    def test_build_ics_script_contains_names_hnetshare_sharing_calls_and_result_path(self):
        script = build_ics_script(
            "Pub'lic Wi-Fi",
            "Priv'ate RNDIS",
            Path("C:/Temp/ics'result.json"),
        )

        self.assertIn("Pub''lic Wi-Fi", script)
        self.assertIn("Priv''ate RNDIS", script)
        self.assertIn("HNetCfg.HNetShare", script)
        self.assertIn("EnableSharing(0)", script)
        self.assertIn("EnableSharing(1)", script)
        self.assertIn("C:/Temp/ics''result.json", script)

    def test_build_elevated_ics_command_contains_runas_wait_and_script_filename(self):
        command = build_elevated_ics_command(Path("C:/Temp/configure-ics.ps1"))
        command_text = " ".join(command)

        self.assertIn("Start-Process", command_text)
        self.assertIn("-Verb RunAs", command_text)
        self.assertIn("-Wait", command_text)
        self.assertIn("configure-ics.ps1", command_text)

    def test_build_elevated_ics_command_quotes_spaced_script_path_as_single_file_argument(self):
        command = build_elevated_ics_command(Path(r"C:\Users\A B\enable-ics.ps1"))
        command_text = " ".join(command)

        self.assertIn("'-File'", command_text)
        self.assertIn("'\"C:\\Users\\A B\\enable-ics.ps1\"'", command_text)

    def test_load_ics_result_reads_success_and_failure_json(self):
        with TemporaryDirectory() as tmpdir:
            success_path = Path(tmpdir) / "success.json"
            failure_path = Path(tmpdir) / "failure.json"
            success_path.write_text('{"ok": true, "message": "done"}', encoding="utf-8-sig")
            failure_path.write_text('{"ok": false, "message": "failed"}', encoding="utf-8-sig")

            success = load_ics_result(success_path)
            failure = load_ics_result(failure_path)

        self.assertTrue(success.ok)
        self.assertEqual(success.message, "done")
        self.assertFalse(failure.ok)
        self.assertEqual(failure.message, "failed")

    def test_open_manual_network_settings_launches_ncpa_control_panel(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))

        open_manual_network_settings(runner=runner)

        self.assertEqual(calls, [(["control.exe", "ncpa.cpl"], {"check": False})])


if __name__ == "__main__":
    unittest.main()
