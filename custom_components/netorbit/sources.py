"""Read hub and placement hints that other Home Assistant integrations already have."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .detect import NETWORK_DOMAINS
from .logic import normalize_mac, ping_label, tracker_label, useful_name


@dataclass
class RegistryInfo:
    """What another integration says about a MAC."""

    name: str | None
    model: str | None
    manufacturer: str | None
    domain: str | None
    # Only a device tracker's own device knows this MAC: its maker and model are kept, but it
    # says nothing about whether the client is network gear.
    tracker_only: bool = False


def _entry_ids(dev: dr.DeviceEntry) -> list[str]:
    """The config entries a device belongs to, on old and new Home Assistant.

    Newer versions give each device one `config_entry_id` and deprecate the
    `config_entries` set; older ones only have the set.
    """
    if hasattr(dev, "config_entry_id"):
        entry_id = dev.config_entry_id
        return [entry_id] if entry_id else []
    return list(getattr(dev, "config_entries", ()) or ())


def _all_devices(reg: dr.DeviceRegistry) -> list[dr.DeviceEntry]:
    """Every device entry, on old and new Home Assistant.

    Newer versions want `registry.devices` iterated (it yields entries); older ones
    hand back a mapping whose iteration yields ids.
    """
    entries = list(reg.devices)
    if entries and isinstance(entries[0], str):
        return list(reg.devices.values())
    return entries


def _is_tracker_only(ent_reg: er.EntityRegistry, dev: dr.DeviceEntry) -> bool:
    """Whether a device holds nothing but device trackers (turned on or off).

    From Home Assistant 2026.11 every network-scanner tracker (UniFi, Nmap and other
    router integrations) gets a device of its own, named by that integration after an
    alias, a hostname or the maker plus part of the MAC, and most of these trackers start
    turned off. Such a device says nothing about what the client is, so it must not make
    a client look like network gear or outrank the name NetOrbit found for it.
    """
    entities = er.async_entries_for_device(ent_reg, dev.id, include_disabled_entities=True)
    return bool(entities) and all(ent.domain == "device_tracker" for ent in entities)


def _device_domain(hass: HomeAssistant, dev: dr.DeviceEntry) -> str | None:
    """The integration a device belongs to, preferring network integrations."""
    domain = None
    for entry_id in _entry_ids(dev):
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain in NETWORK_DOMAINS:
            return entry.domain
        if entry and domain is None and entry.domain != "netorbit":
            domain = entry.domain
    return domain


def registry_by_mac(hass: HomeAssistant) -> dict[str, RegistryInfo]:
    """Every device in Home Assistant that has a MAC connection, keyed by MAC."""
    reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    out: dict[str, RegistryInfo] = {}
    trackers: dict[str, RegistryInfo] = {}
    for dev in _all_devices(reg):
        macs = [normalize_mac(v) for k, v in dev.connections if k == dr.CONNECTION_NETWORK_MAC]
        macs = [m for m in macs if m]
        if not macs:
            continue
        domain = _device_domain(hass, dev)
        if _is_tracker_only(ent_reg, dev):
            # Of the name only one the user gave the tracker's device counts. The tracker's own
            # name still comes through `tracker_names_by_mac` while the tracker is on.
            info = RegistryInfo(useful_name(dev.name_by_user), dev.model, dev.manufacturer, domain, tracker_only=True)
            for mac in macs:
                old = trackers.get(mac)
                trackers[mac] = info if old is None else RegistryInfo(
                    old.name or info.name, old.model or info.model,
                    old.manufacturer or info.manufacturer, old.domain or info.domain, tracker_only=True,
                )
            continue
        info = RegistryInfo(
            name=useful_name(dev.name_by_user) or useful_name(dev.name),
            model=dev.model, manufacturer=dev.manufacturer, domain=domain,
        )
        for mac in macs:
            old = out.get(mac)
            if old is None:
                out[mac] = info
                continue
            # The same MAC often shows up under several integrations (a speaker and its
            # media renderer, say). Prefer network integrations, then a real name.
            if domain in NETWORK_DOMAINS and old.domain not in NETWORK_DOMAINS:
                out[mac] = RegistryInfo(info.name or old.name, info.model or old.model,
                                        info.manufacturer or old.manufacturer, domain)
            elif old.name is None and info.name:
                out[mac] = RegistryInfo(info.name, old.model or info.model,
                                        old.manufacturer or info.manufacturer, old.domain)
    # A tracker's device only fills in what no other device says about the MAC.
    for mac, info in trackers.items():
        old = out.get(mac)
        if old is None:
            out[mac] = info
        else:
            out[mac] = RegistryInfo(old.name or info.name, old.model or info.model,
                                    old.manufacturer or info.manufacturer, old.domain)
    return out


def tracker_names_by_mac(hass: HomeAssistant) -> dict[str, str]:
    """{mac: name} from device trackers (nmap, router integrations) that report a MAC."""
    out: dict[str, str] = {}
    for state in hass.states.async_all("device_tracker"):
        mac = normalize_mac(state.attributes.get("mac"))
        if not mac:
            continue
        name = tracker_label(state.attributes.get("friendly_name")) or tracker_label(state.attributes.get("host_name"))
        if name:
            out.setdefault(mac, name)
    return out


def ping_names_by_ip(hass: HomeAssistant) -> dict[str, str]:
    """{ip: name} from Home Assistant's Ping integration, which many people already set up by hand."""
    out: dict[str, str] = {}
    ent_reg = er.async_get(hass)
    for entry in hass.config_entries.async_entries("ping"):
        host = (entry.data or {}).get("host") or (entry.options or {}).get("host")
        if not host:
            continue
        name = None
        for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            state = hass.states.get(ent.entity_id)
            name = ping_label(state.attributes.get("friendly_name") if state else None) or ping_label(ent.name)
            if name:
                break
        name = name or ping_label(entry.title)
        if name:
            out.setdefault(str(host), name)
    return out


