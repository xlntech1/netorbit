"""Reading a switch's forwarding table, with pysnmp's walk faked at the call boundary."""

from __future__ import annotations

from pysnmp.proto.rfc1902 import Integer32, ObjectName, OctetString

from custom_components.netorbit.snmp import OID_FDB_PORT, OID_Q_FDB_PORT, SnmpClient

OID_FDB_ADDRESS = "1.3.6.1.2.1.17.4.3.1.1"  # dot1dTpFdbAddress
MACS = ["00:00:5e:00:53:01", "00:00:5e:00:53:02", "00:00:5e:00:53:03"]


def _oid(mac: str) -> str:
    """A MAC as the six OID sub-identifiers a standard agent indexes its table with."""
    return ".".join(str(int(b, 16)) for b in mac.split(":"))


class FakeAgent:
    """Enough of pysnmp.hlapi for SnmpClient: answers bulk walks from (oid, value) rows, a GETBULK's worth at a time."""

    def __init__(self, rows: list[tuple[str, object]]) -> None:
        self.rows = sorted(((tuple(int(x) for x in oid.split(".")), val) for oid, val in rows), key=lambda r: r[0])
        self.walked: list[str] = []
        # The pysnmp constructors the client calls; their arguments only need to come back out.
        self.CommunityData = self.ContextData = self.ObjectIdentity = self.ObjectType = lambda *a, **_k: a[0] if a else None

    class UdpTransportTarget:
        @staticmethod
        async def create(addr, timeout, retries):
            return addr

    async def bulk_walk_cmd(self, _engine, _auth, _target, _ctx, _non_rep, max_rep, base, lexicographicMode):  # noqa: N803
        self.walked.append(base)
        prefix = tuple(int(x) for x in base.split("."))
        rows = [(ObjectName(oid), val) for oid, val in self.rows if oid[: len(prefix)] == prefix]
        for i in range(0, len(rows), max_rep):
            yield None, None, 0, rows[i : i + max_rep]


def _client(agent: FakeAgent) -> SnmpClient:
    client = SnmpClient(hass=None)
    client._mod, client._engine = agent, object()  # already loaded, so _ensure() has nothing to do  # noqa: SLF001
    return client


async def test_bridge_mib_rows_numbered_instead_of_indexed_by_mac_are_joined_with_the_address_column():
    """Some switches number dot1dTpFdbPort 1, 2, 3... and keep the MAC in dot1dTpFdbAddress under the same number."""
    rows: list[tuple[str, object]] = []
    for index, (mac, port) in enumerate(zip(MACS, (8, 8, 5)), start=1):
        rows.append((f"{OID_FDB_PORT}.{index}", Integer32(port)))
        rows.append((f"{OID_FDB_ADDRESS}.{index}", OctetString(hexValue=mac.replace(":", ""))))
    rows.append((f"{OID_FDB_PORT}.4", Integer32(11)))  # a port with no address row is left out, not guessed
    rows.append((f"{OID_FDB_ADDRESS}.5", OctetString(hexValue="00005e005305")))  # and so is an address with no port
    agent = FakeAgent(rows)
    assert await _client(agent).mac_table("192.0.2.2", "public") == {MACS[0]: 8, MACS[1]: 8, MACS[2]: 5}
    # Q-BRIDGE first (this agent has no such object), then both BRIDGE-MIB columns, nothing else.
    assert agent.walked == [OID_Q_FDB_PORT, OID_FDB_PORT, OID_FDB_ADDRESS]


async def test_standard_agents_are_read_as_before():
    # Q-BRIDGE (dot1qTpFdbPort.<vlan>.<mac>) is preferred, and the BRIDGE-MIB columns are not walked at all.
    agent = FakeAgent([(f"{OID_Q_FDB_PORT}.1.{_oid(MACS[0])}", Integer32(3)), (f"{OID_Q_FDB_PORT}.20.{_oid(MACS[1])}", Integer32(4))])
    assert await _client(agent).mac_table("192.0.2.2", "public") == {MACS[0]: 3, MACS[1]: 4}
    assert agent.walked == [OID_Q_FDB_PORT]
    # BRIDGE-MIB indexed by MAC needs no join, so the address column is not asked for; port 0 rows are skipped.
    agent = FakeAgent([(f"{OID_FDB_PORT}.{_oid(MACS[0])}", Integer32(3)), (f"{OID_FDB_PORT}.{_oid(MACS[2])}", Integer32(0))])
    assert await _client(agent).mac_table("192.0.2.2", "public") == {MACS[0]: 3}
    assert agent.walked == [OID_Q_FDB_PORT, OID_FDB_PORT]
