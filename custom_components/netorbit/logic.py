"""Pure helpers for NetOrbit. No Home Assistant imports so they are easy to test."""

from __future__ import annotations

from datetime import datetime, timedelta
import ipaddress
import re

from .const import STATUS_ONLINE, STATUS_RECENT, STATUS_STALE

_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")

# Keyword -> icon. First match wins, checked against the lowercased name.
_ICON_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("iphone", "android", "pixel", "galaxy", "phone"), "mdi:cellphone"),
    (("ipad", "tablet"), "mdi:tablet"),
    (("macbook", "laptop", "notebook", "thinkpad"), "mdi:laptop"),
    (("imac", "desktop", "pc", "workstation", "studio"), "mdi:monitor"),
    (("appletv", "apple-tv", "apple tv", "roku", "firetv", "fire-tv", "chromecast", "shield", "streamer"), "mdi:television-play"),
    (("tv", "television", "bravia", "lgwebos", "tizen"), "mdi:television"),
    (("speaker", "homepod", "echo", "nest-audio", "soundbar"), "mdi:speaker"),
    (("cam", "camera", "doorbell", "ring", "wyze", "reolink"), "mdi:cctv"),
    (("printer", "print", "hp", "epson", "brother", "canon"), "mdi:printer"),
    (("thermostat",), "mdi:thermostat"),
    (("vacuum", "roomba", "roborock", "deebot"), "mdi:robot-vacuum"),
    (("playstation", "ps4", "ps5", "xbox", "nintendo", "switch-console", "steamdeck"), "mdi:gamepad-variant"),
    (("homeassistant", "home-assistant", "hass"), "mdi:home-assistant"),
    (("nas", "synology", "qnap", "unraid", "truenas", "server"), "mdi:server"),
    (("esp", "shelly", "tasmota", "tuya", "plug", "bulb", "light"), "mdi:chip"),
    (("garage",), "mdi:garage"),
    (("watch",), "mdi:watch"),
]


def normalize_mac(mac: str | None) -> str | None:
    """Return a lowercase colon separated MAC, or None if it is not a MAC."""
    if not mac:
        return None
    raw = re.sub(r"[^0-9a-fA-F]", "", mac).lower()
    if len(raw) != 12:
        return None
    out = ":".join(raw[i : i + 2] for i in range(0, 12, 2))
    if out in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"):
        return None
    return out if _MAC_RE.match(out) else None


def normalize_ipv4(ip: str | None) -> str | None:
    """Return a canonical IPv4 address, or None if the text is not one (a hostname, IPv6, junk)."""
    if not ip:
        return None
    try:
        return str(ipaddress.IPv4Address(str(ip).strip()))
    except ipaddress.AddressValueError:
        return None


def is_random_mac(mac: str | None) -> bool:
    """True when the MAC is locally administered (phones and laptops randomize these)."""
    mac = normalize_mac(mac)
    return bool(mac) and mac[1] in "26ae"


def compute_status(
    online: bool,
    last_seen: datetime | None,
    first_seen: datetime | None,
    now: datetime,
    stale_after: timedelta,
) -> str:
    """Online now, seen within the window, or not seen for longer than the window."""
    if online:
        return STATUS_ONLINE
    ref = last_seen or first_seen
    if ref is None or now - ref < stale_after:
        return STATUS_RECENT
    return STATUS_STALE


def rollup_status(children: list[tuple[str, bool]]) -> str:
    """Status for a hub with no address, from the (status, sleepy) of what's behind it.

    Online if anything behind it is online, seen recently if anything was, and not seen only when
    everything behind it is stale. Sleepy devices that are off don't count, so a switch with only a
    TV behind it doesn't turn red. Empty ("unknown") when nothing behind it says either way.
    """
    statuses = {status for status, sleepy in children if status == STATUS_ONLINE or not sleepy}
    for status in (STATUS_ONLINE, STATUS_RECENT, STATUS_STALE):
        if status in statuses:
            return status
    return ""


def guess_icon(name: str | None, default: str = "mdi:lan-connect") -> str:
    """Pick a sensible icon from a device name or hostname."""
    if not name:
        return default
    low = name.lower()
    tokens = set(re.split(r"[^a-z0-9]+", low))
    for words, icon in _ICON_HINTS:
        # Short words must match a whole token so "hp" does not match "iphone".
        if any((w in tokens) if len(w) < 5 else (w in low) for w in words):
            return icon
    return default


# When the name says nothing, the maker often does. Only makers whose products are
# mostly one kind of thing; Wi-Fi chip makers (Realtek, AzureWave...) say nothing useful.
_VENDOR_ICONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("sonos", "bose", "denon", "yamaha", "harman", "bang & olufsen", "devialet"), "mdi:speaker"),
    (("roku", "vizio", "tcl", "hisense"), "mdi:television"),
    (("sony interactive", "nintendo", "valve"), "mdi:gamepad-variant"),
    (("meta platforms", "oculus"), "mdi:virtual-reality"),
    (("ecobee", "honeywell", "resideo", "tado"), "mdi:thermostat"),
    (("nest labs", "google"), "mdi:home-automation"),
    (("amazon",), "mdi:speaker-message"),
    (("espressif", "tuya", "shelly", "allterco", "sonoff", "itead", "particle", "raspberry pi"), "mdi:chip"),
    (("chamberlain", "liftmaster", "meross"), "mdi:garage"),
    (("tesla",), "mdi:car-electric"),
    (("signify", "philips lighting", "lifx", "lutron", "nanoleaf", "wiz "), "mdi:lightbulb"),
    (("ring ", "ring llc", "arlo", "wyze", "reolink", "hikvision", "dahua", "eufy", "anker", "axis comm", "ubiquiti camera"), "mdi:cctv"),
    (("hewlett packard", "hp inc", "brother", "seiko epson", "canon", "xerox", "lexmark", "kyocera"), "mdi:printer"),
    (("synology", "qnap", "western digital", "asustor", "terramaster"), "mdi:nas"),
    (("apple",), "mdi:cellphone-link"),
    (("peloton",), "mdi:bike"),
    (("control4", "savant", "crestron", "hubitat", "smartthings", "home assistant", "nabu casa"), "mdi:home-automation"),
    (("whisker", "litter-robot", "petsafe", "sure petcare"), "mdi:cat"),
    (("samsung", "lg electronics"), "mdi:television"),
)


