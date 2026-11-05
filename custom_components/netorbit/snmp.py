"""Read-only SNMP helpers: identify switches and read their MAC address tables."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
OID_BRIDGE_PORTS = "1.3.6.1.2.1.17.1.2.0"  # dot1dBaseNumPorts
OID_Q_FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2"  # dot1qTpFdbPort.<vlan>.<mac>
OID_FDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"  # dot1dTpFdbPort.<mac>
OID_FDB_ADDRESS = "1.3.6.1.2.1.17.4.3.1.1"  # dot1dTpFdbAddress.<index>: the MAC, for agents that do not index by it

# Grandstream GWN access points list their Wi-Fi clients in GRANDSTREAM-GWN-MIB (gwnClientTable).
GRANDSTREAM_OID_PREFIX = "1.3.6.1.4.1.42397"
OID_GWN_CLIENT_MAC = "1.3.6.1.4.1.42397.1.1.3.3.1.1"  # gwnClientMACAddress, also the table index
OID_GWN_CLIENT_IP = "1.3.6.1.4.1.42397.1.1.3.3.1.2"  # gwnClientIPAddress, same index

_ENTERPRISES_NAME = "SNMPv2-SMI::enterprises."

PROBE_TIMEOUT = 1.0
WALK_TIMEOUT = 2.0
WALK_DEADLINE = 15.0  # a whole client table walk; WALK_TIMEOUT only bounds one request
MAX_TABLE = 4096


@dataclass
class ProbeResult:
    """What a host told us over SNMP."""

    descr: str | None
    name: str | None
    bridge: bool
    object_id: str | None = None  # sysObjectID, e.g. 1.3.6.1.4.1.42397... for Grandstream


def is_grandstream(object_id: str | None, descr: str | None = None) -> bool:
    """True for a Grandstream device, by its sysObjectID or, failing that, its description."""
    oid = (object_id or "").strip().lstrip(".")
    if oid.startswith(_ENTERPRISES_NAME):
        # pysnmp prints known prefixes by name: SNMPv2-SMI::enterprises.42397.1.1
        oid = "1.3.6.1.4.1." + oid[len(_ENTERPRISES_NAME) :]
    if oid == GRANDSTREAM_OID_PREFIX or oid.startswith(GRANDSTREAM_OID_PREFIX + "."):
        return True
    return "grandstream" in (descr or "").lower()


_HEX_MAC = re.compile(r"^[0-9a-f]{12}$")


def parse_mac(value: Any) -> str | None:
    """A MAC as colon separated lowercase hex from raw bytes (6 octets) or from text in
    colon, dash or bare hex, optionally with a 0x prefix."""
    if value is None:
        return None
    raw: bytes | None = None
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif hasattr(value, "asOctets"):
        try:
            raw = bytes(value.asOctets())
        except Exception:  # noqa: BLE001
            return None
    elif isinstance(value, str):
        text = value.strip().lower()
        if not text.isascii():
            return None
        return _mac_from_text(text)
    if raw is None:
        return None
    if len(raw) == 6:
        return ":".join(f"{b:02x}" for b in raw)
    try:
        text = raw.decode("ascii").strip().lower()
    except UnicodeDecodeError:
        return None
    return _mac_from_text(text)


def _mac_from_text(text: str) -> str | None:
    """A MAC from lowercase ASCII text in colon, dash, dot or bare hex form."""
    if text.startswith("0x"):
        text = text[2:]
    text = re.sub(r"[\s:.\-]", "", text)
    if _HEX_MAC.match(text):
        return ":".join(text[i : i + 2] for i in range(0, 12, 2))
    return None


class SnmpClient:
    """Thin wrapper so the rest of NetOrbit never touches pysnmp directly."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self._engine = None
        self._mod: Any = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> bool:
        async with self._lock:
            if self._engine is not None:
                return True
            try:
                self._mod, self._engine = await self.hass.async_add_executor_job(_load)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("SNMP unavailable: %s", err)
                return False
            return True

    async def _target(self, host: str, timeout: float):
        return await self._mod.UdpTransportTarget.create((host, 161), timeout=timeout, retries=0)

    async def probe(self, host: str, community: str) -> ProbeResult | None:
        """Ask a host what it is. None when it does not answer with this community."""
        if not await self._ensure():
            return None
        m = self._mod
        try:
            target = await self._target(host, PROBE_TIMEOUT)
            err_ind, err_stat, _idx, binds = await m.get_cmd(
                self._engine, m.CommunityData(community, mpModel=1), target, m.ContextData(),
                m.ObjectType(m.ObjectIdentity(OID_SYS_DESCR)),
                m.ObjectType(m.ObjectIdentity(OID_SYS_NAME)),
                m.ObjectType(m.ObjectIdentity(OID_BRIDGE_PORTS)),
                m.ObjectType(m.ObjectIdentity(OID_SYS_OBJECT_ID)),
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("SNMP probe of %s failed: %s", host, err)
            return None
        if err_ind or err_stat:
            return None
        values = [_value(v) for _n, v in binds]
        descr, name, ports, _ = (values + [None, None, None, None])[:4]
        # pysnmp prints a sysObjectID under a known prefix by name, so take the numbers from it.
        object_id = _oid_text(binds[3][1]) if len(binds) > 3 else None
        bridge = isinstance(ports, int) and ports > 0
        return ProbeResult(
            descr=str(descr) if descr else None, name=str(name) if name else None, bridge=bridge,
            object_id=object_id or None,
        )

    async def mac_table(self, host: str, community: str) -> dict[str, int] | None:
        """{mac: port} from the switch's forwarding table, or None when unreadable."""
        if not await self._ensure():
            return None
        table = await self._walk_fdb(host, community, OID_Q_FDB_PORT, vlan=True)
        if not table:
            table = await self._walk_fdb(host, community, OID_FDB_PORT, vlan=False)
        return table

    async def wireless_clients(self, host: str, community: str) -> set[str] | None:
        """MACs of the Wi-Fi clients a Grandstream GWN access point lists, or None when unreadable.

        An empty set means the AP answered but has no clients right now. The table is indexed by
        the client MAC, so when the MAC column cannot be read (an index column may be hidden) the
        MAC is taken from the row index of the IP column instead.
        """
        if not await self._ensure():
            return None
        try:
            # WALK_TIMEOUT only bounds one request, so a slow AP answering a row at a time could
            # hold the whole scan; the deadline covers the walk as a whole.
            async with asyncio.timeout(WALK_DEADLINE):
                found = await self._walk_gwn(host, community, OID_GWN_CLIENT_MAC)
                if found is None:
                    return None
                if not found:
                    found = await self._walk_gwn(host, community, OID_GWN_CLIENT_IP)
                return found
        except TimeoutError:
            _LOGGER.debug("SNMP client walk of %s took longer than %ss", host, WALK_DEADLINE)
            return None

    async def _walk_gwn(self, host: str, community: str, base: str) -> set[str] | None:
        m = self._mod
        base_t = tuple(int(x) for x in base.split("."))
        out: set[str] = set()
        try:
            target = await self._target(host, WALK_TIMEOUT)
            async for err_ind, err_stat, _idx, binds in m.bulk_walk_cmd(
                self._engine, m.CommunityData(community, mpModel=1), target, m.ContextData(),
                0, 40, m.ObjectType(m.ObjectIdentity(base)), lexicographicMode=False,
            ):
                if err_ind or err_stat:
                    _LOGGER.debug("SNMP client walk of %s %s: %s", host, base, err_ind or err_stat)
                    return out or None
                for name, val in binds:
                    oid = tuple(name)
                    if oid[: len(base_t)] != base_t:
                        continue
                    index = oid[len(base_t) :]
                    mac = parse_mac(val) or (
                        ":".join(f"{b:02x}" for b in index[-6:]) if len(index) >= 6 and all(0 <= b <= 255 for b in index[-6:]) else None
                    )
                    if mac:
                        out.add(mac)
                    if len(out) >= MAX_TABLE:
                        return out
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("SNMP client walk of %s %s failed: %s", host, base, err)
            return out or None
        return out

    async def _walk_fdb(self, host: str, community: str, base: str, vlan: bool) -> dict[str, int]:
        out: dict[str, int] = {}
        by_index: dict[tuple[int, ...], int] = {}  # rows an agent numbered instead of indexing by MAC
        async for tail, val in self._rows(host, community, base):
            port = _value(val)
            if not isinstance(port, int) or port <= 0:
                continue
            mac_part = tail[-6:]
            if len(mac_part) == 6 and not (vlan and len(tail) < 7):
                out[_mac(mac_part)] = port
            elif not vlan:
                by_index[tail] = port
            if len(out) + len(by_index) >= MAX_TABLE:
                break
        if not out and by_index:
            # RFC 4188 indexes dot1dTpFdbPort by the MAC itself, but some agents number the rows 1, 2, 3...
            # and keep the MAC in the sibling column dot1dTpFdbAddress under the same number. Join the two.
            async for tail, val in self._rows(host, community, OID_FDB_ADDRESS):
                port, raw = by_index.get(tail), _octets(val)
                if port and raw and len(raw) == 6:
                    out[_mac(raw)] = port
        return out

    async def _rows(self, host: str, community: str, base: str):
        """Yield (index, value) for every row under base. A walk that fails or is refused just ends early."""
        m = self._mod
        base_t = tuple(int(x) for x in base.split("."))
        try:
            target = await self._target(host, WALK_TIMEOUT)
            async for err_ind, err_stat, _idx, binds in m.bulk_walk_cmd(
                self._engine, m.CommunityData(community, mpModel=1), target, m.ContextData(),
                0, 40, m.ObjectType(m.ObjectIdentity(base)), lexicographicMode=False,
            ):
                if err_ind or err_stat:
                    return
                for name, val in binds:
                    oid = tuple(name)
                    if oid[: len(base_t)] == base_t:
                        yield oid[len(base_t) :], val
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("SNMP walk of %s %s failed: %s", host, base, err)


def _load():
    """Import pysnmp and build the engine off the event loop (both are slow)."""
    import pysnmp.hlapi.v3arch.asyncio as mod  # noqa: PLC0415
    from pysnmp.smi import view  # noqa: PLC0415

    engine = mod.SnmpEngine()
    # pysnmp reads its MIB files from disk on first use. Do that here, off the event loop,
    # the same way Home Assistant's own SNMP integration does.
    controller = view.MibViewController(engine.message_dispatcher.mib_instrum_controller.get_mib_builder())
    engine.cache["mibViewController"] = controller
    controller.mibBuilder.load_modules()
    return mod, engine


def _oid_text(val: Any) -> str | None:
    """A sysObjectID value as dotted numbers (1.3.6.1.4.1...), or None."""
    try:
        get_oid = getattr(val, "get_oid", None) or getattr(val, "asTuple", None)
        if get_oid is None:
            return None
        parts = get_oid()
        return ".".join(str(int(x)) for x in parts) or None
    except Exception:  # noqa: BLE001
        return None


def _mac(raw) -> str:
    """Colon-separated lower-case hex from six OID sub-identifiers or six bytes."""
    return ":".join(f"{b:02x}" for b in raw)


def _octets(val: Any) -> bytes | None:
    """The raw bytes of an OCTET STRING value; None for anything else (an integer, a missing instance)."""
    if isinstance(val, (bytes, bytearray)):
        return bytes(val)
    try:
        return bytes(val.asOctets())
    except Exception:  # noqa: BLE001
        return None


def _value(val: Any) -> Any:
    try:
        if val.__class__.__name__ in ("NoSuchObject", "NoSuchInstance", "EndOfMibView", "Null"):
            return None
        if hasattr(val, "prettyPrint") and val.__class__.__name__ in ("OctetString", "DisplayString"):
            return val.prettyPrint()
        return int(val)
    except (TypeError, ValueError):
        try:
            return val.prettyPrint()
        except Exception:  # noqa: BLE001
            return None
