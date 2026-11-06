"""Changing many hubs and devices at once: picking the group (groups.py), the change (manage.update_many) and the
update_many service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import voluptuous as vol
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.netorbit import groups, manage
from custom_components.netorbit.const import DOMAIN

from .conftest import GATEWAY, MAC_B, MAC_C, SUBNET

MAC_D = "00:00:5e:00:53:0d"


def _n(key, kind, name, link=None, **kw):
    base = {"key": key, "kind": kind, "name": name, "link": link, "icon": "mdi:lan-connect", "hub_type": None, "ip": None,
            "wireless": None, "fields": {}, "vendor": None}
    return SimpleNamespace(**{**base, **kw})


def _map():
    nodes = [
        _n("hub:gateway", "hub", "Router", hub_type="router", ip="192.0.2.1"),
        _n("hub:house", "hub", "House AP", "gateway", hub_type="access_point", ip="192.0.2.5", fields={"Group": "Critical"}),
        _n("hub:garage", "hub", "Garage switch", "house", hub_type="switch", ip="192.0.2.6"),
        _n("aa", "device", "Porch cam", "garage", icon="mdi:cctv", ip="192.0.2.21", vendor="Acme Vision"),
        _n("bb", "device", "Hall camera", "house", icon="mdi:doorbell-video", ip="192.0.2.22",
           wireless={"radio": "wifi"}, fields={"group": "critical"}),
        _n("cc", "device", "Living Room TV", "house", icon="mdi:television", ip="192.0.2.40", wireless={"radio": "wifi"}),
        _n("dd", "device", "NAS", "gateway", icon="mdi:nas", ip="192.0.2.50"),
        _n("ee", "device", "Hall sensor", "gateway", icon="mdi:chip", ip="192.0.2.60", wireless={"radio": "zigbee"}),
        _n("internet", "internet", "Internet"),
    ]
    return {n.key: n for n in nodes}


def test_types_and_connections_follow_the_card() -> None:
    assert groups.device_type("mdi:cctv") == "cameras"
    assert groups.device_type("mdi:television-play") == "media"
    assert groups.device_type("mdi:laptop") == "computers"
    assert groups.device_type("mdi:chip") == "home"
    assert groups.device_type("mdi:lan-connect") == "other"
    nodes = _map()
    assert groups.connection(nodes["bb"]) == "wifi"
    assert groups.connection(nodes["aa"]) == "wired"
    assert groups.connection(nodes["ee"]) == "zigbee"
    assert groups.connection(_n("x", "device", "X", wireless={"radio": "lora"})) == "other"
    assert groups.connection(nodes["hub:house"]) == "wired"


def test_match() -> None:
    nodes = _map()
    m = lambda **kw: set(groups.match(nodes, **kw))  # noqa: E731
    # Every hub and device; never the internet node.
    assert len(m()) == 8 and "internet" not in m()
    assert m(role=["hub"]) == {"hub:gateway", "hub:house", "hub:garage"}
    assert m(role=["device"]) == {"aa", "bb", "cc", "dd", "ee"}
    # Under a hub: the whole branch (not the hub itself), or only what hangs straight off it.
    assert m(under="house") == {"hub:garage", "aa", "bb", "cc"}
    assert m(under="house", direct_only=True) == {"hub:garage", "bb", "cc"}
    # A type is a device's type group or a hub's type.
    assert m(types=["cameras"]) == {"aa", "bb"}
    assert m(types=["cameras", "switch"]) == {"aa", "bb", "hub:garage"}
    assert m(connections=["wifi"]) == {"bb", "cc"}
    assert m(connections=["zigbee"]) == {"ee"}
    assert m(connections=["wired"], role=["hub"]) == {"hub:gateway", "hub:house", "hub:garage"}
    # A field matches by label and value, ignoring case; a label alone matches any value.
    assert m(field="Group: Critical") == {"hub:house", "bb"}
    assert m(field={"group": "CRITICAL"}) == {"hub:house", "bb"}
    assert m(field="Group") == {"hub:house", "bb"}
    assert m(field="Group: Spare") == set()
    assert m(name="cam") == {"aa", "bb"}
    assert m(name="*cam") == {"aa"}
    assert m(vendor="acme") == {"aa"}
    assert m(ip_range="192.0.2.16/28") == {"aa", "bb"}
    # Conditions add up.
    assert m(types=["cameras"], under="house", direct_only=True) == {"bb"}
    with pytest.raises(ValueError):
        groups.match(nodes, field=": x")


def _opts():
    return {
        "hubs": [
            {"id": "gateway", "name": "Router", "parent": None},
            {"id": "house", "name": "House AP", "parent": "gateway"},
            {"id": "garage", "name": "Garage switch", "parent": "house"},
        ],
        "devices": {"aa": {"hub": "garage", "tracked": True, "fields": {"Rack": "1"}}},
        "ignored": ["bb"],
    }


def test_update_many_skips_what_a_node_does_not_have() -> None:
    opts = _opts()
    result = manage.update_many(
        opts, [("hub:house", "hub"), ("aa", "device"), ("bb", "device")], sleepy=True, fields={"Group": "Critical"},
    )
    assert result["changed"] == ["hub:house", "aa", "bb"]
    assert result["skipped"] == {"sleepy": ["hub:house"]}
    house = manage.hub_by_id(opts, "house")
    assert house["fields"] == {"Group": "Critical"}
    assert "sleepy" not in house
    # Fields are merged with what is there.
    assert opts["devices"]["aa"]["fields"] == {"Rack": "1", "Group": "Critical"}
    assert opts["devices"]["aa"]["sleepy"] is True
    # A changed device is tracked and no longer ignored, as with update_device.
    assert opts["devices"]["bb"]["tracked"] is True and opts["ignored"] == []


def test_update_many_moves_devices_and_hubs_but_never_loops() -> None:
    opts = _opts()
    result = manage.update_many(
        opts, [("hub:gateway", "hub"), ("hub:house", "hub"), ("hub:garage", "hub"), ("aa", "device"), ("cc", "device")],
        hub="garage",
    )
    # The router never moves, a hub not under itself, and not under a hub below it.
    assert result["skipped"] == {"hub": ["hub:gateway", "hub:house", "hub:garage"]}
    assert result["changed"] == ["cc"]  # aa was there already
    assert opts["devices"]["cc"]["hub"] == "garage" and opts["devices"]["cc"]["placed_at"]
    result = manage.update_many(opts, [("aa", "device"), ("dd", "device")], reset_placement=True)
    assert result["changed"] == ["aa"]
    assert "hub" not in opts["devices"]["aa"]
    # Nothing to change leaves no empty settings behind.
    assert "dd" not in opts["devices"]
    with pytest.raises(manage.ManageError, match="No hub"):
        manage.update_many(opts, [("aa", "device")], hub="nowhere")


def test_update_many_names_the_node_a_value_fails_on() -> None:
    opts = _opts()
    with pytest.raises(manage.ManageError, match="^Porch cam: Field name"):
        manage.update_many(opts, [("aa", "device")], names={"aa": "Porch cam"}, fields={"L" * 41: "x"})


async def test_update_many_service(hass: HomeAssistant, fake_net) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.11", "192.0.2.12", "192.0.2.13"}
    fake_net.arp = {"192.0.2.11": MAC_B, "192.0.2.12": MAC_C, "192.0.2.13": MAC_D}
    entry = MockConfigEntry(
        domain=DOMAIN, title="NetOrbit", unique_id=SUBNET, data={"subnet": SUBNET, "gateway": GATEWAY},
        options={"mode": "auto", "ping_interval": 60, "discovery_interval": 300, "stale_hours": 24, "ignore_random_mac": True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED

    async def call(service, data, response=False):
        result = await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=response)
        await hass.async_block_till_done()
        return result

    await call("add_hub", {"name": "Upstairs", "type": "access_point", "ip": "192.0.2.5"})
    await call("add_hub", {"name": "Attic", "type": "switch", "parent": "Upstairs"})
    await call("assign_device", {"device": [MAC_B], "hub": "Upstairs"})
    await call("update_device", {"device": MAC_C, "hub": "Attic", "icon": "mdi:cctv"})

    def nodes():
        return {s.attributes["label"]: s.attributes for s in hass.states.async_all("sensor")
                if s.attributes.get("netorbit") and s.attributes.get("kind") not in ("summary", "internet")}

    # A preview says what would change and saves nothing.
    before = dict(entry.options)
    got = await call("update_many", {"match": {"under": "Upstairs"}, "sleepy": True, "preview": True}, True)
    assert got["preview"] is True
    assert set(got["matched"]) == {"Attic", "Device 53:0B", "Device 53:0C"}
    assert set(got["changed"]) == {"Device 53:0B", "Device 53:0C"}
    assert got["skipped"] == {"sleepy": ["Attic"]}
    assert dict(entry.options) == before
    got = await call("update_many", {"match": {"under": "Upstairs", "direct_only": True}, "preview": True}, True)
    assert set(got["matched"]) == {"Attic", "Device 53:0B"}

    # Listed and matched together, in one save.
    with patch.object(hass.config_entries, "async_update_entry", wraps=hass.config_entries.async_update_entry) as update:
        got = await call("update_many", {"device": ["hub:upstairs", "192.0.2.13", "nothing here"], "match": {"type": "cameras"},
                                         "sleepy": True, "fields": {"Group": "Critical"}}, True)
    assert update.call_count == 1
    assert set(got["changed"]) == {"Upstairs", "Device 53:0C", "Device 53:0D"}
    assert got["skipped"] == {"sleepy": ["Upstairs"]} and got["not_found"] == ["nothing here"]
    states = nodes()
    assert states["Device 53:0C"]["sleepy"] is True and states["Device 53:0D"]["sleepy"] is True
    assert states["Device 53:0B"]["sleepy"] is False
    assert states["Upstairs"]["fields"] == {"Group": "Critical"} and states["Upstairs"]["notify"] is False

    # The field picks the same group again; the hub change moves devices and skips a hub it would loop through.
    got = await call("update_many", {"match": {"field": "Group: Critical"}, "hub": "Attic"}, True)
    assert set(got["matched"]) == {"Upstairs", "Device 53:0C", "Device 53:0D"}
    assert got["changed"] == ["Device 53:0D"] and got["skipped"] == {"hub": ["Upstairs"]}
    assert nodes()["Device 53:0D"]["link"] == "hub:attic"

    # Nothing to change, or nothing found, is refused with a readable message.
    with pytest.raises(ServiceValidationError, match="Nothing to change"):
        await call("update_many", {"match": {"role": "hub"}})
    with pytest.raises(ServiceValidationError, match="Nothing matches"):
        await call("update_many", {"match": {"name": "no such thing"}, "sleepy": True})
    with pytest.raises(ServiceValidationError, match="not both"):
        await call("update_many", {"device": [MAC_B], "hub": "Attic", "reset_placement": True})
    # Alert settings stay per device (update_device) for now.
    with pytest.raises(vol.Invalid):
        await call("update_many", {"device": [MAC_B], "notify": True})
