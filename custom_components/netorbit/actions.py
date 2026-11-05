"""High level operations shared by services, the card and AI tools.

Each returns a small dict describing what happened, in words an assistant can relay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from . import manage
from .const import CONF_DEVICES, CONF_HUBS, CONF_IGNORED, HUB_AP, INTERNET_KEY, ROOT_HUB_ID
from .logic import extract_addresses, normalize_ipv4, normalize_mac

if TYPE_CHECKING:
    from .coordinator import NetOrbitCoordinator


class ActionError(manage.ManageError):
    """Raised when a request cannot be carried out."""


def ipv4_address(value: Any) -> str:
    """Validator for service and tool fields: an IPv4 address, in its canonical form.

    Names are refused on purpose. NetOrbit pings by address, and a name that does not resolve
    makes icmplib raise, which fails every refresh and keeps the entry from loading.
    """
    ip = normalize_ipv4(cv.string(value))
    if not ip:
        raise vol.Invalid(f"{value} is not an IPv4 address")
    return ip


def mac_address(value: Any) -> str:
    """Validator for service and tool fields: a MAC address, normalized to lowercase colon form."""
    mac = normalize_mac(cv.string(value))
    if not mac:
        raise vol.Invalid(f"{value} is not a MAC address")
    return mac


async def _save(hass: HomeAssistant, entry: ConfigEntry, coord: NetOrbitCoordinator, opts: dict[str, Any]) -> None:
    coord.internal_update = True
    hass.config_entries.async_update_entry(entry, options=opts)
    coord.apply_options(entry)
    # Redraw the map now from what NetOrbit already knows, then check the network in the
    # background. Waiting for a ping round here made every drag take a second or two.
    coord.async_rebuild()
    entry.async_create_background_task(hass, coord.async_request_refresh(), "netorbit refresh after change")


def _opts(coord: NetOrbitCoordinator) -> dict[str, Any]:
    return manage.copy_options(coord.opts)


def _hub(coord: NetOrbitCoordinator, ref: str | None, default_root: bool = False) -> str:
    if not ref and default_root:
        return ROOT_HUB_ID
    hub = coord.resolve_hub(ref or "")
    if hub is None:
        names = ", ".join(h.get("name") or h["id"] for h in coord.opts[CONF_HUBS])
        raise ActionError(f"No hub matches '{ref}'. Hubs: {names}")
    return hub


def _devices(coord: NetOrbitCoordinator, refs: list[str]) -> tuple[list[str], list[str]]:
    found: list[str] = []
    missing: list[str] = []
    for ref in refs:
        key = coord.resolve_device(ref)
        if key and key not in found:
            found.append(key)
        elif not key:
            missing.append(str(ref))
    return found, missing


def _name(coord: NetOrbitCoordinator, key: str) -> str:
    node = coord.data.nodes.get(key) if coord.data else None
    return node.name if node else coord._discovered_name(key, coord.known_device(key) or {})  # noqa: SLF001


def _internet_status(data: Any) -> str | None:
    """online, stale (down while the router answers), unknown, or None when the check is off."""
    node = data.nodes.get(INTERNET_KEY) if data else None
    return None if node is None else (node.status or "unknown")


def network_map(coord: NetOrbitCoordinator) -> dict[str, Any]:
    """The whole map in a compact form."""
    data = coord.data
    hubs = []
    devices = []
    if data:
        for node in data.nodes.values():
            if node.kind == INTERNET_KEY:
                continue
            if node.kind == "hub":
                hubs.append({
                    "id": node.key.removeprefix("hub:"), "name": node.name, "type": node.hub_type,
                    "connected_to": node.link, "ip": node.ip, "mac": node.mac, "status": node.status,
                    "added_by": node.hub_source,
                })
            else:
                devices.append({
                    "name": node.name, "ip": node.ip, "mac": node.mac, "hub": node.link,
                    "placed_by": node.placement, "status": node.status, "vendor": node.vendor,
                    "hostname": node.hostname, "allowed_to_sleep": node.sleepy,
                })
    return {
        "hubs": hubs,
        "devices": sorted(devices, key=lambda d: (d["hub"] or "", d["name"].lower())),
        "new_devices": data.new_devices if data else [],
        "suggested_hubs": data.suggested_hubs if data else [],
        "automatic_sources": data.sources if data else [],
        "internet": _internet_status(data),
        "mode": coord.opts.get("mode"),
    }


async def assign(hass, entry, coord, devices: list[str], hub: str) -> dict[str, Any]:
    hub_id = _hub(coord, hub)
    keys, missing = _devices(coord, devices)
    if not keys:
        raise ActionError(f"None of these devices were found: {', '.join(missing)}")
    opts = _opts(coord)
    manage.assign(opts, keys, hub_id)
    await _save(hass, entry, coord, opts)
    return {"hub": hub_id, "assigned": [_name(coord, k) for k in keys], "not_found": missing}


async def reset(hass, entry, coord, devices: list[str]) -> dict[str, Any]:
    keys, missing = _devices(coord, devices)
    opts = _opts(coord)
    manage.reset_placement(opts, keys)
    await _save(hass, entry, coord, opts)
    return {"reset": [_name(coord, k) for k in keys], "not_found": missing}


async def add_hub(
    hass, entry, coord, name: str | None = None, hub_type: str = HUB_AP, parent: str | None = None,
    ip: str | None = None, mac: str | None = None, device: str | None = None,
) -> dict[str, Any]:
    if device:
        key = coord.resolve_device(device)
        if not key:
            raise ActionError(f"No device matches '{device}'")
        rec = coord.known_device(key) or {}
        ip = ip or rec.get("ip")
        mac = mac or rec.get("mac")
        name = name or _name(coord, key)
    if not name:
        raise ActionError("A hub needs a name")
    parent_id = _hub(coord, parent, default_root=True)
    opts = _opts(coord)
    result = manage.add_hub(opts, name, hub_type, parent_id, ip, normalize_mac(mac), source="manual")
    if parent:
        manage.update_hub(opts, result["hub"], parent=parent_id)
    await _save(hass, entry, coord, opts)
    return result


async def update_hub(hass, entry, coord, hub: str, **fields: Any) -> dict[str, Any]:
    hub_id = _hub(coord, hub)
    if fields.get("parent"):
        fields["parent"] = _hub(coord, fields["parent"])
    opts = _opts(coord)
    manage.update_hub(opts, hub_id, **{k: v for k, v in fields.items() if v is not None})
    await _save(hass, entry, coord, opts)
    return {"hub": hub_id}


async def remove_hub(hass, entry, coord, hub: str) -> dict[str, Any]:
    hub_id = _hub(coord, hub)
    opts = _opts(coord)
    result = manage.remove_hub(opts, hub_id)
    await _save(hass, entry, coord, opts)
    return result


async def import_list(hass, entry, coord, hub: str, text: str, add_missing: bool = True) -> dict[str, Any]:
    """Assign every device mentioned in pasted text (an AP's client table, an app screen) to a hub."""
    hub_id = _hub(coord, hub)
    macs, ips = extract_addresses(text)
    if not macs and not ips:
        raise ActionError("No MAC or IP addresses found in that text")
    keys, unmatched = coord.match_addresses(macs, ips)
    added = []
    if add_missing:
        for addr in list(unmatched):
            mac = normalize_mac(addr)
            if mac:
                keys.append(coord.seed_device(mac, None))
                added.append(addr)
                unmatched.remove(addr)
    if not keys:
        raise ActionError("None of those addresses match a device NetOrbit knows")
    opts = _opts(coord)
    manage.assign(opts, keys, hub_id)
    await _save(hass, entry, coord, opts)
    return {
        "hub": hub_id, "assigned": [_name(coord, k) for k in keys],
        "added_new": added, "not_matched": unmatched,
    }


async def confirm_hub(
    hass, entry, coord, device: str, hub_type: str | None = None, name: str | None = None,
    assign: list[str] | None = None,
) -> dict[str, Any]:
    """Make a device a hub. `assign` places other devices under the new hub in the same save
    (the card does this when someone drops a device on a suggested hub)."""
    key = coord.resolve_device(device)
    rec = coord.known_device(key) if key else None
    if not rec:
        raise ActionError(f"No device matches '{device}'")
    keys: list[str] = []
    if assign:
        keys, missing = _devices(coord, assign)
        keys = [k for k in keys if k != key]
        if not keys:
            raise ActionError(f"None of these devices were found: {', '.join(missing) or ', '.join(assign)}")
    suggestion = next((s for s in (coord.data.suggested_hubs if coord.data else []) if s["key"] == key), None)
    hub_type = hub_type or (suggestion or {}).get("type") or HUB_AP
    name = name or (suggestion or {}).get("name") or _name(coord, key)
    opts = _opts(coord)
    result = manage.add_hub(opts, name, hub_type, None, rec.get("ip"), rec.get("mac"), source="manual")
    # The device is now a hub, so drop any device-level settings for it.
    opts[CONF_DEVICES].pop(key, None)
    if keys:
        manage.assign(opts, keys, result["hub"])
        result["assigned"] = [_name(coord, k) for k in keys]
    await _save(hass, entry, coord, opts)
    return result


async def dismiss_hub(hass, entry, coord, device: str) -> dict[str, Any]:
    key = coord.resolve_device(device)
    rec = coord.known_device(key) if key else None
    if not rec or not rec.get("mac"):
        raise ActionError(f"No device matches '{device}'")
    opts = _opts(coord)
    manage.dismiss_hub(opts, rec["mac"])
    await _save(hass, entry, coord, opts)
    return {"dismissed": _name(coord, key)}


async def update_device(
    hass, entry, coord, device: str, name: str | None = None, icon: str | None = None,
    sleepy: bool | None = None, hub: str | None = None,
) -> dict[str, Any]:
    key = coord.resolve_device(device)
    if not key:
        raise ActionError(f"No device matches '{device}'")
    opts = _opts(coord)
    cfg = opts[CONF_DEVICES].setdefault(key, {})
    cfg["tracked"] = True
    if name is not None:
        # An empty name clears the one you set, so the device goes back to its automatic name.
        if name.strip():
            cfg["name"] = name.strip()
        else:
            cfg.pop("name", None)
    if icon:
        cfg["icon"] = icon
    if sleepy is not None:
        cfg["sleepy"] = sleepy
    if hub:
        manage.assign(opts, [key], _hub(coord, hub))
    if key in opts[CONF_IGNORED]:
        opts[CONF_IGNORED].remove(key)
    await _save(hass, entry, coord, opts)
    return {"device": (name or "").strip() or _name(coord, key)}


EXPORT_VERSION = 1


def export_config(coord: NetOrbitCoordinator) -> dict[str, Any]:
    """Everything a person has set up, keyed by MAC, so it can be backed up or moved."""
    opts = coord.opts
    keep = ("name", "icon", "hub", "sleepy", "tracked", "host", "placed_at")
    return {
        "netorbit_export": EXPORT_VERSION,
        "hubs": [
            {k: h.get(k) for k in ("id", "name", "type", "parent", "parent_locked", "host", "mac", "source") if h.get(k) is not None}
            for h in opts[CONF_HUBS]
        ],
        "devices": {key: {k: v for k, v in cfg.items() if k in keep} for key, cfg in opts[CONF_DEVICES].items()},
        "ignored": list(opts[CONF_IGNORED]),
        "dismissed_hubs": list(opts.get("dismissed_hubs", [])),
    }


async def import_config(hass, entry, coord, data: dict[str, Any], replace: bool = False) -> dict[str, Any]:
    """Restore an export. By default it merges: imported settings win, nothing else is removed."""
    if not isinstance(data, dict) or data.get("netorbit_export") != EXPORT_VERSION:
        raise ActionError("That is not a NetOrbit export")
    opts = _opts(coord)
    hubs = {h["id"]: h for h in ([] if replace else opts[CONF_HUBS])}
    for h in data.get("hubs", []):
        if not isinstance(h, dict) or not h.get("id"):
            continue
        hubs[h["id"]] = {**hubs.get(h["id"], {}), **h}
    if ROOT_HUB_ID not in hubs:
        hubs[ROOT_HUB_ID] = next(x for x in opts[CONF_HUBS] if x["id"] == ROOT_HUB_ID)
    hubs[ROOT_HUB_ID]["parent"] = None
    ids = set(hubs)
    for h in hubs.values():
        if h["id"] != ROOT_HUB_ID and (h.get("parent") not in ids or manage.creates_cycle(list(hubs.values()), h["id"], h.get("parent") or ROOT_HUB_ID)):
            h["parent"] = ROOT_HUB_ID
    opts[CONF_HUBS] = [hubs[ROOT_HUB_ID], *[h for k, h in hubs.items() if k != ROOT_HUB_ID]]
    devices = {} if replace else opts[CONF_DEVICES]
    for key, cfg in (data.get("devices") or {}).items():
        mac = normalize_mac(key)
        key = mac or str(key)
        if isinstance(cfg, dict):
            if cfg.get("hub") and cfg["hub"] not in ids:
                cfg = {k: v for k, v in cfg.items() if k != "hub"}
            devices[key] = {**devices.get(key, {}), **cfg}
    opts[CONF_DEVICES] = devices
    for field in (CONF_IGNORED, "dismissed_hubs"):
        merged = list(dict.fromkeys([*([] if replace else opts.get(field, [])), *(data.get(field) or [])]))
        opts[field] = merged
    await _save(hass, entry, coord, opts)
    return {"hubs": len(opts[CONF_HUBS]), "devices": len(devices)}


async def track(hass, entry, coord, mac: str | None = None, ip: str | None = None, **fields: Any) -> dict[str, Any]:
    key = coord.find_key(mac, ip)
    if key is None or key not in (coord._seen):  # noqa: SLF001
        if not normalize_mac(mac) and not ip:
            raise ActionError("Give a MAC or IP address")
        key = coord.seed_device(mac, ip)
    opts = _opts(coord)
    cfg = opts[CONF_DEVICES].setdefault(key, {})
    cfg["tracked"] = True
    if ip:
        cfg["host"] = ip
    if fields.get("name") is not None:
        # An empty name clears the one you set, so the device goes back to its automatic name.
        if fields["name"].strip():
            cfg["name"] = fields["name"].strip()
        else:
            cfg.pop("name", None)
    for field in ("icon", "sleepy"):
        if fields.get(field) is not None:
            cfg[field] = fields[field]
    if fields.get("hub"):
        manage.assign(opts, [key], _hub(coord, fields["hub"]))
    if key in opts[CONF_IGNORED]:
        opts[CONF_IGNORED].remove(key)
    await _save(hass, entry, coord, opts)
    return {"tracking": _name(coord, key)}


async def ignore(hass, entry, coord, mac: str | None = None, ip: str | None = None, device: str | None = None) -> dict[str, Any]:
    key = coord.resolve_device(device) if device else coord.find_key(mac, ip)
    if key is None:
        raise ActionError("Device not found")
    opts = _opts(coord)
    if key not in opts[CONF_IGNORED]:
        opts[CONF_IGNORED].append(key)
    opts[CONF_DEVICES].pop(key, None)
    name = _name(coord, key)
    await _save(hass, entry, coord, opts)
    return {"ignored": name}
