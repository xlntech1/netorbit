"""One place for every change to the map, used by services, the options flow, the card and AI tools.

Every function takes a copy of the entry options, changes it and returns a result dict.
The caller saves the options.
"""

from __future__ import annotations

import copy
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICES,
    CONF_DISMISSED_HUBS,
    CONF_HUBS,
    CONF_IGNORED,
    HUB_OTHER,
    HUB_TYPES,
    ROOT_HUB_ID,
)
from .logic import slugify_id


class ManageError(ValueError):
    """A change that cannot be made, with a message meant for people."""


def copy_options(opts: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(opts)


def hub_ids(opts: dict[str, Any]) -> set[str]:
    return {h["id"] for h in opts[CONF_HUBS]}


def hub_by_id(opts: dict[str, Any], hub_id: str) -> dict[str, Any]:
    for hub in opts[CONF_HUBS]:
        if hub["id"] == hub_id:
            return hub
    raise ManageError(f"No hub called {hub_id}")


def assign(opts: dict[str, Any], keys: list[str], hub_id: str) -> dict[str, Any]:
    """Pin devices to a hub. Manual placement beats anything automatic."""
    if hub_id not in hub_ids(opts):
        raise ManageError(f"No hub called {hub_id}")
    stamp = dt_util.utcnow().isoformat()
    for key in keys:
        cfg = opts[CONF_DEVICES].setdefault(key, {})
        cfg["hub"] = hub_id
        cfg["placed_at"] = stamp
        cfg["tracked"] = True
        if key in opts[CONF_IGNORED]:
            opts[CONF_IGNORED].remove(key)
    return {"assigned": keys, "hub": hub_id}


def reset_placement(opts: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Forget manual placement so automatic sources (or the router) decide again."""
    for key in keys:
        cfg = opts[CONF_DEVICES].get(key)
        if cfg:
            cfg.pop("hub", None)
            cfg.pop("placed_at", None)
    return {"reset": keys}


def add_hub(
    opts: dict[str, Any],
    name: str,
    hub_type: str = "access_point",
    parent: str | None = None,
    host: str | None = None,
    mac: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    """Create a hub and return its id."""
    if hub_type not in HUB_TYPES:
        hub_type = HUB_OTHER
    parent = parent or ROOT_HUB_ID
    if parent not in hub_ids(opts):
        raise ManageError(f"No hub called {parent}")
    for hub in opts[CONF_HUBS]:
        if (mac and hub.get("mac") == mac) or (host and hub.get("host") == host):
            raise ManageError(f"{hub.get('name')} already uses that address")
    base = slugify_id(name)
    ids = hub_ids(opts)
    hub_id, n = base, 2
    while hub_id in ids:
        hub_id, n = f"{base}_{n}", n + 1
    hub = {"id": hub_id, "name": name.strip() or hub_id, "host": host, "mac": mac, "type": hub_type, "parent": parent, "source": source}
    # A parent picked by a person is kept; automatic hubs let the topology decide.
    hub["parent_locked"] = source == "manual" and parent != ROOT_HUB_ID
    opts[CONF_HUBS].append(hub)
    if mac and mac in opts.get(CONF_DISMISSED_HUBS, []):
        opts[CONF_DISMISSED_HUBS].remove(mac)
    return {"hub": hub_id, "name": hub["name"]}


def update_hub(opts: dict[str, Any], hub_id: str, **fields: Any) -> dict[str, Any]:
    hub = hub_by_id(opts, hub_id)
    if "name" in fields and fields["name"]:
        hub["name"] = fields["name"].strip()
    if "type" in fields and fields["type"] in HUB_TYPES:
        hub["type"] = fields["type"]
    if "host" in fields:
        host = fields["host"] or None
        if host != hub.get("host"):
            # A new address means a different box: the MAC is learned again from it.
            hub["mac"] = None
        hub["host"] = host
    if "parent" in fields and hub_id != ROOT_HUB_ID:
        parent = fields["parent"] or ROOT_HUB_ID
        if parent not in hub_ids(opts):
            raise ManageError(f"No hub called {parent}")
        if creates_cycle(opts[CONF_HUBS], hub_id, parent):
            raise ManageError("A hub cannot connect through itself")
        hub["parent"] = parent
        hub["parent_locked"] = True
    return {"hub": hub_id}


def remove_hub(opts: dict[str, Any], hub_id: str) -> dict[str, Any]:
    if hub_id == ROOT_HUB_ID:
        raise ManageError("The router cannot be removed")
    hub = hub_by_id(opts, hub_id)
    parent = hub.get("parent") or ROOT_HUB_ID
    opts[CONF_HUBS] = [h for h in opts[CONF_HUBS] if h["id"] != hub_id]
    for h in opts[CONF_HUBS]:
        if h.get("parent") == hub_id:
            h["parent"] = parent
    for cfg in opts[CONF_DEVICES].values():
        if cfg.get("hub") == hub_id:
            cfg["hub"] = parent
    # Do not suggest it again.
    if hub.get("mac"):
        dismissed = opts.setdefault(CONF_DISMISSED_HUBS, [])
        if hub["mac"] not in dismissed:
            dismissed.append(hub["mac"])
    return {"removed": hub_id}


def dismiss_hub(opts: dict[str, Any], mac: str) -> dict[str, Any]:
    dismissed = opts.setdefault(CONF_DISMISSED_HUBS, [])
    if mac not in dismissed:
        dismissed.append(mac)
    return {"dismissed": mac}


def creates_cycle(hubs: list[dict[str, Any]], hub_id: str, new_parent: str) -> bool:
    parents = {h["id"]: h.get("parent") for h in hubs}
    parents[hub_id] = new_parent
    seen: set[str] = set()
    cur: str | None = hub_id
    while cur:
        if cur in seen:
            return True
        seen.add(cur)
        cur = parents.get(cur)
    return False
