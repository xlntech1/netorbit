// Fake networks for previewing the card without Home Assistant.
// Every address is from documentation ranges (192.0.2.0/24, 00:00:5e:00:53:xx).
(function () {
  let n = 0;
  const mac = () => "00:00:5E:00:53:" + (n++).toString(16).padStart(2, "0").toUpperCase();
  const ago = (h) => new Date(Date.now() - h * 3600e3).toISOString();

  function build(def) {
    const states = {};
    let ip = 10;
    const hub = (key, label, type, parent, status = "online") => {
      const id = "sensor.netorbit_" + key;
      states[id] = { entity_id: id, state: status, attributes: {
        netorbit: true, kind: "hub", label, node_key: "hub:" + key, link: parent ? "hub:" + parent : null,
        hub_type: type, ip: "192.0.2." + (key === "gateway" ? 1 : ip++), icon: { router: "mdi:router-network", switch: "mdi:switch", access_point: "mdi:access-point", mesh_node: "mdi:access-point-network" }[type],
        last_seen: ago(0), sleepy: false } };
    };
    const dev = (label, icon, parent, status = "online", sleepy = false, placement) => {
      const m = mac();
      const id = "sensor.netorbit_" + label.toLowerCase().replace(/[^a-z0-9]+/g, "_");
      states[id] = { entity_id: id, state: status, attributes: {
        netorbit: true, kind: "device", label, node_key: m.toLowerCase(), link: "hub:" + parent, ip: "192.0.2." + ip++, mac: m,
        icon, sleepy, last_seen: status === "online" ? ago(0) : status === "recent" ? ago(5) : ago(40), source: "discovered",
        placement: placement || (parent === "gateway" ? "none" : "snmp") } };
    };
    def(hub, dev);
    return states;
  }

  function summary(states, fresh, suggested = []) {
    states["sensor.netorbit_devices_online"] = { entity_id: "sensor.netorbit_devices_online", state: "0", attributes: {
      netorbit: true, kind: "summary", stale_hours: 24, mode: "manual", config_entry_id: "preview", group_by_type: true, weak_after_minutes: 10,
      suggested_hubs: suggested.map(([name, type, reasons]) => { const m = mac(); return { key: m.toLowerCase(), mac: m, ip: "192.0.2." + (220 + n), name, type, reasons }; }),
      new_devices: fresh.map((name, i) => ({ key: "new" + i, name, mac: mac(), ip: "192.0.2." + (200 + i), first_seen: ago(1), last_seen: ago(0) })) } };
    // ?internet=down shows an outage, ?internet=off leaves the node out.
    const inet = new URLSearchParams(location.search).get("internet");
    if (inet !== "off") {
      states["sensor.netorbit_internet"] = { entity_id: "sensor.netorbit_internet", state: inet === "down" ? "stale" : "online", attributes: {
        netorbit: true, kind: "internet", label: "Internet", node_key: "internet", last_seen: ago(3) } };
    }
    return states;
  }

  const full = (hub, dev) => {
      hub("gateway", "Router", "router", null);
      hub("core", "Core Switch", "switch", "gateway");
      hub("up", "Hallway AP", "access_point", "core");
      hub("down", "Den AP", "access_point", "core");
      hub("garage", "Patio AP", "access_point", "core");
      hub("office", "Office Switch", "switch", "core");
      ["Desktop:mdi:monitor", "NAS:mdi:server", "Home Assistant:mdi:home-assistant", "Soundbar:mdi:soundbar", "Bookshelf Speaker:mdi:speaker", "Printer:mdi:printer", "Game Console:mdi:gamepad-variant"]
        .forEach((s, i) => { const [l, ...ic] = s.split(":"); dev(l, ic.join(":"), "office", i === 6 ? "recent" : "online", i === 6); });
      ["Bedroom TV:mdi:television", "Laptop:mdi:laptop", "Thermostat 2F:mdi:thermostat", "E-Reader:mdi:book-open-variant", "Indoor Cam 1:mdi:cctv", "Tablet:mdi:tablet", "Smart Watch:mdi:watch", "VR Headset:mdi:virtual-reality"]
        .forEach((s, i) => { const [l, ...ic] = s.split(":"); dev(l, ic.join(":"), "up", i === 7 ? "recent" : "online", i >= 6); });
      ["Family Room TV:mdi:television", "Streamer:mdi:television-play", "Thermostat 1F:mdi:thermostat", "Smart Plug:mdi:power-socket-us", "Air Purifier:mdi:air-purifier", "Doorbell:mdi:doorbell-video", "Smoke Alarm Hub:mdi:smoke-detector", "Robot Vac 1:mdi:robot-vacuum", "Indoor Cam 2:mdi:cctv", "Smart Display:mdi:home-automation", "Guest Streamer:mdi:television-play"]
        .forEach((s, i) => { const [l, ...ic] = s.split(":"); dev(l, ic.join(":"), "down", i === 10 ? "stale" : "online", i === 0 || i === 1); });
      ["Garage Door 1:mdi:garage", "Garage Door 2:mdi:garage", "Shop Lights:mdi:lightbulb-group", "Freezer Sensor:mdi:fridge", "Sprinklers:mdi:sprinkler"]
        .forEach((s) => { const [l, ...ic] = s.split(":"); dev(l, ic.join(":"), "garage"); });
      dev("Weather Station", "mdi:weather-partly-cloudy", "gateway");
  };
  // Scan progress on the summary sensor (see NetOrbit's coordinator).
  const scanning = (states, attrs) => {
    Object.assign(states["sensor.netorbit_devices_online"].attributes, attrs);
    return states;
  };

  window.NETORBIT_SCENARIOS = {
    full: summary(build(full), ["Device 3A:91"], [["esp-7c2d1a", "access_point", ["its name looks like an access point"]]]),
    // The very first scan on a new install, 30% in: only the router is known yet.
    firstscan: scanning(summary(build((hub) => hub("gateway", "Router", "router", null)), []),
      { scanning: true, scan_phase: "ping", scan_progress: 30, found: 12, first_scan_done: false }),
    // A later scan, every few minutes: the normal map with a small chip.
    rescan: scanning(summary(build(full), ["Device 3A:91"], [["esp-7c2d1a", "access_point", ["its name looks like an access point"]]]),
      { scanning: true, scan_phase: "names", scan_progress: 50, found: 33, first_scan_done: true }),
    // The first scan has finished.
    done: scanning(summary(build(full), []), { scanning: false, scan_phase: null, scan_progress: 100, found: 33, first_scan_done: true }),

    mesh: summary(build((hub, dev) => {
      hub("gateway", "Mesh Router", "router", null);
      hub("m1", "Living Room Node", "mesh_node", "gateway");
      hub("m2", "Upstairs Node", "mesh_node", "gateway");
      ["Phone:mdi:cellphone", "TV:mdi:television", "Streamer:mdi:television-play", "Speaker:mdi:speaker", "Thermostat:mdi:thermostat"].forEach((s) => { const [l, ...ic] = s.split(":"); dev(l, ic.join(":"), "m1"); });
      ["Laptop:mdi:laptop", "Kids Tablet:mdi:tablet", "Printer:mdi:printer", "Doorbell:mdi:cctv"].forEach((s, i) => { const [l, ...ic] = s.split(":"); dev(l, ic.join(":"), "m2", i === 1 ? "recent" : "online", i === 1); });
      ["Desktop:mdi:monitor", "Home Assistant:mdi:home-assistant"].forEach((s) => { const [l, ...ic] = s.split(":"); dev(l, ic.join(":"), "gateway"); });
    }), []),

    flat: summary(build((hub, dev) => {
      hub("gateway", "Router", "router", null);
      ["living-room-tv:mdi:television", "kitchen-speaker:mdi:speaker", "office-printer:mdi:printer", "Device 4B:12:mdi:lan-connect", "homeassistant:mdi:home-assistant", "shelly-plug-3:mdi:chip", "esp-garage:mdi:chip", "nas:mdi:server", "work-laptop:mdi:laptop", "Device 77:E0:mdi:lan-connect"]
        .forEach((s, i) => { const parts = s.split(":"); const ic = parts.slice(-2).join(":"); const l = parts.slice(0, -2).join(":"); dev(l, ic, "gateway", i === 9 ? "stale" : "online"); });
    }), ["Device 9C:04"]),

    // A typical mesh home where nothing reports which node a device uses.
    // Several hubs straight off the router with long names, everything else grouped by type.
    hubs: summary(build((hub, dev) => {
      hub("gateway", "Router", "router", null);
      hub("sw1", "PoE Switch (8 port)", "switch", "gateway");
      hub("ap1", "Hallway AP", "access_point", "gateway");
      hub("ap2", "Upstairs Bedroom AP", "access_point", "gateway");
      hub("sw2", "Rack Switch 16-Port (Main)", "switch", "gateway");
      ["Family Room TV:mdi:television", "Bedroom TV:mdi:television", "Streamer:mdi:television-play", "Kitchen Speaker:mdi:speaker", "Game Console:mdi:gamepad-variant",
       "Laptop:mdi:laptop", "Desktop:mdi:monitor", "Tablet:mdi:tablet", "Printer:mdi:printer", "NAS:mdi:nas",
       "Doorbell:mdi:doorbell-video", "Front Cam:mdi:cctv", "Back Cam:mdi:cctv", "Garage Cam:mdi:cctv",
       "Thermostat:mdi:thermostat", "Smart Plug:mdi:power-socket-us", "Robot Vac:mdi:robot-vacuum", "Garage Door:mdi:garage", "Lamp:mdi:lightbulb", "Air Purifier:mdi:air-purifier",
       "Device 4B:12:mdi:lan-connect", "Device 7C:01:mdi:lan-connect"]
        .forEach((s) => { const parts = s.split(":"); const ic = parts.slice(-2).join(":"); const l = parts.slice(0, -2).join(":"); dev(l, ic, "gateway", "online", false, "none"); });
    }), [], [["Shed AP", "access_point", ["its name looks like an access point"]]]),
    novice: summary(build((hub, dev) => {
      hub("gateway", "Router", "router", null);
      hub("m1", "Mesh Node 2", "mesh_node", "gateway");
      ["Family Room TV:mdi:television", "Bedroom TV:mdi:television", "Streamer:mdi:television-play", "Kitchen Speaker:mdi:speaker", "Game Console:mdi:gamepad-variant",
       "Laptop:mdi:laptop", "Desktop:mdi:monitor", "Tablet:mdi:tablet", "Printer:mdi:printer",
       "Doorbell:mdi:doorbell-video", "Front Cam:mdi:cctv", "Back Cam:mdi:cctv",
       "Thermostat:mdi:thermostat", "Smart Plug:mdi:power-socket-us", "Robot Vac:mdi:robot-vacuum", "Garage Door:mdi:garage", "Lamp:mdi:lightbulb", "Air Purifier:mdi:air-purifier",
       "Device 4B:12:mdi:lan-connect"]
        .forEach((s, i) => { const parts = s.split(":"); const ic = parts.slice(-2).join(":"); const l = parts.slice(0, -2).join(":"); dev(l, ic, "gateway", i === 4 ? "recent" : "online", i === 4); });
    }), [], [["Mesh Node 3", "mesh_node", ["made by eero"]]]),
  };
  // DNS names and free text on a few nodes of the full scenario, to preview the details popup.
  (function () {
    const full = window.NETORBIT_SCENARIOS.full;
    const byLabel = (l) => Object.values(full).find((st) => st.attributes.label === l);
    Object.assign(byLabel("Router").attributes, { fqdn: "edge.home.example", hostname: "edge", managed_by: "ISP support, ticket 4471" });
    Object.assign(byLabel("Office Switch").attributes, { fqdn: "sw-office.home.example", hostname: "sw-office", fields: { Rack: "Office closet, shelf 2", Firmware: "7.5.15" } });
    Object.assign(byLabel("NAS").attributes, { fqdn: "nas.home.example", hostname: "nas", managed_by: "Office Switch", first_seen: new Date(Date.now() - 90 * 86400e3).toISOString(),
      fields: { Location: "Office closet", Serial: "NAS-00042", Notes: "Backups run at 02:00; spare disk in the drawer" } });
    Object.assign(byLabel("Printer").attributes, { fqdn: "printer.home.example", hostname: "printer", managed_by: "https://192.0.2.30/", fields: { Toner: "ordered 2026-10" } });
    // Radio details: a controller knows the AP, band and channel; a plain sensor only the signal.
    Object.assign(byLabel("Smart Plug").attributes, { wireless: { radio: "wifi", ap_name: "Den AP", ssid: "IoT", band: "2.4 GHz", channel: 6, signal_dbm: -61, snr: 34, quality: 78, source: "fortigate:Edge", at: scanned } });
    Object.assign(byLabel("Streamer").attributes, { wireless: { radio: "wifi", ssid: "Home", band: "5 GHz", channel: 44, signal_dbm: -72, quality: 56, source: "tracker:device_tracker.streamer", at: scanned } });
    // The doorbell has read poor for 25 minutes (drawn yellow-green); the purifier dipped 3 minutes ago (still green).
    Object.assign(byLabel("Doorbell").attributes, { wireless: { radio: "wifi", signal_dbm: -91, quality: 18, source: "entity:sensor.doorbell_rssi", at: scanned, weak_since: new Date(Date.now() - 25 * 60e3).toISOString(), weak: true } });
    Object.assign(byLabel("Air Purifier").attributes, { wireless: { radio: "wifi", ap_name: "Den AP", ssid: "IoT", band: "2.4 GHz", channel: 6, signal_dbm: -84, snr: 12, quality: 32, source: "fortigate:Edge", at: scanned, weak_since: new Date(Date.now() - 3 * 60e3).toISOString(), weak: false } });
    Object.assign(byLabel("Thermostat 1F").attributes, { wireless: { radio: "thread", lqi: 196, signal_dbm: -64, quality: 77, source: "entity:sensor.thermostat_rssi", at: scanned }, linked_entities: { signal: "sensor.thermostat_rssi" } });
    // Alerts: the router pages when it goes offline.
    Object.assign(byLabel("Router").attributes, { notify: true });
  })();
})();
