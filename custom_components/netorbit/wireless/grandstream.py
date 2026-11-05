"""Grandstream GWN access points: each one lists its own Wi-Fi clients over SNMP (GRANDSTREAM-GWN-MIB).

The SNMP walk itself lives in snmp.py (SnmpClient.wireless_clients); this module is the plug-in
that recognises the access point and turns its client list into WirelessInfo records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..snmp import is_grandstream
from .base import AccessPointReader
from .model import RADIO_WIFI, WirelessInfo

if TYPE_CHECKING:
    from ..snmp import SnmpClient


class GrandstreamAccessPoint(AccessPointReader):
    kind = "grandstream_gwn"
    label = "Grandstream GWN access point"

    @staticmethod
    def matches(snmp: dict[str, Any]) -> bool:
        # A switch (it answers the bridge table) is read as a switch, whoever made it.
        return not snmp.get("bridge") and is_grandstream(snmp.get("object_id"), snmp.get("descr"))

    async def read(self, client: SnmpClient, host: str, community: str) -> list[WirelessInfo] | None:
        macs = await client.wireless_clients(host, community)
        if macs is None:
            return None
        return [WirelessInfo(mac=mac, radio=RADIO_WIFI, source=f"{self.kind}:{host}") for mac in sorted(macs)]
