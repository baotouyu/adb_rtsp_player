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
