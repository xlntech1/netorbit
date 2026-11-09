// Layout tests for the card. Run with: node --test tests/card.test.js
const test = require("node:test");
const assert = require("node:assert");
// Minimal browser stand-ins so the card file can load under Node.
globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => undefined, define: (name, cls) => { globalThis.NetOrbitCard = cls; } };
globalThis.window = globalThis;
console.info = () => {};
const { netorbitLayout, netorbitBalloonLayout, netorbitFocus, netorbitDraw, noPrivateMac } = require("../custom_components/netorbit/frontend/netorbit-card.js");

function model(hubDefs, devCounts) {
  const hubs = {};
  hubDefs.forEach(([key, parent]) => (hubs[key] = { key, parent, label: key }));
  const devices = [];
  Object.entries(devCounts).forEach(([hub, n]) => {
    for (let i = 0; i < n; i++) devices.push({ key: `${hub}-d${i}`, link: hub, label: `${hub} ${i}` });
  });
  return { hubs, devices, root: hubDefs[0][0] };
}

function dist(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

test("every device and hub gets a position", () => {
  const m = model([["r", null], ["sw", "r"], ["ap1", "sw"], ["ap2", "sw"], ["mesh", "r"]], { r: 2, sw: 3, ap1: 10, ap2: 7, mesh: 4 });
  const L = netorbitLayout(m);
  for (const d of m.devices) assert.ok(L.pos[d.key], d.key);
  for (const k of Object.keys(m.hubs)) assert.ok(L.pos[k], k);
});

test("devices do not overlap", () => {
  const m = model([["r", null], ["a", "r"], ["b", "r"]], { r: 5, a: 30, b: 25 });
  const L = netorbitLayout(m);
  const pts = m.devices.map((d) => L.pos[d.key]);
  for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) assert.ok(dist(pts[i], pts[j]) > 30);
});

test("deeper hubs sit further out than their parents", () => {
  const m = model([["r", null], ["sw", "r"], ["ap", "sw"], ["rep", "ap"]], { rep: 3 });
  const L = netorbitLayout(m);
  const c = L.pos.r;
  assert.ok(dist(c, L.pos.ap) > dist(c, L.pos.sw));
  assert.ok(dist(c, L.pos.rep) > dist(c, L.pos.ap));
  assert.ok(dist(c, L.pos.rep) < 370);
});

test("flat network with only a router", () => {
  const m = model([["r", null]], { r: 12 });
  const L = netorbitLayout(m);
  assert.strictEqual(Object.keys(L.pos).length, 13);
});

test("unknown parent and cycles fall back to the root", () => {
  const m = model([["r", null], ["x", "missing"], ["y", "z"], ["z", "y"]], { x: 1, y: 1, z: 1 });
  m.devices.push({ key: "orphan", link: "nowhere", label: "orphan" });
  const L = netorbitLayout(m);
  for (const k of ["x", "y", "z", "orphan"]) assert.ok(L.pos[k], k);
});

test("large networks stagger device rings", () => {
  const m = model([["r", null], ["a", "r"]], { a: 120 });
  const L = netorbitLayout(m);
  const radii = new Set(m.devices.map((d) => Math.round(L.pos[d.key].r)));
  assert.strictEqual(radii.size, 2);
});

// ---------------------------------------------------------------- balloon layout and branches

// A chain of switches, each feeding the next, plus two busy access points off the router.
function chain() {
  return model(
    [["r", null], ["ap1", "r"], ["ap2", "r"], ["s1", "r"], ["s2", "s1"], ["s3", "s2"], ["s4", "s3"], ["s5", "s4"], ["ap3", "s5"], ["side", "s1"]],
    { ap1: 16, ap2: 10, s1: 3, s2: 1, s3: 1, s4: 1, s5: 1, ap3: 6, side: 2 }
  );
}

test("balloon: every hub and device gets a position, each device on a ring round its own hub", () => {
  const m = chain();
  const L = netorbitBalloonLayout(m);
  for (const k of Object.keys(m.hubs)) assert.ok(L.pos[k], k);
  for (const d of m.devices) {
    const p = L.pos[d.key], h = L.pos[d.link];
    assert.ok(p, d.key);
    assert.strictEqual(p.hub, d.link);
    assert.ok(Math.abs(p.ox - h.x) < 0.05 && Math.abs(p.oy - h.y) < 0.05, `${d.key} ring centre is its hub`);
    assert.ok(Math.abs(dist(p, h) - p.r) < 0.5, `${d.key} sits on its ring`);
  }
});

test("balloon: nothing overlaps, across branches too", () => {
  const m = chain();
  const L = netorbitBalloonLayout(m);
  const devs = m.devices.map((d) => L.pos[d.key]);
  const hubs = Object.keys(m.hubs).map((k) => L.pos[k]);
  for (let i = 0; i < devs.length; i++) for (let j = i + 1; j < devs.length; j++) assert.ok(dist(devs[i], devs[j]) > 30, `devices ${i} and ${j}`);
  for (let i = 0; i < hubs.length; i++) for (let j = i + 1; j < hubs.length; j++) assert.ok(dist(hubs[i], hubs[j]) > 70, `hubs ${i} and ${j}`);
  for (const d of devs) for (const h of hubs) assert.ok(dist(d, h) > 45, "device clear of every hub");
});

