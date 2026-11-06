"""End to end tests: setup, discovery, status, events, services, options."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.netorbit.const import DOMAIN

from .conftest import GATEWAY, MAC_A, MAC_B, MAC_C, SUBNET


def _entry(mode: str = "auto", **opts) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="NetOrbit",
        unique_id=SUBNET,
        data={"subnet": SUBNET, "gateway": GATEWAY},
        options={"mode": mode, "ping_interval": 60, "discovery_interval": 300, "stale_hours": 24, "ignore_random_mac": True, **opts},
    )


def _node_states(hass: HomeAssistant) -> dict[str, object]:
    out = {}
    for st in hass.states.async_all("sensor"):
        if st.attributes.get("netorbit") and st.attributes.get("kind") not in ("summary", "internet"):
            out[st.attributes["label"]] = st
    return out


def _summary(hass: HomeAssistant):
    return next(s for s in hass.states.async_all("sensor") if s.attributes.get("kind") == "summary")


async def _advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    for _ in range(3):
        await hass.async_block_till_done(wait_background_tasks=True)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set the entry up and wait for the first network scan, which runs in the background."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED


async def test_user_flow(hass: HomeAssistant, fake_net) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"subnet": "192.0.2.0/24", "gateway": "203.0.113.1", "mode": "auto", "ping_interval": 60}
    )
    assert result["errors"] == {"gateway": "gateway_outside"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"subnet": "10.0.0.0/16", "gateway": "10.0.0.1", "mode": "auto", "ping_interval": 60}  # example-ok: synthetic test value
    )
    assert result["errors"] == {"subnet": "subnet_too_large"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"subnet": "192.0.2.9/24", "gateway": GATEWAY, "mode": "manual", "ping_interval": 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"subnet": "192.0.2.0/24", "gateway": GATEWAY}
    assert result["options"]["mode"] == "manual"
    assert result["options"]["hubs"][0]["id"] == "gateway"
    # The "setup finished" dialog points people to adding the card.
    assert result["description_placeholders"]["guide_url"].endswith("#add-the-map-to-a-dashboard")
    await hass.async_block_till_done()

    dup = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    dup = await hass.config_entries.flow.async_configure(
        dup["flow_id"], {"subnet": "192.0.2.0/24", "gateway": GATEWAY, "mode": "auto", "ping_interval": 60}
    )
    assert dup["type"] is FlowResultType.ABORT


async def test_auto_mode_discovers_and_tracks(hass: HomeAssistant, fake_net) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.10", "192.0.2.11", "192.0.2.12"}
    fake_net.arp = {GATEWAY: "00:00:5e:00:53:01", "192.0.2.10": MAC_A, "192.0.2.11": MAC_B, "192.0.2.12": MAC_C}
    events = async_capture_events(hass, "netorbit_new_device")
    await _setup(hass, _entry("auto"))

    nodes = _node_states(hass)
    # router hub + two real MACs; the randomized MAC is ignored, the gateway is not a device
    assert set(nodes) == {"Router", "Device 53:0B", "Device 53:0C"}
    assert all(s.state == "online" for s in nodes.values())
    assert nodes["Device 53:0B"].attributes["link"] == "hub:gateway"
    assert nodes["Router"].attributes["kind"] == "hub"
    assert nodes["Router"].attributes["link"] is None
    assert _summary(hass).state == "2"
    # the very first sweep fills the map quietly
    assert events == []


async def test_new_device_event_and_manual_mode(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    events = async_capture_events(hass, "netorbit_new_device")
    entry = _entry("manual")
    await _setup(hass, entry)

    # manual mode: found but not tracked, listed as new
    assert set(_node_states(hass)) == {"Router"}
    new = _summary(hass).attributes["new_devices"]
    assert [d["mac"] for d in new] == [MAC_B.upper()]

    # a device joins later and the next sweep announces it
    fake_net.alive.add("192.0.2.12")
    fake_net.arp["192.0.2.12"] = MAC_C
    await _advance(hass, freezer, 301)
    assert [e.data["mac"] for e in events] == [MAC_C]

    # track one through the service, ignore the other
    await hass.services.async_call(DOMAIN, "track_device", {"mac": MAC_B, "name": "Kitchen Speaker", "sleepy": True}, blocking=True)
    await hass.services.async_call(DOMAIN, "ignore_device", {"mac": MAC_C}, blocking=True)
    await hass.async_block_till_done()
    nodes = _node_states(hass)
    assert "Kitchen Speaker" in nodes
    assert nodes["Kitchen Speaker"].attributes["sleepy"] is True
    assert nodes["Kitchen Speaker"].attributes["icon"] == "mdi:speaker"
    assert _summary(hass).attributes["new_devices"] == []
    assert entry.options["ignored"] == [MAC_C]


async def test_stale_and_recovered(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    stale = async_capture_events(hass, "netorbit_device_stale")
    back = async_capture_events(hass, "netorbit_device_recovered")
    await _setup(hass, _entry("auto"))
    name = "Device 53:0B"

    fake_net.alive.discard("192.0.2.11")
    await _advance(hass, freezer, 61)
    assert _node_states(hass)[name].state == "recent"

    await _advance(hass, freezer, 25 * 3600)
    assert _node_states(hass)[name].state == "stale"
    assert [e.data["name"] for e in stale] == [name]

    fake_net.alive.add("192.0.2.11")
    await _advance(hass, freezer, 61)
    assert _node_states(hass)[name].state == "online"
    assert [e.data["name"] for e in back] == [name]


async def test_address_handed_to_another_device(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """A device that leaves doesn't stay online because DHCP gave its address to another one."""
    mac_d = "00:00:5e:00:53:0d"
    fake_net.alive = {GATEWAY, "192.0.2.11", "192.0.2.12"}
    fake_net.arp = {"192.0.2.11": MAC_B, "192.0.2.12": mac_d}
    await _setup(hass, _entry("auto"))
    gone, moved = "Device 53:0B", "Device 53:0D"
    assert _node_states(hass)[gone].state == "online"

    # B leaves; D renews onto B's old address before the next sweep
    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": mac_d}
    await _advance(hass, freezer, 61)
    assert _node_states(hass)[gone].state == "recent"

    # the sweep finds D at its new address
    await _advance(hass, freezer, 300)
    assert _node_states(hass)[moved].state == "online"
    assert _node_states(hass)[moved].attributes["ip"] == "192.0.2.11"
    assert _node_states(hass)[gone].state == "recent"


