"""Wi-Fi plug-ins: which access point each wireless client is on.

Two kinds, one module per product family:

* Controller: a Wi-Fi controller added under Configure (address and a read-only token or login).
  NetOrbit asks it every ping round for its clients and the access point each one uses.
* AccessPointReader: an access point that is a hub on the map and lists its own clients over
  SNMP. Nothing to set up: hubs whose SNMP identity a reader recognises are asked during a sweep.

Both hand back WirelessInfo records (see model.py), and the coordinator places clients under
their access points from those. Registering a new module here is all it takes to add one.
"""

from __future__ import annotations

from typing import Any

from .base import AUTH_TOKEN, AUTH_USER_PASSWORD, AccessPointReader, Controller, ControllerError, has_credentials
from .fortigate import FortiGateController
from .grandstream import GrandstreamAccessPoint
from .model import (
    BAND_24,
    BAND_5,
    BAND_6,
    RADIOS,
    WirelessInfo,
    band_for_channel,
    band_from_text,
    complete,
    merge,
    quality_from,
)

REGISTRY: dict[str, type[Controller]] = {FortiGateController.kind: FortiGateController}
AP_READERS: tuple[type[AccessPointReader], ...] = (GrandstreamAccessPoint,)


def controller_for(cfg: dict[str, Any]) -> Controller | None:
    cls = REGISTRY.get(str(cfg.get("kind") or ""))
    return cls(cfg) if cls else None


def reader_for(snmp: dict[str, Any] | None) -> AccessPointReader | None:
    """The access point reader for a hub with this SNMP probe result, if any reader knows it."""
    if not snmp:
        return None
    cls = next((c for c in AP_READERS if c.matches(snmp)), None)
    return cls() if cls else None


__all__ = [
    "AP_READERS", "AUTH_TOKEN", "AUTH_USER_PASSWORD", "BAND_24", "BAND_5", "BAND_6", "RADIOS", "REGISTRY",
    "AccessPointReader", "Controller", "ControllerError", "WirelessInfo", "band_for_channel", "band_from_text",
    "complete", "controller_for", "has_credentials", "merge", "quality_from", "reader_for",
]