test("balloon: branches pulled in towards the middle still never overlap, in a large random network", () => {
  let seed = 7;
  const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const defs = [["r", null]];
  const counts = { r: 3 };
  for (let i = 0; i < 18; i++) { defs.push([`h${i}`, i < 4 ? "r" : `h${Math.floor(rnd() * i)}`]); counts[`h${i}`] = Math.floor(rnd() * 12); }
  const m = model(defs, counts);
  const L = netorbitBalloonLayout(m);
  const devs = m.devices.map((d) => L.pos[d.key]);
  const hubs = Object.keys(m.hubs).map((k) => L.pos[k]);
  for (let i = 0; i < devs.length; i++) for (let j = i + 1; j < devs.length; j++) assert.ok(dist(devs[i], devs[j]) > 30, `devices ${i} and ${j}`);
  for (let i = 0; i < hubs.length; i++) for (let j = i + 1; j < hubs.length; j++) assert.ok(dist(hubs[i], hubs[j]) > 70, `hubs ${i} and ${j}`);
  for (const d of devs) for (const h of hubs) assert.ok(dist(d, h) > 45, "device clear of every hub");
});

test("balloon: a chain of switches grows a step at a time, not doubling", () => {
  const steps = (n) => {
    const defs = [["r", null]];
    const counts = {};
    for (let i = 1; i <= n; i++) { defs.push([`s${i}`, i === 1 ? "r" : `s${i - 1}`]); counts[`s${i}`] = 1; }
    const L = netorbitBalloonLayout(model(defs, counts));
    for (let i = 2; i <= n; i++) assert.ok(dist(L.pos[`s${i}`], L.pos[`s${i - 1}`]) < 400, `step ${i}`);
    return Math.max(L.view.w, L.view.h);
  };
  // Twice the switches makes a map roughly twice as long, not many times longer.
  assert.ok(steps(8) < steps(4) * 2.6);
});

test("balloon: the view holds everything and has the card's shape", () => {
  for (const aspect of [0.8, 1.5, 2.2]) {
    const m = chain();
    const L = netorbitBalloonLayout(m, { aspect });
    const v = L.view;
    assert.ok(v.w / v.h >= aspect - 0.01, `aspect ${aspect}`);
    for (const p of Object.values(L.pos)) assert.ok(p.x > v.x && p.x < v.x + v.w && p.y > v.y && p.y < v.y + v.h);
  }
});

test("balloon: unknown parents, loops, a big access point and a bare router all work", () => {
  const m = model([["r", null], ["x", "missing"], ["y", "z"], ["z", "y"], ["big", "r"]], { x: 1, y: 1, z: 1, big: 120 });
  m.devices.push({ key: "orphan", link: "nowhere", label: "orphan" });
  const L = netorbitBalloonLayout(m);
  for (const k of ["x", "y", "z", "big", "orphan"]) assert.ok(L.pos[k], k);
  const big = m.devices.filter((d) => d.link === "big").map((d) => L.pos[d.key]);
  for (let i = 1; i < big.length; i++) assert.ok(dist(big[i], big[i - 1]) > 30);
  const bare = netorbitBalloonLayout(model([["r", null]], {}));
  assert.ok(bare.pos.r && bare.view.w > 0);
});

test("balloon: drawn labels run out from the device's own hub", () => {
  const m = chain();
  const D = netorbitDraw(m, {}, { layout: "balloon" });
  assert.ok(D.view, "the balloon map says what part of the map to show");
  for (const l of D.scene.devLabels) {
    const d = m.devices.find((x) => x.key === l.k);
    const hub = D.pos[d.link], dev = D.pos[d.key];
    assert.ok(dist(l, hub) > dist(dev, hub), `${d.key} label beyond its device`);
  }
  assert.strictEqual(netorbitDraw(m, {}, {}).view, null, "the radial map keeps its fixed view");
});

test("a branch on its own: the hub becomes the middle, with only what is below it", () => {
  const m = chain();
  m.internet = { key: "internet", status: "online" };
  const f = netorbitFocus(m, "s2");
  assert.strictEqual(f.root, "s2");
  assert.strictEqual(f.hubs.s2.parent, null);
  // The branch, plus the hub above it as the way back up: hanging off the middle hub, without its own devices.
  assert.deepStrictEqual(Object.keys(f.hubs).sort(), ["ap3", "s1", "s2", "s3", "s4", "s5"]);
  assert.strictEqual(f.hubs.s1.kind, "uphub");
  assert.strictEqual(f.hubs.s1.parent, "s2");
  assert.strictEqual(f.up, "s1");
  assert.ok(f.devices.every((d) => f.hubs[d.link] && d.link !== "s1"));
  assert.strictEqual(f.devices.length, 1 + 1 + 1 + 1 + 6);
  assert.deepStrictEqual(f.path, ["r", "s1", "s2"]);
  // A branch straight off the router has the router as its way up.
  const top = netorbitFocus(m, "s1");
  assert.strictEqual(top.hubs.r.kind, "uphub");
  assert.strictEqual(top.up, "r");
  assert.strictEqual(m.hubs.r.kind, undefined, "the whole map's hubs are copied, not changed");
  assert.strictEqual(f.internet, null);
  assert.strictEqual(m.hubs.s2.parent, "s1", "the whole map is left as it was");
  // The root, or a hub that isn't there, is the whole map.
  assert.strictEqual(netorbitFocus(m, "r"), m);
  assert.strictEqual(netorbitFocus(m, "gone"), m);
  assert.strictEqual(netorbitFocus(m, null), m);
  // Both layouts draw a branch.
  assert.ok(netorbitBalloonLayout(f).pos.ap3);
  assert.ok(netorbitLayout(f).pos.ap3);
});

test("devices are grouped by type from their icon", () => {
  const { noGroupFor } = require("../custom_components/netorbit/frontend/netorbit-card.js");
  assert.strictEqual(noGroupFor("mdi:television"), "media");
  assert.strictEqual(noGroupFor("mdi:laptop"), "computers");
  assert.strictEqual(noGroupFor("mdi:cctv"), "cameras");
  assert.strictEqual(noGroupFor("mdi:thermostat"), "home");
  assert.strictEqual(noGroupFor("mdi:lan-connect"), "other");
});

