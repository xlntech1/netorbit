"""TCP port discovery: which well-known services a device listens on.

A plain connect is the whole test: the port is open when the handshake completes, closed when
it is refused or nothing answers in time. Nothing is sent on the connection. TCP only: UDP has
no handshake, so a scan can only say "open or filtered", and the UDP services worth knowing
about (Bonjour, SSDP) are already read the proper way.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import socket

# Ports a home or lab network is likely to have, with the names people know them by.
COMMON_PORTS: dict[int, str] = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns", 80: "http", 110: "pop3", 123: "ntp",
    139: "netbios", 143: "imap", 161: "snmp", 389: "ldap", 443: "https", 445: "smb", 465: "smtps",
    515: "lpd", 548: "afp", 554: "rtsp", 587: "submission", 631: "ipp", 636: "ldaps", 853: "dns-over-tls",
    873: "rsync", 993: "imaps", 995: "pop3s", 1080: "socks", 1194: "openvpn", 1433: "mssql",
    1521: "oracle", 1723: "pptp", 1883: "mqtt", 1900: "ssdp", 2049: "nfs", 2375: "docker", 2376: "docker-tls",
    3000: "grafana", 3306: "mysql", 3389: "rdp", 3478: "stun", 3689: "daap", 4443: "https-alt",
    5000: "upnp", 5001: "synology", 5060: "sip", 5061: "sips", 5432: "postgres", 5900: "vnc",
    6379: "redis", 6443: "kubernetes", 7000: "airplay", 7443: "https-alt", 8000: "http-alt",
    8006: "proxmox", 8008: "http-alt", 8080: "http-alt", 8081: "http-alt", 8083: "http-alt",
    8096: "jellyfin", 8123: "home-assistant", 8181: "http-alt", 8200: "dlna", 8443: "https-alt",
    8554: "rtsp-alt", 8883: "mqtts", 8888: "http-alt", 9000: "http-alt", 9090: "http-alt",
    9100: "jetdirect", 9443: "portainer", 10000: "webmin", 32400: "plex", 49152: "upnp-alt",
}

# A wider sweep: everything above plus more admin, database, media, IoT and remote-access ports.
EXTENDED_PORTS: dict[int, str] = {
    **COMMON_PORTS,
    20: "ftp-data", 37: "time", 42: "wins", 49: "tacacs", 67: "dhcp", 69: "tftp", 70: "gopher",
    79: "finger", 81: "http-alt", 82: "http-alt", 88: "kerberos", 102: "iso-tsap", 111: "rpcbind",
    113: "ident", 119: "nntp", 135: "msrpc", 137: "netbios-ns", 138: "netbios-dgm", 179: "bgp",
    194: "irc", 264: "bgmp", 311: "macos-server", 318: "tsp", 427: "slp", 464: "kpasswd", 500: "isakmp",
    512: "exec", 513: "login", 514: "syslog", 520: "rip", 543: "klogin", 544: "kshell", 563: "nntps",
    593: "http-rpc", 623: "ipmi", 646: "ldp", 691: "msexchange", 749: "kerberos-adm", 830: "netconf",
    902: "vmware-auth", 989: "ftps-data", 990: "ftps", 992: "telnets", 1025: "msrpc-alt", 1099: "rmi",
    1110: "nfsd", 1177: "pps", 1234: "http-alt", 1311: "openmanage", 1337: "http-alt", 1352: "notes",
    1400: "sonos", 1434: "mssql-browser", 1443: "https-alt", 1494: "citrix", 1500: "vlsi", 1515: "wazuh",
    1701: "l2tp", 1812: "radius", 1813: "radius-acct", 1880: "node-red", 2000: "cisco-sccp",
    2001: "http-alt", 2022: "ssh-alt", 2082: "cpanel", 2083: "cpanel-ssl", 2086: "whm", 2087: "whm-ssl",
    2095: "webmail", 2096: "webmail-ssl", 2121: "ftp-alt", 2181: "zookeeper", 2222: "ssh-alt",
    2323: "telnet-alt", 2379: "etcd", 2380: "etcd-peer", 2483: "oracle", 2484: "oracle-ssl",
    2601: "zebra", 2604: "ospfd", 3001: "http-alt", 3002: "http-alt", 3030: "http-alt", 3128: "squid",
    3260: "iscsi", 3268: "ldap-gc", 3269: "ldaps-gc", 3283: "apple-remote",
    3307: "mysql-alt", 3310: "clamav", 3333: "http-alt", 3400: "http-alt", 3551: "apcupsd",
    3632: "distcc", 3690: "svn", 3702: "ws-discovery", 3777: "http-alt", 3780: "nessus", 3784: "bfd",
    3790: "metasploit", 3889: "http-alt", 4000: "http-alt", 4001: "http-alt", 4040: "http-alt",
    4200: "http-alt", 4369: "epmd", 4444: "http-alt", 4500: "ipsec-nat", 4567: "http-alt", 4662: "edonkey",
    4786: "cisco-smi", 4840: "opc-ua", 4848: "glassfish", 5006: "synology-ssl", 5009: "airport-admin",
    5010: "http-alt", 5050: "http-alt", 5080: "http-alt", 5222: "xmpp", 5223: "xmpp-ssl", 5269: "xmpp-server",
    5353: "mdns", 5355: "llmnr", 5357: "wsd", 5380: "technitium", 5431: "upnp-alt", 5443: "https-alt", 5500: "vnc-alt",
    5555: "adb", 5601: "kibana", 5631: "pcanywhere", 5672: "amqp", 5683: "coap", 5800: "vnc-http",
    5901: "vnc-1", 5902: "vnc-2", 5938: "teamviewer", 5984: "couchdb", 5985: "winrm", 5986: "winrm-ssl",
    6000: "x11", 6001: "x11-1", 6053: "esphome", 6080: "novnc", 6082: "http-alt", 6346: "gnutella",
    6514: "syslog-tls", 6566: "sane", 6600: "mpd", 6646: "mcafee", 6666: "irc-alt", 6667: "irc",
    6668: "irc-alt", 6669: "irc-alt", 6690: "synology-drive", 6881: "bittorrent", 6969: "bittorrent-tracker",
    7001: "weblogic", 7070: "http-alt", 7080: "http-alt", 7100: "x-font", 7199: "cassandra-jmx",
    7474: "neo4j", 7547: "cwmp", 7777: "http-alt", 7778: "http-alt", 7878: "radarr", 7880: "http-alt",
    7979: "http-alt", 8001: "http-alt", 8002: "http-alt", 8009: "ajp", 8010: "http-alt", 8020: "hadoop",
    8060: "roku", 8069: "odoo", 8082: "http-alt", 8084: "http-alt", 8085: "http-alt", 8086: "influxdb",
    8087: "riak", 8088: "http-alt", 8089: "splunk", 8090: "http-alt", 8091: "couchbase", 8099: "http-alt",
    8100: "http-alt", 8112: "deluge", 8118: "privoxy", 8125: "statsd", 8161: "activemq", 8180: "http-alt",
    8222: "http-alt", 8243: "https-alt", 8280: "http-alt", 8291: "winbox", 8300: "consul", 8333: "bitcoin",
    8384: "syncthing", 8400: "http-alt", 8444: "https-alt", 8500: "consul-http", 8530: "wsus",
    8531: "wsus-ssl", 8600: "consul-dns", 8686: "lidarr", 8687: "http-alt", 8800: "http-alt",
    8834: "nessus-web", 8880: "http-alt", 8889: "http-alt", 8899: "http-alt", 8989: "sonarr",
    8990: "http-alt", 8999: "http-alt", 9001: "tor-or", 9002: "http-alt", 9003: "http-alt", 9009: "http-alt",
    9010: "http-alt", 9042: "cassandra", 9050: "tor-socks", 9051: "tor-control", 9080: "http-alt",
    9091: "transmission", 9092: "kafka", 9093: "alertmanager", 9117: "jackett",
    9160: "cassandra-thrift", 9200: "elasticsearch", 9300: "elasticsearch-nodes", 9389: "adws",
    9418: "git", 9500: "http-alt", 9600: "http-alt", 9696: "prowlarr", 9800: "http-alt", 9898: "http-alt",
    9900: "http-alt", 9981: "tvheadend", 9982: "tvheadend-htsp", 9990: "http-alt", 9999: "http-alt",
    10001: "ubiquiti", 10050: "zabbix-agent", 10051: "zabbix", 10250: "kubelet", 10443: "https-alt",
    11211: "memcached", 12345: "http-alt", 15672: "rabbitmq", 16010: "hbase", 18080: "http-alt",
    19999: "netdata", 20000: "webmin-usermin", 27017: "mongodb", 28017: "mongodb-http", 32768: "http-alt",
    32469: "plex-dlna", 37777: "dahua", 44158: "mikrotik", 47808: "bacnet", 49153: "upnp-alt",
    50000: "http-alt", 51413: "transmission-peer", 55443: "http-alt", 61616: "activemq-openwire",
    62078: "iphone-sync",
}

PORT_SETS: dict[str, dict[int, str]] = {"common": COMMON_PORTS, "extended": EXTENDED_PORTS}
MAX_CUSTOM_PORTS = 1024
_SERVBYPORT_CACHE: dict[int, str | None] = {}


def service_name(port: int) -> str | None:
    """The usual name for a port: from the built-in table, else from the system's services file once
    `warm_service_names` has looked it up (that read happens off the event loop)."""
    if port in EXTENDED_PORTS:
        return EXTENDED_PORTS[port]
    return _SERVBYPORT_CACHE.get(port)


def warm_service_names(ports: Iterable[int]) -> None:
    """Look up names for ports outside the built-in table in the system's services file. Blocking: run it
    in an executor, once, when the custom port list changes."""
    for port in ports:
        if port in EXTENDED_PORTS or port in _SERVBYPORT_CACHE:
            continue
        try:
            _SERVBYPORT_CACHE[port] = socket.getservbyport(port, "tcp")
        except (OSError, OverflowError):
            _SERVBYPORT_CACHE[port] = None


def parse_ports(text: str | None) -> list[int]:
    """Read '22, 80, 8000-8100' into a sorted list of ports. Raises ValueError when it makes no sense."""
    ports: set[int] = set()
    for part in (text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        lo, dash, hi = part.partition("-")
        try:
            a = int(lo)
            b = int(hi) if dash else a
        except ValueError as err:
            raise ValueError(f"'{part}' is not a port or a range") from err
        if not (1 <= a <= 65535 and 1 <= b <= 65535) or b < a:
            raise ValueError(f"'{part}' is not a valid port range")
        ports.update(range(a, b + 1))
        if len(ports) > MAX_CUSTOM_PORTS:
            raise ValueError(f"At most {MAX_CUSTOM_PORTS} ports can be scanned")
    return sorted(ports)


def ports_for(choice: str, custom: str | None) -> list[int]:
    """The ports a setting asks for: a built-in set, or a custom list. Bad custom text means no ports."""
    if choice == "custom":
        try:
            return parse_ports(custom)
        except ValueError:
            return []
    return sorted(PORT_SETS.get(choice, COMMON_PORTS))


async def scan(ip: str, ports: list[int], timeout: float = 1.0, concurrency: int = 16) -> set[int]:
    """Which of these TCP ports accept a connection on this host."""
    sem = asyncio.Semaphore(concurrency)
    open_ports: set[int] = set()

    async def probe(port: int) -> None:
        async with sem:
            try:
                _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
            except (OSError, asyncio.TimeoutError):
                return
            open_ports.add(port)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    await asyncio.gather(*(probe(p) for p in ports))
    return open_ports