async def test_hub_mac_not_in_arp_still_answers(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """A hub given a MAC that ARP never shows at its address (its base MAC, next to the LAN MAC
    ARP has) still gets credit for its replies."""
    fake_net.alive = {GATEWAY, "192.0.2.20"}
    fake_net.arp = {"192.0.2.20": "00:00:5e:00:53:21"}
    await _setup(hass, _entry("auto"))
    await hass.services.async_call(
        DOMAIN, "add_hub", {"name": "Hallway AP", "type": "access_point", "ip": "192.0.2.20", "mac": "00:00:5e:00:53:20"}, blocking=True
    )
    await _advance(hass, freezer, 61)
    assert _node_states(hass)["Hallway AP"].state == "online"
    await _advance(hass, freezer, 25*3600)
    assert _node_states(hass)["Hallway AP"].state == "online"


async def test_device_mac_not_in_arp_still_answers(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """A device tracked by a MAC that ARP never shows at its address (entered by hand for a
    device behind a MAC-NAT repeater, where ARP has the repeater's MAC) still gets credit."""
    fake_net.alive = {GATEWAY}
    await _setup(hass, _entry("auto"))
    await hass.services.async_call(DOMAIN, "track_device", {"mac": MAC_B, "ip": "192.0.2.30", "name": "Garden Cam"}, blocking=True)

    fake_net.alive.add("192.0.2.30")
    fake_net.arp = {"192.0.2.30": MAC_C}
    await _advance(hass, freezer, 61)
    assert _node_states(hass)["Garden Cam"].state == "online"
    # a sweep finds the repeater's MAC at that address; the camera keeps its credit
    await _advance(hass, freezer, 301)
    await _advance(hass, freezer, 25*3600)
    assert _node_states(hass)["Garden Cam"].state == "online"


async def test_addressless_hubs_follow_what_is_behind_them(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """Hubs with no address can't be pinged, so they take their status from the devices behind
    them (through other addressless hubs too) instead of turning stale once the window passes."""
    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    stale = async_capture_events(hass, "netorbit_device_stale")
    hubs = [
        {"id": "shop", "name": "Shop Switch", "host": None, "type": "switch", "parent": "gateway"},
        {"id": "bed", "name": "Bed Switch", "host": None, "type": "switch", "parent": "shop"},
        {"id": "spare", "name": "Spare Switch", "host": None, "type": "switch", "parent": "gateway"},
    ]
    await _setup(hass, _entry("manual", hubs=hubs, devices={MAC_B: {"name": "Desk PC", "hub": "bed"}}))

    def states() -> dict[str, str]:
        nodes = _node_states(hass)
        return {n: nodes[n].state for n in ("Desk PC", "Bed Switch", "Shop Switch", "Spare Switch")}

    assert states() == {"Desk PC": "online", "Bed Switch": "online", "Shop Switch": "online", "Spare Switch": "unknown"}

    # well past the window, still green while the device behind them answers
    await _advance(hass, freezer, 25 * 3600)
    assert states() == {"Desk PC": "online", "Bed Switch": "online", "Shop Switch": "online", "Spare Switch": "unknown"}
    assert stale == []

    # once everything behind them is stale, so are they
    fake_net.alive.discard("192.0.2.11")
    await _advance(hass, freezer, 61)
    assert states()["Shop Switch"] == "recent"
    await _advance(hass, freezer, 25 * 3600)
    assert states() == {"Desk PC": "stale", "Bed Switch": "stale", "Shop Switch": "stale", "Spare Switch": "unknown"}
    assert sorted(e.data["name"] for e in stale) == ["Bed Switch", "Desk PC", "Shop Switch"]


async def test_addressless_hub_recovers_with_the_device_behind_it(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """The hub goes stale with its only device and fires the recovered event when it comes back."""
    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    back = async_capture_events(hass, "netorbit_device_recovered")
    hubs = [{"id": "shop", "name": "Shop Switch", "host": None, "type": "switch", "parent": "gateway"}]
    await _setup(hass, _entry("manual", hubs=hubs, devices={MAC_B: {"name": "Desk PC", "hub": "shop"}}))

    fake_net.alive.discard("192.0.2.11")
    await _advance(hass, freezer, 61)
    await _advance(hass, freezer, 25 * 3600)
    nodes = _node_states(hass)
    assert (nodes["Desk PC"].state, nodes["Shop Switch"].state) == ("stale", "stale")
    assert back == []

    fake_net.alive.add("192.0.2.11")
    await _advance(hass, freezer, 61)
    nodes = _node_states(hass)
    assert (nodes["Desk PC"].state, nodes["Shop Switch"].state) == ("online", "online")
    assert sorted(e.data["name"] for e in back) == ["Desk PC", "Shop Switch"]


async def test_addressless_hub_with_only_a_sleeping_device_stays_grey(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """A sleepy device that is off doesn't count, so the hub is unknown (grey) and never stale."""
    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    stale = async_capture_events(hass, "netorbit_device_stale")
    hubs = [{"id": "shop", "name": "Shop Switch", "host": None, "type": "switch", "parent": "gateway"}]
    await _setup(hass, _entry("manual", hubs=hubs, devices={MAC_B: {"name": "Shop TV", "hub": "shop", "sleepy": True}}))
    nodes = _node_states(hass)
    assert (nodes["Shop TV"].state, nodes["Shop Switch"].state) == ("online", "online")

    # the TV goes to sleep and stays off past the window
    fake_net.alive.discard("192.0.2.11")
    await _advance(hass, freezer, 61)
    nodes = _node_states(hass)
    assert (nodes["Shop TV"].state, nodes["Shop Switch"].state) == ("recent", "unknown")
    await _advance(hass, freezer, 25 * 3600)
    nodes = _node_states(hass)
    assert (nodes["Shop TV"].state, nodes["Shop Switch"].state) == ("stale", "unknown")
    assert stale == []


async def test_addressless_hub_follows_a_pingable_hub_behind_it(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """A hub that has an address is judged by its ping, and the addressless hub above it follows it."""
    fake_net.alive = {GATEWAY, "192.0.2.5"}
    hubs = [
        {"id": "shop", "name": "Shop Switch", "host": None, "type": "switch", "parent": "gateway"},
        {"id": "ap", "name": "Shop AP", "host": "192.0.2.5", "type": "access_point", "parent": "shop"},
    ]
    stale = async_capture_events(hass, "netorbit_device_stale")
    back = async_capture_events(hass, "netorbit_device_recovered")
    await _setup(hass, _entry("manual", hubs=hubs))

    def states() -> tuple[str, str]:
        nodes = _node_states(hass)
        return nodes["Shop AP"].state, nodes["Shop Switch"].state

    assert states() == ("online", "online")
    await _advance(hass, freezer, 25 * 3600)
    assert states() == ("online", "online")

    fake_net.alive.discard("192.0.2.5")
    await _advance(hass, freezer, 61)
    assert states() == ("recent", "recent")
    await _advance(hass, freezer, 25 * 3600)
    assert states() == ("stale", "stale")
    assert sorted(e.data["name"] for e in stale) == ["Shop AP", "Shop Switch"]

    fake_net.alive.add("192.0.2.5")
    await _advance(hass, freezer, 61)
    assert states() == ("online", "online")
    assert sorted(e.data["name"] for e in back) == ["Shop AP", "Shop Switch"]


async def test_options_hubs_and_devices(hass: HomeAssistant, fake_net) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.5", "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    entry = _entry("auto")
    await _setup(hass, entry)

    # add an access point hub
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] is FlowResultType.MENU
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "add_hub"})
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"name": "Hallway AP", "host": "192.0.2.5", "type": "access_point", "parent": "gateway"}
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert [h["id"] for h in entry.options["hubs"]] == ["gateway", "hallway_ap"]

    # move the device under the AP and rename it
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "edit_device"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"device": MAC_B})
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"name": "Office Printer", "hub": "hallway_ap", "sleepy": False}
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    nodes = _node_states(hass)
    assert nodes["Office Printer"].attributes["link"] == "hub:hallway_ap"
    assert nodes["Office Printer"].attributes["icon"] == "mdi:printer"
    assert nodes["Hallway AP"].attributes["link"] == "hub:gateway"
    assert nodes["Hallway AP"].state == "online"

    # a hub cannot become its own ancestor
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "edit_hub"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"hub": "gateway"})
    assert flow["step_id"] == "edit_hub_details"
    assert "parent" not in flow["data_schema"].schema

    # removing the hub moves its device back to the router
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "edit_hub"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"hub": "hallway_ap"})
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"name": "Hallway AP", "type": "access_point", "parent": "gateway", "remove": True}
    )
    await hass.async_block_till_done()
    nodes = _node_states(hass)
    assert "Hallway AP" not in nodes
    assert nodes["Office Printer"].attributes["link"] == "hub:gateway"