def guess_icon_from(name: str | None, vendor: str | None, default: str = "mdi:lan-connect") -> str:
    """Icon from the name first, then from the maker."""
    icon = guess_icon(name, default="")
    if icon:
        return icon
    low = f" {(vendor or '').lower()} "
    for words, vicon in _VENDOR_ICONS:
        if any(w in low for w in words):
            return vicon
    return default


def short_hostname(name: str | None) -> str | None:
    """Strip the domain from a reverse DNS name and ignore names that are just an IP."""
    if not name:
        return None
    name = name.strip().rstrip(".")
    try:
        ipaddress.ip_address(name)
        return None
    except ValueError:
        pass
    host = name.split(".")[0]
    if not host or re.fullmatch(r"[0-9-]+", host):
        return None
    return host


_MAC_IN_TEXT = re.compile(r"([0-9a-f]{2}[:-]){5}[0-9a-f]{2}|(?<![0-9a-f])[0-9a-f]{12}(?![0-9a-f])", re.I)
_PING_PREFIX = re.compile(r"^\s*ping\s*[:\-]?\s+", re.I)


def useful_name(name: str | None) -> str | None:
    """A name a person would recognize, or None for names that are just an address.

    Integrations often name devices after their MAC or IP ("00:00:5e:00:53:1e",
    "00:00:5e:00:53:1e Speaker 53:1E", "192.0.2.20"). Those are worse than nothing.
    """
    if not name:
        return None
    name = " ".join(str(name).split())
    if not name or _MAC_IN_TEXT.search(name):
        return None
    try:
        ipaddress.ip_address(name)
        return None
    except ValueError:
        pass
    return name


def ping_label(name: str | None) -> str | None:
    """'Ping Hallway AP' -> 'Hallway AP'. People often prefix ping sensors with the word."""
    name = useful_name(name)
    if not name:
        return None
    return useful_name(_PING_PREFIX.sub("", name)) or None


def fallback_name(mac: str | None, ip: str | None) -> str:
    """Name for a device we know nothing about."""
    if mac:
        return "Device " + mac[-5:].upper()
    return "Device " + (ip or "unknown")


def parse_proc_arp(text: str) -> dict[str, str]:
    """Parse /proc/net/arp into {ip: mac} for complete entries."""
    out: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        ip, _hw, flags, mac = parts[0], parts[1], parts[2], parts[3]
        try:
            complete = int(flags, 16) & 0x2
        except ValueError:
            continue
        mac = normalize_mac(mac)
        if complete and mac:
            out[ip] = mac
    return out


def keys_answering(keys: list[str], macs: dict[str, str], answered_by: str | None) -> list[str]:
    """Which of the keys pinged at one address the reply belongs to.

    DHCP hands a departed device's address to the next one that asks, so a reply proves only
    that something has the address. `macs` holds the MAC each key is held to: only keys whose
    MAC ARP has already shown at this address, so a hub given its base MAC or a device behind a
    MAC-NAT repeater is never held to a MAC that can't appear. When ARP says which MAC replied,
    a held key with a different MAC didn't answer. Other keys, and replies ARP can't place,
    count as before.
    """
    if not answered_by:
        return keys
    return [k for k in keys if not macs.get(k) or macs[k] == answered_by]


def subnet_hosts(subnet: str) -> list[str]:
    """All usable host addresses in a subnet."""
    net = ipaddress.ip_network(subnet, strict=False)
    return [str(h) for h in net.hosts()]


def validate_subnet(subnet: str, max_hosts: int) -> str:
    """Return the canonical subnet string or raise ValueError."""
    net = ipaddress.ip_network(subnet.strip(), strict=False)
    if net.version != 4:
        raise ValueError("ipv4_only")
    if net.num_addresses - 2 > max_hosts:
        raise ValueError("too_large")
    return str(net)


_ANY_MAC_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}|[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})(?![0-9A-Fa-f])")
_ANY_IP_RE = re.compile(r"(?<![\d.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\d.])")


def extract_addresses(text: str) -> tuple[list[str], list[str]]:
    """Pull every MAC and IPv4 address out of pasted text (a table, CSV, app screen dump)."""
    macs: list[str] = []
    for raw in _ANY_MAC_RE.findall(text or ""):
        mac = normalize_mac(raw)
        if mac and mac not in macs:
            macs.append(mac)
    ips: list[str] = []
    for ip in _ANY_IP_RE.findall(text or ""):
        if ip not in ips and not ip.endswith(".255") and ip != "0.0.0.0":
            ips.append(ip)
    return macs, ips


def slugify_id(text: str) -> str:
    """Simple id slug: lowercase letters, digits and underscores."""
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s or "item"
