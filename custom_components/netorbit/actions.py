"""High level operations shared by services, the card and AI tools.

Each returns a small dict describing what happened, in words an assistant can relay.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import groups, manage
from .const import CONF_DEVICES, CONF_HUBS, CONF_IGNORED, HUB_AP, INTERNET_KEY, ROOT_HUB_ID
from .logic import extract_addresses, normalize_mac

if TYPE_CHECKING:
    from .coordinator import NetOrbitCoordinator

_LOGGER = logging.getLogger(__name__)


class ActionError(manage.ManageError):
    """Raised when a request cannot be carried out."""


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
            extra = {k: v for k, v in (("managed_by", node.managed_by), ("fields", node.fields), ("dns_name", node.fqdn),
                                       ("open_ports", [p["port"] for p in node.ports]), ("wireless", node.wireless), ("alerts", node.notify), ("port_alerts", node.notify_ports),
                                       ("throughput", node.throughput)) if v}
            if node.kind == "hub":
                hubs.append({
                    "id": node.key.removeprefix("hub:"), "name": node.name, "type": node.hub_type,
                    "connected_to": node.link, "ip": node.ip, "mac": node.mac, "status": node.status,
                    "added_by": node.hub_source, **extra,
                })
            else:
                devices.append({
                    "name": node.name, "ip": node.ip, "mac": node.mac, "hub": node.link,
                    "placed_by": node.placement, "status": node.status, "vendor": node.vendor,
                    "hostname": node.hostname, "allowed_to_sleep": node.sleepy, **extra,
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
    named_by_netorbit = False
    if device:
        key = coord.resolve_device(device)
        if not key:
            raise ActionError(f"No device matches '{device}'")
        rec = coord.known_device(key) or {}
        ip = ip or rec.get("ip")
        mac = mac or rec.get("mac")
        if not name:
            name, named_by_netorbit = _name(coord, key), True
    if not name:
        raise ActionError("A hub needs a name")
    parent_id = _hub(coord, parent, default_root=True)
    opts = _opts(coord)
    # A name taken from the device record is NetOrbit's guess, not a choice.
    result = manage.add_hub(opts, name, hub_type, parent_id, ip, normalize_mac(mac), source="manual", name_auto=named_by_netorbit)
    if parent:
        manage.update_hub(opts, result["hub"], parent=parent_id)
    await _save(hass, entry, coord, opts)
    return result


async def update_hub(hass, entry, coord, hub: str, **changes: Any) -> dict[str, Any]:
    """Rename a hub, change its type or parent, or its Managed by / extra fields."""
    hub_id = _hub(coord, hub)
    if changes.get("parent"):
        changes["parent"] = _hub(coord, changes["parent"])
    opts = _opts(coord)
    manage.update_hub(opts, hub_id, **{k: v for k, v in changes.items() if v is not None})
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
    chosen = bool(name)
    name = name or (suggestion or {}).get("name") or _name(coord, key)
    opts = _opts(coord)
    result = manage.add_hub(opts, name, hub_type, None, rec.get("ip"), rec.get("mac"), source="manual", name_auto=not chosen)
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
    sleepy: bool | None = None, hub: str | None = None, managed_by: str | None = None,
    fields: dict[str, Any] | None = None, entities: dict[str, Any] | None = None, notify: bool | None = None,
    notify_ports: Any = None,
) -> dict[str, Any]:
    """Change what a person set on a device. An empty name or icon goes back to the discovered one."""
    key = coord.resolve_device(device)
    if not key:
        raise ActionError(f"No device matches '{device}'")
    opts = _opts(coord)
    cfg = opts[CONF_DEVICES].setdefault(key, {})
    cfg["tracked"] = True
    for label, value in (("name", name), ("icon", icon)):
        if value is None:
            continue
        # An empty name or icon clears the one you set, so the device goes back to its automatic one.
        if value.strip():
            cfg[label] = value.strip()
        else:
            cfg.pop(label, None)
    if sleepy is not None:
        cfg["sleepy"] = sleepy
    if hub:
        manage.assign(opts, [key], _hub(coord, hub))
    manage.set_fields(cfg, managed_by, fields)
    manage.set_notify(cfg, notify, notify_ports)
    manage.set_links(cfg, entities)
    if key in opts[CONF_IGNORED]:
        opts[CONF_IGNORED].remove(key)
    await _save(hass, entry, coord, opts)
    return {"device": (name or "").strip() or _name(coord, key)}


def _node_key(coord: NetOrbitCoordinator, ref: Any) -> str | None:
    """A hub ('hub:<id>', or its name, IP or MAC when no device has it) or a device, as its key on the map."""
    ref = str(ref).strip()
    if not ref.startswith("hub:"):
        key = coord.resolve_device(ref)
        if key:
            return key
    hub = coord.resolve_hub(ref)
    return f"hub:{hub}" if hub else None


def _kind(coord: NetOrbitCoordinator, key: str) -> str:
    node = coord.data.nodes.get(key) if coord.data else None
    if node is not None and node.kind in groups.ROLES:
        return node.kind
    return "hub" if key.startswith("hub:") else "device"


def _label(coord: NetOrbitCoordinator, key: str) -> str:
    if key.startswith("hub:"):
        node = coord.data.nodes.get(key) if coord.data else None
        if node is not None:
            return node.name
        hub = next((h for h in coord.opts[CONF_HUBS] if h["id"] == key[4:]), None)
        return (hub or {}).get("name") or key[4:]
    return _name(coord, key)


async def update_many(
    hass, entry, coord, devices: list[str] | None = None, match: dict[str, Any] | None = None, preview: bool = False,
    **changes: Any,
) -> dict[str, Any]:
    """Make the same changes on many hubs and devices at once, in one save: the ones listed, plus the ones a match
    finds. preview returns what would change without saving anything."""
    if not devices and not match:
        raise ActionError("Give the devices to change, a match, or both")
    nodes = coord.data.nodes if coord.data else {}
    keys: list[str] = []
    missing: list[str] = []
    for ref in devices or []:
        key = _node_key(coord, ref)
        if key is None:
            missing.append(str(ref))
        elif key not in keys:
            keys.append(key)
    if match:
        under = _hub(coord, match["under"]) if match.get("under") else None
        try:
            found = groups.match(
                nodes, role=match.get("role"), under=under, direct_only=bool(match.get("direct_only")),
                types=match.get("type"), connections=match.get("connection"), field=match.get("field"),
                name=match.get("name"), vendor=match.get("vendor"), ip_range=match.get("ip_range"),
            )
        except ValueError as err:
            raise ActionError(str(err)) from err
        keys += [k for k in found if k not in keys]
    # None leaves a setting alone (False is a real change for sleep; for reset_placement it means no).
    changes = {k: v for k, v in changes.items() if v is not None and not (k == "reset_placement" and not v)}
    if changes.get("hub") and changes.get("reset_placement"):
        raise ActionError("Pick a hub or automatic placement, not both")
    if not keys and not preview:
        raise ActionError("Nothing matches" + (f". Not found: {', '.join(missing)}" if missing else ""))
    if not changes and not preview:
        raise ActionError("Nothing to change: give at least one setting, or preview: true to see what matches")
    if changes.get("hub"):
        changes["hub"] = _hub(coord, changes["hub"])
    names = {k: _label(coord, k) for k in keys}
    opts = _opts(coord)
    result = manage.update_many(opts, [(k, _kind(coord, k)) for k in keys], names=names, **changes)
    if result["changed"] and not preview:
        await _save(hass, entry, coord, opts)
    out: dict[str, Any] = {
        "matched": [names[k] for k in keys],
        "changed": [names[k] for k in result["changed"]],
        "unchanged": len(keys) - len(result["changed"]),
    }
    if preview:
        out["preview"] = True
    if result["skipped"]:
        out["skipped"] = {setting: [names[k] for k in ks] for setting, ks in result["skipped"].items()}
    if missing:
        out["not_found"] = missing
    return out


async def scan_ports(hass, entry, coord, devices: list[str] | None = None) -> dict[str, Any]:
    """Scan the TCP ports of these hubs or devices now. With none given, everything online is scanned in the background."""
    if not devices:
        return {"scheduled": coord.request_port_scan()}
    keys: list[str] = []
    missing: list[str] = []
    for ref in devices:
        ref = str(ref)
        hub = coord.resolve_hub(ref) if ref.startswith("hub:") else None
        key = f"hub:{hub}" if hub else coord.resolve_device(ref)
        if not key and (hub := coord.resolve_hub(ref)):
            key = f"hub:{hub}"
        (keys if key else missing).append(key or ref)
    if missing:
        raise ActionError(f"No hub or device matches {', '.join(missing)}")
    result = await coord.scan_ports(keys)
    return {"scanned": len(result), "open": {_name(coord, k): v for k, v in result.items()}}


EXPORT_VERSION = 1


def export_config(coord: NetOrbitCoordinator) -> dict[str, Any]:
    """Everything a person has set up, keyed by MAC, so it can be backed up or moved."""
    opts = coord.opts
    keep = ("name", "icon", "hub", "sleepy", "tracked", "host", "placed_at", "managed_by", "fields", "entities", "notify", "notify_ports")
    hub_keep = ("id", "name", "type", "parent", "parent_locked", "host", "mac", "source", "name_auto", "managed_by", "fields", "entities", "notify", "notify_ports")
    return {
        "netorbit_export": EXPORT_VERSION,
        "hubs": [
            {k: h.get(k) for k in hub_keep if h.get(k) is not None}
            for h in opts[CONF_HUBS]
        ],
        "devices": {key: {k: v for k, v in cfg.items() if k in keep} for key, cfg in opts[CONF_DEVICES].items()},
        "ignored": list(opts[CONF_IGNORED]),
        "dismissed_hubs": list(opts.get("dismissed_hubs", [])),
    }


TEXT_KEYS = ("managed_by", "fields")


def _import_text(target: dict[str, Any], src: dict[str, Any]) -> int:
    """Set Managed by and the extra fields of an imported hub or device on `target` through manage.set_fields, so
    an import gets the same checks as the services and forms. A value that fails them is left out and the setting
    already there is kept; an imported list of fields replaces the old one. Returns how many values were left out."""
    skipped = 0
    if "managed_by" in src:
        value = src["managed_by"]
        try:
            if value is not None and not isinstance(value, str):
                raise manage.ManageError("Managed by must be text")
            manage.set_fields(target, managed_by=value or "")
        except manage.ManageError:
            skipped += 1
    if "fields" in src:
        fields = src["fields"]
        if isinstance(fields, dict):
            target.pop("fields", None)
            for label, value in fields.items():
                try:
                    if not isinstance(value, str):
                        raise manage.ManageError("A field value must be text")
                    manage.set_fields(target, fields={label: value})
                except manage.ManageError:
                    skipped += 1
        elif fields is not None:
            skipped += 1
    return skipped


async def import_config(hass, entry, coord, data: dict[str, Any], replace: bool = False) -> dict[str, Any]:
    """Restore an export. By default it merges: imported settings win, nothing else is removed."""
    if not isinstance(data, dict) or data.get("netorbit_export") != EXPORT_VERSION:
        raise ActionError("That is not a NetOrbit export")
    opts = _opts(coord)
    hubs = {h["id"]: h for h in ([] if replace else opts[CONF_HUBS])}
    skipped = 0
    for h in data.get("hubs", []):
        if not isinstance(h, dict) or not h.get("id"):
            continue
        merged = {**hubs.get(h["id"], {}), **{k: v for k, v in h.items() if k not in TEXT_KEYS}}
        skipped += _import_text(merged, h)
        hubs[h["id"]] = merged
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
            merged = {**devices.get(key, {}), **{k: v for k, v in cfg.items() if k not in TEXT_KEYS}}
            skipped += _import_text(merged, cfg)
            devices[key] = merged
    opts[CONF_DEVICES] = devices
    for field in (CONF_IGNORED, "dismissed_hubs"):
        merged = list(dict.fromkeys([*([] if replace else opts.get(field, [])), *(data.get(field) or [])]))
        opts[field] = merged
    await _save(hass, entry, coord, opts)
    result = {"hubs": len(opts[CONF_HUBS]), "devices": len(devices)}
    if skipped:
        _LOGGER.warning("NetOrbit: the import left out %d Managed by or field values that were not valid", skipped)
        result["skipped"] = skipped
    return result


async def track(hass, entry, coord, mac: str | None = None, ip: str | None = None, **fields: Any) -> dict[str, Any]:
    key = coord.find_key(mac, ip)
    if key is None or key not in (coord._seen):  # noqa: SLF001
        if not mac and not ip:
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
