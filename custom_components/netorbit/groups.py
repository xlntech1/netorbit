"""Pick a group of hubs and devices on the map, to change many of them at once (the update_many service).

Pure helpers over the map's nodes (anything with the Node fields), so they are easy to test. The type groups and
connections are the card's own (NO_GROUPS and noSelConn in netorbit-card.js): keep the two in step.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase
import ipaddress
import re
from typing import Any

from .wireless.model import RADIO_OTHER, RADIOS

ROLES = ("hub", "device")

# The card's type groups, matched against the icon (mdi:cctv -> cameras). First match wins.
TYPE_GROUPS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("media", re.compile(r"television|speaker|soundbar|gamepad|nintendo|playstation|xbox|virtual-reality|apple|cast|music|movie|play")),
    ("computers", re.compile(r"laptop|monitor|desktop|cellphone|tablet|watch|server|printer|nas|book")),
    ("cameras", re.compile(r"cctv|camera|doorbell|smoke|alarm|lock|shield")),
    ("home", re.compile(r"chip|thermostat|robot|garage|light|bulb|power|socket|plug|home|fan|purifier|kettle|fridge|sprinkler|pool|ev-|car|bowl|cat|dog|weather|blind|switch")),
)
DEVICE_TYPES = (*(g for g, _ in TYPE_GROUPS), "other")

# Wired, or the radio a node's link details name (wireless/model.py).
CONNECTIONS = ("wired", *RADIOS)


def device_type(icon: str | None) -> str:
    """The card's type group for an icon: media, computers, cameras, home or other."""
    text = str(icon or "")
    for group, pattern in TYPE_GROUPS:
        if pattern.search(text):
            return group
    return "other"


def node_type(node: Any) -> str:
    """A hub's type (access_point, switch, ...), or a device's type group."""
    return (node.hub_type or "other") if node.kind == "hub" else device_type(node.icon)


def connection(node: Any) -> str:
    """How a node reaches the network: the radio its link details name, else wired."""
    radio = (node.wireless or {}).get("radio") if isinstance(node.wireless, dict) else None
    if not radio:
        return "wired"
    return radio if radio in RADIOS else RADIO_OTHER


def parse_field(value: Any) -> tuple[str, str] | None:
    """'Label: value' or 'Label' (any value) or {Label: value} -> (label, value) in lower case; value '' = any."""
    if value is None or value == "":
        return None
    if isinstance(value, Mapping):
        if len(value) != 1:
            raise ValueError("Match one field, like {Group: Critical}")
        label, text = next(iter(value.items()))
    else:
        label, _, text = str(value).partition(":")
    label = " ".join(str(label).split()).lower()
    if not label:
        raise ValueError("Give the field as 'Label: value', or 'Label' for any value")
    text = " ".join(str(text or "").split()).lower()
    return label, "" if text == "*" else text


def _ancestors(node: Any, nodes: Mapping[str, Any]) -> list[str]:
    """The hub ids above a node, nearest first."""
    out: list[str] = []
    cur = node.link
    while cur and cur not in out and len(out) < 64:
        out.append(cur)
        parent = nodes.get(f"hub:{cur}")
        cur = parent.link if parent is not None else None
    return out


def _name_matches(name: str, pattern: str) -> bool:
    name, pattern = name.lower(), pattern.lower().strip()
    if any(c in pattern for c in "*?["):
        return fnmatchcase(name, pattern)
    return pattern in name


def match(
    nodes: Mapping[str, Any],
    *,
    role: Iterable[str] | None = None,
    under: str | None = None,
    direct_only: bool = False,
    types: Iterable[str] | None = None,
    connections: Iterable[str] | None = None,
    field: Any = None,
    name: str | None = None,
    vendor: str | None = None,
    ip_range: str | None = None,
) -> list[str]:
    """Keys of the hubs and devices that meet every condition given. Within one condition any of
    the listed values will do. `under` is a hub id: everything below it, or only what hangs straight off it."""
    roles = set(role or ())
    kinds = set(types or ())
    conns = set(connections or ())
    wanted = parse_field(field)
    net = ipaddress.ip_network(ip_range, strict=False) if ip_range else None
    out: list[str] = []
    for key, node in nodes.items():
        if node.kind not in ROLES:
            continue
        if roles and node.kind not in roles:
            continue
        if under is not None:
            if key == f"hub:{under}":
                continue
            if direct_only and node.link != under:
                continue
            if not direct_only and under not in _ancestors(node, nodes):
                continue
        if kinds and node_type(node) not in kinds:
            continue
        if conns and connection(node) not in conns:
            continue
        if wanted:
            have = {k.lower(): v.lower() for k, v in (node.fields or {}).items()}
            if wanted[0] not in have or (wanted[1] and have[wanted[0]] != wanted[1]):
                continue
        if name and not _name_matches(node.name or "", name):
            continue
        if vendor and vendor.lower().strip() not in (node.vendor or "").lower():
            continue
        if net is not None:
            try:
                if not node.ip or ipaddress.ip_address(node.ip) not in net:
                    continue
            except ValueError:
                continue
        out.append(key)
    return out