async def test_stop_tracking_removes_entity(hass: HomeAssistant, fake_net) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    entry = _entry("auto")
    await _setup(hass, entry)
    reg = er.async_get(hass)
    before = {e.entity_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}

    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "edit_device"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"device": MAC_B})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"hub": "gateway", "sleepy": False, "stop_tracking": True})
    await hass.async_block_till_done()
    after = {e.entity_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
    assert len(after) == len(before) - 1
    assert "Device 53:0B" not in _node_states(hass)


async def test_diagnostics_redacts(hass: HomeAssistant, fake_net) -> None:
    from custom_components.netorbit.diagnostics import async_get_config_entry_diagnostics

    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    entry = _entry("auto", snmp_community="hunter2secret", dismissed_hubs=["00:00:5e:00:53:99"])
    await _setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "hunter2secret" not in repr(diag)
    assert "53:99" not in repr(diag)
    text = repr(diag)
    assert "192.0.2" not in text
    assert MAC_B not in text.lower()
    assert diag["nodes"]


async def test_unload(hass: HomeAssistant, fake_net) -> None:
    entry = _entry("auto")
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_names_from_other_integrations(hass: HomeAssistant, fake_net) -> None:
    """Real names win over MAC-named duplicates; device trackers and ping sensors fill the gaps."""
    from homeassistant.helpers import device_registry as dr

    fake_net.alive = {GATEWAY, "192.0.2.10", "192.0.2.11", "192.0.2.12"}
    fake_net.arp = {GATEWAY: "00:00:5e:00:53:01", "192.0.2.10": MAC_A, "192.0.2.11": MAC_B, "192.0.2.12": MAC_C}
    MAC_D, MAC_E = "00:00:5e:00:53:0d", "00:00:5e:00:53:0e"
    fake_net.alive |= {"192.0.2.13", "192.0.2.14"}
    fake_net.arp.update({"192.0.2.13": MAC_D, "192.0.2.14": MAC_E})

    dev_reg = dr.async_get(hass)
    # The same speaker under two integrations: one named after its MAC, one with a real name.
    for title, name in (("Renderer", MAC_E), ("Speaker", "Pool")):
        other = MockConfigEntry(domain="test", title=title)
        other.add_to_hass(hass)
        dev_reg.async_get_or_create(
            config_entry_id=other.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, MAC_E)}, name=name
        )
    # A device tracker that knows MAC_B by name, and one named after its MAC (useless).
    hass.states.async_set("device_tracker.thermostat", "home", {"mac": MAC_B, "friendly_name": "Hall Thermostat"})
    hass.states.async_set("device_tracker.x", "home", {"mac": MAC_C, "friendly_name": f"{MAC_C} Acme 53:0C"})
    # A ping sensor the user set up by hand for 192.0.2.13.
    ping = MockConfigEntry(domain="ping", title="192.0.2.13", data={}, options={"host": "192.0.2.13"})
    ping.add_to_hass(hass)
    er.async_get(hass).async_get_or_create("binary_sensor", "ping", "p13", config_entry=ping, suggested_object_id="ping_nas")
    hass.states.async_set("binary_sensor.ping_nas", "on", {"friendly_name": "Ping NAS"})

    # Bonjour fills in a name when nothing else in Home Assistant knows the device.
    fake_net.mdns["192.0.2.12"] = "Alexs-MacBook.local."

    await _setup(hass, _entry("auto"))
    names = set(_node_states(hass))
    assert {"Pool", "Hall Thermostat", "NAS", "Alexs MacBook"} <= names
    assert not any(":" in n and n.count(":") >= 5 for n in names)


