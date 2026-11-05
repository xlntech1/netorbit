"""Wi-Fi plug-ins: the shared record, the controller parser and how access point readers are picked."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant

from custom_components.netorbit import wireless
from custom_components.netorbit.snmp import GRANDSTREAM_OID_PREFIX, ProbeResult
from custom_components.netorbit.wireless import (
    AccessPointReader,
    WirelessInfo,
    band_for_channel,
    band_from_text,
    controller_for,
    merge,
    quality_from,
    reader_for,
)
from custom_components.netorbit.wireless.fortigate import FortiGateController, parse_client
from custom_components.netorbit.wireless.grandstream import GrandstreamAccessPoint

from .conftest import GATEWAY
from .test_integration import _entry, _node_states, _setup


def test_bands_and_quality() -> None:
    assert band_for_channel(6) == "2.4 GHz" and band_for_channel(44) == "5 GHz" and band_for_channel("x") is None
    assert band_from_text("802.11ax-5G") == "5 GHz" and band_from_text("802.11ax-2.4G") == "2.4 GHz"
    assert band_from_text("ng") == "2.4 GHz" and band_from_text("na") == "5 GHz" and band_from_text("6E") == "6 GHz"
    assert band_from_text("") is None
    assert quality_from(-61, None) == 78 and quality_from(-100, None) == 0 and quality_from(-40, None) == 100
    assert quality_from(-58, 212) == 83 and quality_from(None, None) is None


def test_merge_later_sources_win_field_by_field() -> None:
    first = WirelessInfo(ssid="Home", band="5 GHz", source="a")
    second = WirelessInfo(ap_name="Hall AP", channel=44, signal_dbm=-61, snr=37, source="b")
    assert merge(first, second).as_dict() == {"radio": "wifi", "ap_name": "Hall AP", "ssid": "Home", "band": "5 GHz", "channel": 44,
                                              "signal_dbm": -61, "snr": 37, "quality": 78, "source": "b"}
    assert merge(None, None) is None


def test_fortigate_parser() -> None:
    aps = {"FP231FTF20001234": {"serial": "FP231FTF20001234", "name": "Hall AP", "board_mac": "00:00:5e:00:53:a1"}}
    client = {"mac": "00:00:5E:00:53:10", "ip": "192.0.2.10", "host": "living-room-tv", "wtp_id": "FP231FTF20001234",
              "wtp_name": "Hall AP", "vap": "home-iot", "ssid": "IoT", "signal": -58, "noise": -95, "snr": 37,
              "channel": 44, "radio_type": "802.11ax-5G", "os": "Roku"}
    info = parse_client(client, aps, "Edge", "2026-10-31T00:00:00+00:00")
    assert info.mac == "00:00:5e:00:53:10" and info.ap_mac == "00:00:5e:00:53:a1" and info.ap_name == "Hall AP"
    assert info.ssid == "IoT" and info.band == "5 GHz" and info.channel == 44
    assert info.signal_dbm == -58 and info.snr == 37 and info.quality == 84 and info.source == "fortigate:Edge"
    # Without the AP list the name still carries; a client with no MAC is skipped; a missing radio_type falls back to the channel.
    bare = parse_client({"mac": "00:00:5e:00:53:11", "wtp_name": "Den AP", "channel": 6, "signal": -70}, {}, "Edge", "t")
    assert bare.ap_mac is None and bare.ap_name == "Den AP" and bare.band == "2.4 GHz" and bare.quality == 60
    assert parse_client({"wtp_name": "Den AP"}, {}, "Edge", "t") is None


def test_plugins_are_picked_from_the_registry() -> None:
    assert isinstance(controller_for({"kind": "fortigate", "host": "192.0.2.1"}), FortiGateController)
    assert controller_for({"kind": "nothing-like-it"}) is None
    gwn = {"descr": "Grandstream GWN7660", "object_id": f"{GRANDSTREAM_OID_PREFIX}.1.1", "bridge": False}
    assert isinstance(reader_for(gwn), GrandstreamAccessPoint)
    # A switch is read as a switch, whoever made it; other access points have no reader yet.
    assert reader_for({**gwn, "bridge": True}) is None
    assert reader_for({"descr": "Some AP", "object_id": "1.3.6.1.4.1.41112.1.6", "bridge": False}) is None
    assert reader_for(None) is None


AP_IP = "192.0.2.6"
PHONE_MAC = "00:00:5e:00:53:40"


@pytest.mark.parametrize("answer", [[PHONE_MAC], None])
async def test_a_new_access_point_plugin_needs_no_coordinator_change(
    hass: HomeAssistant, fake_net, monkeypatch: pytest.MonkeyPatch, answer
) -> None:
    """An access point family is one AccessPointReader in AP_READERS: the coordinator asks every hub it matches."""
    asked: list[tuple[str, str]] = []

    class ExampleAccessPoint(AccessPointReader):
        kind = "example"
        label = "Example access point"

        @staticmethod
        def matches(snmp):
            return str(snmp.get("descr") or "").startswith("Example AP")

        async def read(self, client, host, community):
            asked.append((host, community))
            return None if answer is None else [WirelessInfo(mac=m, source=f"example:{host}") for m in answer]

    monkeypatch.setattr(wireless, "AP_READERS", (ExampleAccessPoint,))
    fake_net.alive = {GATEWAY, AP_IP, "192.0.2.40"}
    fake_net.arp = {AP_IP: "00:00:5e:00:53:06", "192.0.2.40": PHONE_MAC}
    fake_net.snmp = {AP_IP: ("public", ProbeResult(descr="Example AP 2", name="ap-1", bridge=False))}
    hubs = [{"id": "gateway", "name": "Router", "type": "router", "parent": None},
            {"id": "hall_ap", "name": "Hall AP", "type": "access_point", "parent": "gateway", "host": AP_IP}]
    entry = _entry("auto", hubs=hubs, snmp_enabled=True)
    await _setup(hass, entry)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert (AP_IP, "public") in asked
    phone = next(s for s in _node_states(hass).values() if str(s.attributes.get("mac")).lower() == PHONE_MAC)
    if answer:
        assert phone.attributes["link"] == "hub:hall_ap" and phone.attributes["placement"] == "snmp"
    else:
        # An access point that could not be read leaves the map as it was.
        assert phone.attributes["link"] == "hub:gateway" and phone.attributes["placement"] == "none"


async def test_wifi_controller_places_clients_under_their_access_points(hass: HomeAssistant, fake_net, aioclient_mock) -> None:
    """A controller places each client under the access point it reports: by the AP's MAC, else by the hub's name."""
    import json  # noqa: PLC0415

    from homeassistant.data_entry_flow import FlowResultType  # noqa: PLC0415

    from custom_components.netorbit.diagnostics import async_get_config_entry_diagnostics  # noqa: PLC0415

    from .conftest import MAC_B, MAC_C  # noqa: PLC0415
    from .test_integration import _summary  # noqa: PLC0415

    fake_net.alive = {GATEWAY, AP_IP, "192.0.2.10", "192.0.2.11"}
    fake_net.arp = {AP_IP: "00:00:5e:00:53:a1", "192.0.2.10": MAC_B, "192.0.2.11": MAC_C}
    aioclient_mock.get("https://192.0.2.1/api/v2/monitor/wifi/client", json={"results": [
        {"mac": MAC_B.upper(), "ip": "192.0.2.10", "wtp_id": "FP231F", "wtp_name": "Hall AP", "ssid": "IoT",
         "signal": -61, "snr": 37, "channel": 44, "radio_type": "802.11ax-5G"},
        # The den AP has no address on the map, so only its name ties it to a hub.
        {"mac": MAC_C.upper(), "ip": "192.0.2.11", "wtp_id": "FP221E", "wtp_name": "Den AP", "channel": 6},
    ]})
    aioclient_mock.get("https://192.0.2.1/api/v2/monitor/wifi/managed_ap", json={"results": [{"serial": "FP231F", "name": "Hall AP", "board_mac": "00:00:5e:00:53:a1"}]})
    hubs = [{"id": "gateway", "name": "Router", "type": "router", "parent": None},
            {"id": "hall_ap", "name": "Hall AP", "type": "access_point", "parent": "gateway", "host": AP_IP},
            {"id": "den_ap", "name": "Den AP", "type": "access_point", "parent": "gateway"}]
    entry = _entry("auto", hubs=hubs, wifi_controllers=[{"id": "c1", "kind": "fortigate", "name": "Edge", "host": "192.0.2.1", "port": 443, "verify_ssl": False, "token": "secret-token"}])
    await _setup(hass, entry)
    nodes = {str(s.attributes.get("mac")).lower(): s for s in _node_states(hass).values()}
    assert nodes[MAC_B].attributes["link"] == "hub:hall_ap" and nodes[MAC_B].attributes["placement"] == "controller"
    assert nodes[MAC_C].attributes["link"] == "hub:den_ap" and nodes[MAC_C].attributes["placement"] == "controller"
    assert "controller" in _summary(hass).attributes["sources"]
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == "Bearer secret-token"

    # The token and address never reach diagnostics.
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["settings"]["wifi_controllers"] == [{"kind": "fortigate", "has_credentials": True}]
    assert "secret-token" not in json.dumps(diag) and "192.0.2.1\"" not in json.dumps(diag["settings"])

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
    # Editing with the token box left empty keeps the saved token; removing goes through the same step.
    second = entry.options["wifi_controllers"][1]["id"]
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "edit_controller"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"controller": second})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"name": "Second AP", "host": "192.0.2.2", "port": 443, "verify_ssl": False})
    assert flow["type"] is FlowResultType.CREATE_ENTRY and entry.options["wifi_controllers"][1]["token"] == "good"
    assert entry.options["wifi_controllers"][1]["name"] == "Second AP"
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "edit_controller"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"controller": second})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"name": "Second AP", "host": "192.0.2.2", "port": 443, "verify_ssl": False, "remove": True})
    assert flow["type"] is FlowResultType.CREATE_ENTRY and [c["name"] for c in entry.options["wifi_controllers"]] == ["Edge"]

    # A controller saved by a build with a plug-in that is not installed here can only be removed; the flow survives it.
    hass.config_entries.async_update_entry(entry, options={**entry.options, "wifi_controllers": [*entry.options["wifi_controllers"], {"id": "x1", "kind": "nope", "name": "Odd", "host": "192.0.2.9"}]})
    await hass.async_block_till_done()
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "edit_controller"})
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"controller": "x1"})
    assert flow["type"] is FlowResultType.FORM and flow["errors"] == {"base": "unknown_kind"}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"remove": True})
    assert flow["type"] is FlowResultType.CREATE_ENTRY and [c["name"] for c in entry.options["wifi_controllers"]] == ["Edge"]
