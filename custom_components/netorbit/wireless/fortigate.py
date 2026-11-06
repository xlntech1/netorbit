"""FortiGate as a wireless controller: the stations its FortiAPs serve, over the REST monitor API.

Needs a REST API administrator whose profile grants only Monitor > WiFi (read), with the Home
Assistant address as its trusted host. Nothing is ever written.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from homeassistant.util import dt as dt_util

from ..logic import normalize_mac
from .base import AUTH_TOKEN, Controller, ControllerError
from .model import RADIO_WIFI, WirelessInfo, band_for_channel, band_from_text, complete, to_float, to_int

CLIENTS = "/api/v2/monitor/wifi/client"
MANAGED_APS = "/api/v2/monitor/wifi/managed_ap"
TIMEOUT = 10


class FortiGateController(Controller):
    kind = "fortigate"
    label = "FortiGate (FortiAP wireless controller)"
    note = ("Create a REST API administrator with a profile that allows only Monitor > WiFi (read), set this "
            "Home Assistant's address as its trusted host, and paste the token here. The token is stored in "
            "NetOrbit's settings.")
    auth = AUTH_TOKEN
    default_port = 443
    default_verify_ssl = False  # FortiGates ship with a self-signed certificate

    async def fetch(self, session: aiohttp.ClientSession) -> list[WirelessInfo]:
        clients = await self._get(session, CLIENTS)
        aps: dict[str, dict[str, Any]] = {}
        try:
            for ap in await self._get(session, MANAGED_APS):
                for key in (ap.get("serial"), ap.get("wtp_id"), ap.get("name")):
                    if key:
                        aps[str(key)] = ap
        except ControllerError:
            pass  # the AP list is only there to learn AP MACs; clients still have the AP's name
        stamp = dt_util.utcnow().isoformat()
        return [info for info in (parse_client(c, aps, self.name, stamp) for c in clients) if info]

    async def _get(self, session: aiohttp.ClientSession, path: str) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.cfg.get('token', '')}", "Accept": "application/json"}
        try:
            async with asyncio.timeout(TIMEOUT):
                resp = await session.get(f"{self.base_url}{path}", headers=headers, ssl=self.ssl)
                if resp.status in (401, 403):
                    raise ControllerError("invalid_auth", f"HTTP {resp.status}")
                if resp.status != 200:
                    raise ControllerError("cannot_connect", f"HTTP {resp.status}")
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
            raise ControllerError("cannot_connect", str(err) or err.__class__.__name__) from err
        results = data.get("results") if isinstance(data, dict) else data
        return [r for r in results if isinstance(r, dict)] if isinstance(results, list) else []


def parse_client(c: dict[str, Any], aps: dict[str, dict[str, Any]], source: str, stamp: str) -> WirelessInfo | None:
    """One station from the monitor API into a WirelessInfo. Field names vary a little between FortiOS versions."""
    mac = normalize_mac(c.get("mac") or c.get("sta_mac"))
    if not mac:
        return None
    ap = aps.get(str(c.get("wtp_id") or "")) or aps.get(str(c.get("wtp_name") or "")) or {}
    ap_mac = normalize_mac(ap.get("board_mac") or ap.get("mac") or ap.get("wtp_mac"))
    band = band_from_text(c.get("band") or c.get("radio_type")) or band_for_channel(c.get("channel"))
    return complete(WirelessInfo(
        mac=mac, radio=RADIO_WIFI, ap_mac=ap_mac,
        ap_name=c.get("wtp_name") or ap.get("name") or (str(c.get("wtp_id")) if c.get("wtp_id") else None),
        ssid=c.get("ssid") or c.get("vap"), band=band, channel=to_int(c.get("channel")),
        signal_dbm=to_float(c.get("signal")), snr=to_float(c.get("snr")),
        tx_bps=to_float(c.get("bandwidth_tx")), rx_bps=to_float(c.get("bandwidth_rx")),
        rate_mbps=(rate / 1_000_000) if (rate := to_float(c.get("data_rate_bps"))) else None,
        source=f"fortigate:{source}", at=stamp,
    ))