async def test_old_installs_look_names_up_again(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """A device checked recently by an older version gets looked up again by the new one."""
    fake_net.alive = {GATEWAY, "192.0.2.12"}
    fake_net.arp = {GATEWAY: "00:00:5e:00:53:01", "192.0.2.12": MAC_C}
    entry = _entry("auto")
    await _setup(hass, entry)
    assert "Device 53:0C" in _node_states(hass)

    # Now the device would answer Bonjour, but its record looks like an older version
    # checked it a moment ago (no lookup version stored).
    fake_net.mdns["192.0.2.12"] = "Office-Mac.local."
    for rec in entry.runtime_data._seen.values():
        rec.pop("dns_version", None)
    await _advance(hass, freezer, 301)
    assert "Office Mac" in _node_states(hass)


async def test_scan_now_looks_names_up_again(hass: HomeAssistant, fake_net) -> None:
    """A scan asked for by hand reads every device's DNS name again, however recently it was checked,
    so records added to the DNS server show on the map at once."""
    fake_net.alive = {GATEWAY, "192.0.2.12"}
    fake_net.arp = {GATEWAY: "00:00:5e:00:53:01", "192.0.2.12": MAC_C}
    await _setup(hass, _entry("auto", prefer_dns_names=True))
    assert "Device 53:0C" in _node_states(hass)

    fake_net.dns["192.0.2.12"] = "deck-cam.home.example."
    await hass.services.async_call(DOMAIN, "scan_now", {}, blocking=True)
    await hass.async_block_till_done()
    assert "deck-cam" in _node_states(hass)


def _internet(hass: HomeAssistant):
    return next((s for s in hass.states.async_all("sensor") if s.attributes.get("kind") == "internet"), None)


async def test_internet_check(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """The Internet node is online while a public resolver answers, turns red (stale) after two
    missed rounds while the router still answers, and is unknown when the router is down too."""
    fake_net.alive = {GATEWAY, "1.1.1.1", "8.8.8.8"}
    down = async_capture_events(hass, "netorbit_internet_down")
    up = async_capture_events(hass, "netorbit_internet_up")
    stale = async_capture_events(hass, "netorbit_device_stale")
    await _setup(hass, _entry("auto"))
    assert _internet(hass).state == "online"

    fake_net.alive -= {"1.1.1.1", "8.8.8.8"}
    await _advance(hass, freezer, 61)
    assert _internet(hass).state == "online"  # one missed round is not an outage
    await _advance(hass, freezer, 61)
    assert _internet(hass).state == "stale"
    assert len(down) == 1 and stale == []

    fake_net.alive.discard(GATEWAY)
    await _advance(hass, freezer, 61)
    assert _internet(hass).state == "unknown"  # router down too: can't tell

    fake_net.alive |= {GATEWAY, "8.8.8.8"}
    await _advance(hass, freezer, 61)
    assert _internet(hass).state == "online"
    assert len(up) == 0  # it went stale -> unknown -> online, not stale -> online

    fake_net.alive -= {"8.8.8.8"}
    await _advance(hass, freezer, 61)
    await _advance(hass, freezer, 61)
    fake_net.alive.add("1.1.1.1")
    await _advance(hass, freezer, 61)
    assert len(down) == 2 and len(up) == 1


async def test_internet_check_can_be_turned_off(hass: HomeAssistant, fake_net) -> None:
    fake_net.alive = {GATEWAY, "1.1.1.1"}
    pinged: list[str] = []
    real = fake_net.multiping

    async def spy(addresses, **kwargs):
        pinged.extend(addresses)
        return await real(addresses, **kwargs)

    fake_net.multiping = spy
    await _setup(hass, _entry("auto", check_internet=False))
    assert _internet(hass) is None
    assert "1.1.1.1" not in pinged and "8.8.8.8" not in pinged


async def test_prefer_dns_names(hass: HomeAssistant, fake_net) -> None:
    """With the option on, the network's own name beats other integrations, and replaces made-up hub names."""
    fake_net.alive = {GATEWAY, "192.0.2.11", "192.0.2.12"}
    fake_net.arp = {GATEWAY: "00:00:5e:00:53:01", "192.0.2.11": MAC_B, "192.0.2.12": MAC_C}
    fake_net.dns = {GATEWAY: "edge.home.example.", "192.0.2.11": "printer-hall.home.example"}
    hass.states.async_set("device_tracker.p", "home", {"mac": MAC_B, "friendly_name": "Hall Printer"})
    entry = _entry("auto")
    await _setup(hass, entry)
    nodes = _node_states(hass)
    assert {"Router", "Hall Printer", "Device 53:0C"} <= set(nodes)
    assert nodes["Hall Printer"].attributes["fqdn"] == "printer-hall.home.example"
    assert nodes["Hall Printer"].attributes["hostname"] == "printer-hall"
    assert nodes["Router"].attributes["fqdn"] == "edge.home.example"
    assert nodes["Device 53:0C"].attributes["fqdn"] is None

    hass.config_entries.async_update_entry(entry, options={**entry.options, "prefer_dns_names": True})
    await hass.async_block_till_done()
    nodes = _node_states(hass)
    assert {"edge", "printer-hall", "Device 53:0C"} <= set(nodes)
    assert "Router" not in nodes and "Hall Printer" not in nodes

    # A name a person typed is kept, for hubs and devices alike.
    await hass.services.async_call(DOMAIN, "update_hub", {"hub": "gateway", "name": "Core router"}, blocking=True)
    await hass.services.async_call(DOMAIN, "update_device", {"device": MAC_B, "name": "Lobby printer"}, blocking=True)
    await hass.async_block_till_done()
    nodes = _node_states(hass)
    assert {"Core router", "Lobby printer"} <= set(nodes)
    assert next(h for h in entry.options["hubs"] if h["id"] == "gateway")["name_auto"] is False

    # Clearing the device name goes back to the DNS name.
    await hass.services.async_call(DOMAIN, "update_device", {"device": MAC_B, "name": ""}, blocking=True)
    await hass.async_block_till_done()
    assert "printer-hall" in _node_states(hass)


async def test_import_checks_managed_by_and_fields(hass: HomeAssistant, fake_net) -> None:
    """An import goes through the same checks as the services: bad values are left out, the rest applies, and a
    broken value already saved can't make the refreshes fail."""
    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    entry = _entry("auto")
    await _setup(hass, entry)
    coord = entry.runtime_data
    await hass.services.async_call(DOMAIN, "update_hub", {"hub": "gateway", "managed_by": "ISP", "fields": {"Model": "Edge 1"}}, blocking=True)
    await hass.async_block_till_done()

    exported = await hass.services.async_call(DOMAIN, "export_config", {}, blocking=True, return_response=True)
    exported["hubs"][0]["fields"] = "abc"  # not a mapping: the hub keeps the fields it has
    exported["hubs"][0]["managed_by"] = "m" * 501  # too long: the hub keeps its Managed by
    many = {f"F{i}": "v" for i in range(25)}
    exported["devices"][MAC_B] = {"name": "Printer", "managed_by": ["a", "list"], "fields": {"Ok": "fine", "Long": "y" * 501, "Rack": 2, **many}}
    res = await hass.services.async_call(DOMAIN, "import_config", {"data": exported}, blocking=True, return_response=True)
    await hass.async_block_till_done()
    # hub fields + hub managed_by + device managed_by + Long + Rack + the 6 fields past the limit of 20
    assert res["skipped"] == 11

    hub = next(h for h in entry.options["hubs"] if h["id"] == "gateway")
    assert hub["fields"] == {"Model": "Edge 1"} and hub["managed_by"] == "ISP"
    dev = entry.options["devices"][MAC_B]
    assert dev["name"] == "Printer" and "managed_by" not in dev
    assert list(dev["fields"]) == ["Ok", *[f"F{i}" for i in range(19)]]

    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.last_update_success
    assert _node_states(hass)["Printer"].attributes["fields"]["Ok"] == "fine"

    # A broken value saved some other way (an edit by hand) doesn't stop the refreshes either.
    opts = {**entry.options, "hubs": [{**h, "fields": "abc", "managed_by": 5} if h["id"] == "gateway" else h for h in entry.options["hubs"]]}
    hass.config_entries.async_update_entry(entry, options=opts)
    await hass.async_block_till_done()
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.last_update_success
    router = _node_states(hass)["Router"].attributes
    assert router["fields"] == {} and router["managed_by"] is None


async def test_managed_by_and_fields(hass: HomeAssistant, fake_net) -> None:
    """Free text on devices and hubs: services, attributes, export/import and the options flow."""
    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    entry = _entry("auto")
    await _setup(hass, entry)

    await hass.services.async_call(
        DOMAIN, "update_device",
        {"device": MAC_B, "managed_by": "https://192.0.2.1/", "fields": {"Location": "Hall", "Owner": " Sam "}},
        blocking=True,
    )
    await hass.async_block_till_done()
    dev = _node_states(hass)["Device 53:0B"]
    assert dev.attributes["managed_by"] == "https://192.0.2.1/"
    assert dev.attributes["fields"] == {"Location": "Hall", "Owner": "Sam"}

    # An empty value removes a field, an empty managed_by removes it.
    await hass.services.async_call(
        DOMAIN, "update_device", {"device": MAC_B, "managed_by": "", "fields": {"Owner": None, "Serial": "ABC"}}, blocking=True
    )
    await hass.async_block_till_done()
    dev = _node_states(hass)["Device 53:0B"]
    assert dev.attributes["managed_by"] is None
    assert dev.attributes["fields"] == {"Location": "Hall", "Serial": "ABC"}

    # Hubs take the same fields.
    await hass.services.async_call(DOMAIN, "update_hub", {"hub": "gateway", "managed_by": "ISP", "fields": {"Model": "Edge 1"}}, blocking=True)
    await hass.async_block_till_done()
    assert _node_states(hass)["Router"].attributes["fields"] == {"Model": "Edge 1"}
    assert _node_states(hass)["Router"].attributes["managed_by"] == "ISP"

    # Too much text is refused with a readable error.
    with pytest.raises(Exception, match="500"):
        await hass.services.async_call(DOMAIN, "update_device", {"device": MAC_B, "fields": {"Notes": "x" * 501}}, blocking=True)

    # Exports carry the text; an import restores it.
    exported = await hass.services.async_call(DOMAIN, "export_config", {}, blocking=True, return_response=True)
    assert exported["devices"][MAC_B]["fields"] == {"Location": "Hall", "Serial": "ABC"}
    assert exported["hubs"][0]["fields"] == {"Model": "Edge 1"} and exported["hubs"][0]["managed_by"] == "ISP"
    await hass.services.async_call(DOMAIN, "update_device", {"device": MAC_B, "fields": {"Location": None, "Serial": None}}, blocking=True)
    await hass.async_block_till_done()
    assert _node_states(hass)["Device 53:0B"].attributes["fields"] == {}
    await hass.services.async_call(DOMAIN, "import_config", {"data": exported}, blocking=True)
    await hass.async_block_till_done()
    assert _node_states(hass)["Device 53:0B"].attributes["fields"] == {"Location": "Hall", "Serial": "ABC"}

    # The options flow edits the same text, one "Label: value" per line, and replaces the whole list.
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "edit_device"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"device": MAC_B})
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"hub": "gateway", "sleepy": False, "fields_text": "no separator"}
    )
    assert flow["type"] is FlowResultType.FORM and flow["errors"] == {"fields_text": "bad_fields"}
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"hub": "gateway", "sleepy": False, "managed_by": "Core switch", "fields_text": "Rack: 2\nNotes: spare"}
    )
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    dev = _node_states(hass)["Device 53:0B"]
    assert dev.attributes["managed_by"] == "Core switch"
    assert dev.attributes["fields"] == {"Rack": "2", "Notes": "spare"}

    # Diagnostics only count them.
    from homeassistant.components.diagnostics import REDACTED  # noqa: F401, PLC0415
    from custom_components.netorbit.diagnostics import async_get_config_entry_diagnostics  # noqa: PLC0415

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert all("Rack" not in str(n) and "Core switch" not in str(n) for n in diag["nodes"])
    assert any(n["field_count"] == 2 and n["has_managed_by"] for n in diag["nodes"])


