"""The pure sums behind throughput on the links."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.netorbit.topology import infer
from custom_components.netorbit.traffic import from_port, port_rates, throughput, utilization


def test_port_rates_from_two_readings() -> None:
    t0 = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=60)
    prev = {1: (1_000_000, 2_000_000, 1000), 2: (500, 500, 100), 3: (10, 10, None)}
    now = {1: (1_000_000 + 7_500_000, 2_000_000 + 750_000, 1000), 2: (100, 600, 100), 3: (10, 10, None), 4: (1, 1, 1000)}
    rates = port_rates(prev, t0, now, t1)
    assert rates[1] == (1_000_000.0, 100_000.0, 1000)  # 7.5 MB in 60 s = 1 Mbit/s into the port
    assert 2 not in rates  # the in-counter went backwards: a reboot or a wrap, no rate this time
    assert rates[3] == (0.0, 0.0, None) and 4 not in rates  # a port without a previous reading waits
    assert port_rates(prev, t1, now, t0) == {}  # time did not move


def test_utilization_and_the_attribute_shape() -> None:
    assert utilization(100_000_000, 10_000_000, 1000) == 10 and utilization(0, 0, 1000) == 0
    assert utilization(2_000_000_000, 0, 1000) == 100 and utilization(1, 1, None) is None
    assert throughput(None, None, 1000, "snmp:sw", "t") is None
    assert throughput(1_234.6, None, None, "snmp:sw", "t") == {"in_bps": 1235, "out_bps": 0, "source": "snmp:sw", "at": "t"}
    assert throughput(100_000_000, 10_000_000, 1000, "snmp:sw", "t") == {
        "in_bps": 100_000_000, "out_bps": 10_000_000, "speed_mbps": 1000, "utilization": 10, "source": "snmp:sw", "at": "t"}
    # Seen from the switch port, its output is the device's input.
    assert from_port((1_000_000.0, 100_000.0, 1000), "snmp:sw", "t")["in_bps"] == 100_000
    assert from_port((1_000_000.0, 100_000.0, 1000), "snmp:sw", "t")["out_bps"] == 1_000_000
    assert from_port(None, "snmp:sw", "t") is None


def test_topology_remembers_ports_and_uplinks() -> None:
    tables = {"sw": {"00:00:5e:00:53:a1": 1, "00:00:5e:00:53:a2": 2, "ff:00:00:00:00:ap": 5, "00:00:5e:00:53:a3": 5, "gw:00:00:00:00:00": 24},
              "sw2": {"gw:00:00:00:00:00": 1, "00:00:5e:00:53:a4": 3}}
    hub_macs = {"gateway": "gw:00:00:00:00:00", "sw": "sw:00:00:00:00:00", "sw2": "s2:00:00:00:00:00", "ap": "ff:00:00:00:00:ap"}
    devices = {"d1": "00:00:5e:00:53:a1", "d2": "00:00:5e:00:53:a2", "d3": "00:00:5e:00:53:a3", "d4": "00:00:5e:00:53:a4"}
    topo = infer(tables, hub_macs, "gw:00:00:00:00:00", devices, "gateway", leaf_hubs={"ap"})
    assert topo.device_port["d1"] == ("sw", 1) and topo.device_port["d3"] == ("sw", 5) and topo.device_hub["d3"] == "ap"
    assert topo.hub_port["ap"] == ("sw", 5) and topo.uplink == {"sw": 24, "sw2": 1}
    assert topo.device_port["d4"] == ("sw2", 3)
