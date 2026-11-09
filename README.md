# NetOrbit

[![Open NetOrbit in the Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=the-scott-davis&repository=netorbit&category=integration)

![Version](https://img.shields.io/github/v/release/the-scott-davis/netorbit) ![License](https://img.shields.io/github/license/the-scott-davis/netorbit)

A live, radial map of your home network for Home Assistant. Every device orbits the router, switch, access point or mesh node it connects through, colored by whether it's answering right now, was seen recently, or has gone quiet.

Install it, click Submit, and NetOrbit draws the best map your network can tell it about. Then fix anything it couldn't work out by dragging devices around, pasting a client list, or asking an AI assistant to do it for you.

<p align="center">
<a href="#install"><img src="docs/nav/install.svg" width="250" alt="Install"></a>
<a href="#what-it-does"><img src="docs/nav/features.svg" width="250" alt="What it does"></a>
<a href="#tested-on-simulated-networks"><img src="docs/nav/gallery.svg" width="250" alt="See it"></a><br>
<a href="#placing-devices-by-hand"><img src="docs/nav/place.svg" width="250" alt="Place devices"></a>
<a href="#netorbit"><img src="docs/nav/hub.svg" width="250" alt="NetOrbit"></a>
<a href="docs/SETUP.md"><img src="docs/nav/setup.svg" width="250" alt="Setup guide"></a><br>
<a href="#settings"><img src="docs/nav/settings.svg" width="250" alt="Settings"></a>
<a href="#entities-events-and-services"><img src="docs/nav/services.svg" width="250" alt="Automations"></a>
<a href="#requirements-and-limits"><img src="docs/nav/limits.svg" width="250" alt="Limits and privacy"></a>
</p>

![NetOrbit card](docs/full.png)

| Watch it find your network | Share your map |
| --- | --- |
| ![The first scan: a radar sweeps around the router, then every device pops in](docs/scan.gif) | ![A shared map with generic names and no addresses](docs/share.png) |

## What it does

- **Watch the first scan happen.** Right after you add NetOrbit, the card shows a radar sweeping around your router with a live count of what it has found ("Scanning your network... found 12 devices") and what it's doing right now. When the scan is done, the map plays in: hubs and devices pop up as the beam passes them, the links draw in and the names fade in. Later scans just show a small *Scanning...* chip. If your device asks for less motion, the radar stays still and the map fades in instead. You can replay the animation from the Share menu any time.
- **Share your map.** The *Share* button makes a picture of your map to download or copy, or a short video of the scan animation. Device names are hidden by default, so a TV shows up as "TV 1" and a camera as "Camera 2", and hubs only show their type. Turn names back on with one switch. IP and MAC addresses are never in what you share, and neither are devices waiting to be added or suggested hubs.
- **Finds every device.** Sweeps your subnet, learns MAC addresses from the ARP table, and names devices from what your setup already knows: Home Assistant's device list, device trackers, Ping sensors you've set up, your router's local DNS, or the name the device announces over Bonjour. When nothing knows a name, it falls back to the maker (for example "Apple 28:54"), and you can rename it.
- **Finds your network gear.** Spots routers, switches, access points and mesh nodes from who made them, what they call themselves, what they announce on the network, and what other integrations already know. Obvious ones are added for you. Likely ones show up with a spinning pink ring and a one-tap "It's a hub / Not a hub".
- **Works out where each device connects, when your network will say:**
  - **Managed switches with SNMP:** NetOrbit reads their MAC address tables and works out which switch port, and so which access point, every device is behind. No port mapping needed.
  - **Grandstream GWN access points with SNMP:** NetOrbit reads each access point's own Wi-Fi client list, so every wireless client shows under the access point it is connected to.
  - **UniFi**, and other integrations that report which access point each client uses (Netgear/Orbi's per-device "connected AP" sensors, for example).
- **Lets you place the rest, three ways:**
  1. **Drag and drop on the card.** Tap *Edit layout*, drag a device onto its hub, or tap it for *Move to*, *Make it a hub* and *Automatic*. To move a hub (a switch from the router to an access point, say), tap the hub in Edit layout and pick *Connected to*.
  2. **Paste a client list.** Copy the client list from an access point's web page or a mesh app, paste it into NetOrbit, pick the hub. Done.
  3. **Ask an AI assistant.** NetOrbit exposes tools to Claude, ChatGPT and other assistants through Home Assistant's MCP Server, and to Assist. The assistant walks you through each piece of gear and does the placing. See [docs/ASSISTANT.md](docs/ASSISTANT.md).
- **Looks good even when it knows nothing.** If no source reports the layout, devices are grouped by type (TV and media, computers and phones, cameras, smart home) until you place them.
- **Remembers when it last saw each device.** Green = answering, yellow = seen within your window (24 h by default), red = gone longer than that. Survives restarts.
- **Events for automations,** plus ready-made notification blueprints.
- **Lightweight.** One ping round per interval (default 60 s), one subnet sweep every 5 minutes, one SNMP question per device per hour. A few kilobits per second.

| Wired with access points | Mesh system | Mesh with nothing reporting placement |
| --- | --- | --- |
| ![](docs/full.png) | ![](docs/mesh.png) | ![](docs/novice.png) |

| Editing on the card |
| --- |
| ![](docs/edit.png) |

<p align="right"><sub><a href="#netorbit">back to the map</a></sub></p>

## Tested on simulated networks

Every release is run against hundreds of generated home networks (see [the network simulator](#the-network-simulator)). These are a few of them, drawn by the real card from the real integration's output.

| Router only, 25 devices | Mesh with nothing reporting placement |
| --- | --- |
| ![](docs/sim-flat-25.png) | ![](docs/sim-mesh.png) |

| UniFi | Managed switches with SNMP |
| --- | --- |
| ![](docs/sim-unifi.png) | ![](docs/sim-snmp.png) |

| 330 devices behind three managed switches | 360 devices on a busy mesh network |
| --- | --- |
| ![](docs/sim-big-snmp.png) | ![](docs/sim-big-mesh.png) |

| After three rounds of DHCP changes |
| --- |
| ![](docs/sim-dhcp-tip.png) |

Big networks fold quiet devices into "+N more" bubbles (tap one to see the list), while devices that need attention and possible hubs always stay on the map. In the DHCP shot the router reshuffled addresses three times; every name, icon and placement followed its MAC address, and hovering a device whose IP changed shows the reservation tip.

<p align="right"><sub><a href="#netorbit">back to the map</a></sub></p>

## Placing devices by hand

Whatever NetOrbit can't work out, you can fix in about a minute. Full guide, including turning on SNMP so you barely have to: **[docs/SETUP.md](docs/SETUP.md)**.

| Drag a device onto its hub | Confirm a possible hub | On a phone |
| --- | --- | --- |
| ![](docs/howto-drag.gif) | ![](docs/howto-confirm-hub.gif) | ![](docs/howto-phone-move.gif) |

### Renaming a device and telling similar devices apart

In **Edit layout**, tap a device to open its menu. It has a **Name** field, like the one hubs have: type a name and press **Save name** (or Enter). Empty the field to go back to the automatic name. The name follows the device's MAC address, so it survives a new IP address and restarts. NetOrbit saves it as its own name for the device, and the device's sensor in Home Assistant takes that name, so the map, Home Assistant, backups and AI assistants all show the same one. If you had set a name in the sensor's entity settings in Home Assistant, that name is changed too, because it would otherwise hide the new one. Names are cut at 64 characters.

The menu also shows the device's IP address, MAC address, maker and when it was last seen, even when `show_ip` is off, so you can tell which is which before you name it. Devices that use a private (randomized) MAC address get a note that the name may not stick if the device changes its address.

Tip for two devices that look the same, such as two from the same maker: power one off, or look up its IP address in its own app, then see which circle goes grey or which IP matches. Name it, then do the other.

<p align="right"><sub><a href="#netorbit">back to the map</a></sub></p>

## What your network can tell NetOrbit

| Your setup | Hubs found | Devices placed under the right hub |
| --- | --- | --- |
| UniFi with the UniFi integration | Automatically | Automatically (wireless clients) |
| Managed switches with SNMP on | Automatically | Automatically (wired and wireless, through the switch port) |
| Netgear/Orbi with the Netgear integration | Suggested | Automatically, once you enable its "connected AP" sensors |
| eero, Google/Nest Wifi, Deco, Velop, ISP routers | Suggested | By you: drag and drop, paste a list, or an AI assistant |

How to turn each of these on, step by step: [docs/SETUP.md](docs/SETUP.md).

Placement you choose always wins over automatic placement. Each device shows how it was placed, and *Automatic* hands it back to NetOrbit.

<p align="right"><sub><a href="#netorbit">back to the map</a></sub></p>

## Install

NetOrbit is in the default store, so you can find it by searching. On Home Assistant 2026.11 and newer that's the built-in **Marketplace**; on older versions it's **HACS**. It's the same repository either way.

NetOrbit needs Home Assistant 2026.2 or newer.

### Marketplace (Home Assistant 2026.11 and newer)

[![Open NetOrbit in the Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=the-scott-davis&repository=netorbit&category=integration)

1. Click the button above, or go to **Settings > Marketplace** and search for **NetOrbit**.
2. Download it. Home Assistant shows a warning that community code runs with full access to your home; read it and confirm.
3. Set it up when asked, or go to **Settings > Devices & services > Add integration > NetOrbit**. The subnet and router are filled in for you. No restart is needed for a first install.
4. Refresh your browser once so the card loads, then [add the map to a dashboard](#add-the-map-to-a-dashboard).

Updates show up in **Settings > Updates** like any other. Updating still needs a restart.

### HACS (Home Assistant 2026.10 and older)

1. In HACS, search for **NetOrbit** and download it, then restart Home Assistant.
2. Go to **Settings > Devices & services > Add integration > NetOrbit**.
3. [Add the map to a dashboard](#add-the-map-to-a-dashboard).

HACS on 2026.10 and older shows a blank icon for NetOrbit in its list. That's expected: older HACS only looks up icons on Home Assistant's brand site, which no longer takes new custom integrations. NetOrbit ships its own icon, which Home Assistant shows on the integration's page and the Marketplace shows everywhere.

When you later update to 2026.11, Home Assistant moves NetOrbit into the Marketplace for you. Nothing to reinstall, and your settings stay.

### Manual

Copy `custom_components/netorbit` into your Home Assistant `config/custom_components` folder, restart, add the integration under **Settings > Devices & services**, then [add the map to a dashboard](#add-the-map-to-a-dashboard). You won't get update notifications this way.

## Add the map to a dashboard

Setting up the integration starts tracking your devices (you'll see them as entities), but the map itself is a dashboard card. Add it once:

1. Open a dashboard and click the pencil (**Edit dashboard**) in the top right.
2. Click **Add card**, search for **NetOrbit**, pick it and save.

Or paste this into a **Manual** card:

```yaml
type: custom:netorbit-card
title: Home Network
```

**Full screen looks best.** Go to **Settings > Dashboards > Add dashboard** and make one just for the map. Edit its view, set the view type to **Panel (single card)**, and add the NetOrbit card there.

**NetOrbit isn't in the card search, or the card says "Custom element doesn't exist"?** First make sure you've added the integration under **Settings > Devices & services**. The card only loads once NetOrbit is set up there. Then do a hard refresh (Ctrl+Shift+R, or Cmd+Shift+R on a Mac). The integration serves the card itself, so normally there's no dashboard resource to add. If it still won't load on Home Assistant 2026.10 or older, update NetOrbit to 0.2.3 or newer, or add `/netorbit/netorbit-card.js` as a **JavaScript module** under **Settings > Dashboards > three-dot menu > Resources** and remove it again after updating.

Next: tap any device for its details, and use **Edit layout** to place anything NetOrbit couldn't work out. The [setup guide](docs/SETUP.md) covers getting more of it placed for you.

<p align="right"><sub><a href="#netorbit">back to the map</a></sub></p>

## Settings

Under the integration's **Configure** menu:

| Option | What it does |
| --- | --- |
| Review suggested hubs | Confirm or dismiss everything NetOrbit thinks might be network gear. |
| Paste a client list | Paste a client list from an access point, app or switch, pick the hub, and every device in it is placed there. |
| Add / edit a hub | Add gear NetOrbit can't see, rename hubs, change what they connect to, *Managed by* and extra fields. |
| Track / edit a device | Name, icon, hub (or *Automatic*), "allowed to sleep", *Managed by*, extra fields, stop tracking. |
| Review new devices | In manual mode, choose which newly found devices to track. |
| Settings | Tracking mode, ping and scan intervals, the "not seen" window, randomized MACs, automatic hubs, grouping by type, the internet check, DNS names first, SNMP on/off and SNMP community. |

**Tracking mode:** *Automatic* tracks everything it finds. *Manual* only tracks devices you add, and lists the rest under "New devices".

**Managed by and extra fields** are free text on any hub or device: a link to its admin page, the name of the switch or controller that manages it (the map jumps there), a location, a serial number, who owns it. Tap the device on the map to read them, and *Edit* (admins) to change them; `netorbit.update_device` and `netorbit.update_hub` set them too.

**Prefer DNS and Bonjour names** (off by default) puts the name your network gives a device first, before what other integrations call it, and uses it for hubs NetOrbit named itself, such as *Router*. Anything you renamed yourself keeps your name.

**Allowed to sleep** is for TVs, consoles and anything else that's off a lot. They still show their status but never fire the stale event.

**Hubs with no IP**, such as an unmanaged switch or an access point in bridge mode, can't be pinged, so they take their status from what's behind them: green if anything behind them is online, yellow if something was seen recently, red only when nothing behind them has been seen for the "not seen" window, and grey when nothing is behind them yet or when the only devices behind them are sleeping and off.

A hub with no IP that has the Home Assistant host behind it stays green as long as Home Assistant can ping itself, which it normally can.

**The internet check** (on by default) puts an Internet node just above your router. Each ping round also pings two public DNS servers, Cloudflare's `1.1.1.1` and Google's `8.8.8.8`. The node turns red ("Internet down") when neither answers for two rounds in a row while your router still answers, so you can tell an internet outage from a Wi-Fi problem. If the router isn't answering either, it shows grey, because NetOrbit can't tell. Turn it off under **Settings** if you'd rather NetOrbit never sends anything outside your network.

### DHCP, MAC addresses and keeping your setup

Most homes hand out addresses with DHCP, so a device's IP can change at any time. NetOrbit is built for that:

- **Everything is keyed by MAC address.** Names, icons, hub placement, "allowed to sleep" and history all follow the device's MAC, so a new IP changes nothing. When a device's IP changes, NetOrbit just pings the new one.
- **Hubs follow their MAC too.** If an access point gets a new IP, NetOrbit notices on the next sweep and updates it.
- **Devices added by IP switch to their MAC** as soon as NetOrbit sees them on the network, so they survive the next DHCP change as well.
- **Renaming works either way.** Rename from the card (Edit layout, tap a device), in NetOrbit's settings, from an AI assistant, or in Home Assistant's own entity settings; the map uses the newest name you set. The one exception is a name typed into Home Assistant's entity settings, which wins over NetOrbit's name until you clear it there (renaming from the card changes it for you).
- **Back up your setup.** `netorbit.export_config` returns every name, icon, hub and placement, keyed by MAC. `netorbit.import_config` restores it (merging by default), for example after reinstalling. *Managed by* and extra fields in an import get the same checks as when you type them; any that fail are left out and counted as `skipped` in the response.

Tips for the tidiest map:

- **Give network gear a DHCP reservation** (sometimes called a static lease or address reservation) in your router: switches, access points and mesh nodes. NetOrbit copes without it, but reserved addresses keep everything else that talks to them happy too. Hovering a hub whose IP has changed shows this tip.
- **Reserve addresses for devices other things depend on**, like printers, NAS boxes, cameras and Home Assistant itself. Hovering a device whose IP keeps changing shows a reminder.
- **Phones and laptops** usually use a private (randomized) MAC address per network. NetOrbit hides those by default. Turn off *Ignore randomized MAC addresses* if you want them: on current phones the private address normally stays the same for your network unless the phone is set to rotate it.

### SNMP

SNMP is how managed switches share their MAC address tables. NetOrbit only ever reads (it never changes anything). Once an hour it asks devices whether they speak SNMP using the factory "public" community. Your own community is only sent to hubs, suggested hubs and gear from network makers, because SNMP v2c sends it unencrypted and any device that receives it could read it.

- If your switches still use the factory read-only community, there's nothing to do.
- If you changed it (good idea), enter it under **Settings > SNMP community**. Letters and numbers only work best; some switches silently ignore communities with symbols.
- Where to turn SNMP on for UniFi, Omada and other switches, and which switches don't have it: [docs/SETUP.md](docs/SETUP.md#2-turn-on-snmp-on-managed-switches).
- Grandstream GWN access points: turn SNMP on in the access point and NetOrbit reads its Wi-Fi client list. See [docs/SETUP.md](docs/SETUP.md#grandstream-gwn-access-points).
- Consumer routers and mesh systems don't support SNMP. That's normal.

<p align="right"><sub><a href="#netorbit">back to the map</a></sub></p>

## Card options

| Option | Default | Description |
| --- | --- | --- |
| `title` | `Network` | Card title. |
| `height` | `900` | Maximum height: pixels, or a CSS length. `calc(100vh - 180px)` fills the window below the header on any screen. |
| `show_ip` | `false` | Show hub IPs under their names instead of the hub type. Off by default so screenshots are safe to share. |
| `show_legend` | `true` | Show the legend at the bottom. |
| `show_internet` | `true` | Show the Internet node above the router (needs the internet check turned on in the integration's settings). |
| `group_by_type` | `true` | Group unplaced devices by type. |
| `hide_sleepy_offline` | `false` | Hide sleep-allowed devices while they're offline. |
| `max_devices` | `80` | Above this many devices, each hub shows its problem devices first and folds the rest into a "+N more" bubble. |
| `zoom` | `true` | Pinch, double-tap, Ctrl/Cmd+scroll or the + and − buttons zoom the map; drag to look around while zoomed in. `false` for a fixed map. |
| `device_id` | | Only show one NetOrbit entry when you have several. |
| `show_share` | `true` | Show the Share button (image or video of the map, with names hidden by default and no addresses). |
| `layout` | `radial` | `radial`: every device on one ring round the router. `balloon`: each hub in the middle of its own ring of devices, with the hubs below it branching away (good for chains of switches and busy access points). A pick in the header's Radial \| Balloon switch overrides this for that card in that browser, until the card's options are edited. |
| `layout_toggle` | `true` | Show the Radial \| Balloon switch in the header. With `false` the card always shows its `layout`. |

Hover a device for a summary. Tap a hub or device for its details: DNS name, addresses, maker, the hub it connects through and how it was placed, *Managed by* and extra fields, first and last seen. *More info* there opens Home Assistant's own dialog. **Long-press a hub** to show just its branch (the hubs and devices below it). The hub above shows in grey: long-press it to go up a level, or use the row under the header to go back up. Pinch or double-tap to zoom in on a busy part of the map (Ctrl/Cmd+scroll with a mouse, or the + and − buttons), drag to look around, and zoom out again to scroll the page past the map. Admins get **Edit** in the popup and an **Edit layout** button on the card. Everyone gets **Share**: a PNG to download or copy, or a 7 second video of the scan animation (mp4 where the browser can record it, otherwise webm). The video option only shows up in browsers that can record a canvas, and Copy only where the browser can put images on the clipboard.

<p align="right"><sub><a href="#netorbit">back to the map</a></sub></p>

## Entities, events and services

- One sensor per hub and tracked device. State is `online`, `recent` or `stale` (unknown for a hub with no IP and nothing behind it). Attributes include `ip`, `mac`, `vendor`, `link` (the hub), `placement` (`manual`, `controller`, `snmp` or `none`), `last_seen`, `hostname`, `fqdn` (the full DNS name), `sleepy`, `managed_by` and `fields`.
- `sensor.netorbit_devices_online` counts online devices and lists `new_devices` and `suggested_hubs`. While a network scan runs it also shows `scanning: true`, the current `scan_phase` (`ping`, `arp`, `names`, `snmp`, `layout`), a rough `scan_progress` (0 to 100) and how many addresses it has `found` so far. `first_scan_done` turns true once the very first scan on this install has finished.
- `sensor.netorbit_internet` (when the internet check is on): `online`, `stale` (down while the router answers) or unknown.

| Event | Data |
| --- | --- |
| `netorbit_new_device` | `name`, `ip`, `mac` |
| `netorbit_device_stale` | `name`, `ip`, `mac`, `kind`, `last_seen` |
| `netorbit_device_recovered` | `name`, `ip`, `mac`, `kind`, `last_seen` |
| `netorbit_internet_down` | `since` |
| `netorbit_internet_up` | `since` |

Every service returns a response describing what it did. Devices can be given by name, IP or MAC; hubs by name or id.

| Service | Fields |
| --- | --- |
| `netorbit.assign_device` | `device` (one or a list), `hub` |
| `netorbit.reset_placement` | `device` |
| `netorbit.import_client_list` | `hub`, `text`, `add_missing` |
| `netorbit.add_hub` | `name` or `device`, `type`, `parent`, `ip`, `mac` |
| `netorbit.update_hub` | `hub`, `name`, `type`, `parent`, `managed_by`, `fields` |
| `netorbit.remove_hub` | `hub` |
| `netorbit.confirm_hub` | `device`, `type`, `name` |
| `netorbit.dismiss_hub` | `device` |
| `netorbit.track_device` | `mac` or `ip`, `name`, `icon`, `hub`, `sleepy` |
| `netorbit.update_device` | `device`, `name`, `icon`, `hub`, `sleepy`, `managed_by`, `fields` (`{label: value}`, an empty value removes the label) |
| `netorbit.export_config` | none (returns your settings, keyed by MAC) |
| `netorbit.import_config` | `data` (an export), `replace` |
| `netorbit.ignore_device` | `device` or `mac` or `ip` |
| `netorbit.scan_now` | none |

### Blueprints

- [Notify when a device goes offline](blueprints/automation/netorbit/device_offline_notify.yaml)
- [Notify when a new device joins](blueprints/automation/netorbit/new_device_notify.yaml)

Import either from **Settings > Automations & scenes > Blueprints > Import blueprint** using the file's GitHub URL. The Marketplace and HACS install the integration only, so blueprints are always imported this way.

<p align="right"><sub><a href="#netorbit">back to the map</a></sub></p>

## Requirements and limits

- Home Assistant needs to be on the same network as your devices, with host networking. Home Assistant OS and supervised installs are. Docker installs need `network_mode: host`.
- Presence is based on ping. Devices that block ping show as not seen even when connected. Mark them as allowed to sleep, or ignore them.
- Phones and laptops often use a private MAC address per network. Those are ignored by default since they can change, and they roam between access points anyway.
- If an access point and wired devices share one switch port through an unmanaged switch, the switch can't tell them apart, so those wired devices may be drawn under the access point. Move them by hand if it matters to you.
- Placements from pasted lists are a snapshot. TVs, cameras and smart home gear stay put, so that's fine for them.
- IPv4 only, up to 1024 hosts per entry. Add one entry per subnet if you have several.

<p align="right"><sub><a href="#netorbit">back to the map</a></sub></p>

## Privacy

NetOrbit runs on your network. The only thing it sends outside it is the internet check: a ping to `1.1.1.1` and `8.8.8.8` each round, which you can turn off under **Settings**. No data about your network goes with it. Maker names come from a list bundled with Home Assistant. Diagnostics downloads replace every IP, MAC and name with placeholders, so they're safe to attach to an issue. The card hides IPs by default. Shared images and videos are made in your browser and never hold an IP or MAC address; with "Hide device names" on (the default) they hold no names either.

## Roadmap

- Omada placement through the Omada controller.
- ARP based presence for devices that block ping.
- A visual card editor.

<p align="right"><sub><a href="#netorbit">back to the map</a></sub></p>

## Contributing

Pull requests are welcome from anyone, no permission needed. Fork the repo, make a branch, and open a PR against `main`. PRs are squash-merged with you kept as the commit author, so you show up in the history and the Contributors list. [CONTRIBUTING.md](CONTRIBUTING.md) has the full steps, what CI checks, and how review and releases work.

To run the checks locally:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
node --test tests/card.test.js
python scripts/check_examples.py
```

The section map at the top of this page is drawn by `python scripts/docs/nav.py` (it needs the `mdi.js` file described below).

Examples, tests and docs only use the address ranges reserved for documentation (`192.0.2.x`, `00:00:5e:00:53:xx`), never values from a real network. `scripts/check_examples.py` enforces that, and CI runs it on every push.

Preview the card with fake data: `npm i @mdi/js@7.4.47` and copy `node_modules/@mdi/js/mdi.js` to `scripts/preview/`, serve the repo root (`python -m http.server 8766`), and open `http://localhost:8766/scripts/preview/index.html?s=full` (or `mesh`, `flat`, `novice`). `scripts/preview/interact.js` drives edit mode in a real browser with Playwright.

### The network simulator

`tests/test_simulation.py` generates hundreds of home networks with a known true layout (flat routers, mesh with nothing reporting, UniFi, one or several managed switches, unmanaged switches in between, routers that speak SNMP, odd gateways, randomized MACs, devices that ignore ping, DHCP churn, aged-out MAC table entries, wrong SNMP communities, duplicate and non-ASCII names, up to several hundred devices) and runs the real integration against each one. It fails on crashes, duplicates, loops, devices placed on the wrong branch, manual placement not winning, state lost on restart, or real addresses in diagnostics. `pytest -s -k simulation` prints a report of how much it found and placed.

To draw every simulated map in a browser and check for errors and overlaps: `NETORBIT_DUMP=scripts/preview/_simstates pytest -k simulation`, serve the repo root, then `node scripts/preview/fuzz.js`.

## License

MIT