test("height takes pixels or a CSS length, and nothing that could leave the style block", () => {
  const { noHeight } = require("../custom_components/netorbit/frontend/netorbit-card.js");
  assert.strictEqual(noHeight(1300), "1300px");
  assert.strictEqual(noHeight("1300"), "1300px");
  assert.strictEqual(noHeight(undefined), "900px");
  assert.strictEqual(noHeight(""), "900px");
  assert.strictEqual(noHeight(0), "900px");
  assert.strictEqual(noHeight("calc(100vh - 180px)"), "calc(100vh - 180px)");
  assert.strictEqual(noHeight("80vh"), "80vh");
  assert.strictEqual(noHeight("min(1200px, 90vh)"), "min(1200px, 90vh)");
  assert.strictEqual(noHeight("100px; } svg { display:none"), "900px");
  assert.strictEqual(noHeight("100px /*"), "900px");
  assert.strictEqual(noHeight("100px */"), "900px");
  assert.strictEqual(noHeight(true), "900px");
  assert.strictEqual(noHeight(false), "900px");
  assert.strictEqual(noHeight("1px</style><img src=x onerror=alert(1)>"), "900px");
  assert.strictEqual(noHeight("url('x')"), "900px");
});

const BASE = { x: -70, y: -40, w: 1140, h: 1090 };
const MIDDLE = { x: BASE.x + BASE.w / 2, y: BASE.y + BASE.h / 2 };
const near = (a, b) => Math.abs(a - b) < 1e-9;

test("zooming about the middle keeps the middle and the shape of the map", () => {
  const { netorbitZoomView } = require("../custom_components/netorbit/frontend/netorbit-card.js");
  const v = netorbitZoomView(null, MIDDLE, MIDDLE, 2);
  assert.ok(near(v.w, BASE.w / 2) && near(v.h, BASE.h / 2));
  assert.ok(near(v.x + v.w / 2, MIDDLE.x) && near(v.y + v.h / 2, MIDDLE.y));
  assert.ok(near(v.w / v.h, BASE.w / BASE.h));
});

test("the map point under the finger stays under it through a pinch", () => {
  const { netorbitZoomView } = require("../custom_components/netorbit/frontend/netorbit-card.js");
  const start = netorbitZoomView(null, MIDDLE, MIDDLE, 2);
  const anchor = { x: 300, y: 420 };
  const now = { x: 350, y: 470 }; // the fingers' midpoint moved, and they spread 1.5x
  const v = netorbitZoomView(start, anchor, now, 1.5);
  // Where `now` sits on the screen in the start view is where the anchor must sit in the new one.
  assert.ok(near((anchor.x - v.x) / v.w, (now.x - start.x) / start.w));
  assert.ok(near((anchor.y - v.y) / v.h, (now.y - start.y) / start.h));
  assert.ok(near(v.w, BASE.w / 3));
});

test("a drag pans by the finger's travel", () => {
  const { netorbitZoomView } = require("../custom_components/netorbit/frontend/netorbit-card.js");
  const v = netorbitZoomView(null, MIDDLE, MIDDLE, 2);
  const p = netorbitZoomView(v, { x: 400, y: 400 }, { x: 450, y: 430 }, 1);
  assert.ok(near(p.x, v.x - 50) && near(p.y, v.y - 30) && near(p.w, v.w));
});

test("zooming out past the whole map gives the whole map", () => {
  const { netorbitZoomView } = require("../custom_components/netorbit/frontend/netorbit-card.js");
  const v = netorbitZoomView(null, MIDDLE, MIDDLE, 2);
  assert.strictEqual(netorbitZoomView(v, MIDDLE, MIDDLE, 0.4), null);
  assert.strictEqual(netorbitZoomView(null, MIDDLE, MIDDLE, 0.5), null);
  assert.strictEqual(netorbitZoomView(null, MIDDLE, MIDDLE, 1), null);
});

test("zoom stops at the maximum and the view stays inside the map", () => {
  const { netorbitZoomView } = require("../custom_components/netorbit/frontend/netorbit-card.js");
  let v = null;
  for (let i = 0; i < 20; i++) v = netorbitZoomView(v, MIDDLE, MIDDLE, 2);
  assert.ok(near(v.w, BASE.w / 5) && near(v.h, BASE.h / 5));
  const corner = { x: BASE.x, y: BASE.y };
  const w = netorbitZoomView(null, corner, corner, 3);
  assert.ok(near(w.x, BASE.x) && near(w.y, BASE.y));
  // Dragging the finger far up and left pulls the far corner of the map into view and no further.
  const far = netorbitZoomView(w, corner, { x: corner.x - 5000, y: corner.y - 5000 }, 1);
  assert.ok(near(far.x + far.w, BASE.x + BASE.w) && near(far.y + far.h, BASE.y + BASE.h));
});

test("group hubs sit near their devices, not in the middle", () => {
  const hubs = { r: { key: "r", label: "Router" }, g: { key: "g", parent: "r", label: "TVs", kind: "group" } };
  const devices = [1, 2, 3].map((i) => ({ key: "d" + i, link: "g", label: "TV " + i }));
  const L = netorbitLayout({ hubs, devices, root: "r" });
  assert.ok(Math.hypot(L.pos.g.x - 500, L.pos.g.y - 500) > 200);
});

test("hubs keep clear of the internet node above the router", () => {
  const m = model([["r", null], ["a", "r"], ["b", "r"], ["c", "r"], ["d", "r"], ["e", "r"], ["f", "r"]], { a: 6, b: 6, c: 6, d: 6, e: 6, f: 6 });
  const L = netorbitLayout(m);
  const inet = { x: L.pos.r.x, y: L.pos.r.y - 62 }; // the default spot; the card moves it to a clear diagonal if a link runs there
  for (const k of "abcdef") assert.ok(dist(L.pos[k], inet) > 16 + 25, k); // node radii: internet 16, hub 25
});