async def test_wireless_from_entities_trackers_and_links(hass: HomeAssistant, fake_net) -> None:
    """Radio details come from the device's own sensors, from tracker attributes, and from linked sensors."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er  # noqa: PLC0415

    fake_net.alive = {GATEWAY, "192.0.2.11", "192.0.2.12"}
    fake_net.arp = {"192.0.2.11": MAC_B, "192.0.2.12": MAC_C}
    # A Zigbee relay whose Home Assistant device carries the LAN MAC (a Wi-Fi/Zigbee bridge) with LQI and RSSI sensors.
    other = MockConfigEntry(domain="zha", title="ZHA")
    other.add_to_hass(hass)
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    # The router's integration lists the same MAC as a client first, with a name but no sensors: the
    # sensors on the second device entry must still be found.
    router = MockConfigEntry(domain="unifi", title="UniFi")
    router.add_to_hass(hass)
    dev_reg.async_get_or_create(config_entry_id=router.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, MAC_B)}, name="Relay")
    dev = dev_reg.async_get_or_create(config_entry_id=other.entry_id, identifiers={("zha", "relay")}, connections={(dr.CONNECTION_NETWORK_MAC, MAC_B)}, name="Relay (ZHA)")
    dev_reg.async_update_device(dev.id, name_by_user="Relay")  # a name a person typed wins over the router's automatic one
    ent_reg.async_get_or_create("sensor", "zha", "relay-lqi", device_id=dev.id, suggested_object_id="relay_lqi", original_name="LQI")
    ent_reg.async_get_or_create("sensor", "zha", "relay-rssi", device_id=dev.id, suggested_object_id="relay_rssi",
                                original_device_class="signal_strength", unit_of_measurement="dBm")
    hass.states.async_set("sensor.relay_lqi", "212")
    hass.states.async_set("sensor.relay_rssi", "-58", {"unit_of_measurement": "dBm", "device_class": "signal_strength"})
    # A phone the UniFi-style tracker knows: SSID, band and AP, no signal.
    hass.states.async_set("device_tracker.phone", "home", {"mac": MAC_C, "friendly_name": "Phone", "essid": "Home", "radio": "na", "ap_mac": "00:00:5e:00:53:a1"})
    entry = _entry("auto")
    await _setup(hass, entry)
    nodes = _node_states(hass)
    relay = nodes["Relay"].attributes["wireless"]
    assert relay["radio"] == "zigbee" and relay["lqi"] == 212 and relay["signal_dbm"] == -58 and relay["quality"] == 83
    assert relay["source"] == "entity:sensor.relay_rssi" and relay["at"]
    phone = nodes["Phone"].attributes["wireless"]
    assert phone["radio"] == "wifi" and phone["ssid"] == "Home" and phone["band"] == "5 GHz" and phone["ap_mac"] == "00:00:5e:00:53:a1"
    assert "signal_dbm" not in phone and phone["source"] == "tracker:device_tracker.phone"
    assert nodes["Router"].attributes["wireless"] is None

    # A sensor linked by hand wins over the automatic match, and the sensor's new value shows on the next round.
    hass.states.async_set("sensor.custom_rssi", "-85", {"unit_of_measurement": "dBm"})
    await hass.services.async_call(DOMAIN, "update_device", {"device": MAC_B, "entities": {"signal": "sensor.custom_rssi"}}, blocking=True)
    await hass.async_block_till_done()
    relay = _node_states(hass)["Relay"]
    assert relay.attributes["linked_entities"] == {"signal": "sensor.custom_rssi"}
    assert relay.attributes["wireless"]["signal_dbm"] == -85 and relay.attributes["wireless"]["source"] == "linked:sensor.custom_rssi"
    assert relay.attributes["wireless"]["lqi"] == 212  # the relay's own LQI still shows
    with pytest.raises(Exception, match="role"):
        await hass.services.async_call(DOMAIN, "update_device", {"device": MAC_B, "entities": {"colour": "sensor.x"}}, blocking=True)
    await hass.services.async_call(DOMAIN, "update_device", {"device": MAC_B, "entities": {"signal": ""}}, blocking=True)
    await hass.async_block_till_done()
    relay = _node_states(hass)["Relay"]
    assert relay.attributes["linked_entities"] is None and relay.attributes["wireless"]["signal_dbm"] == -58

    # Exports carry the links; the options flow sets them with entity pickers.
    await hass.services.async_call(DOMAIN, "update_device", {"device": MAC_B, "entities": {"lqi": "sensor.relay_lqi"}}, blocking=True)
    exported = await hass.services.async_call(DOMAIN, "export_config", {}, blocking=True, return_response=True)
    assert exported["devices"][MAC_B]["entities"] == {"lqi": "sensor.relay_lqi"}
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "edit_device"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"device": MAC_B})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"hub": "gateway", "sleepy": False, "signal_entity": "sensor.custom_rssi"})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert _node_states(hass)["Relay"].attributes["linked_entities"] == {"signal": "sensor.custom_rssi"}  # the form shows everything: lqi was cleared


async def test_wifi_controller_signal_and_placement(hass: HomeAssistant, fake_net, aioclient_mock) -> None:
    """A FortiGate controller gives signal details and places clients under the access point it names."""
    import json  # noqa: PLC0415

    fake_net.alive = {GATEWAY, "192.0.2.6", "192.0.2.10"}
    fake_net.arp = {"192.0.2.6": "00:00:5e:00:53:a1", "192.0.2.10": MAC_B}
    aioclient_mock.get("https://192.0.2.1/api/v2/monitor/wifi/client", json={"results": [
        {"mac": MAC_B.upper(), "ip": "192.0.2.10", "wtp_id": "FP231F", "wtp_name": "Hall AP", "ssid": "IoT",
         "signal": -61, "snr": 37, "channel": 44, "radio_type": "802.11ax-5G"},
    ]})
    aioclient_mock.get("https://192.0.2.1/api/v2/monitor/wifi/managed_ap", json={"results": [{"serial": "FP231F", "name": "Hall AP", "board_mac": "00:00:5e:00:53:a1"}]})
    hubs = [{"id": "gateway", "name": "Router", "type": "router", "parent": None},
            {"id": "hall_ap", "name": "Hall AP", "type": "access_point", "parent": "gateway", "host": "192.0.2.6"}]
    entry = _entry("auto", hubs=hubs, wifi_controllers=[{"id": "c1", "kind": "fortigate", "name": "Edge", "host": "192.0.2.1", "port": 443, "verify_ssl": False, "token": "secret-token"}])
    await _setup(hass, entry)
    dev = _node_states(hass)["Device 53:0B"]
    w = dev.attributes["wireless"]
    assert w["source"] == "fortigate:Edge" and w["ap_name"] == "Hall AP" and w["ap_mac"] == "00:00:5e:00:53:a1"
    assert w["ssid"] == "IoT" and w["band"] == "5 GHz" and w["channel"] == 44 and w["signal_dbm"] == -61 and w["snr"] == 37
    assert dev.attributes["link"] == "hub:hall_ap" and dev.attributes["placement"] == "controller"
    assert "controller" in _summary(hass).attributes["sources"]
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer secret-token"

    # The token and address never reach diagnostics.
    from custom_components.netorbit.diagnostics import async_get_config_entry_diagnostics  # noqa: PLC0415

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["settings"]["wifi_controllers"] == [{"kind": "fortigate", "has_credentials": True}]
    assert "secret-token" not in json.dumps(diag) and "192.0.2.1" not in json.dumps(diag["settings"])
    assert any(n["has_wireless"] and n["wireless_source"] == "fortigate" for n in diag["nodes"])

    # Adding a controller through the options flow tests it first: a refused token is an error, a good one is saved.
    aioclient_mock.get("https://192.0.2.2/api/v2/monitor/wifi/client", status=401)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "add_controller"})
    assert flow["step_id"] == "add_controller"
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"kind": "fortigate"})
    assert flow["step_id"] == "controller_details"
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"name": "Second", "host": "192.0.2.2", "port": 443, "verify_ssl": False, "token": "bad"})
    assert flow["type"] is FlowResultType.FORM and flow["errors"] == {"base": "invalid_auth"}
    aioclient_mock.clear_requests()
    aioclient_mock.get("https://192.0.2.2/api/v2/monitor/wifi/client", json={"results": []})
    aioclient_mock.get("https://192.0.2.2/api/v2/monitor/wifi/managed_ap", json={"results": []})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"name": "Second", "host": "192.0.2.2", "port": 443, "verify_ssl": False, "token": "good"})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert [c["name"] for c in entry.options["wifi_controllers"]] == ["Edge", "Second"]
    assert entry.options["wifi_controllers"][1]["token"] == "good" and entry.options["wifi_controllers"][1]["id"].startswith("fortigate_")
    # Removing it through the edit step.
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "edit_controller"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"controller": entry.options["wifi_controllers"][1]["id"]})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"name": "Second", "host": "192.0.2.2", "port": 443, "verify_ssl": False, "remove": True})
    assert flow["type"] is FlowResultType.CREATE_ENTRY and [c["name"] for c in entry.options["wifi_controllers"]] == ["Edge"]


async def test_weak_signal_is_flagged_after_a_while(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """A signal below good notes weak_since at once and sets `weak` after weak_signal_minutes; a good reading clears both."""
    from homeassistant.helpers import device_registry as dr, entity_registry as er  # noqa: PLC0415

    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    other = MockConfigEntry(domain="esphome", title="ESPHome")
    other.add_to_hass(hass)
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    dev = dev_reg.async_get_or_create(config_entry_id=other.entry_id, identifiers={("esphome", "plug")}, connections={(dr.CONNECTION_NETWORK_MAC, MAC_B)}, name="Plug")
    ent_reg.async_get_or_create("sensor", "esphome", "plug-rssi", device_id=dev.id, suggested_object_id="plug_rssi",
                                original_device_class="signal_strength", unit_of_measurement="dBm")
    rssi = {"unit_of_measurement": "dBm", "device_class": "signal_strength"}
    hass.states.async_set("sensor.plug_rssi", "-86", rssi)
    entry = _entry("auto", weak_signal_minutes=10)
    await _setup(hass, entry)

    def wireless():
        return _node_states(hass)["Plug"].attributes["wireless"]

    w = wireless()
    assert w["signal_dbm"] == -86 and w["weak"] is False and w["weak_since"]
    since = w["weak_since"]
    assert _summary(hass).attributes["weak_signal"] == 0 and _summary(hass).attributes["weak_after_minutes"] == 10
    await _advance(hass, freezer, 5 * 60 + 1)
    assert wireless()["weak"] is False and wireless()["weak_since"] == since  # the clock keeps its start
    # A reading just over the threshold is jitter, not recovery: the clock keeps running.
    hass.states.async_set("sensor.plug_rssi", "-78", rssi)
    await _advance(hass, freezer, 61)
    assert wireless()["signal_dbm"] == -78 and wireless()["weak_since"] == since
    hass.states.async_set("sensor.plug_rssi", "-86", rssi)
    await _advance(hass, freezer, 5 * 60 + 1)
    assert wireless()["weak"] is True and wireless()["weak_since"] == since
    assert _summary(hass).attributes["weak_signal"] == 1
    # A device that never dipped does not start a clock at -78 either.
    assert "weak_since" not in (_node_states(hass)["Router"].attributes.get("wireless") or {})

    # A clearly good reading clears the flag and the clock; the next dip starts a new clock.
    hass.states.async_set("sensor.plug_rssi", "-70", rssi)
    await _advance(hass, freezer, 61)
    assert "weak" not in wireless() and "weak_since" not in wireless()
    assert _summary(hass).attributes["weak_signal"] == 0
    hass.states.async_set("sensor.plug_rssi", "-86", rssi)
    await _advance(hass, freezer, 61)
    assert wireless()["weak"] is False and wireless()["weak_since"] != since

    # 0 minutes in Settings never colours anything, though the popup can still say since when.
    hass.config_entries.async_update_entry(entry, options={**entry.options, "weak_signal_minutes": 0})
    await hass.async_block_till_done()
    await _advance(hass, freezer, 30 * 60)
    assert wireless()["weak"] is False and wireless()["weak_since"]


async def test_offline_and_online_alerts(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """Flagged nodes fire offline after offline_after_rounds missed rounds and online on the first answer; others never."""
    fake_net.alive = {GATEWAY, "192.0.2.11", "192.0.2.12"}
    fake_net.arp = {GATEWAY: "00:00:5e:00:53:01", "192.0.2.11": MAC_B, "192.0.2.12": MAC_C}
    entry = _entry("auto")
    await _setup(hass, entry)
    offline = async_capture_events(hass, "netorbit_device_offline")
    online = async_capture_events(hass, "netorbit_device_online")
    await hass.services.async_call(DOMAIN, "update_device", {"device": MAC_B, "notify": True}, blocking=True)
    await hass.services.async_call(DOMAIN, "update_hub", {"hub": "gateway", "notify": True}, blocking=True)
    await hass.async_block_till_done()
    nodes = _node_states(hass)
    assert nodes["Device 53:0B"].attributes["notify"] is True and nodes["Router"].attributes["notify"] is True
    assert nodes["Device 53:0C"].attributes["notify"] is False

    # Both flagged nodes and the unflagged one stop answering: two misses are not enough, the third is.
    fake_net.alive = set()
    await _advance(hass, freezer, 60)
    await _advance(hass, freezer, 60)
    assert offline == []
    await _advance(hass, freezer, 60)
    assert sorted(e.data["name"] for e in offline) == ["Device 53:0B", "Router"]
    ev = next(e for e in offline if e.data["name"] == "Device 53:0B")
    assert ev.data["ip"] == "192.0.2.11" and ev.data["mac"] == MAC_B and ev.data["kind"] == "device"
    assert ev.data["hub"] == "gateway" and ev.data["missed_rounds"] == 3 and ev.data["last_seen"]
    await _advance(hass, freezer, 60)
    assert len(offline) == 2  # staying down fires nothing more

    # The device answers again: one online event; the router stays down.
    fake_net.alive = {"192.0.2.11"}
    await _advance(hass, freezer, 60)
    assert [e.data["name"] for e in online] == ["Device 53:0B"]
    # A single missed round after that is not an outage.
    fake_net.alive = set()
    await _advance(hass, freezer, 60)
    fake_net.alive = {"192.0.2.11"}
    await _advance(hass, freezer, 60)
    assert len(offline) == 2 and len(online) == 1

    # The window is a setting: with 1 round, the next miss fires at once.
    hass.config_entries.async_update_entry(entry, options={**entry.options, "offline_after_rounds": 1})
    await hass.async_block_till_done()
    fake_net.alive = set()
    await _advance(hass, freezer, 60)
    assert len(offline) == 3 and offline[-1].data["missed_rounds"] == 1

    # Export and import carry the flags.
    exported = await hass.services.async_call(DOMAIN, "export_config", {}, blocking=True, return_response=True)
    assert exported["devices"][MAC_B]["notify"] is True and exported["hubs"][0]["notify"] is True
    await hass.services.async_call(DOMAIN, "update_device", {"device": MAC_B, "notify": False}, blocking=True)
    await hass.async_block_till_done()
    assert _node_states(hass)["Device 53:0B"].attributes["notify"] is False
    await hass.services.async_call(DOMAIN, "import_config", {"data": exported}, blocking=True)
    await hass.async_block_till_done()
    assert _node_states(hass)["Device 53:0B"].attributes["notify"] is True


async def test_port_scan(hass: HomeAssistant, fake_net, freezer: FrozenDateTimeFactory) -> None:
    """Port discovery runs on its schedule, on demand, remembers ports that closed, and is settable in the options flow."""
    fake_net.alive = {GATEWAY, "192.0.2.11", "192.0.2.12"}
    fake_net.arp = {GATEWAY: "00:00:5e:00:53:01", "192.0.2.11": MAC_B, "192.0.2.12": MAC_C}
    fake_net.ports = {GATEWAY: {53, 80, 443}, "192.0.2.11": {22, 8123, 65000}, "192.0.2.12": set()}
    entry = _entry("auto", port_scan_interval=6)
    await _setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)

    nodes = _node_states(hass)
    dev = nodes["Device 53:0B"]
    assert dev.attributes["ports"] == [22, 8123]  # 65000 is not in the common set
    assert dev.attributes["ports_named"] == ["22/ssh", "8123/home-assistant"]
    assert dev.attributes["ports_closed"] == [] and dev.attributes["ports_checked"]
    assert nodes["Router"].attributes["ports"] == [53, 80, 443]  # hubs are scanned too by default
    assert nodes["Device 53:0C"].attributes["ports"] == [] and nodes["Device 53:0C"].attributes["ports_checked"]
    assert sorted(fake_net.port_scans) == sorted([GATEWAY, "192.0.2.11", "192.0.2.12"])
    first_check = dev.attributes["ports_checked"]

    # Not again before the interval has passed; then the whole round runs once more.
    fake_net.ports["192.0.2.11"] = {22}
    await _advance(hass, freezer, 3600)
    assert _node_states(hass)["Device 53:0B"].attributes["ports"] == [22, 8123]
    await _advance(hass, freezer, 6 * 3600)
    dev = _node_states(hass)["Device 53:0B"]
    assert dev.attributes["ports"] == [22]
    assert dev.attributes["ports_closed"] == ["8123/home-assistant"]
    assert dev.attributes["ports_checked"] != first_check

    # On demand for one device: the answer lists what is open, and a port back again leaves the closed list.
    fake_net.ports["192.0.2.11"] = {22, 8123}
    fake_net.port_scans.clear()
    result = await hass.services.async_call(DOMAIN, "scan_ports", {"device": [MAC_B]}, blocking=True, return_response=True)
    assert result == {"scanned": 1, "open": {"Device 53:0B": [22, 8123]}}
    assert fake_net.port_scans == ["192.0.2.11"]
    await hass.async_block_till_done()
    assert _node_states(hass)["Device 53:0B"].attributes["ports_closed"] == []
    # Hubs by id, name or key; unknown names are refused.
    result = await hass.services.async_call(DOMAIN, "scan_ports", {"device": ["hub:gateway", "Router"]}, blocking=True, return_response=True)
    assert result["scanned"] == 1 and result["open"] == {"Router": [53, 80, 443]}
    with pytest.raises(Exception, match="nope"):
        await hass.services.async_call(DOMAIN, "scan_ports", {"device": ["nope"]}, blocking=True)
    # With no device, everything online is scanned in the background.
    fake_net.port_scans.clear()
    result = await hass.services.async_call(DOMAIN, "scan_ports", {}, blocking=True, return_response=True)
    assert result == {"scheduled": 3}
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(fake_net.port_scans) == 3

    # The map tool lists open ports; diagnostics only count them.
    from custom_components.netorbit.actions import network_map  # noqa: PLC0415
    from custom_components.netorbit.diagnostics import async_get_config_entry_diagnostics  # noqa: PLC0415

    assert next(d for d in network_map(entry.runtime_data)["devices"] if d["mac"].lower() == MAC_B)["open_ports"] == [22, 8123]
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert sorted(n["port_count"] for n in diag["nodes"]) == [0, 0, 2, 3]  # the internet node has none

    # Settings: a custom list must parse; hubs can be left out; the new set is scanned right away.
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "settings"})
    base = {
        "mode": "auto", "ping_interval": 60, "discovery_interval": 300, "stale_hours": 24, "ignore_random_mac": True,
        "auto_hubs": True, "group_by_type": True, "check_internet": True, "prefer_dns_names": False, "snmp_enabled": False,
        "port_scan_interval": 1, "port_scan_ports": "custom", "port_scan_custom": "22, 80-70", "port_scan_hubs": False,
    }
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], base)
    assert flow["type"] is FlowResultType.FORM and flow["errors"] == {"port_scan_custom": "bad_ports"}
    fake_net.port_scans.clear()
    fake_net.ports["192.0.2.11"] = {22, 8123, 65000}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {**base, "port_scan_custom": "65000"})
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["port_scan_custom"] == "65000" and entry.options["port_scan_hubs"] is False
    await _advance(hass, freezer, 60)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert sorted(fake_net.port_scans) == ["192.0.2.11", "192.0.2.12"]  # the router sat this one out
    # Ports outside the new set keep their last result instead of being called closed.
    dev = _node_states(hass)["Device 53:0B"]
    assert dev.attributes["ports_named"] == ["22/ssh", "8123/home-assistant", "65000"] and dev.attributes["ports_closed"] == []


async def test_port_scan_is_off_by_default(hass: HomeAssistant, fake_net) -> None:
    fake_net.alive = {GATEWAY, "192.0.2.11"}
    fake_net.arp = {"192.0.2.11": MAC_B}
    fake_net.ports = {"192.0.2.11": {22}}
    await _setup(hass, _entry("auto"))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert fake_net.port_scans == []
    dev = _node_states(hass)["Device 53:0B"]
    assert dev.attributes["ports"] == [] and dev.attributes["ports_checked"] is None
