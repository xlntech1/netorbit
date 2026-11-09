# Changelog

## Unreleased

### Added
- **Tap a hub or device for its details.** Outside Edit layout, a tap opens a NetOrbit popup with the DNS name, IP, MAC, maker, the hub it connects through and how it was placed, when it was first and last seen, and any text you attached to it. *More info* still opens Home Assistant's own dialog. Admins get *Edit* there to change the name, *Managed by* and the extra fields.
- **Managed by and extra fields.** Every hub and device can carry a *Managed by* line (a link, or the name of another hub or device on the map, which the popup then jumps to) and up to 20 extra fields (`Label: value`). Set them from the details popup, the integration's *Edit* forms, the new `netorbit.update_device` service, `netorbit.update_hub`, or an AI assistant. Exports include them, and an import checks them the same way (anything that fails is left out and counted).
- **Prefer DNS and Bonjour names** (Settings, off by default). The name your network gives a device comes first, before names from other integrations, and replaces names NetOrbit made up for hubs, such as *Router*. Names you typed are kept. Every sensor now also carries the full DNS name as `fqdn`.
- **Balloon layout.** A Radial | Balloon switch in the card header. In the balloon layout every hub sits in the middle of its own ring of devices, and hubs below it branch away from it, each with room for everything under it. A chain of switches (one feeding the next) becomes a line of hubs instead of piling up beside the router, busy access points get a circle each, and the map is turned to fill the card's width. The card option `layout: balloon` makes it the card's layout, and `layout_toggle: false` hides the switch, so the card always shows its `layout`. A pick in the switch is remembered in that browser for that card only, and editing the card's options starts it again from its `layout`. The radial map is unchanged and stays the default. Share (image and video) uses whichever layout is on show; a balloon share gets a frame of the map's own shape (thanks @ninchistudios, #66).
- **Show one branch on its own.** Long-press a hub with something below it to see just that hub, the hubs under it and their devices, in either layout. The hub above the branch hangs off it in grey ("Up a level"): long-press it, or the middle hub, to go up a level. A row under the header also leads back up (Whole map, or any hub on the way). The counts in the header are for the branch on show (thanks @ninchistudios, #66).

### Fixed
- The first change made in Settings after a restart was ignored when NetOrbit had saved something itself during its first sweep (a hub's MAC address, a DHCP move).
- Opening a second popup over the first (for example *Edit* from a device's details) no longer freezes the map until the page is reloaded.
- **A popup left open no longer freezes the map.** The map didn't redraw while a popup was open, so one left open (on a wall panel, say) stopped all updates until someone closed it. The details popup now updates along with the map, and every popup closes on a tap outside it, on Escape, and after two minutes without a touch; a tap on another device still opens that device's popup, and a form with unsaved changes stays open until you close it.
- A tooltip shown on a map redrawn under the mouse now appears next to the pointer, not in the corner of the card (thanks @ninchistudios, #66).

## 0.3.1

### Changed
- **Releases now carry `netorbit.zip`.** Each release attaches the integration as a zip, and HACS and the Marketplace install from it. This gives NetOrbit a download count in both stores. The count starts with the first release that has the zip and includes updates, so it runs higher than the number of users.

## 0.3.0

### Added
- **Grandstream GWN access points over SNMP.** NetOrbit reads the Wi-Fi client table (`GRANDSTREAM-GWN-MIB`) from Grandstream access points you have as hubs and places their clients under the access point they're connected to. Not yet tested on real Grandstream hardware, so reports are welcome (thanks @fluffymadness for the request and the MIB details, #18).
- **Rename a device from the card** (#24). In Edit layout, tap a device and use the Name field; empty it to go back to the automatic name. The name is saved by MAC address, so it follows the device across IP changes, and the device's sensor takes it too. The device menu now shows IP, MAC, maker and last seen even with `show_ip` off, notes when a private (randomized) MAC may not keep a name, and stays inside the map on small phones.

### Fixed
- **A device that leaves no longer stays online when DHCP hands its address to another device** (thanks @ninchistudios, #47). A ping reply now only counts for the device whose MAC answered, read from ARP, so the device that left goes offline and its alert fires. Hubs given a base MAC, devices behind a MAC-rewriting repeater, devices added by IP only and the Home Assistant host count as before.
- **A hub given by MAC now matches exactly** before a near MAC is considered, so access points bought together aren't confused (thanks @xlntech1, #41).
- **A mesh node that bridges through an access point** no longer sends that switch port's devices back to the switch once you lock its parent to the access point (thanks @xlntech1, #51).
- **Touching the map no longer swipes the dashboard to another view** while the map is zoomed in, in Edit layout or mid-pinch, on dashboards that swipe between views. At the whole map a sideways swipe still changes views (thanks @xlntech1, #31).
- **Assistant tools on Home Assistant 2026.10.** NetOrbit's AI assistant tools now answer in the format Home Assistant 2026.10 expects (thanks @xlntech1, #30). No more deprecation warning on every call, and they keep working after 2027.11, when the old format stops being accepted. Older Home Assistant versions work as before.
- **The assistant tool that undoes hand placement** (`netorbit_reset_placement`) is now marked destructive, since those placements can only be set again by hand (thanks @xlntech1, #52).
- **Saved videos start right away** and end without the long pause at the start and end (#29).

### Known issues
- **Devices that left before you upgraded may show online.** If a device left before 0.3.0 and its address has since gone to another device, it can stay online, because the #47 check needs an address saved by 0.3.0. To clear it, open the device under the integration's Configure menu and choose "Stop tracking and ignore this device", or call `netorbit.ignore_device`. This happens only once: devices that leave from now on go offline as #47 describes (thanks @ninchistudios, #65).

## 0.2.10

### Fixed
- The radar beam no longer swings around the whole card during the map reveal and "Replay scan animation". It now turns around the router, as on the live scan. The reveal moves the beam with a transform attribute, and a leftover CSS transform origin shifted the turn to the wrong point.
- The shared scan video (Share, Animation, Save video) no longer freezes after a second and then jumps ahead. The animation is now stepped one frame at a time at 30 frames per second, so a stall can pause the video but never skip ahead. Frames are handed to the recorder one by one, the first frame is held for half a second while the encoder starts, and the status line updates a few times a second instead of every frame. The video is about half a second longer.

## 0.2.9

### Added
- **Zoom and pan the map.** Pinch, double-tap or Ctrl/Cmd+scroll to zoom, drag to look around, or use the + and - buttons (thanks @xlntech1, #12). Turn it off with the card option `zoom: false`.
- **Card `height` takes any CSS length**, like `80vh` or `calc(100vh - 180px)`, so the map can fill a Panel view (thanks @ninchistudios, #11). Plain numbers still mean pixels.
- **First-scan animation on the card.** While the first scan on a new install runs, the card shows a radar sweeping around the router, a "Scanning N%" chip, and a pill at the bottom with how many devices it has found and what it's doing, updated live. When the map arrives it plays in once: the beam turns, hubs and devices pop in as it passes, links draw in, then the labels and the normal header come back. Later scans only add a small "Scanning..." chip before Edit layout. With reduced motion turned on, there's no beam or pulsing, the range rings stay still and the map fades in.
- **Share your map.** A Share button in the card header makes a PNG of the map (download, or copy where the browser allows) or a short video of the scan animation (mp4 where the browser can record it, otherwise webm). On phones and other browsers with a share sheet, the file opens in it instead of downloading. "Hide device names" is on by default: devices become "TV 1", "Camera 2" and so on, hubs show only their type, and the title becomes "My home network". IP and MAC addresses are never included, and devices waiting to be added and suggested hubs are left out. Turn the button off with the card option `show_share: false`.
- "Replay scan animation" in the Share popup plays the reveal again.
- Move a hub under another hub from the card: in Edit layout, tap the hub and pick Connected to. (#20)
- Scan progress on `sensor.netorbit_devices_online`: `scanning`, `scan_phase`, `scan_progress`, `found` and `first_scan_done`. They change a few times per scan, for the first scan and for the regular ones, and stay out of the history database (`first_scan_done` aside).

### Changed
- **Faster startup.** Home Assistant no longer waits for NetOrbit's network scan when it starts, so the "Waiting for integrations to complete setup: netorbit" message is gone. NetOrbit draws the map from what it saved and pings those devices, then runs the full scan (ping sweep, ARP, names, SNMP) in the background and updates the map when it's done. The hub tree from the last scan is saved too, so the map looks the same right after a restart.
- A brand new install finishes setup right away and fills the map once the first scan is done.

### Fixed
- The Home Assistant host itself now shows on the map (#10, reported by @ninchistudios). A machine never has an ARP entry for its own address, so it was never found. NetOrbit now adds the host from Home Assistant's network adapters when an adapter address is inside the watched subnet (a container on a Docker bridge network is skipped). It is named "Home Assistant" unless a hostname is known and gets the Home Assistant icon. The first scan after upgrading reports the host as a new device once. If you added the host by hand, that entry is kept and not doubled.
- A mouse button released just outside the map no longer leaves the map panning whenever the mouse moves over it.
- A Home Assistant update that arrives while you tap or press the map is drawn when you let go. Before, it waited for the next update.
- Ctrl+scroll zooms at the same speed in Firefox, which reports scroll in lines.
- Hubs with no IP (an unmanaged switch, or an access point in bridge mode) no longer turn red once the "not seen" window passes. NetOrbit can't ping them, so they now take their status from the devices behind them: green while anything behind them answers, red only once nothing behind them has been seen for the window, grey when nothing is behind them. Before, they went red (and fired `netorbit_device_stale`) a day after being added, whatever was behind them (thanks @ninchistudios, #22).

## 0.2.8

### Added
- **Internet node.** An Internet globe sits just above the router. Each ping round also pings two public DNS servers (1.1.1.1 and 8.8.8.8). It turns red ("Internet down") when neither answers for two rounds in a row while the router still answers, and grey when the router isn't answering either. Comes with `sensor.netorbit_internet` and `netorbit_internet_down` / `netorbit_internet_up` events. On by default; turn it off under Settings ("Show the internet on the map"), or hide just the node with the card option `show_internet: false`.

### Changed
- Devices you placed by hand are easier to spot in Edit layout: their circle fills blue and gets a pin badge, while the outline keeps its green, yellow or red status. Before, it was a small blue dot.

### Fixed
- You can change a hub's type from the card: in Edit layout, tap the hub and pick a Type (Switch, Access point, Mesh node or Hub). Before, the hub menu only offered rename and remove.
- 0.2.7 could move a wireless device to the router after a restart, when the switch next to the router had forgotten it but a switch further down still listed it on its uplink. Only switches plugged straight into the router count as proof that a device is wired to the router now; otherwise the device keeps its last placement.

## 0.2.7

### Fixed
- Making a device a hub (or removing a hub) places the devices behind it straight away. Before, the map waited for the next network scan, up to 5 minutes. NetOrbit now works the layout out again from the switch tables it already has.
- With SNMP, a device the switches only ever see on the port facing the router (plugged into the router itself, into an unmanaged switch on it, or on the router's own Wi-Fi) is placed under the router. Before, it stayed unplaced.

## 0.2.6

### Changed
- Moving a device is instant. After a drag (or Move to), the device is drawn under its new hub right away with a spinning blue "saving" ring until Home Assistant confirms. Before, nothing happened on screen for a second or two.
- Any change from the card, a service or an AI assistant redraws the map straight away from what NetOrbit already knows, and checks the network afterwards in the background. Before, every change waited for a full ping round, which takes a couple of seconds when some devices don't answer.

## 0.2.5

### Changed
- Dragging a device onto a suggested hub (the spinning pink ring) now asks "Make it a hub?" and, if you say yes, makes it a hub and moves the device under it in one step. Before, suggested hubs ignored the drop.
- The `confirm_hub` service takes an optional `assign` list of devices to place under the new hub.

## 0.2.4

### Fixed
- Map icons on Safari and in the iOS/iPadOS companion app sat away from their circles, like a second ring of loose icons. Icons are now drawn as part of the map itself, so every browser puts them in the same place.

Thanks to @mgeorgieff for tracking this down and fixing it in #2.

## 0.2.3

### Fixed
- On Home Assistant 2026.10 and older, the card could fail to load: the card picker showed a tile that spun forever, and a NetOrbit card said "Custom element doesn't exist". The card script sometimes loaded a moment before Home Assistant was ready and got lost. It now registers itself again once Home Assistant is ready.

### Changed
- When setup finishes, NetOrbit tells you the one remaining step: add the NetOrbit card to a dashboard. The README has a new "Add the map to a dashboard" section, including a full-screen Panel view.

## 0.2.2

### Security
- AI assistant tools that change the map now require a Home Assistant admin. Reading the map is still open to the assistant. Voice satellites and other callers with no user can't make changes.
- The assistant prompt tells the model to treat device names as data and never act on instructions inside them, since any device can pick its own name.
- Your custom SNMP community is only sent to hubs, suggested hubs and network-gear makers, not to every device on the network. SNMP v2c sends it unencrypted. Gear suggested during a scan is asked in the same scan.

Thanks to @ninchistudios for the review in #1.

## 0.2.1

### Fixed
- Drag and drop now judges the drop where you let go, so a quick flick onto a hub works.
- Google and Nest devices get an icon that exists (one was blank).
- Hub labels no longer overlap each other on busy maps.
- After an update, browsers load the new card right away instead of a cached copy.
- Uses the current Home Assistant field for a device's integration (the old one is deprecated and logged a warning on 2026.10).

## 0.2.0

First public release.

### Added
- Ready for the Home Assistant Marketplace (2026.11 and newer) as well as HACS: brand icon shipped with the integration, Marketplace categories, install docs for both.
- Hub detection: obvious network gear is added for you, likely gear is suggested with a one-tap confirm or dismiss.
- SNMP: reads managed switch MAC address tables to place wired and wireless devices automatically. Community is configurable and redacted from diagnostics.
- Controller placement from UniFi and Netgear/Orbi "connected AP" data.
- Three ways to place devices by hand: drag and drop on the card, paste a client list, or an AI assistant through Home Assistant's MCP Server and Assist.
- DHCP handling: everything is keyed by MAC, hubs follow their MAC to new IPs, devices added by IP switch to their MAC, IP change counts with DHCP reservation tips on the card.
- `netorbit.export_config` and `netorbit.import_config` to back up and restore your setup.
- Large networks fold quiet devices into "+N more" bubbles (`max_devices`, default 80). Problem devices and possible hubs always stay on the map.
- Devices are grouped by type until NetOrbit knows where they connect, using the name or, failing that, the maker.
- Names come from Home Assistant's device list (skipping entries that are just a MAC), device trackers, Ping sensors you already set up, the router's local DNS, and Bonjour.
- Possible hubs have their own color (pink), so they never look like "seen recently".
- Network simulator and browser tests covering hundreds of generated home networks.

### Changed
- Needs Home Assistant 2026.2 or newer.

## 0.1.0

- Initial version: ping sweep, ARP, radial card, events and blueprints.
