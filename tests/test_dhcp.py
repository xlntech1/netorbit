"""DHCP: things keep their identity when their IP changes, and settings can be exported and restored."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.netorbit.const import DOMAIN

from .conftest import GATEWAY
from .test_dhcp_helpers import advance
from .test_integration import _entry, _node_states, _setup

AP = "00:00:5f:00:53:04"  # example-ok: synthetic test value
TV = "00:00:5e:00:53:10"
NEW = "00:00:5e:00:53:30"


async def test_device_keeps_name_and_hub_when_ip_changes(hass: HomeAssistant, fake_net, freezer) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.6", "192.0.2.10"}
    fake_net.arp = {"192.0.2.6": AP, "192.0.2.10": TV}
    entry = _entry("auto")
    await _setup(hass, entry)
    await hass.services.async_call(DOMAIN, "confirm_hub", {"device": "192.0.2.6", "name": "Hall AP"}, blocking=True)
    await hass.services.async_call(DOMAIN, "assign_device", {"device": "192.0.2.10", "hub": "Hall AP"}, blocking=True)
    await hass.services.async_call(DOMAIN, "track_device", {"mac": TV, "name": "Living Room TV"}, blocking=True)

    # DHCP hands the TV and the AP new addresses; the old ARP entries linger.
    fake_net.alive = {GATEWAY, "192.0.2.66", "192.0.2.77"}
    fake_net.arp = {"192.0.2.6": AP, "192.0.2.66": AP, "192.0.2.10": TV, "192.0.2.77": TV}
    await advance(hass, freezer, 301)

    nodes = _node_states(hass)
    tv = nodes["Living Room TV"].attributes
    assert tv["ip"] == "192.0.2.77" and tv["link"] == "hub:hall_ap" and tv["ip_changes"] == 1
    assert nodes["Living Room TV"].state == "online"
    hall = nodes["Hall AP"].attributes
    assert hall["ip"] == "192.0.2.66" and hall["ip_changes"] == 1
    assert nodes["Hall AP"].state == "online"
    assert next(h for h in entry.options["hubs"] if h["id"] == "hall_ap")["host"] == "192.0.2.66"


async def test_name_set_from_the_card_sticks_across_an_ip_change_and_clears(hass: HomeAssistant, fake_net, freezer) -> None:
    """The card's Name field sets NetOrbit's name by MAC. The sensor follows it, so every later rename shows too, and empty clears."""
    fake_net.alive = {GATEWAY, "192.0.2.10"}
    fake_net.arp = {"192.0.2.10": TV}
    entry = _entry("auto")
    await _setup(hass, entry)
    start = next(s for s in _node_states(hass).values() if s.attributes["mac"] == TV.upper())
    automatic, entity_id = start.attributes["label"], start.entity_id

    await hass.services.async_call(DOMAIN, "track_device", {"mac": TV.upper(), "name": "  Exercise Bike  "}, blocking=True)
    assert entry.options["devices"][TV]["name"] == "Exercise Bike"
    bike = _node_states(hass)["Exercise Bike"]
    # No entity registry name is needed: the sensor itself carries the name.
    assert bike.entity_id == entity_id and bike.attributes["friendly_name"].endswith("Exercise Bike")

    # DHCP hands the bike a new address.
    fake_net.alive = {GATEWAY, "192.0.2.88"}
    fake_net.arp = {"192.0.2.10": TV, "192.0.2.88": TV}
    await advance(hass, freezer, 301)
    bike = _node_states(hass)["Exercise Bike"]
    assert bike.entity_id == entity_id and bike.attributes["ip"] == "192.0.2.88" and bike.attributes["ip_changes"] == 1

    # A later rename by another route (the AI assistant's tool, the update_device action) shows on the sensor at once.
    from custom_components.netorbit import actions  # noqa: PLC0415

    coord = entry.runtime_data
    await actions.update_device(hass, entry, coord, TV, name="Spin Bike")
    spin = _node_states(hass)["Spin Bike"]
    assert spin.entity_id == entity_id and spin.attributes["friendly_name"].endswith("Spin Bike")
    assert entry.options["devices"][TV]["name"] == "Spin Bike"

    # An empty name (or only spaces) clears it, and the device goes back to its automatic name.
    await hass.services.async_call(DOMAIN, "track_device", {"mac": TV.upper(), "name": "   "}, blocking=True)
    assert "name" not in entry.options["devices"][TV]
    back = _node_states(hass)[automatic]
    assert back.entity_id == entity_id and back.attributes["friendly_name"].endswith(automatic)
    assert "name" not in actions.export_config(coord)["devices"].get(TV, {})

    # update_device clears with an empty name the same way, and leaves the name alone when none is given.
    await actions.update_device(hass, entry, coord, TV, name="Rower")
    await actions.update_device(hass, entry, coord, TV, icon="mdi:bike")
    assert entry.options["devices"][TV]["name"] == "Rower"
    await actions.update_device(hass, entry, coord, TV, name="")
    assert "name" not in entry.options["devices"][TV] and entry.options["devices"][TV]["icon"] == "mdi:bike"
    assert _node_states(hass)[automatic].entity_id == entity_id


async def test_lookup_by_ip_finds_the_device_that_has_it_now(hass: HomeAssistant, fake_net, freezer) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.10"}
    fake_net.arp = {"192.0.2.10": TV}
    entry = _entry("auto")
    await _setup(hass, entry)
    coord = entry.runtime_data
    assert coord.resolve_device("192.0.2.10") == TV

    # The TV leaves and DHCP hands its address to a new device. Services and assistant tools given
    # that address act on the new device, and the TV no longer shows the address as its own.
    fake_net.arp = {"192.0.2.10": NEW}
    await advance(hass, freezer, 301)
    assert coord.resolve_device("192.0.2.10") == NEW
    nodes = _node_states(hass)
    assert nodes["Device 53:30"].attributes["ip"] == "192.0.2.10"
    assert nodes["Device 53:10"].attributes["ip"] is None


async def test_device_keeps_its_ip_while_arp_still_lists_its_mac_there(hass: HomeAssistant, fake_net, freezer) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.10"}
    fake_net.arp = {"192.0.2.10": TV}
    entry = _entry("auto")
    await _setup(hass, entry)

    # ARP now lists the address under two MACs at once (a bridge on a second interface, say), the
    # other one last. The TV is still there, so it keeps its address.
    fake_net.arp = {"192.0.2.10": NEW}
    fake_net.arp_also = {"192.0.2.10": [TV]}
    await advance(hass, freezer, 301)
    assert _node_states(hass)["Device 53:10"].attributes["ip"] == "192.0.2.10"


async def test_device_added_by_ip_switches_to_its_mac(hass: HomeAssistant, fake_net, freezer) -> None:
    fake_net.alive = {GATEWAY}
    fake_net.arp = {}
    entry = _entry("manual")
    await _setup(hass, entry)
    await hass.services.async_call(DOMAIN, "track_device", {"ip": "192.0.2.40", "name": "Garden Cam", "sleepy": True}, blocking=True)
    assert "ip:192.0.2.40" in entry.options["devices"]

    fake_net.alive.add("192.0.2.40")
    fake_net.arp = {"192.0.2.40": NEW}
    await advance(hass, freezer, 301)
    assert "ip:192.0.2.40" not in entry.options["devices"]
    assert entry.options["devices"][NEW]["name"] == "Garden Cam"

    # Now DHCP moves it, and it is still the same device.
    fake_net.alive = {GATEWAY, "192.0.2.41"}
    fake_net.arp = {"192.0.2.41": NEW}
    await advance(hass, freezer, 301)
    cams = [s for s in _node_states(hass).values() if s.attributes["label"] == "Garden Cam"]
    assert len(cams) == 1
    cam = cams[0]
    assert cam.attributes["ip"] == "192.0.2.41" and cam.attributes["sleepy"] is True and cam.state == "online"


async def test_export_and_import(hass: HomeAssistant, fake_net) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.6", "192.0.2.10"}
    fake_net.arp = {"192.0.2.6": AP, "192.0.2.10": TV}
    entry = _entry("auto")
    await _setup(hass, entry)
    await hass.services.async_call(DOMAIN, "confirm_hub", {"device": "192.0.2.6", "name": "Hall AP"}, blocking=True)
    await hass.services.async_call(DOMAIN, "assign_device", {"device": TV, "hub": "Hall AP"}, blocking=True)
    await hass.services.async_call(DOMAIN, "track_device", {"mac": TV, "name": "Living Room TV", "icon": "mdi:television"}, blocking=True)
    exported = await hass.services.async_call(DOMAIN, "export_config", {}, blocking=True, return_response=True)
    assert exported["devices"][TV]["name"] == "Living Room TV"
    assert "192.0.2" not in str(exported["devices"])  # devices are keyed by MAC, not IP

    # Wipe everything back to defaults, then restore.
    await hass.services.async_call(DOMAIN, "remove_hub", {"hub": "Hall AP"}, blocking=True)
    await hass.services.async_call(DOMAIN, "reset_placement", {"device": TV}, blocking=True)
    res = await hass.services.async_call(DOMAIN, "import_config", {"data": exported}, blocking=True, return_response=True)
    assert res["hubs"] == 2
    tv = _node_states(hass)["Living Room TV"].attributes
    assert tv["link"] == "hub:hall_ap" and tv["icon"] == "mdi:television"

    bad = await hass.services.async_call(DOMAIN, "export_config", {}, blocking=True, return_response=True)
    bad["netorbit_export"] = 99
    import pytest  # noqa: PLC0415
    from homeassistant.exceptions import ServiceValidationError  # noqa: PLC0415

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "import_config", {"data": bad}, blocking=True)