// ---------------------------------------------------------------- scanning and sharing

const card = require("../custom_components/netorbit/frontend/netorbit-card.js");

test("scan mode comes from the summary sensor's attributes", () => {
  const { netorbitScanMode } = card;
  assert.strictEqual(netorbitScanMode({ scanning: true, first_scan_done: false, scan_phase: "ping" }), "takeover");
  // A first sweep that is not running (it failed, or has not started) never hides the map.
  assert.strictEqual(netorbitScanMode({ scanning: false, first_scan_done: false }), "none");
  assert.strictEqual(netorbitScanMode({ first_scan_done: false }), "none");
  assert.strictEqual(netorbitScanMode({ scanning: true, first_scan_done: true }), "chip");
  assert.strictEqual(netorbitScanMode({ scanning: false, first_scan_done: true }), "none");
  // Older versions of the integration have none of these: draw the map as before.
  assert.strictEqual(netorbitScanMode({ counts: {} }), "none");
  assert.strictEqual(netorbitScanMode(null), "none");
});

test("scan text shows the phase, the found count and the progress", () => {
  const { netorbitScanText } = card;
  const s = netorbitScanText({ scan_phase: "names", scan_progress: 50, found: 17 });
  assert.strictEqual(s.phase, "Asking devices their names");
  assert.strictEqual(s.line, "Scanning your network... found 17 devices");
  assert.strictEqual(s.pct, 50);
  assert.strictEqual(netorbitScanText({ scan_phase: "ping", found: 1 }).line, "Scanning your network... found 1 device");
  assert.strictEqual(netorbitScanText({ scan_phase: "arp" }).phase, "Reading the router's address table");
  assert.strictEqual(netorbitScanText({ scan_phase: "snmp" }).phase, "Asking switches what is plugged in where");
  assert.strictEqual(netorbitScanText({ scan_phase: "layout" }).phase, "Working out the layout");
  assert.strictEqual(netorbitScanText({ scan_phase: "starting" }).phase, "Getting ready");
  assert.strictEqual(netorbitScanText({ scan_phase: null, scan_progress: 140, found: -3 }).pct, 100);
  assert.strictEqual(netorbitScanText({ found: -3 }).found, 0);
});

// A map model shaped like the card builds it from Home Assistant, with everything a real one carries.
function richModel(order) {
  const hub = (key, label, hub_type, parent, icon) => ({ key, label, kind: "hub", hub_type, parent, link: parent, status: "online", icon,
    ip: "192.0.2." + (key.length + 1), mac: "00:00:5E:00:53:0" + key.length, entity: "sensor.netorbit_" + key, hostname: label.toLowerCase() + ".lan", vendor: "Acme" });
  const hubs = {
    "hub:gw": hub("hub:gw", "Kitchen Router", "router", null, "mdi:router-network"),
    "hub:sw": hub("hub:sw", "Basement Switch", "switch", "hub:gw", "mdi:switch"),
    "hub:ap": hub("hub:ap", "Attic AP", "access_point", "hub:sw", "mdi:access-point"),
    __new: { key: "__new", label: "New devices", kind: "newhub", parent: "hub:gw", status: "new", icon: "mdi:tag-plus-outline" },
  };
  let i = 10;
  const dev = (label, icon, link, extra) => Object.assign({ key: "00:00:5e:00:53:" + (i++).toString(16), label, kind: "device", link, parent: link, status: "online",
    icon, ip: "192.0.2." + i, mac: "00:00:5E:00:53:" + i.toString(16).toUpperCase(), entity: "sensor.netorbit_" + i, hostname: "host-" + i, vendor: "Acme", last_seen: "2026-01-01T00:00:00Z", placement: "snmp" }, extra || {});
  let devices = [
    dev("Living Room TV", "mdi:television", "hub:ap"),
    dev("Bedroom TV", "mdi:television", "hub:ap"),
    dev("Front Door Cam", "mdi:cctv", "hub:ap"),
    dev("Garage Cam", "mdi:cctv", "hub:sw"),
    dev("Office Laptop", "mdi:laptop", "hub:sw"),
    dev("192.0.2.77", "mdi:lan-connect", "hub:sw"),
    dev("Device 3A:91", "mdi:lan-connect", "hub:gw"),
    dev("Kids Tablet", "mdi:tablet", "hub:gw", { pending: true }),
    dev("esp-shed", "mdi:access-point-network", "hub:gw", { suggested: { key: "x", type: "access_point", reasons: ["Shed"] } }),
    { key: "new:new0", label: "Strange Gadget", kind: "new", link: "__new", status: "new", icon: "mdi:help-circle-outline", ip: "192.0.2.200", mac: "00:00:5E:00:53:C8", raw: { mac: "00:00:5E:00:53:C8", ip: "192.0.2.200" } },
  ];
  if (order) devices = order(devices);
  return { hubs, devices, root: "hub:gw", summary: { attributes: { config_entry_id: "abc" } }, internet: { key: "internet", entity: "sensor.netorbit_internet", kind: "internet", label: "Internet", status: "online" }, suggestions: { X: {} }, sig: "x" };
}
const REAL = ["Kitchen Router", "Basement Switch", "Attic AP", "Living Room TV", "Bedroom TV", "Front Door Cam", "Garage Cam", "Office Laptop", "Kids Tablet", "esp-shed", "Strange Gadget", "Acme", "host-", ".lan", "sensor.netorbit", "abc"];
const MAC_RE = /\b[0-9a-f]{2}([:-][0-9a-f]{2})+\b/i;

function assertSafe(text, what) {
  assert.ok(!text.includes("192.0.2."), `${what} holds an IP address`);
  assert.ok(!MAC_RE.test(text), `${what} holds a MAC address: ${(text.match(MAC_RE) || [])[0]}`);
  for (const name of REAL) assert.ok(!text.includes(name), `${what} holds ${name}`);
}

