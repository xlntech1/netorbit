"""Radio details from device_tracker attributes (UniFi, Omada, Netgear and friends expose some)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..logic import normalize_mac
from .model import RADIO_WIFI, WirelessInfo, band_from_text, complete, to_float, to_int


def tracker_wireless_by_mac(hass: HomeAssistant) -> dict[str, WirelessInfo]:
    """{mac: WirelessInfo} for every home device_tracker that reports a MAC and something about its radio."""
    out: dict[str, WirelessInfo] = {}
    stamp = dt_util.utcnow().isoformat()
    for state in hass.states.async_all("device_tracker"):
        a = state.attributes
        mac = normalize_mac(a.get("mac"))
        if not mac or state.state != "home" or a.get("is_wired") is True:
            continue
        info = WirelessInfo(
            mac=mac, radio=RADIO_WIFI,
            ap_mac=normalize_mac(a.get("ap_mac")), ssid=a.get("essid") or a.get("ssid") or None,
            band=band_from_text(a.get("radio") or a.get("radio_proto")), channel=to_int(a.get("channel")),
            signal_dbm=to_float(a.get("signal") if a.get("signal") is not None else a.get("rssi")),
            source=f"tracker:{state.entity_id}", at=stamp,
        )
        if not any((info.ap_mac, info.ssid, info.band, info.channel, info.signal_dbm is not None)):
            continue
        out.setdefault(mac, complete(info))
    return out
