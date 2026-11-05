"""End to end tests: setup, discovery, status, events, services, options."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
import voluptuous as vol
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


async def test_services_reject_hostnames_and_bad_macs(hass: HomeAssistant, fake_net) -> None:
    """A hostname would reach icmplib and fail every refresh; a bad MAC used to create a phantom 'ip:None' device."""
    fake_net.alive = {GATEWAY}
    entry = _entry("manual")
    await _setup(hass, entry)
    for service, data in (
        ("track_device", {"ip": "example-host"}),
        ("track_device", {"mac": "not-a-mac"}),
        ("track_device", {"ip": "192.0.2.300"}),
        ("ignore_device", {"ip": "example-host"}),
        ("add_hub", {"name": "Shed AP", "ip": "shed-ap"}),
    ):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(DOMAIN, service, data, blocking=True)
    coord = entry.runtime_data
    assert coord.opts["devices"] == {} and [h["id"] for h in coord.opts["hubs"]] == ["gateway"]
    assert "ip:None" not in coord._seen  # noqa: SLF001

    # Common spellings are accepted and stored in one form.
    await hass.services.async_call(DOMAIN, "track_device", {"mac": "00-00-5E-00-53-0B", "ip": " 192.0.2.11 "}, blocking=True)
    assert entry.options["devices"][MAC_B]["host"] == "192.0.2.11"


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


async def test_old_installs_look_names_up_again(hass: HomeAssistant, fake_net) -> None:
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
    await hass.services.async_call(DOMAIN, "scan_now", {}, blocking=True)
    await hass.async_block_till_done()
    assert "Office Mac" in _node_states(hass)


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