test("shareModel names devices by type, numbered per type by hub then name", () => {
  const m = card.shareModel(richModel());
  const byType = m.devices.map((d) => d.label);
  // Hubs by name (Attic AP, Basement Switch, Kitchen Router), then devices by name within each hub.
  assert.deepStrictEqual(byType, ["TV 1", "Camera 1", "TV 2", "Device 1", "Camera 2", "Laptop 1", "Device 2", "Tablet 1"]);
  assert.strictEqual(m.title, "My home network");
  // The same network in another order gives the same names.
  const again = card.shareModel(richModel((list) => list.slice().reverse()));
  assert.deepStrictEqual(again.devices.map((d) => d.label), byType);
  assert.deepStrictEqual(again.devices.map((d) => d.key), m.devices.map((d) => d.key));
});

test("shareModel hubs show their type only and waiting or suggested devices are left out", () => {
  const m = card.shareModel(richModel());
  assert.deepStrictEqual(Object.values(m.hubs).map((h) => h.label).sort(), ["Access point", "Router", "Switch"]);
  assert.ok(!Object.values(m.hubs).some((h) => h.kind === "newhub"));
  assert.ok(!m.devices.some((d) => d.kind === "new" || d.suggested || d.pending));
  assert.strictEqual(m.devices.length, 8);
  assert.deepStrictEqual(m.suggestions, {});
  assert.strictEqual(m.summary, null);
});

test("shared output never holds addresses or real names", () => {
  const m = card.shareModel(richModel());
  assertSafe(JSON.stringify(m), "shareModel");
  assertSafe(card.netorbitShareSvg(m, m.title), "share SVG");
  for (const d of m.devices) for (const k of ["ip", "mac", "entity", "hostname", "vendor", "raw", "last_seen"]) assert.strictEqual(d[k], undefined, k);
});

test("with names shown, labels stay but addresses still never do", () => {
  const m = card.shareModel(richModel(), { hideNames: false });
  const labels = m.devices.map((d) => d.label);
  assert.ok(labels.includes("Living Room TV") && labels.includes("Garage Cam"));
  assert.ok(Object.values(m.hubs).some((h) => h.label === "Attic AP"));
  // A device named after its address gets a generic name.
  assert.ok(!labels.some((l) => l.includes("192.0.2.") || MAC_RE.test(l)), labels.join(","));
  const svg = card.netorbitShareSvg(m, "Network");
  assert.ok(!svg.includes("192.0.2.") && !MAC_RE.test(svg));
  assert.ok(svg.includes("Living Room TV"));
});

test("the share image follows the layout on show: radial keeps its frame, balloon gets its own", () => {
  const m = card.shareModel(richModel());
  const size = (svg) => svg.match(/^<svg[^>]* width="(\d+)" height="(\d+)"/).slice(1).map(Number);
  const radial = card.netorbitShareSvg(m, m.title);
  assert.deepStrictEqual(size(radial), [1140, 1220]);
  assert.ok(radial.includes('viewBox="-70 -40 1140 1090"') && radial.includes('class="ring"'));
  const balloon = card.netorbitShareSvg(m, m.title, "balloon");
  const [w, h] = size(balloon);
  assert.ok(w >= 1140 && w <= 1600 && h > 0);
  assert.ok(!balloon.includes('class="ring"'), "no router ring on a balloon map");
  const view = card.netorbitDraw(m, { show_ip: false }, { layout: "balloon", aspect: 1.4 }).view;
  assert.ok(balloon.includes(`viewBox="${view.x} ${view.y} ${view.w} ${view.h}"`), "the map is the balloon map");
  assertSafe(balloon, "balloon share SVG");
});

test("the reveal pops nodes in the order the beam passes them", () => {
  const { netorbitRevealNode, netorbitRevealGlobal } = card;
  const top = netorbitRevealNode(0.4, 0.1), left = netorbitRevealNode(0.4, 1.5 * Math.PI);
  assert.ok(top.o > 0 && left.o === 0);
  assert.ok(netorbitRevealNode(0.4, 0.1).at < netorbitRevealNode(0.4, Math.PI).at);
  for (const a of [0, 1, 3, 6.2]) assert.deepStrictEqual([netorbitRevealNode(4, a).s, netorbitRevealNode(4, a).o, netorbitRevealNode(4, a).draw], [1, 1, 1]);
  // Reduced motion: no scaling, only a fade.
  assert.strictEqual(netorbitRevealNode(0.4, 0.1, true).s, 1);
  assert.strictEqual(netorbitRevealGlobal(0.5).labels, 0);
  assert.strictEqual(netorbitRevealGlobal(4).labels, 1);
  assert.strictEqual(netorbitRevealGlobal(0.5).header, false);
  assert.strictEqual(netorbitRevealGlobal(4).header, true);
});

test("links draw in from their start", () => {
  const { noPartialPath } = card;
  assert.strictEqual(noPartialPath("M0,0 L10,20", 0.5), "M0.0,0.0 L5.0,10.0");
  assert.strictEqual(noPartialPath("M0,0 Q10,0 10,10", 1), "M0,0 Q10,0 10,10");
  assert.strictEqual(noPartialPath("M0,0 Q10,0 10,10", 0.5), "M0.0,0.0 Q5.0,0.0 7.5,2.5");
});

// Names shown, one device called `name`: what does the share model make of it?
function sharedLabel(name) {
  const m = richModel();
  m.devices = [Object.assign({}, m.devices[0], { label: name })];
  return card.shareModel(m, { hideNames: false }).devices[0].label;
}