def client_access_points(hass: HomeAssistant) -> dict[str, str]:
    """{client mac: AP mac} from integrations that know which AP each client uses.

    * Any device_tracker exposing ``mac`` and ``ap_mac`` attributes (UniFi does).
    * Netgear's per-device ``conn_ap_mac`` sensors (Orbi and other mesh routers).
    """
    out: dict[str, str] = {}
    for state in hass.states.async_all("device_tracker"):
        ap = normalize_mac(state.attributes.get("ap_mac"))
        mac = normalize_mac(state.attributes.get("mac"))
        if ap and mac and state.state == "home":
            out[mac] = ap

    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    for entry in ent_reg.entities.values():
        if entry.domain != "sensor" or not (entry.unique_id or "").endswith("conn_ap_mac"):
            continue
        state = hass.states.get(entry.entity_id)
        ap = normalize_mac(state.state) if state else None
        if not ap or not entry.device_id:
            continue
        dev = dev_reg.async_get(entry.device_id)
        if not dev:
            continue
        for kind, value in dev.connections:
            mac = normalize_mac(value) if kind == dr.CONNECTION_NETWORK_MAC else None
            if mac:
                out[mac] = ap
    return out


async def ssdp_types_by_ip(hass: HomeAssistant) -> dict[str, list[str]]:
    """{ip: [device types]} for devices that announced themselves over UPnP."""
    if "ssdp" not in hass.config.components:
        return {}
    try:
        from homeassistant.components import ssdp  # noqa: PLC0415
        from urllib.parse import urlparse  # noqa: PLC0415
    except ImportError:
        return {}
    out: dict[str, list[str]] = {}
    for st in (
        "urn:schemas-upnp-org:device:WLANAccessPointDevice:1",
        "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
        "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
    ):
        try:
            infos = await ssdp.async_get_discovery_info_by_st(hass, st)
        except Exception:  # noqa: BLE001
            continue
        for info in infos:
            host = urlparse(info.ssdp_location or "").hostname
            if host:
                out.setdefault(host, []).append(info.upnp.get("deviceType") or st)
    return out
