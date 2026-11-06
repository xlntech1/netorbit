"""Throughput per node from switch port counters and from Wi-Fi controllers.

A managed switch counts the bytes in and out of every port (IF-MIB `ifHCInOctets` /
`ifHCOutOctets`, 64-bit) and knows each port's speed (`ifHighSpeed`, Mbit/s). Two readings a
ping round apart give bits per second per port; the MAC tables NetOrbit already reads say which
device sits on which port, so a device on a port of its own gets the port's rate, and a hub on
a port (an access point, a downstream switch) gets the port's rate as the traffic of everything
behind it. Wi-Fi clients get their rate from the controller instead (the AP's port carries all
of them together).

Directions are the device's: `in_bps` is what flows towards the device (the switch port's
output), `out_bps` what the device sends (the port's input).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# A port reading: (octets into the port, octets out of the port, speed in Mbit/s or None).
Counters = tuple[int, int, int | None]
# A port rate in the switch's terms: (bits/s into the port, bits/s out of the port, speed in Mbit/s or None).
PortRate = tuple[float, float, int | None]


def port_rates(prev: dict[int, Counters], prev_at: datetime, now: dict[int, Counters], now_at: datetime) -> dict[int, PortRate]:
    """Bits per second per interface index from two counter readings. A counter that went backwards
    (the switch rebooted, or a 32-bit counter wrapped) gives no rate for that port this time."""
    dt = (now_at - prev_at).total_seconds()
    if dt <= 0:
        return {}
    out: dict[int, PortRate] = {}
    for idx, (in_now, out_now, speed) in now.items():
        before = prev.get(idx)
        if before is None:
            continue
        d_in, d_out = in_now - before[0], out_now - before[1]
        if d_in < 0 or d_out < 0:
            continue
        out[idx] = (d_in * 8 / dt, d_out * 8 / dt, speed)
    return out


def utilization(in_bps: float | None, out_bps: float | None, speed_mbps: float | None) -> int | None:
    """0-100: the busier direction against the link speed; None without a speed."""
    if not speed_mbps or speed_mbps <= 0:
        return None
    peak = max(in_bps or 0.0, out_bps or 0.0)
    return max(0, min(100, round(peak * 100 / (speed_mbps * 1_000_000))))


def throughput(in_bps: float | None, out_bps: float | None, speed_mbps: float | None, source: str, at: str) -> dict[str, Any] | None:
    """The attribute shape, rounded to whole bits per second; None when nothing was measured."""
    if in_bps is None and out_bps is None:
        return None
    out: dict[str, Any] = {
        "in_bps": round(in_bps or 0.0), "out_bps": round(out_bps or 0.0), "source": source, "at": at,
    }
    if speed_mbps:
        out["speed_mbps"] = round(speed_mbps)
        out["utilization"] = utilization(in_bps, out_bps, speed_mbps)
    return out


def from_port(rate: PortRate | None, source: str, at: str) -> dict[str, Any] | None:
    """A device's throughput from the rate of the switch port it sits on (directions swapped: the port's
    output is the device's input)."""
    if rate is None:
        return None
    port_in, port_out, speed = rate
    return throughput(port_out, port_in, speed, source, at)