test("with names shown, a name holding any form of address is replaced", () => {
  const leaky = [
    "192.0.2.7", "Cam 192.0.2.7", "Cam_192.0.2.7", "cam-192.0.2.7-lan", // IPv4, also next to an underscore
    "00:00:5e:00:53:01", "00-00-5E-00-53-01", "Device 53:01", // MAC with separators, whole or partial
    "00005e005301", "Cam 00005E005301", "Cam_00005e005301", // 12 hex characters
    "0000.5e00.5301", "Cam_0000.5e00.5301", // dotted Cisco form
    "ESP_A1B2C3", "esp32-a1b2c3", "Plug 00ff12", "Shelly.5e0053", // last six characters of a MAC after a separator
    "2001:db8::1", "Cam_2001:db8::7", "fe80::", "::1", "2001:db8:0:0:0:0:0:1", // IPv6
  ];
  for (const n of leaky) assert.notStrictEqual(sharedLabel(n), n, n + " should be replaced");
});

test("with names shown, ordinary names stay", () => {
  // Names made of the letters a to f only (Deadbeef, Facade) are words, not addresses: six hex characters need a digit.
  // A name needs more than a short number or a version to be treated as an address.
  const fine = ["Living Room TV", "Office Switch", "Cafe", "Deadbeef Lamp", "Facade Light", "Decade", "Echo Dot 3", "Pixel 7 Pro", "Room 12", "Hallway 2nd Floor", "TV: Den", "Attic AP2"];
  for (const n of fine) assert.strictEqual(sharedLabel(n), n, n + " should stay");
});

test("a private (locally administered) MAC is spotted, a normal one is not", () => {
  // example-ok: synthetic values, the second hex digit is what makes a MAC private
  for (const m of ["02:00:5E:00:53:01", "06-00-5e-00-53-01", "0a0000000001", "FE:00:5E:00:53:01", "AE:00:5E:00:53:01"]) assert.ok(noPrivateMac(m), m); // example-ok
  for (const m of ["00:00:5E:00:53:01", "", null, undefined, "02:00"]) assert.ok(!noPrivateMac(m), String(m));
});

// The share video's frame pump: animation time comes from the frame number, so a late timer never makes it jump.
const { noFramePump } = require("../custom_components/netorbit/frontend/netorbit-card.js");

function fakeClock() {
  const c = { now: 0, q: [], id: 0 };
  c.later = (fn, ms) => { const id = ++c.id; c.q.push({ id, at: c.now + ms, fn }); return id; };
  c.clear = (id) => { c.q = c.q.filter((x) => x.id !== id); };
  // Runs timers in order; `late(i)` says how many ms a timer fires after it was due (a stalled main thread).
  c.run = (late) => {
    let n = 0;
    while (c.q.length && n++ < 10000) {
      c.q.sort((a, b) => a.at - b.at || a.id - b.id);
      const x = c.q.shift();
      c.now = Math.max(c.now, x.at) + (late ? late(n) : 0);
      x.fn();
    }
  };
  return c;
}

function pumpRun(late, opts) {
  const clk = fakeClock();
  const painted = [], pushed = [];
  let finished = 0;
  const o = Object.assign({ fps: 30, frames: 120, lead: 8 }, opts);
  noFramePump(Object.assign(o, {
    frame: (t, i) => { painted.push(t); pushed.push(i); },
    done: () => finished++,
    now: () => clk.now, later: clk.later, clear: clk.clear,
  }));
  clk.run(late);
  return { painted, pushed, finished, clk };
}

