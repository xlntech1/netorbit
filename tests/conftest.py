"""Shared fixtures. All addresses use the 192.0.2.0/24 documentation range."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

SUBNET = "192.0.2.0/24"
GATEWAY = "192.0.2.1"
MAC_A = "02:00:5e:00:00:0a"  # randomized style (locally administered)  example-ok
MAC_B = "00:00:5e:00:53:0b"  # IANA documentation range
MAC_C = "00:00:5e:00:53:0c"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/netorbit."""
    return


@dataclass
class FakeHost:
    address: str
    is_alive: bool


class FakeNet:
    """Stands in for the network: who answers pings and what the ARP table holds."""

    def __init__(self) -> None:
        self.alive: set[str] = set()
        self.arp: dict[str, str] = {}
        self.arp_also: dict[str, list[str]] = {}  # ip -> MACs ARP lists for it before arp[ip] (a second interface)
        # SNMP: ip -> (community, ProbeResult) and ip -> {mac: port}
        self.snmp: dict[str, tuple[str, object]] = {}
        self.tables: dict[str, dict[str, int]] = {}
        self.wifi: dict[str, object] = {}  # ip -> set of Wi-Fi client MACs a Grandstream AP lists (or None: unreadable)
        self.dns: dict[str, str] = {}
        self.probed: list[tuple[str, str]] = []  # every (ip, community) NetOrbit asked
        self.mdns: dict[str, str] = {}  # ip -> Bonjour name, e.g. "Office-iMac.local"
        self.vendors: dict[str, str] = {}  # "AA:BB:CC" -> vendor name

    async def snmp_probe(self, _client, ip, community):
        self.probed.append((ip, community))
        entry = self.snmp.get(ip)
        if entry and entry[0] == community:
            return entry[1]
        return None

    async def snmp_table(self, _client, ip, community):
        entry = self.snmp.get(ip)
        if entry and entry[0] == community:
            return dict(self.tables.get(ip, {}))
        return None

    async def snmp_wifi(self, _client, ip, community):
        entry = self.snmp.get(ip)
        if entry and entry[0] == community and ip in self.wifi:
            return self.wifi[ip]
        return None

    async def mdns_name(self, ip, timeout=1.0):
        return self.mdns.get(ip)

    def arp_all(self) -> dict[str, list[str]]:
        return {ip: [*self.arp_also.get(ip, []), mac] for ip, mac in self.arp.items()}

    async def multiping(self, addresses, **kwargs):
        return [FakeHost(a, a in self.alive) for a in addresses]

    async def ping(self, *args, **kwargs):
        return FakeHost("127.0.0.1", True)


@pytest.fixture
def fake_net():
    net = FakeNet()

    async def multiping(*args, **kwargs):  # looked up per call, so a test can swap net.multiping
        return await net.multiping(*args, **kwargs)

    with (
        patch("icmplib.async_multiping", side_effect=multiping),
        patch("icmplib.async_ping", side_effect=net.ping),
        patch("custom_components.netorbit.coordinator._read_arp", side_effect=lambda: dict(net.arp)),
        patch("custom_components.netorbit.coordinator._read_arp_all", side_effect=net.arp_all),
        patch("custom_components.netorbit.coordinator._reverse_dns", side_effect=lambda ip: net.dns.get(ip)),
        patch("custom_components.netorbit.coordinator.mdns_name", side_effect=net.mdns_name),
        patch("aiooui.is_loaded", return_value=True),
        patch("aiooui.get_vendor", side_effect=lambda prefix: net.vendors.get(prefix)),
        patch("custom_components.netorbit.snmp.SnmpClient.probe", autospec=True, side_effect=net.snmp_probe),
        patch("custom_components.netorbit.snmp.SnmpClient.mac_table", autospec=True, side_effect=net.snmp_table),
        patch("custom_components.netorbit.snmp.SnmpClient.wireless_clients", autospec=True, side_effect=net.snmp_wifi),
    ):
        yield net
