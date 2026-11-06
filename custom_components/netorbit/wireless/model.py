"""The one shape every radio source produces, and the small sums that go with it."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

RADIO_WIFI = "wifi"
RADIO_ZIGBEE = "zigbee"
RADIO_ZWAVE = "zwave"
RADIO_THREAD = "thread"
RADIO_BLUETOOTH = "bluetooth"
RADIO_OTHER = "other"
RADIOS = (RADIO_WIFI, RADIO_ZIGBEE, RADIO_ZWAVE, RADIO_THREAD, RADIO_BLUETOOTH, RADIO_OTHER)

BAND_24 = "2.4 GHz"
BAND_5 = "5 GHz"
BAND_6 = "6 GHz"

# How a signal reads, with the thresholds people already use on their dashboards:
# good from LQI 80 / -80 dBm / quality 40, fair from LQI 40 / -90 dBm / quality 20, poor below.
GRADE_GOOD = "good"
GRADE_FAIR = "fair"
GRADE_POOR = "poor"
# A weak-signal clock started below good only stops once the signal reads clearly good again (a band
# above the threshold), so a device hovering at -79/-81 dBm counts as weak instead of restarting the
# clock with every bit of jitter: LQI 100 / -75 dBm / quality 50.
RECOVER_LQI = 100
RECOVER_DBM = -75
RECOVER_QUALITY = 50


@dataclass
class WirelessInfo:
    """What is known about one node's radio link. Every field is optional; None means unknown."""

    mac: str | None = None
    radio: str | None = None  # one of RADIOS
    ap_mac: str | None = None
    ap_name: str | None = None
    ssid: str | None = None
    band: str | None = None  # BAND_24 | BAND_5 | BAND_6
    channel: int | None = None
    signal_dbm: float | None = None
    snr: float | None = None
    lqi: int | None = None  # Zigbee link quality, 0-255
    quality: int | None = None  # 0-100
    source: str | None = None  # "entity:<id>", "tracker:<id>", "linked:<id>" or "<kind>:<controller name>"
    at: str | None = None
    # Current traffic as a Wi-Fi controller sees it: towards the station (tx) and from it (rx), and the PHY rate.
    tx_bps: float | None = None
    rx_bps: float | None = None
    rate_mbps: float | None = None
    # Filled by the coordinator, not by sources: since when the signal has read below good, and whether
    # that has lasted long enough (Settings > Weak signal after) to colour the node on the map.
    weak_since: str | None = None
    weak: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None and k != "mac"}


def to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def band_for_channel(channel: Any) -> str | None:
    """2.4 GHz for channels 1-14, 5 GHz for 32-177. 6 GHz reuses low numbers, so only a source that says so counts."""
    ch = to_int(channel)
    if ch is None:
        return None
    if 1 <= ch <= 14:
        return BAND_24
    if 32 <= ch <= 177:
        return BAND_5
    return None


def band_from_text(text: Any) -> str | None:
    """A band from the words controllers and trackers use: '802.11ax-5G', 'na', 'ng', '6E', '2.4GHz'."""
    t = str(text or "").lower().replace(" ", "")
    if not t:
        return None
    if any(x in t for x in ("6ghz", "6e", "-6g", "6g")):
        return BAND_6
    if any(x in t for x in ("2.4", "2g", "24g", "11b", "11g", "11n-2", "ng")):
        return BAND_24
    if any(x in t for x in ("5ghz", "5g", "11a", "11ac", "11ax-5", "na")):
        return BAND_5
    return None


def quality_from(signal_dbm: float | None, lqi: int | None) -> int | None:
    """0-100: LQI/255 when there is one, else a straight line from -100 dBm (0) to -50 dBm (100)."""
    if lqi is not None:
        return max(0, min(100, round(int(lqi) * 100 / 255)))
    if signal_dbm is not None:
        return max(0, min(100, int(round((float(signal_dbm) + 100) * 2))))
    return None


def grade(info: WirelessInfo | dict[str, Any] | None) -> str | None:
    """good, fair or poor from the LQI when there is one, else the dBm, else the quality; None when nothing is known.

    The same thresholds as the card's colours, so the map and the popup agree.
    """
    if info is None:
        return None
    get = info.get if isinstance(info, dict) else lambda k: getattr(info, k)
    lqi, dbm, quality = to_int(get("lqi")), to_float(get("signal_dbm")), to_int(get("quality"))
    if lqi is not None:
        return GRADE_GOOD if lqi >= 80 else GRADE_FAIR if lqi >= 40 else GRADE_POOR
    if dbm is not None:
        return GRADE_GOOD if dbm >= -80 else GRADE_FAIR if dbm >= -90 else GRADE_POOR
    if quality is not None:
        return GRADE_GOOD if quality >= 40 else GRADE_FAIR if quality >= 20 else GRADE_POOR
    return None


def recovered(info: WirelessInfo | dict[str, Any] | None) -> bool:
    """True once a signal reads clearly good (the band above the good threshold), the point where a
    weak-signal clock stops. Nothing known counts as not recovered; the caller decides what that means."""
    if info is None:
        return False
    get = info.get if isinstance(info, dict) else lambda k: getattr(info, k)
    lqi, dbm, quality = to_int(get("lqi")), to_float(get("signal_dbm")), to_int(get("quality"))
    if lqi is not None:
        return lqi >= RECOVER_LQI
    if dbm is not None:
        return dbm >= RECOVER_DBM
    if quality is not None:
        return quality >= RECOVER_QUALITY
    return False


def complete(info: WirelessInfo) -> WirelessInfo:
    """Fill what follows from what is known: band from the channel, quality from the signal, the radio kind."""
    if info.band is None and info.channel is not None:
        info.band = band_for_channel(info.channel)
    if info.quality is None:
        info.quality = quality_from(info.signal_dbm, info.lqi)
    if info.radio is None:
        info.radio = RADIO_WIFI if (info.ssid or info.ap_mac or info.ap_name or info.band or info.channel) else RADIO_OTHER
    return info


def merge(*infos: WirelessInfo | None) -> WirelessInfo | None:
    """Fold several sources into one; later arguments win field by field.

    Callers pass the least trusted source first (a tracker), then the device's own entities, then a
    controller, then anything a person linked by hand. A source that brings a new signal or LQI
    also resets the quality, so it is worked out from the winning numbers.
    """
    out: WirelessInfo | None = None
    for info in infos:
        if info is None:
            continue
        if out is None:
            out = WirelessInfo()
        if (info.signal_dbm is not None or info.lqi is not None) and info.quality is None:
            out.quality = None
        for f in fields(WirelessInfo):
            value = getattr(info, f.name)
            if value is not None:
                setattr(out, f.name, value)
    return complete(out) if out else None