test("a node popup closes on a tap outside, on Escape and when left alone; unsaved changes keep it open", () => {
  const saved = { document: globalThis.document, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const on = {};
  const timers = [];
  globalThis.document = { addEventListener: (t, f) => (on[t] = f), removeEventListener: (t, f) => { if (on[t] === f) delete on[t]; } };
  globalThis.setTimeout = (f, ms) => timers.push({ f, ms });
  globalThis.clearTimeout = (id) => { if (id) timers[id - 1].f = null; };
  try {
    const make = () => {
      const l = {};
      return { isConnected: true, addEventListener: (t, f) => (l[t] = f), remove() { this.isConnected = false; }, fire: (t) => l[t]({}) };
    };
    const el = (cls) => ({ classList: { contains: (c) => c === cls } });
    const tap = (path) => on.click({ composedPath: () => path });
    const card = new globalThis.NetOrbitCard();
    let redraws = 0;
    Object.defineProperty(card, "hass", { get: () => undefined, set: () => redraws++ });
    let pop = make();
    const wrap = { querySelector: () => (pop.isConnected ? pop : null) };
    const open = () => { pop = make(); card._popOpen = true; card._popAway(pop, wrap); };
    const run = () => timers.splice(0).forEach((x) => x.f && x.f());

    open();
    tap([el("node")]);
    assert.ok(pop.isConnected, "a tap on another node is left to that node, which swaps the popup");
    tap([el("row"), pop]);
    assert.ok(pop.isConnected, "a tap inside keeps it");
    tap([el("sharebtn")]);
    assert.ok(!pop.isConnected, "a tap outside closes it");
    assert.ok(!on.click && !on.keydown && !card._popOff, "and lets go of the page");
    assert.strictEqual(redraws, 0, "the redraw waits until the tap has been handled, so the button under it still works");
    run();
    assert.strictEqual(redraws, 1);

    open();
    tap([el("sharebtn")]);
    card._popOpen = true; // that tap opened the share popup
    run();
    assert.strictEqual(redraws, 1, "no redraw under a popup the same tap opened");
    card._popOpen = false;

    open();
    on.keydown({ key: "Escape" });
    assert.ok(!pop.isConnected, "Escape closes it");
    assert.strictEqual(redraws, 2);

    open();
    const t = timers.find((x) => x.f && x.ms > 119000);
    t.f();
    assert.ok(!pop.isConnected, "left alone for two minutes, it closes");
    run();

    open();
    pop.fire("input");
    tap([el("map")]);
    timers.forEach((x) => x.f && x.f());
    assert.ok(pop.isConnected, "a form with unsaved changes stays open");
    on.keydown({ key: "Escape" });
    assert.ok(!pop.isConnected, "until Escape (or Close, or its own buttons)");
    run();

    open();
    pop.fire("input");
    pop.isConnected = false; // the card redrew under it
    tap([el("map")]);
    assert.ok(!card._popOpen && !card._popOff, "a popup no longer on the page never keeps the map frozen");

    open();
    pop.fire("pointerdown");
    assert.ok(card._popPressed, "a press inside holds redraws");
    on.pointerup({});
    assert.ok(card._popPressed, "until its click has been handled");
    timers.filter((x) => x.f && x.ms === 0).forEach((x) => { const f = x.f; x.f = null; f(); });
    assert.ok(!card._popPressed);
    on.keydown({ key: "Escape" });
    assert.ok(!on.pointerup && !on.pointercancel, "and lets go of the page when it closes");
  } finally {
    Object.assign(globalThis, saved);
  }
});

test("the details popup lets the map update and opens again from the new data; forms and presses hold updates", () => {
  const st = (id, attrs, state = "online") => ({ entity_id: id, state, attributes: Object.assign({ netorbit: true }, attrs) });
  const PC = "00:00:5e:00:53:10";
  const list = (pc) => [
    st("sensor.sum", { kind: "summary", config_entry_id: "E1" }, "1"),
    st("sensor.r", { kind: "hub", node_key: "hub:gateway", label: "Router", hub_type: "router" }),
    ...(pc ? [st("sensor.pc", { kind: "device", node_key: PC, mac: PC.toUpperCase(), link: "hub:gateway", label: "PC" }, pc)] : []),
  ];
  const hass = (l) => ({ states: Object.fromEntries(l.map((s) => [s.entity_id, s])), entities: {}, user: { is_admin: true } });
  const card = new globalThis.NetOrbitCard();
  card.shadowRoot = {};
  card.setConfig({});
  let drawn = 0;
  const shown = [];
  // What _render and _wire leave behind, without a DOM: the popup sat at 40,60 scrolled down 30 px.
  const wrap = { isConnected: true, querySelector: () => ({ style: { left: "40px", top: "60px" }, scrollTop: 30 }) };
  card._render = (m) => {
    drawn++;
    card._detailsCtx = { wrap, place: () => {}, hubs: m.hubs, all: Object.fromEntries(m.devices.map((d) => [d.key, d])), col: () => "" };
  };
  card._detailsPopup = (n, ev, w, place, hubs, all, col, keep) => {
    shown.push([n.status, keep.left, keep.top, keep.scroll, keep.touched]);
    card._liveDetails = { key: n.key, ev };
  };
  card.hass = hass(list("online"));
  assert.strictEqual(drawn, 1);

  card._popOpen = true;
  card._liveDetails = { key: PC, ev: {} };
  card._popLast = 1234;
  card.hass = hass(list("stale"));
  assert.strictEqual(drawn, 2, "the map updates under the details popup");
  assert.deepStrictEqual(shown, [["stale", "40px", "60px", 30, 1234]], "and the popup opens again with the new status, where it was");

  card._liveDetails = null; // a form (Edit, a menu) is open instead
  card.hass = hass(list("online"));
  assert.strictEqual(drawn, 2, "a form holds updates");

  card._liveDetails = { key: PC, ev: {} };
  card._popPressed = true;
  card.hass = hass(list("online"));
  assert.strictEqual(drawn, 2, "so does a press inside the details popup");
  card._popPressed = false;
  card.hass = card._hass;
  assert.strictEqual(drawn, 3);
  assert.strictEqual(shown[1][0], "online");

  card.hass = hass(list(null));
  assert.strictEqual(drawn, 4);
  assert.ok(!card._popOpen && !card._liveDetails, "a device gone from the map closes its popup");
});

test("the video pump holds the first frame, then advances exactly 1/30 s per frame", () => {
  const { painted, pushed, finished } = pumpRun();
  assert.strictEqual(painted.length, 120);
  assert.strictEqual(finished, 1);
  assert.deepStrictEqual(pushed, painted.map((_, i) => i), "one frame per tick, in order");
  assert.ok(painted.slice(0, 9).every((t) => t === 0), "opening held");
  for (let i = 9; i < painted.length; i++) assert.ok(Math.abs(painted[i] - painted[i - 1] - 1 / 30) < 1e-9, `step ${i}`);
  assert.ok(Math.abs(painted[119] - 111 / 30) < 1e-9);
});

test("a stalled timer freezes the video but never makes the animation jump", () => {
  // Frames 20 to 25 each fire 700 ms late, and one later tick is 3 s late.
  const { painted, finished } = pumpRun((n) => (n >= 20 && n <= 25 ? 700 : n === 60 ? 3000 : 0));
  assert.strictEqual(painted.length, 120);
  assert.strictEqual(finished, 1);
  for (let i = 9; i < painted.length; i++) assert.ok(Math.abs(painted[i] - painted[i - 1] - 1 / 30) < 1e-9, `step ${i} jumped`);
});

test("a late timer is followed by one frame per tick, not a burst that skips ahead", () => {
  const { painted, clk } = pumpRun((n) => (n === 10 ? 1000 : 0), { frames: 40, lead: 0 });
  assert.strictEqual(painted.length, 40);
  assert.deepStrictEqual(painted.map((t) => Math.round(t * 30)), painted.map((_, i) => i));
  assert.ok(clk.now >= 1000);
});

test("the video is about 7.2 s: a quarter second lead, the scan and reveal, then a short hold on the finished map", () => {
  // The same frame count the card computes: lead + ceil((PRE + reveal end + tail) * fps) + 1.
  const lead = Math.round(0.25 * 30);
  const frames = lead + Math.ceil((2.05 + 4 + 0.8) * 30) + 1;
  const { painted, finished } = pumpRun(null, { frames, lead });
  assert.strictEqual(lead, 8);
  assert.strictEqual(frames, 215);
  assert.strictEqual(painted.length, frames);
  assert.strictEqual(finished, 1);
  assert.ok(Math.abs(painted.length / 30 - 7.17) < 0.01);
  // The animation reaches the end of the reveal plus the 0.8 s hold on the very last frame.
  assert.ok(Math.abs(painted[frames - 1] - (frames - 1 - lead) / 30) < 1e-9);
  assert.ok(painted[frames - 1] >= 2.05 + 4 + 0.8 - 1 / 30);
});

test("stop() ends the pump and clears its timer", () => {
  const clk = fakeClock();
  let n = 0, finished = 0, p;
  p = noFramePump({ fps: 30, frames: 100, lead: 0, frame: () => { if (++n === 5) p.stop(); }, done: () => finished++, now: () => clk.now, later: clk.later, clear: clk.clear });
  clk.run();
  assert.strictEqual(n, 5);
  assert.strictEqual(finished, 0);
  assert.strictEqual(clk.q.length, 0);
});

const { noLink, noParseFields } = require("../custom_components/netorbit/frontend/netorbit-card.js");

test("managed by: a link, a node on the map, or words", () => {
  const nodes = { "hub:core": { key: "hub:core", kind: "hub", label: "Core Switch", ip: "192.0.2.5" }, d1: { key: "d1", kind: "device", label: "NAS", mac: "00:00:5E:00:53:0A", hostname: "nas" } };
  assert.deepStrictEqual(noLink("https://192.0.2.5/admin", nodes), { kind: "url", href: "https://192.0.2.5/admin" });
  assert.deepStrictEqual(noLink("core switch", nodes), { kind: "node", key: "hub:core" });
  assert.deepStrictEqual(noLink("core", nodes), { kind: "node", key: "hub:core" });
  assert.deepStrictEqual(noLink("00:00:5e:00:53:0a", nodes), { kind: "node", key: "d1" });
  assert.deepStrictEqual(noLink("nas", nodes), { kind: "node", key: "d1" });
  assert.deepStrictEqual(noLink("ISP support", nodes), { kind: "text" });
  assert.deepStrictEqual(noLink("javascript:alert(1)", nodes), { kind: "text" });
  assert.deepStrictEqual(noLink("", nodes), { kind: "none" });
});

test("extra fields parse one Label: value per line", () => {
  assert.deepStrictEqual(noParseFields("Location: Hall\n\nURL: https://192.0.2.1/x\nEmpty:"), { Location: "Hall", URL: "https://192.0.2.1/x", Empty: "" });
  assert.throws(() => noParseFields("no separator"), /Label: value/);
  assert.throws(() => noParseFields(": nothing before"), /Label: value/);
  assert.deepStrictEqual(noParseFields(""), {});
});

// ---------------------------------------------------------------- the layout a card shows

function layoutCard(config, path, store) {
  globalThis.localStorage = store;
  globalThis.location = { pathname: path };
  const c = new card.NetOrbitCard();
  c.shadowRoot = {};
  Object.defineProperty(c, "hass", { set() {}, configurable: true }); // _setLayout redraws; nothing to draw here
  c.setConfig(config);
  return c;
}

function memStore() {
  const m = {};
  return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, keys: () => Object.keys(m) };
}

