"""SNMPv3: a user in Settings reads switches, goes only where the community goes, and stays out of logs and diagnostics."""

from __future__ import annotations

import pysnmp.hlapi.v3arch.asyncio as pysnmp_api
import pytest

from homeassistant.core import HomeAssistant

from custom_components.netorbit.snmp import SnmpClient, SnmpV3User

from .test_auto_and_tools import _network
from .test_integration import _entry, _node_states, _setup

# A made-up user; the switch in _network answers only to what it is given.
V3 = SnmpV3User("netorbit-ro", "sha256", "auth-pass-1", "aes", "priv-pass-1")
V3_FORM = {
    "snmp_v3_user": "netorbit-ro",
    "snmp_v3_auth_protocol": "sha256",
    "snmp_v3_auth_key": "auth-pass-1",
    "snmp_v3_priv_protocol": "aes",
    "snmp_v3_priv_key": "priv-pass-1",
}
SETTINGS = {
    "mode": "auto", "ping_interval": 60, "discovery_interval": 300, "stale_hours": 24,
    "ignore_random_mac": True, "auto_hubs": True, "group_by_type": True, "snmp_enabled": True,
}


async def _settings(hass: HomeAssistant, entry, **extra):
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], {"next_step_id": "settings"})
    return await hass.config_entries.options.async_configure(flow["flow_id"], {**SETTINGS, **extra})


async def _sweeps(hass: HomeAssistant, entry, count: int) -> None:
    for _ in range(count):
        entry.runtime_data.request_sweep()
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


async def test_v3_user_reads_the_switch(hass: HomeAssistant, fake_net) -> None:
    _network(fake_net, community=V3)
    fake_net.dns["192.0.2.2"] = "gs308-core.lan"  # a switch model name: NetOrbit suggests it as a hub
    entry = _entry("auto")
    await _setup(hass, entry)
    assert "core-switch" not in {h["name"] for h in entry.options["hubs"]}

    result = await _settings(hass, entry, snmp_v3=V3_FORM)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    # Stored flat, like the community; the form's section name is not an option.
    assert entry.options["snmp_v3_user"] == "netorbit-ro"
    assert entry.options["snmp_v3_auth_protocol"] == "sha256"
    assert "snmp_v3" not in entry.options

    await _sweeps(hass, entry, 3)  # suggest it, ask it with the user, lay devices out under it
    assert "core-switch" in {h["name"] for h in entry.options["hubs"]}
    # The NAS sits behind the switch: its table was read with the SNMPv3 user.
    assert _node_states(hass)["nas"].attributes["link"] == "hub:core_switch"
    # The user went only to likely network gear, never to the TV or the NAS.
    told = {ip for ip, auth in fake_net.probed if auth == V3}
    assert "192.0.2.2" in told
    assert not told & {"192.0.2.10", "192.0.2.12"}, told


async def test_v3_user_first_then_the_community(hass: HomeAssistant, fake_net) -> None:
    """With both set, a switch that only knows the community still works, and is asked with the user first."""
    _network(fake_net, community="s3cretRO")
    fake_net.dns["192.0.2.2"] = "gs308-core.lan"
    entry = _entry("auto")
    await _setup(hass, entry)
    await _settings(hass, entry, snmp_community="s3cretRO", snmp_v3=V3_FORM)
    await hass.async_block_till_done()
    await _sweeps(hass, entry, 3)

    assert "core-switch" in {h["name"] for h in entry.options["hubs"]}
    assert _node_states(hass)["nas"].attributes["link"] == "hub:core_switch"
    asked = [auth for ip, auth in fake_net.probed if ip == "192.0.2.2" and auth != "public"]
    assert asked[:2] == [V3, "s3cretRO"]


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"snmp_v3_auth_key": "short"}, "snmp_v3_key_short"),
        ({"snmp_v3_priv_key": "short"}, "snmp_v3_key_short"),
        ({"snmp_v3_auth_protocol": "none"}, "snmp_v3_priv_needs_auth"),
    ],
)
async def test_v3_form_checks_what_cannot_work(hass: HomeAssistant, fake_net, change, error) -> None:
    entry = _entry("auto")
    await _setup(hass, entry)
    result = await _settings(hass, entry, snmp_v3={**V3_FORM, **change})
    assert result["type"] == "form"
    assert result["errors"] == {"base": error}
    assert not entry.options.get("snmp_v3_user")


async def test_v3_off_without_a_user_and_no_auth_is_allowed(hass: HomeAssistant, fake_net) -> None:
    entry = _entry("auto")
    await _setup(hass, entry)
    # No user name: SNMPv3 stays off, and what else is in the section isn't checked.
    result = await _settings(hass, entry, snmp_v3={**V3_FORM, "snmp_v3_user": " ", "snmp_v3_auth_key": "x"})
    assert result["type"] == "create_entry"
    assert entry.options["snmp_v3_user"] == ""
    # A user with neither authentication nor privacy (noAuthNoPriv) is valid.
    result = await _settings(
        hass, entry,
        snmp_v3={"snmp_v3_user": "monitor", "snmp_v3_auth_protocol": "none", "snmp_v3_priv_protocol": "none"},
    )
    assert result["type"] == "create_entry"
    assert entry.options["snmp_v3_user"] == "monitor"


def test_v3_user_in_pysnmp_terms() -> None:
    client = SnmpClient(hass=None)
    client._mod = pysnmp_api  # noqa: SLF001
    full = client._auth(V3)  # noqa: SLF001
    assert isinstance(full, pysnmp_api.UsmUserData)
    assert full.userName == "netorbit-ro"
    assert full.authentication_protocol == pysnmp_api.usmHMAC192SHA256AuthProtocol
    assert full.privacy_protocol == pysnmp_api.usmAesCfb128Protocol

    auth_only = client._auth(SnmpV3User("u", "sha", "auth-pass-1", "aes", ""))  # noqa: SLF001
    assert auth_only.authentication_protocol == pysnmp_api.usmHMACSHAAuthProtocol
    assert auth_only.privacy_protocol == pysnmp_api.usmNoPrivProtocol

    bare = client._auth(SnmpV3User("u", "none", "", "none", ""))  # noqa: SLF001
    assert bare.authentication_protocol == pysnmp_api.usmNoAuthProtocol

    v2c = client._auth("s3cretRO")  # noqa: SLF001
    assert isinstance(v2c, pysnmp_api.CommunityData)
    assert v2c.message_processing_model == 1

    # Passphrases never reach a log line.
    assert "auth-pass-1" not in repr(V3) and "priv-pass-1" not in repr(V3)
    assert V3.level == "authPriv"


async def test_diagnostics_leave_the_v3_user_out(hass: HomeAssistant, fake_net) -> None:
    from custom_components.netorbit.diagnostics import async_get_config_entry_diagnostics

    entry = _entry("auto", **V3_FORM)
    await _setup(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = repr(diag)
    for secret in ("netorbit-ro", "auth-pass-1", "priv-pass-1"):
        assert secret not in text
    assert diag["settings"]["snmp_v3_user_set"] is True
    assert diag["settings"]["snmp_v3_auth_protocol"] == "sha256"
