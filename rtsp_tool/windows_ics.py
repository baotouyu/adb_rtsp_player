"""Windows ICS network adapter selection helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import platform
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


def is_windows() -> bool:
    return platform.system().lower() == "windows"


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