test("a layout picked on one card stays on that card", () => {
  const store = memStore();
  const a = layoutCard({ title: "Network" }, "/lovelace/net", store);
  a._setLayout("balloon");
  assert.strictEqual(a._layoutName(), "balloon");
  assert.deepStrictEqual(store.keys(), [card.noLayoutKey({ title: "Network" }, "/lovelace/net")]);
  assert.ok(!store.keys().includes("netorbit-layout"), "no site-wide key");
  // The same card again (a reload) remembers it.
  assert.strictEqual(layoutCard({ title: "Network" }, "/lovelace/net", store)._layoutName(), "balloon");
  // Another card, or the same card on another view, starts from its own config.
  assert.strictEqual(layoutCard({ title: "Upstairs" }, "/lovelace/net", store)._layoutName(), "radial");
  assert.strictEqual(layoutCard({ title: "Network" }, "/lovelace/other", store)._layoutName(), "radial");
});

test("with the switch hidden, the card's layout option always wins", () => {
  const store = memStore();
  const cfg = { title: "Network", layout: "radial", layout_toggle: false };
  store.setItem(card.noLayoutKey(cfg, "/lovelace/net"), "balloon");
  const c = layoutCard(cfg, "/lovelace/net", store);
  assert.strictEqual(c._layoutName(), "radial");
  c._layoutOverride = "balloon"; // left over from before the switch was hidden
  assert.strictEqual(c._layoutName(), "radial");
  assert.strictEqual(layoutCard({ layout: "balloon", layout_toggle: false }, "/", memStore())._layoutName(), "balloon");
});

test("editing the card's layout option takes effect over an earlier pick", () => {
  const store = memStore();
  const c = layoutCard({ title: "Network" }, "/lovelace/net", store);
  c._setLayout("balloon");
  c.setConfig({ title: "Network", layout: "radial" });
  assert.strictEqual(c._layoutName(), "radial", "a new config starts from its own layout");
  c.setConfig({ title: "Network", layout: "balloon" });
  assert.strictEqual(c._layoutName(), "balloon");
});

test("blocked storage falls back to the card's option, and a pick still works on show", () => {
  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  const c = layoutCard({ layout: "balloon" }, "/", blocked);
  assert.strictEqual(c._layoutName(), "balloon");
  c._setLayout("radial");
  assert.strictEqual(c._layoutName(), "radial");
});
