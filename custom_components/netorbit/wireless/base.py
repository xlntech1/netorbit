"""What a Wi-Fi plug-in has to provide: a Controller or an AccessPointReader subclass, one module per product family."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiohttp
import voluptuous as vol

from homeassistant.helpers import selector as sel

from .model import WirelessInfo

if TYPE_CHECKING:
    from ..snmp import SnmpClient

AUTH_TOKEN = "token"
AUTH_USER_PASSWORD = "user_password"


class ControllerError(Exception):
    """A controller could not be read. `key` is the options-flow error key: cannot_connect or invalid_auth."""

    def __init__(self, key: str, detail: str = "") -> None:
        super().__init__(detail or key)
        self.key = key


class Controller:
    """A read-only client for one wireless controller. The coordinator only ever sees WirelessInfo."""

    kind: str = ""
    label: str = ""
    note: str = ""  # the least-privilege account the module needs, shown in the options form
    auth: str = AUTH_TOKEN
    default_port: int = 443
    default_verify_ssl: bool = True

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg

    @property
    def id(self) -> str:
        return str(self.cfg.get("id") or f"{self.kind}:{self.host}")

    @property
    def name(self) -> str:
        return str(self.cfg.get("name") or self.host)

    @property
    def host(self) -> str:
        return str(self.cfg.get("host") or "")

    @property
    def port(self) -> int:
        try:
            return int(self.cfg.get("port") or self.default_port)
        except (TypeError, ValueError):
            return self.default_port

    @property
    def verify_ssl(self) -> bool:
        return bool(self.cfg.get("verify_ssl", self.default_verify_ssl))

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"https://{host}" + (f":{self.port}" if self.port != 443 else "")

    @property
    def ssl(self) -> bool | None:
        """aiohttp's per-request ssl argument: None verifies, False does not."""
        return None if self.verify_ssl else False

    @classmethod
    def fields(cls, cfg: dict[str, Any] | None = None) -> dict[Any, Any]:
        """The options-form boxes for this kind, filled from an existing entry when editing.

        A secret box is required on a new entry and optional on an edit (empty keeps the old one).
        """
        cfg = cfg or {}
        out: dict[Any, Any] = {
            vol.Required("host", default=cfg.get("host", "")): str,
            vol.Required("port", default=cfg.get("port", cls.default_port)): sel.NumberSelector(
                sel.NumberSelectorConfig(min=1, max=65535, step=1, mode=sel.NumberSelectorMode.BOX)
            ),
            vol.Required("verify_ssl", default=bool(cfg.get("verify_ssl", cls.default_verify_ssl))): bool,
        }
        secret = sel.TextSelector(sel.TextSelectorConfig(type=sel.TextSelectorType.PASSWORD))
        if cls.auth == AUTH_TOKEN:
            out[vol.Optional("token") if cfg.get("token") else vol.Required("token")] = secret
        else:
            out[vol.Required("username", default=cfg.get("username", ""))] = str
            out[vol.Optional("password") if cfg.get("password") else vol.Required("password")] = secret
        return out

    async def test(self, session: aiohttp.ClientSession) -> str | None:
        """None when the controller answers with this configuration, else the error key."""
        try:
            await self.fetch(session)
        except ControllerError as err:
            return err.key
        return None

    async def fetch(self, session: aiohttp.ClientSession) -> list[WirelessInfo]:
        """Every wireless client the controller knows about right now."""
        raise NotImplementedError


class AccessPointReader:
    """Reads the client list straight from an access point that is a hub on the map, over SNMP.

    Nothing to configure: during a sweep the coordinator asks every hub whose SNMP probe result a
    reader `matches`, with the community that hub answered to.
    """

    kind: str = ""
    label: str = ""

    @staticmethod
    def matches(snmp: dict[str, Any]) -> bool:
        """True for a hub whose SNMP probe result ({descr, object_id, bridge, ...}) is this family's."""
        raise NotImplementedError

    async def read(self, client: SnmpClient, host: str, community: str) -> list[WirelessInfo] | None:
        """The access point's clients right now; None when it could not be read (the map keeps going)."""
        raise NotImplementedError


def has_credentials(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("token") or cfg.get("password"))
