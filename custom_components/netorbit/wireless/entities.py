"""Radio details from entities Home Assistant already has: the device's own sensors, or ones a person linked."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..logic import normalize_mac
from .model import (
    RADIO_BLUETOOTH,
    RADIO_THREAD,
    RADIO_WIFI,
    RADIO_ZIGBEE,
    RADIO_ZWAVE,
    WirelessInfo,
    complete,
    to_float,
    to_int,
)

SIGNAL_STRENGTH = "signal_strength"
# Roles a person can link an entity to, and the sensor roles the automatic match recognises.
LINK_KINDS = ("signal", "lqi", "quality", "ssid", "bssid", "channel")
_BLE_PLATFORMS = ("bthome", "xiaomi_ble", "govee_ble", "switchbot", "led_ble", "oralb", "inkbird", "thermobeacon")
_WIFI_PLATFORMS = ("esphome", "shelly", "tasmota", "tplink", "wiz", "yeelight", "mqtt", "unifi", "fritz", "tuya")


def classify_entity(ent: er.RegistryEntry) -> str | None:
    """Which radio fact a sensor entity carries, from its class, unit and name, or None."""
    words = " ".join(
        str(x or "") for x in (ent.translation_key, ent.original_name, ent.unique_id, ent.entity_id.split(".", 1)[1])
    ).lower()
    device_class = str(ent.original_device_class or ent.device_class or "")
    unit = str(ent.unit_of_measurement or "")
    if "lqi" in words or "link_quality" in words or "linkquality" in words:
        return "lqi"
    if "bssid" in words:
        return "bssid"
    if "ssid" in words or "essid" in words:
        return "ssid"
    if "channel" in words and any(w in words for w in ("wifi", "wi_fi", "wi-fi", "wlan")):
        return "channel"
    if device_class == SIGNAL_STRENGTH or unit == "dBm" or "rssi" in words:
        return "signal"
    if "signal" in words:
        return "quality" if unit == "%" else "signal"
    return None


def radio_for(platform: str, words: str) -> str:
    """The radio behind an entity, from its integration or its name. IP devices default to Wi-Fi."""
    p = (platform or "").lower()
    w = (words or "").lower()
    if p == "zha" or "zigbee" in p or "zigbee" in w or "zha_" in w:
        return RADIO_ZIGBEE
    if "zwave" in p or "zwave" in w or "z_wave" in w:
        return RADIO_ZWAVE
    if p == "matter":
        return RADIO_WIFI if ("wi_fi" in w or "wifi" in w) else RADIO_THREAD
    if "thread" in w:
        return RADIO_THREAD
    if p in _BLE_PLATFORMS or "ble" in p.split("_") or "bluetooth" in p or "bluetooth" in w or "_ble_" in w:
        return RADIO_BLUETOOTH
    if p in _WIFI_PLATFORMS:
        return RADIO_WIFI
    return RADIO_WIFI


def match_entities(hass: HomeAssistant, device_id: str) -> list[tuple[str, str, str]]:
    """[(entity_id, role, platform)] for the sensors of one Home Assistant device that talk about its radio."""
    ent_reg = er.async_get(hass)
    out: list[tuple[str, str, str]] = []
    for ent in er.async_entries_for_device(ent_reg, device_id):
        if ent.domain != "sensor" or ent.disabled:
            continue
        role = classify_entity(ent)
        if role:
            out.append((ent.entity_id, role, ent.platform or ""))
    return out


def read_entities(hass: HomeAssistant, matched: list[tuple[str, str, str]], prefix: str = "entity") -> WirelessInfo | None:
    """Current values of matched entities as one WirelessInfo, or None when none has a usable state."""
    info = WirelessInfo()
    signal_source: str | None = None  # the dBm sensor, the best thing to name as the source
    lqi_source: str | None = None
    first_source: str | None = None
    for entity_id, role, platform in matched:
        state = hass.states.get(entity_id)
        if state is None or state.state in ("", "unknown", "unavailable"):
            continue
        value = state.state
        if role == "signal":
            num = to_float(value)
            if num is None:
                continue
            if state.attributes.get("unit_of_measurement") == "%":
                info.quality = max(0, min(100, int(num)))
            else:
                info.signal_dbm = num
            signal_source = signal_source or entity_id
        elif role == "lqi":
            num = to_int(value)
            if num is None:
                continue
            info.lqi = max(0, min(255, num))
            lqi_source = lqi_source or entity_id
        elif role == "quality":
            num = to_float(value)
            if num is None:
                continue
            info.quality = max(0, min(100, int(num)))
        elif role == "ssid":
            info.ssid = str(value)
        elif role == "bssid":
            info.ap_mac = normalize_mac(value)
        elif role == "channel":
            info.channel = to_int(value)
        else:
            continue
        first_source = first_source or entity_id
        if info.radio is None:
            info.radio = radio_for(platform, f"{entity_id} {state.attributes.get('friendly_name') or ''}")
    if first_source is None:
        return None
    info.source = f"{prefix}:{signal_source or lqi_source or first_source}"
    info.at = dt_util.utcnow().isoformat()
    return complete(info)


def read_linked(hass: HomeAssistant, links: dict[str, str]) -> WirelessInfo | None:
    """Entities a person linked to a node by role: {signal: sensor.x, lqi: sensor.y, ...}."""
    matched = [(str(eid), role, "") for role, eid in (links or {}).items() if role in LINK_KINDS and eid]
    return read_entities(hass, matched, prefix="linked") if matched else None
