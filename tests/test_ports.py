"""The TCP port scanner and its helpers."""

from __future__ import annotations

import asyncio
import socket

import pytest

from custom_components.netorbit.ports import COMMON_PORTS, EXTENDED_PORTS, parse_ports, ports_for, scan, service_name


def test_parse_ports() -> None:
    assert parse_ports("22, 80,443, 8000-8003;22") == [22, 80, 443, 8000, 8001, 8002, 8003]
    assert parse_ports("") == [] and parse_ports(None) == []
    for bad in ("abc", "0", "70000", "10-5", "1-2000", "22-"):
        with pytest.raises(ValueError):
            parse_ports(bad)


def test_port_sets_and_names() -> None:
    assert set(COMMON_PORTS) <= set(EXTENDED_PORTS)
    assert 60 <= len(COMMON_PORTS) <= 100 and len(EXTENDED_PORTS) >= 300
    assert service_name(22) == "ssh" and service_name(8123) == "home-assistant"
    assert service_name(65000) is None
    assert ports_for("common", None) == sorted(COMMON_PORTS)
    assert ports_for("extended", None) == sorted(EXTENDED_PORTS)
    assert ports_for("custom", "443, 22") == [22, 443]
    assert ports_for("custom", "nonsense") == []
    assert ports_for("whatever", None) == sorted(COMMON_PORTS)


async def test_scan_tells_open_from_closed(socket_enabled) -> None:
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    open_port = server.sockets[0].getsockname()[1]
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()
    try:
        assert await scan("127.0.0.1", [open_port, closed_port], timeout=0.5) == {open_port}
        assert await scan("127.0.0.1", [], timeout=0.5) == set()
    finally:
        server.close()
        await server.wait_closed()
