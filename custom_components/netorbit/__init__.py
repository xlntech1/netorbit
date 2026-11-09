"""NetOrbit: a live radial map of your home network."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from . import actions
from .const import (
    CARD_FILENAME,
    CARD_URL,
    DOMAIN,
    HUB_TYPES,
    SERVICE_ADD_HUB,
    SERVICE_ASSIGN,
    SERVICE_CONFIRM_HUB,
    SERVICE_DISMISS_HUB,
    SERVICE_IGNORE,
    SERVICE_IMPORT_LIST,
    SERVICE_REMOVE_HUB,
    SERVICE_RESET,
    SERVICE_SCAN,
    SERVICE_TRACK,
    SERVICE_UPDATE_DEVICE,
    SERVICE_UPDATE_HUB,
    SERVICE_EXPORT,
    SERVICE_IMPORT,
    VERSION,
)
from .coordinator import NetOrbitCoordinator
from .manage import ManageError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type NetOrbitConfigEntry = ConfigEntry[NetOrbitCoordinator]

ENTRY = {vol.Optional("config_entry_id"): cv.string}
DEVICE_LIST = vol.All(cv.ensure_list, [cv.string])
# Free text per hub or device: {label: value}; a null or empty value removes that label.
FIELDS = vol.Schema({cv.string: vol.Any(None, cv.string)})
# "Managed by" and extra fields, accepted by update_device and update_hub.
TEXT_FIELDS = {vol.Optional("managed_by"): cv.string, vol.Optional("fields"): FIELDS}

SCHEMAS: dict[str, vol.Schema] = {
    SERVICE_TRACK: vol.Schema({**ENTRY, vol.Optional("mac"): cv.string, vol.Optional("ip"): cv.string,
                               vol.Optional("name"): cv.string, vol.Optional("icon"): cv.icon,
                               vol.Optional("hub"): cv.string, vol.Optional("sleepy"): cv.boolean}),
    SERVICE_IGNORE: vol.Schema({**ENTRY, vol.Optional("mac"): cv.string, vol.Optional("ip"): cv.string,
                                vol.Optional("device"): cv.string}),
    SERVICE_SCAN: vol.Schema(ENTRY),
    SERVICE_ASSIGN: vol.Schema({**ENTRY, vol.Required("device"): DEVICE_LIST, vol.Required("hub"): cv.string}),
    SERVICE_RESET: vol.Schema({**ENTRY, vol.Required("device"): DEVICE_LIST}),
    SERVICE_ADD_HUB: vol.Schema({**ENTRY, vol.Optional("name"): cv.string, vol.Optional("type", default="access_point"): vol.In(HUB_TYPES),
                                 vol.Optional("parent"): cv.string, vol.Optional("ip"): cv.string,
                                 vol.Optional("mac"): cv.string, vol.Optional("device"): cv.string}),
    SERVICE_REMOVE_HUB: vol.Schema({**ENTRY, vol.Required("hub"): cv.string}),
    SERVICE_EXPORT: vol.Schema(ENTRY),
    SERVICE_IMPORT: vol.Schema({**ENTRY, vol.Required("data"): dict, vol.Optional("replace", default=False): cv.boolean}),
    SERVICE_UPDATE_HUB: vol.Schema({**ENTRY, vol.Required("hub"): cv.string, vol.Optional("name"): cv.string,
                                    vol.Optional("type"): vol.In(HUB_TYPES), vol.Optional("parent"): cv.string, **TEXT_FIELDS}),
    SERVICE_UPDATE_DEVICE: vol.Schema({**ENTRY, vol.Required("device"): cv.string, vol.Optional("name"): cv.string,
                                       vol.Optional("icon"): vol.Any("", cv.icon), vol.Optional("sleepy"): cv.boolean,
                                       vol.Optional("hub"): cv.string, **TEXT_FIELDS}),
    SERVICE_IMPORT_LIST: vol.Schema({**ENTRY, vol.Required("hub"): cv.string, vol.Required("text"): cv.string,
                                     vol.Optional("add_missing", default=True): cv.boolean}),
    SERVICE_CONFIRM_HUB: vol.Schema({**ENTRY, vol.Required("device"): cv.string, vol.Optional("assign"): DEVICE_LIST,
                                     vol.Optional("type"): vol.In(HUB_TYPES), vol.Optional("name"): cv.string}),
    SERVICE_DISMISS_HUB: vol.Schema({**ENTRY, vol.Required("device"): cv.string}),
}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the card, the services and the AI tools once."""
    await _register_card(hass)

    def handler(fn):
        async def _handle(call: ServiceCall) -> ServiceResponse:
            entry, coord = resolve_entry(hass, call.data.get("config_entry_id"))
            args = {k: v for k, v in call.data.items() if k != "config_entry_id"}
            try:
                result = await fn(entry, coord, args)
            except ManageError as err:
                raise ServiceValidationError(str(err)) from err
            return result if call.return_response else None

        return _handle

    async def _export(entry, coord, args):
        return actions.export_config(coord)

    async def _scan(entry, coord, args):
        coord.request_sweep(probe=True)
        await coord.async_refresh()
        return {"devices": len(coord.data.nodes) if coord.data else 0}

    table = {
        SERVICE_TRACK: lambda e, c, a: actions.track(hass, e, c, **a),
        SERVICE_IGNORE: lambda e, c, a: actions.ignore(hass, e, c, **a),
        SERVICE_SCAN: _scan,
        SERVICE_ASSIGN: lambda e, c, a: actions.assign(hass, e, c, a["device"], a["hub"]),
        SERVICE_RESET: lambda e, c, a: actions.reset(hass, e, c, a["device"]),
        SERVICE_ADD_HUB: lambda e, c, a: actions.add_hub(hass, e, c, a.get("name"), a.get("type"), a.get("parent"), a.get("ip"), a.get("mac"), a.get("device")),
        SERVICE_REMOVE_HUB: lambda e, c, a: actions.remove_hub(hass, e, c, a["hub"]),
        SERVICE_EXPORT: _export,
        SERVICE_IMPORT: lambda e, c, a: actions.import_config(hass, e, c, a["data"], a["replace"]),
        SERVICE_UPDATE_HUB: lambda e, c, a: actions.update_hub(hass, e, c, a["hub"], name=a.get("name"), type=a.get("type"), parent=a.get("parent"),
                                                                managed_by=a.get("managed_by"), fields=a.get("fields")),
        SERVICE_UPDATE_DEVICE: lambda e, c, a: actions.update_device(hass, e, c, a["device"], name=a.get("name"), icon=a.get("icon"),
                                                                      sleepy=a.get("sleepy"), hub=a.get("hub"),
                                                                      managed_by=a.get("managed_by"), fields=a.get("fields")),
        SERVICE_IMPORT_LIST: lambda e, c, a: actions.import_list(hass, e, c, a["hub"], a["text"], a["add_missing"]),
        SERVICE_CONFIRM_HUB: lambda e, c, a: actions.confirm_hub(hass, e, c, a["device"], a.get("type"), a.get("name"), a.get("assign")),
        SERVICE_DISMISS_HUB: lambda e, c, a: actions.dismiss_hub(hass, e, c, a["device"]),
    }
    for name, fn in table.items():
        async_register_admin_service(
            hass, DOMAIN, name, handler(fn), SCHEMAS[name], supports_response=SupportsResponse.OPTIONAL
        )

    from .llm_api import async_register_llm_api  # noqa: PLC0415

    async_register_llm_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NetOrbitConfigEntry) -> bool:
    """Set up NetOrbit from a config entry."""
    coordinator = NetOrbitCoordinator(hass, entry)
    entry.runtime_data = coordinator
    # Listen before the first sweep: it may save options itself (a hub's MAC, a DHCP move), and
    # the listener is what clears the "that was me" flag. Registered later, the flag stayed set
    # and the first change a person made afterwards was ignored.
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    await coordinator.async_load()
    # The first refresh draws the map from what NetOrbit saved and pings only those devices.
    # The full network scan runs in the background once setup is done, so Home Assistant's
    # startup doesn't wait for it.
    coordinator.defer_sweep = True
    try:
        await coordinator.async_config_entry_first_refresh()
    finally:
        coordinator.defer_sweep = False
    coordinator.set_scan(notify=False, scanning=True, phase="starting")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(hass, coordinator.async_background_sweep(), f"{DOMAIN} first network scan")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NetOrbitConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _options_updated(hass: HomeAssistant, entry: NetOrbitConfigEntry) -> None:
    coordinator = entry.runtime_data
    coordinator.apply_options(entry)
    if coordinator.internal_update:
        # The change came from NetOrbit itself, which already refreshed.
        coordinator.internal_update = False
        return
    await coordinator.async_refresh()


def resolve_entry(hass: HomeAssistant, entry_id: str | None) -> tuple[NetOrbitConfigEntry, NetOrbitCoordinator]:
    """The loaded NetOrbit entry to act on."""
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
    if not entries:
        raise ServiceValidationError("No loaded NetOrbit entry found")
    if len(entries) > 1 and not entry_id:
        raise ServiceValidationError("More than one NetOrbit entry; pass config_entry_id")
    return entries[0], entries[0].runtime_data


async def _register_card(hass: HomeAssistant) -> None:
    """Serve the bundled card and load it on every dashboard."""
    if hass.http is None:
        return
    path = Path(__file__).parent / "frontend" / CARD_FILENAME
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415

    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), True)])
    if "frontend" not in hass.config.components:
        return
    from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415

    # Version the URL by the file's contents, so browsers pick up a changed card right away,
    # even between releases.
    digest = await hass.async_add_executor_job(_file_digest, path)
    add_extra_js_url(hass, f"{CARD_URL}?v={VERSION}-{digest}")


def _file_digest(path: Path) -> str:
    import hashlib  # noqa: PLC0415

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    except OSError:
        return "0"
