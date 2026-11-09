// Browser test of edit mode and zoom: node scripts/preview/interact.js (needs playwright and a server on :8766,
// or on the address in NETORBIT_PREVIEW).
// BROWSER=webkit runs it in WebKit (the touch cases that need Chrome's DevTools protocol are skipped there).
const { chromium, webkit } = require("playwright");
const assert = require("node:assert");
const fs = require("node:fs");
const IS_WEBKIT = process.env.BROWSER === "webkit";
const BASE = (process.env.NETORBIT_PREVIEW || "http://localhost:8766").replace(/\/+$/, "");
(async () => {
  const browser = await (IS_WEBKIT ? webkit : chromium).launch();
  const page = await browser.newPage({ viewport: { width: 1008, height: 1100 } });
  page.setDefaultTimeout(8000);
  page.on("pageerror", (e) => { console.error("PAGE ERROR", e.message); process.exitCode = 1; });
  await page.goto(BASE + "/scripts/preview/index.html?s=novice");
  await page.waitForFunction(() => window.ready);
  const card = page.locator("netorbit-card");
  const center = async (sel) => {
    const b = await card.locator(sel).first().boundingBox();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  };
  const discOf = (key) => `.node[data-key="${key}"] circle.disc`;
  const keyOf = (label) => page.evaluate((l) => {
    const st = Object.values(window.NETORBIT_SCENARIOS.novice).find((s) => s.attributes.label === l);
    return st.attributes.node_key;
  }, label);

  // 1. Turn on edit mode.
  await card.locator(".editbtn").click();
  assert.ok(await card.locator(".banner").isVisible(), "edit banner shown");

  // 2. Drag Smart Plug onto Mesh Node 2.
  const plug = await keyOf("Smart Plug");
  const from = await center(discOf(plug));
  const to = await center(discOf("hub:m1"));
  await page.mouse.move(from.x, from.y);
  await page.mouse.down();
  await page.mouse.move((from.x + to.x) / 2, (from.y + to.y) / 2, { steps: 5 });
  await page.mouse.move(to.x + 4, to.y + 3, { steps: 5 });
  assert.ok(await card.locator('.node.hub.hot[data-key="hub:m1"]').count(), "hub highlights while dragging");
  await page.mouse.up();
  let calls = await page.evaluate(() => window.calls);
  assert.deepStrictEqual(calls.at(-1).slice(0, 2), ["netorbit", "assign_device"]);
  assert.strictEqual(calls.at(-1)[2].hub, "m1");
  // The device is drawn under its new hub right away, with a "saving" ring, before Home Assistant answers.
  assert.ok(await card.locator(`.node.pending[data-key="${plug}"] .pendring`).count(), "moved device shows as saving at once");
  // A device you placed by hand shows as pinned in edit mode: blue fill plus a pin badge.
  assert.ok(await card.locator(`.node.pinned[data-key="${plug}"] .pin path`).count(), "moved device shows as pinned");
  console.log("drag ok:", JSON.stringify(calls.at(-1)[2]));

  // 3. Tap a device, use Move to.
  const tv = await keyOf("Bedroom TV");
  const tvAt = await center(discOf(tv));
  await page.mouse.click(tvAt.x, tvAt.y);
  await card.locator(".pop select.hub").selectOption("m1");
  await card.locator(".pop .move").click();
  calls = await page.evaluate(() => window.calls);
  assert.strictEqual(calls.at(-1)[1], "assign_device");
  console.log("tap move ok:", JSON.stringify(calls.at(-1)[2]));

  // 4. Tap a device, make it a hub.
  await page.mouse.click(tvAt.x, tvAt.y);
  await card.locator(".pop select.type").selectOption("mesh_node");
  await card.locator(".pop .mk").click();
  calls = await page.evaluate(() => window.calls);
  assert.strictEqual(calls.at(-1)[1], "confirm_hub");
  assert.strictEqual(calls.at(-1)[2].type, "mesh_node");
  console.log("make hub ok:", JSON.stringify(calls.at(-1)[2]));

  // 5. Rename a hub.
  await card.locator('.node.hub[data-key="hub:m1"]').click();
  await card.locator(".pop input.name").fill("Upstairs Node");
  await card.locator(".pop .save").click();
  calls = await page.evaluate(() => window.calls);
  assert.deepStrictEqual(calls.at(-1).slice(1), ["update_hub", { hub: "m1", name: "Upstairs Node", config_entry_id: "preview" }]);
  console.log("rename ok");

  // 5b. Change a hub's type (a Wi-Fi extender that was added as a plain hub, say).
  await card.locator('.node.hub[data-key="hub:m1"]').click();
  await card.locator(".pop select.type").selectOption("access_point");
  await card.locator(".pop .save").click();
  calls = await page.evaluate(() => window.calls);
  assert.deepStrictEqual(calls.at(-1).slice(1), ["update_hub", { hub: "m1", type: "access_point", config_entry_id: "preview" }]);
  console.log("hub type ok");

  // 6. Leave edit mode, confirm the suggested hub.
  await card.locator(".editbtn").click();
  const sugKey = await page.evaluate(() => "sug:" + window.NETORBIT_SCENARIOS.novice["sensor.netorbit_devices_online"].attributes.suggested_hubs[0].key);
  await card.locator(`.node[data-key="${sugKey}"] circle.disc`).click({ force: true });
  await card.locator(".pop .yes").click();
  calls = await page.evaluate(() => window.calls);
  assert.strictEqual(calls.at(-1)[1], "confirm_hub");
  console.log("suggestion ok:", JSON.stringify(calls.at(-1)[2]));

  // 7. Outside edit mode, tapping a device opens its details popup; "More info" there opens Home Assistant's dialog.
  await page.evaluate(() => document.addEventListener("hass-more-info", (e) => (window.moreInfo = e.detail.entityId)));
  const tvNow = await center(discOf(tv)); // the edit banner is gone, so the map moved up
  await page.mouse.click(tvNow.x, tvNow.y);
  const info = card.locator(".pop .info");
  await info.waitFor();
  assert.strictEqual((await info.textContent()).trim(), "More info", "tap opens the details popup");
  await info.click();
  const opened = await page.evaluate(() => window.moreInfo);
  assert.ok(opened && opened.startsWith("sensor.netorbit_"), "More info opens Home Assistant's details");
  console.log("details + more-info ok:", opened);

  // 8. Touch: drag with a finger on a phone sized screen.
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  phone.setDefaultTimeout(8000);
  await phone.goto(BASE + "/scripts/preview/index.html?s=novice");
  await phone.waitForFunction(() => window.ready);
  const c2 = phone.locator("netorbit-card");
  await c2.locator(".editbtn").click();
  const b = await c2.locator(`.node[data-key="${tv}"] circle.disc`).boundingBox();
  await c2.locator(`.node[data-key="${tv}"] circle.disc`).tap();
  assert.ok(await c2.locator(".pop select.hub").isVisible(), "tap opens the menu on a phone");
  console.log("phone tap ok, popup width", (await c2.locator(".pop").boundingBox()).width, "screen 390");
  // 8b. A flick: press, one move partway, release on the hub with no move there.
  {
    const fl = await browser.newPage({ viewport: { width: 1008, height: 1100 } });
    await fl.goto(BASE + "/scripts/preview/index.html?s=novice");
    await fl.waitForFunction(() => window.ready);
    const c4 = fl.locator("netorbit-card");
    await c4.locator(".editbtn").click();
    const bb = async (sel) => { const r = await c4.locator(sel).first().boundingBox(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; };
    const lamp = await fl.evaluate(() => Object.values(window.NETORBIT_SCENARIOS.novice).find((s) => s.attributes.label === "Lamp").attributes.node_key);
    const f = await bb(`.node[data-key="${lamp}"] circle.disc`), t2 = await bb('.node[data-key="hub:m1"] circle.disc');
    await fl.mouse.move(f.x, f.y); await fl.mouse.down();
    await fl.mouse.move(f.x + (t2.x - f.x) * 0.2, f.y + (t2.y - f.y) * 0.2);
    await fl.evaluate(([x, y]) => {
      const card = document.querySelector("netorbit-card");
      const el = card.shadowRoot.querySelector(".node.dev.draggable");
      // Release straight over the hub, as a fast flick or some touch screens do.
      card.shadowRoot.querySelectorAll(".node").forEach(() => {});
      const target = card._drag && card.shadowRoot.querySelector(`.node[data-key="${CSS.escape(card._drag.n.key)}"]`);
      (target || el).dispatchEvent(new PointerEvent("pointerup", { bubbles: true, clientX: x, clientY: y, pointerId: card._drag ? card._drag.id : 1 }));
    }, [t2.x, t2.y]);
    await fl.mouse.up();
    const c = await fl.evaluate(() => window.calls);
    assert.ok(c.length && c.at(-1)[1] === "assign_device" && c.at(-1)[2].hub === "m1", "flick release lands on the hub");
    console.log("flick drop ok");
    await fl.close();
  }

  // 9. Drag still lands on a narrower card (tablets, side panels).
  for (const w of [760, 600]) {
    const nar = await browser.newPage({ viewport: { width: w, height: 1000 } });
    await nar.goto(BASE + "/scripts/preview/index.html?s=novice");
    await nar.waitForFunction(() => window.ready);
    const c3 = nar.locator("netorbit-card");
    await c3.locator(".editbtn").click();
    const bb = async (sel) => { const r = await c3.locator(sel).first().boundingBox(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; };
    const f = await bb(`.node[data-key="${plug}"] circle.disc`), t2 = await bb('.node[data-key="hub:m1"] circle.disc');
    await nar.mouse.move(f.x, f.y); await nar.mouse.down();
    await nar.mouse.move(t2.x, t2.y, { steps: 12 }); await nar.mouse.up();
    const c = await nar.evaluate(() => window.calls);
    assert.ok(c.length && c.at(-1)[1] === "assign_device" && c.at(-1)[2].hub === "m1", `drag works at ${w}px`);
    console.log(`narrow drag ok at ${w}px`);
    await nar.close();
  }
  // 10. Drop on a suggested hub (pink ring): asks to make it a hub, then confirms it and moves the device in one call.
  //     A drop on empty space moves nothing.
  {
    const sp = await browser.newPage({ viewport: { width: 1008, height: 1100 } });
    sp.on("pageerror", (e) => { console.error("PAGE ERROR", e.message); process.exitCode = 1; });
    await sp.goto(BASE + "/scripts/preview/index.html?s=novice");
    await sp.waitForFunction(() => window.ready);
    const c5 = sp.locator("netorbit-card");
    await c5.locator(".editbtn").click();
    const bb = async (sel) => { const r = await c5.locator(sel).first().boundingBox(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; };
    const sug = await sp.evaluate(() => window.NETORBIT_SCENARIOS.novice["sensor.netorbit_devices_online"].attributes.suggested_hubs[0].key);
    const f = await bb(`.node[data-key="${plug}"] circle.disc`), t3 = await bb(`.node[data-key="sug:${sug}"] circle.disc`);
    const before = (await sp.evaluate(() => window.calls)).length;

    // Empty space: far from every hub and suggestion.
    const box = await c5.locator("svg.map").boundingBox();
    await sp.mouse.move(f.x, f.y); await sp.mouse.down();
    await sp.mouse.move(box.x + box.width - 8, box.y + 8, { steps: 10 }); await sp.mouse.up();
    assert.strictEqual((await sp.evaluate(() => window.calls)).length, before, "a drop on empty space moves nothing");

    await sp.mouse.move(f.x, f.y); await sp.mouse.down();
    await sp.mouse.move(t3.x, t3.y, { steps: 10 });
    assert.ok(await c5.locator(`.node.hot[data-key="sug:${sug}"]`).count(), "suggested hub highlights while dragging");
    await sp.mouse.up();
    assert.ok(await c5.locator(".pop .yes").isVisible(), "drop on a suggestion asks first");
    assert.strictEqual((await sp.evaluate(() => window.calls)).length, before, "nothing changes until confirmed");
    await c5.locator(".pop .yes").click();
    const c = await sp.evaluate(() => window.calls);
    const last = c.at(-1);
    assert.strictEqual(last[1], "confirm_hub");
    assert.strictEqual(last[2].device, sug);
    assert.ok(Array.isArray(last[2].assign) && last[2].assign.length === 1, "the dragged device is moved under the new hub");
    console.log("drop on suggestion ok:", JSON.stringify(last[2]));
    await sp.close();
  }

  // 11. The internet node: above the router, green when up, red with "Internet down" when not, and gone when turned off.
  for (const [q, want] of [["", "online"], ["&internet=down", "stale"], ["&internet=off", null]]) {
    const ip = await browser.newPage({ viewport: { width: 1008, height: 1100 } });
    ip.on("pageerror", (e) => { console.error("PAGE ERROR", e.message); process.exitCode = 1; });
    await ip.goto(BASE + "/scripts/preview/index.html?s=novice" + q);
    await ip.waitForFunction(() => window.ready);
    const c6 = ip.locator("netorbit-card");
    const node = c6.locator('.node.inet[data-key="internet"]');
    if (!want) {
      assert.strictEqual(await node.count(), 0, "no internet node when the sensor is missing");
    } else {
      assert.ok(await c6.locator(`.node.inet.${want}`).count(), `internet node is ${want}`);
      const ib = await node.locator("circle.disc").boundingBox(), rb = await c6.locator('.node.hub[data-key="hub:gw"] circle.disc, .node.hub circle.disc').first().boundingBox();
      assert.ok(ib.y < rb.y, "internet sits above the router");
      const text = await c6.locator("text.ilab").textContent();
      assert.strictEqual(text, want === "stale" ? "Internet down" : "Internet");
      await node.locator("circle.disc").hover();
      assert.ok((await c6.locator(".tip").textContent()).includes(want === "stale" ? "Down" : "Up"), "tooltip says up or down");
    }
    console.log(`internet ${want || "off"} ok`);
    await ip.close();
  }

  // 12. The first scan: radar, a "Scanning N%" chip and a pill with what was found so far, instead of the
  //     status chips, legend and buttons.
  {
    const sc = await browser.newPage({ viewport: { width: 1008, height: 1100 } });
    sc.on("pageerror", (e) => { console.error("PAGE ERROR", e.message); process.exitCode = 1; });
    await sc.goto(BASE + "/scripts/preview/index.html?s=firstscan");
    await sc.waitForFunction(() => window.ready);
    const c7 = sc.locator("netorbit-card");
    assert.strictEqual((await c7.locator(".scanpill .l1").textContent()).trim(), "Scanning your network... found 12 devices");
    assert.strictEqual((await c7.locator(".scanpill .l2").textContent()).trim(), "Pinging every address");
    assert.strictEqual((await c7.locator(".head .scanchip").textContent()).trim(), "Scanning 30%");
    assert.strictEqual(await c7.locator(".head .chip, .head .editbtn, .head .sharebtn").count(), 0, "status chips and buttons make way for the scan");
    assert.strictEqual(await c7.locator(".legend").evaluate((e) => getComputedStyle(e).visibility), "hidden", "legend hidden while scanning");
    assert.strictEqual(await c7.locator(".node.dev").count(), 0, "devices only arrive when the scan is done");
    assert.ok(await c7.locator(".radar .beam").evaluate((e) => getComputedStyle(e).display !== "none"), "beam sweeps");
    // The found count follows the sensor without redrawing the radar.
    await sc.evaluate(() => {
      const card = document.querySelector("netorbit-card");
      const st = window.NETORBIT_SCENARIOS.firstscan;
      card.shadowRoot.querySelector(".radar").dataset.mark = "same";
      Object.assign(st["sensor.netorbit_devices_online"].attributes, { found: 21, scan_phase: "names", scan_progress: 55 });
      card.hass = Object.assign({}, card._hass, { states: Object.assign({}, st) });
    });
    assert.strictEqual((await c7.locator(".scanpill .l1").textContent()).trim(), "Scanning your network... found 21 devices");
    assert.strictEqual((await c7.locator(".scanpill .l2").textContent()).trim(), "Asking devices their names");
    assert.strictEqual((await c7.locator(".head .scanchip").textContent()).trim(), "Scanning 55%");
    assert.strictEqual(await c7.locator(".radar").getAttribute("data-mark"), "same", "progress updates in place");
    console.log("first scan takeover ok");
    await sc.close();

    // Reduced motion: no beam, no pulses, the rings stay; words and progress still update.
    const rm = await browser.newPage({ viewport: { width: 1008, height: 1100 }, reducedMotion: "reduce" });
    await rm.goto(BASE + "/scripts/preview/index.html?s=firstscan");
    await rm.waitForFunction(() => window.ready);
    const c8 = rm.locator("netorbit-card");
    assert.strictEqual(await c8.locator(".radar .beam").evaluate((e) => getComputedStyle(e).display), "none", "no beam with reduced motion");
    assert.strictEqual(await c8.locator(".radar .pr").first().evaluate((e) => getComputedStyle(e).display), "none", "no pulses with reduced motion");
    assert.strictEqual(await c8.locator(".radar .st").count(), 3, "range rings stay");
    assert.strictEqual(await c8.locator(".scanchip .rb").evaluate((e) => getComputedStyle(e).animationName), "none");
    assert.ok((await c8.locator(".scanpill .l1").textContent()).includes("found 12"));
    console.log("reduced motion ok");
    await rm.close();

    // A later scan: the normal map, plus a small chip before Edit layout.
    const rs = await browser.newPage({ viewport: { width: 1008, height: 1100 } });
    await rs.goto(BASE + "/scripts/preview/index.html?s=rescan");
    await rs.waitForFunction(() => window.ready);
    const c9 = rs.locator("netorbit-card");
    assert.strictEqual((await c9.locator(".head .scanchip").textContent()).trim(), "Scanning...");
    assert.ok(await c9.locator(".head .chip").count() >= 3, "status chips stay");
    assert.ok(await c9.locator(".head .editbtn").isVisible(), "Edit layout stays");
    assert.strictEqual(await c9.locator(".scanpill, .radar").count(), 0, "no takeover on a later scan");
    assert.ok(await c9.locator(".head .scanchip + .sharebtn").count(), "chip sits before Share and Edit layout");
    console.log("rescan chip ok");
    await rs.close();

    // The first scan finishes: the map plays in, then the normal header and legend come back.
    const fin = await browser.newPage({ viewport: { width: 1008, height: 1100 } });
    fin.on("pageerror", (e) => { console.error("PAGE ERROR", e.message); process.exitCode = 1; });
    await fin.goto(BASE + "/scripts/preview/index.html?s=firstscan&finish=800");
    await fin.waitForFunction(() => window.finished);
    const c10 = fin.locator("netorbit-card");
    assert.ok(await c10.locator("ha-card.revealing .radar.js").count(), "reveal plays when the first map arrives");
    assert.ok((await c10.locator(".scanpill .l1").textContent()).startsWith("Found "));
    await fin.waitForFunction(() => {
      const r = document.querySelector("netorbit-card").shadowRoot;
      return r.querySelectorAll(".scanpill, .radar, .scanchip").length === 0;
    }, null, { timeout: 10000 });
    assert.strictEqual(await c10.locator(".scanpill, .radar, .scanchip").count(), 0, "reveal cleaned up");
    assert.ok(await c10.locator(".head .editbtn").isVisible() && await c10.locator(".legend").isVisible(), "normal header and legend are back");
    assert.ok(await c10.locator(".node.dev").count() > 20, "devices on the map");
    console.log("reveal ok");

    // The beam turns around the router. Where its line starts on screen (through the line's screen matrix, which
    // includes any CSS transform-origin acting on the transform attribute) must stay on the router's centre, and
    // the far end must stay one beam length away from it, at several moments of the reveal. In WebKit a leftover
    // transform-origin sent the beam round the whole card.
    // The samples are timed from the first frame that shows the beam, not from the call, so a slow click does not
    // eat into the window. It samples for at least minMs and goes on until the beam has turned through minTurn
    // radians, but gives up after maxMs (the beam turns once in about 2 s and the radar is gone after 3.3 s).
    const beamProbe = (minMs, minTurn, maxMs) => fin.evaluate(([minMs, minTurn, maxMs]) => new Promise((resolve) => {
      const root = document.querySelector("netorbit-card").shadowRoot;
      const out = [];
      // Where every node sits when the map is complete. The scale a node pops in with must keep it centred there.
      const rest = new Map();
      root.querySelectorAll(".node[data-key] circle.disc").forEach((d) => { const r = d.getBoundingClientRect(); rest.set(d, [r.x + r.width / 2, r.y + r.height / 2]); });
      const tStart = performance.now();
      let t0 = null;
      let lo = Infinity, hi = -Infinity, ang = 0, prev = null;
      const tick = () => {
        const line = root.querySelector(".radar.js .beam line");
        const disc = root.querySelector(".node[data-key=\"hub:gateway\"] circle.disc");
        if (line && disc && t0 === null) t0 = performance.now();
        if (line && disc) {
          const m = line.getScreenCTM();
          const at = (x, y) => { const p = new DOMPoint(x, y).matrixTransform(m); return [p.x, p.y]; };
          const a = at(line.x1.baseVal.value, line.y1.baseVal.value), b = at(line.x2.baseVal.value, line.y2.baseVal.value);
          const r = disc.getBoundingClientRect();
          out.push({ t: (performance.now() - t0) / 1000, a, b, c: [r.x + r.width / 2, r.y + r.height / 2],
            len: Math.hypot(b[0] - a[0], b[1] - a[1]),
            drift: Math.max(0, ...[...rest].filter(([d]) => d.parentNode.getAttribute("transform") && getComputedStyle(d.parentNode).opacity > 0.3 && d.getBoundingClientRect().width > 4)
              .map(([d, c]) => { const q = d.getBoundingClientRect(); return Math.hypot(q.x + q.width / 2 - c[0], q.y + q.height / 2 - c[1]); })),
            card: root.querySelector("ha-card").getBoundingClientRect().toJSON() });
          // The angle is unwrapped (no jump at +-pi), so the turn is the real turn and a small turn across the
          // +-pi line cannot read as a full circle.
          const raw = Math.atan2(b[1] - a[1], b[0] - a[0]);
          ang = prev === null ? raw : ang + Math.atan2(Math.sin(raw - prev), Math.cos(raw - prev));
          prev = raw;
          lo = Math.min(lo, ang); hi = Math.max(hi, ang);
        }
        const now = performance.now();
        const done = t0 === null ? now - tStart > maxMs
          : (now - t0 >= minMs && (hi - lo > minTurn || now - t0 >= maxMs)) || !line;
        if (done) resolve(out); else requestAnimationFrame(tick);
      };
      tick();
    }), [minMs, minTurn, maxMs]);
    const checkBeam = (s, what) => {
      assert.ok(s.length >= 5, `${what}: ${s.length} beam samples`);
      s.forEach((p) => {
        const d0 = Math.hypot(p.a[0] - p.c[0], p.a[1] - p.c[1]);
        assert.ok(d0 < 4, `${what}: beam starts ${d0.toFixed(1)}px from the router at ${p.t.toFixed(2)}s`);
        assert.ok(p.drift < 3, `${what}: a popping-in node drifted ${p.drift.toFixed(1)}px off its place at ${p.t.toFixed(2)}s`);
        assert.ok(Math.abs(p.len - s[0].len) < 2, `${what}: beam length stays ${s[0].len.toFixed(1)}px, was ${p.len.toFixed(1)}px at ${p.t.toFixed(2)}s`);
        assert.ok(p.b[0] > p.card.x - 400 && p.b[0] < p.card.x + p.card.width + 400 && p.b[1] > p.card.y - 400 && p.b[1] < p.card.y + p.card.height + 400, `${what}: beam stays on the card`);
      });
      let cur = 0, prev = null;
      const angles = s.map((p) => {
        const raw = Math.atan2(p.b[1] - p.a[1], p.b[0] - p.a[0]);
        cur = prev === null ? raw : cur + Math.atan2(Math.sin(raw - prev), Math.cos(raw - prev));
        prev = raw;
        return cur;
      });
      assert.ok(Math.max(...angles) - Math.min(...angles) > 1.5, `${what}: the beam turned through ${(Math.max(...angles) - Math.min(...angles)).toFixed(2)} rad`);
    };

    // Replay it from the Share popup.
    await c10.locator(".sharebtn").click();
    const beamRun = beamProbe(1700, 1.5, 5000);
    await c10.locator(".sharepop .replay").click();
    assert.ok(await c10.locator("ha-card.revealing .radar.js").count(), "replay plays the reveal");
    checkBeam(await beamRun, "replay");
    console.log("beam turns around the router ok");
    await fin.waitForFunction(() => document.querySelector("netorbit-card").shadowRoot.querySelectorAll(".radar").length === 0, null, { timeout: 10000 });
    assert.strictEqual(await c10.locator(".radar").count(), 0, "replay cleaned up");
    console.log("replay ok");

    // Replaying twice, 1.5 s apart: the older run must not cut the newer one short (it would end 2.5 s in).
    await fin.evaluate(() => document.querySelector("netorbit-card").replayScan());
    await fin.waitForTimeout(1500);
    await fin.evaluate(() => document.querySelector("netorbit-card").replayScan());
    await fin.waitForTimeout(2600);
    assert.ok(await c10.locator("ha-card.revealing .radar.js").count(), "a second replay still plays 2.6 s in");
    await fin.waitForTimeout(2000);
    assert.strictEqual(await c10.locator(".radar").count(), 0, "second replay cleaned up");
    console.log("double replay ok");
    await fin.close();
  }

  // 13. Share: an image with names hidden by default and never an address, and the scan as a video.
  {
    const sctx = await browser.newContext({ viewport: { width: 1008, height: 1100 }, acceptDownloads: true });
    const sh = await sctx.newPage();
    sh.setDefaultTimeout(8000);
    sh.on("pageerror", (e) => { console.error("PAGE ERROR", e.message); process.exitCode = 1; });
    await sh.goto(BASE + "/scripts/preview/index.html?s=full");
    await sh.waitForFunction(() => window.ready);
    await sh.waitForTimeout(500);
    const c11 = sh.locator("netorbit-card");
    await c11.locator(".sharebtn").click();
    assert.ok(await c11.locator(".sharepop").isVisible(), "Share opens");
    assert.strictEqual(await c11.evaluate((e) => getComputedStyle(e).display), "block", "the card is a block element");
    assert.strictEqual(await c11.locator(".sharepop .tg").getAttribute("aria-checked"), "true", "names hidden by default");
    const shared = () => c11.locator(".sharepop .thumb").evaluate((img) => decodeURIComponent(img.src.split(",").slice(1).join(",")));
    const names = await sh.evaluate(() => Object.values(window.NETORBIT_SCENARIOS.full).map((s) => s.attributes.label).filter((l) => l && !/^(Router|Internet)$/.test(l)));
    let svg = await shared();
    assert.ok(svg.startsWith("<svg") && svg.includes("made with NetOrbit") && svg.includes("My home network"));
    assert.ok(!svg.includes("192.0.2."), "no IP addresses in the shared image");
    assert.ok(!/\b[0-9a-f]{2}([:-][0-9a-f]{2})+\b/i.test(svg), "no MAC addresses in the shared image");
    const leaked = names.filter((n) => svg.includes(">" + n + "<"));
    assert.deepStrictEqual(leaked, [], "no real names in the shared image");
    assert.ok(svg.includes(">TV 1<") && svg.includes(">Access point<"), "generic names instead");
    assert.ok(!svg.includes("New devices") && !svg.includes("esp-7c2d1a") && !svg.includes("Edit layout"), "no waiting devices, suggestions or buttons");
    const [png] = await Promise.all([sh.waitForEvent("download"), c11.locator(".sharepop .dl").click()]);
    const pngPath = await png.path();
    const buf = require("fs").readFileSync(pngPath);
    assert.strictEqual(buf.slice(1, 4).toString(), "PNG");
    const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);
    assert.ok(buf.length > 50000 && buf.length < 12e6 && w >= 1000 && h >= 1000, `PNG ${w}x${h}, ${buf.length} bytes`);
    console.log(`share PNG ok: ${png.suggestedFilename()} ${w}x${h} ${buf.length} bytes`);
    await c11.locator(".sharepop .tg").click();
    svg = await shared();
    assert.ok(svg.includes(">Core Switch<") && svg.includes(">Bedroom TV<"), "names come back with the toggle off");
    assert.ok(!svg.includes("192.0.2.") && !/\b[0-9a-f]{2}([:-][0-9a-f]{2})+\b/i.test(svg), "still no addresses with names shown");
    await c11.locator(".sharepop .tg").click();
    // The system share sheet gets the PNG when there is one; closing it does nothing; a refusal falls back to a download.
    await sh.evaluate(() => {
      const card = document.querySelector("netorbit-card");
      window.__dl = 0;
      window.__shared = [];
      window.__shareErr = null;
      card._download = () => { window.__dl++; };
      Object.defineProperty(navigator, "canShare", { configurable: true, value: (d) => !!(d && d.files && d.files.length) });
      Object.defineProperty(navigator, "share", { configurable: true, value: (d) => {
        window.__shared.push(d.files[0].name + ":" + d.files[0].type);
        return window.__shareErr ? Promise.reject(Object.assign(new Error("no"), { name: window.__shareErr })) : Promise.resolve();
      } });
    });
    await c11.locator(".sharepop .dl").click();
    await sh.waitForFunction(() => window.__shared.length === 1);
    assert.deepStrictEqual(await sh.evaluate(() => window.__shared), ["netorbit-map.png:image/png"]);
    await sh.waitForTimeout(300);
    assert.strictEqual(await sh.evaluate(() => window.__dl), 0, "no download when the share sheet took it");
    await sh.evaluate(() => (window.__shareErr = "AbortError"));
    await c11.locator(".sharepop .dl").click();
    await sh.waitForFunction(() => window.__shared.length === 2);
    await sh.waitForTimeout(300);
    assert.strictEqual(await sh.evaluate(() => window.__dl), 0, "closing the share sheet does not download");
    await sh.evaluate(() => (window.__shareErr = "NotAllowedError"));
    await c11.locator(".sharepop .dl").click();
    await sh.waitForFunction(() => window.__dl === 1);
    console.log("share sheet ok");
    await sh.evaluate(() => { delete navigator.canShare; delete navigator.share; });

    // Recording a canvas (MediaRecorder, captureStream) is only checked in Chromium.
    if (IS_WEBKIT) {
      console.log("share video skipped in WebKit");
    } else {
      // Chromium can record a canvas: the Animation option is there and gives a video.
      assert.ok(await c11.locator('.sharepop .seg button[data-m="video"]').isVisible(), "animation option offered");
      await c11.locator('.sharepop .seg button[data-m="video"]').click();
      const status = () => c11.locator(".sharepop .status").textContent();
      const allEnded = () => sh.evaluate(() => window.__streams.length > 0 && window.__streams.every((s) => s.getTracks().every((t) => t.readyState === "ended")));
      // A recorder that throws on creation: the button comes back, the error shows, the stream is released.
      await sh.evaluate(() => {
        window.__streams = [];
        const cs = HTMLCanvasElement.prototype.captureStream;
        HTMLCanvasElement.prototype.captureStream = function () { const s = cs.apply(this, arguments); window.__streams.push(s); return s; };
        window.__MR = window.MediaRecorder;
        window.MediaRecorder = class { constructor() { throw new Error("boom"); } static isTypeSupported() { return true; } };
      });
      await c11.locator(".sharepop .rec").click();
      await sh.waitForFunction(() => document.querySelector("netorbit-card").shadowRoot.querySelector(".sharepop .status").textContent.includes("boom"));
      assert.ok((await status()).startsWith("Couldn't record"), await status());
      assert.ok(await c11.locator(".sharepop .rec").isEnabled(), "Save video is enabled again after a failure");
      assert.ok(await allEnded(), "tracks stopped after a failure");
      await sh.evaluate(() => { window.MediaRecorder = window.__MR; window.__streams = []; window.__dl = 0; });
      // Closing the popup mid-recording cancels it: nothing is downloaded and the stream is released. The recorder
      // here never delivers its "start" event (desktop Chromium only sends it when recording stops), and the
      // animation must still begin at once instead of waiting for it.
      await sh.evaluate(() => {
        window.__early = 0;
        window.__MRreal = window.MediaRecorder;
        window.MediaRecorder = class extends window.__MRreal {
          set onstart(f) { /* never called */ }
          get onstart() { return null; }
          addEventListener(type, ...rest) { if (type !== "start") super.addEventListener(type, ...rest); }
        };
        window.MediaRecorder.isTypeSupported = window.__MRreal.isTypeSupported.bind(window.__MRreal);
        window.__paintReal = window.netorbitPaintFrame;
        window.netorbitPaintFrame = function () { window.__early++; return window.__paintReal.apply(this, arguments); };
      });
      await c11.locator(".sharepop .rec").click();
      await sh.waitForTimeout(700);
      assert.ok(await sh.evaluate(() => window.__early) > 5, `the animation runs without a start event (${await sh.evaluate(() => window.__early)} frames painted after 0.7 s)`);
      await sh.evaluate(() => { window.MediaRecorder = window.__MRreal; window.netorbitPaintFrame = window.__paintReal; });
      await c11.locator(".sharepop .x").click();
      await sh.waitForTimeout(1500);
      assert.strictEqual(await sh.evaluate(() => window.__dl), 0, "a cancelled recording is not downloaded");
      assert.ok(await allEnded(), "tracks stopped after a cancel");
      await sh.evaluate(() => { delete document.querySelector("netorbit-card")._download; });
      await c11.locator(".sharebtn").click();
      assert.ok(await c11.locator(".sharepop .tg").isVisible(), "Share opens again after a cancel");
      await c11.locator('.sharepop .seg button[data-m="video"]').click();
      assert.ok(await c11.locator(".sharepop .rec").isEnabled(), "Save video is ready again");
      console.log("video failure and cancel ok");
      // Time the recorder paints must advance by exactly 1/30 s per frame, even when the page stalls: log every
      // paint, count the frames pushed to the stream, and block the main thread for 600 ms once, a second in.
      await sh.evaluate(() => {
        window.__paints = [];
        window.__pushed = 0;
        window.__wall = [];
        window.__canvasSeen = 0;
        const paint = window.netorbitPaintFrame;
        let stalled = false;
        window.netorbitPaintFrame = function (ctx, scene, t) {
          window.__paints.push(t);
          window.__wall.push(performance.now());
          if (ctx.canvas.isConnected) window.__canvasSeen++;
          if (!stalled && window.__paints.length > 45) { stalled = true; const e = performance.now() + 600; while (performance.now() < e) { /* stall */ } }
          return paint.apply(this, arguments);
        };
        const rf = CanvasCaptureMediaStreamTrack.prototype.requestFrame;
        CanvasCaptureMediaStreamTrack.prototype.requestFrame = function () { window.__pushed++; return rf.apply(this, arguments); };
      });
      const [vid] = await Promise.all([sh.waitForEvent("download", { timeout: 30000 }), c11.locator(".sharepop .rec").click()]);
      const paints = (await sh.evaluate(() => window.__paints)).slice(1); // the first paint is the one made before recording
      const wall = (await sh.evaluate(() => window.__wall)).slice(1); // when each of them happened, in ms
      assert.ok(paints.length > 200, `${paints.length} frames painted`);
      const held = paints.filter((t) => t === paints[0]).length;
      assert.ok(held >= 8 && held <= 12, `the opening is held for ${held} frames`);
      for (let i = held; i < paints.length; i++) assert.ok(Math.abs(paints[i] - paints[i - 1] - 1 / 30) < 1e-6, `video time jumped by ${(paints[i] - paints[i - 1]).toFixed(3)} s at frame ${i}`);
      assert.strictEqual(await sh.evaluate(() => window.__pushed), paints.length + 1, "one frame pushed per painted frame, plus the opening frame pushed at start");
      assert.ok(await sh.evaluate(() => window.__canvasSeen) >= paints.length, "the canvas stays attached to the page while recording");
      assert.strictEqual(await sh.evaluate(() => document.querySelectorAll("body > canvas").length), 0, "the recording canvas is removed afterwards");
      const size = require("fs").statSync(await vid.path()).size;
      assert.ok(size > 20000, `video has ${size} bytes`);
      // The clip is as long as the animation it recorded: the frames painted (30 per second) is the least it can be,
      // and the wall clock time the painting took is the most (plus the encoder's closing 120 ms and a frame).
      // MediaRecorder stamps frames with the clock, not the frame number, so a slow or busy machine stretches the
      // file past paints / 30 and a fixed tolerance around it is flaky; this window moves with the machine and
      // still catches a long wait at the start or a long hold at the end.
      const expected = paints.length / 30;
      assert.ok(Math.abs(expected - 7.17) < 0.1, `expected length ${expected.toFixed(2)} s`);
      const spent = (wall[wall.length - 1] - wall[0]) / 1000;
      const b64 = require("fs").readFileSync(await vid.path()).toString("base64");
      const dur = await sh.evaluate(async ([data, mime]) => {
        const bin = atob(data), u8 = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
        const url = URL.createObjectURL(new Blob([u8], { type: mime }));
        const v = document.createElement("video");
        v.muted = true;
        v.preload = "metadata";
        v.src = url;
        await new Promise((res, rej) => { v.onloadedmetadata = res; v.onerror = () => rej(new Error("video did not load")); });
        if (!isFinite(v.duration)) { // MediaRecorder webm has no duration header: seek far ahead to make the browser find it
          await new Promise((res) => { v.ondurationchange = () => { if (isFinite(v.duration)) res(); }; v.currentTime = 1e9; });
        }
        const d = v.duration;
        URL.revokeObjectURL(url);
        return d;
      }, [b64, vid.suggestedFilename().endsWith(".mp4") ? "video/mp4" : "video/webm"]);
      console.log(`video duration ${dur.toFixed(2)} s (frames ${expected.toFixed(2)} s, painted over ${spent.toFixed(2)} s)`);
      assert.ok(dur >= expected - 0.3, `video is ${dur.toFixed(2)} s, shorter than its ${expected.toFixed(2)} s of frames`);
      assert.ok(dur <= spent + 0.75, `video is ${dur.toFixed(2)} s, longer than the ${spent.toFixed(2)} s it took to paint`);
      assert.ok(/^netorbit-scan\.(mp4|webm)$/.test(vid.suggestedFilename()), vid.suggestedFilename());
      console.log(`share video ok: ${vid.suggestedFilename()} ${size} bytes`);
    }
    await c11.locator(".sharepop .x").click();
    assert.strictEqual(await c11.locator(".sharepop").count(), 0, "popup closes");
    await sctx.close();
  }

  // 14. Zoom and pan. Each case gets a fresh page.
  const URL = BASE + "/scripts/preview/index.html?s=novice";
  const open = async (opts = {}, query = "") => {
    const p = await browser.newPage(Object.assign({ viewport: { width: 1008, height: 1100 } }, opts));
    p.setDefaultTimeout(8000);
    p.on("pageerror", (e) => { console.error("PAGE ERROR", e.message); process.exitCode = 1; });
    await p.goto(URL + query);
    await p.waitForFunction(() => window.ready);
    return p;
  };
  const viewBox = (p) => p.evaluate(() => document.querySelector("netorbit-card").shadowRoot.querySelector("svg.map").getAttribute("viewBox"));
  const viewW = async (p) => Number((await viewBox(p)).split(" ")[2]);
  const labelOf = (p, key) => p.evaluate((k) => {
    const el = document.querySelector("netorbit-card").shadowRoot.querySelector(`.node[data-key="${CSS.escape(k)}"] text`);
    return el ? el.textContent : null;
  }, key);
  // Rename a device in the fake states and push a new hass object, the way Home Assistant sends an update.
  const relabel = (p, name, label) => p.evaluate(([n, l]) => {
    Object.values(window.NETORBIT_SCENARIOS.novice).find((s) => s.attributes.label === n).attributes.label = l;
    window.pushHass();
  }, [name, label]);
  const keyOfIn = (p, label) => p.evaluate((l) => Object.values(window.NETORBIT_SCENARIOS.novice).find((s) => s.attributes.label === l).attributes.node_key, label);
  const centerIn = async (p, sel) => {
    const b = await p.locator("netorbit-card").locator(sel).first().boundingBox();
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  };
  const mapBox = (p) => p.locator("netorbit-card").locator("svg.map").boundingBox();
  // A spot on the map background: not a device, hub or button.
  const backgroundPoint = (p) => p.evaluate(() => {
    const root = document.querySelector("netorbit-card").shadowRoot, r = root.querySelector("svg.map").getBoundingClientRect();
    for (let y = r.top + 12; y < r.bottom - 12; y += 17) for (let x = r.left + 12; x < r.right - 12; x += 17) {
      const el = root.elementFromPoint(x, y);
      if (el && el.closest && el.closest("svg.map") && !el.closest(".node, .zoomctl")) return { x, y };
    }
    return null;
  });
  const settle = (p) => p.waitForTimeout(60);
  // A wheel event on the map, at a screen position (the middle of the map by default). Returns whether the card took it.
  const wheelAt = (p, init, at) => p.evaluate(([i, pos]) => {
    const svg = document.querySelector("netorbit-card").shadowRoot.querySelector("svg.map");
    const r = svg.getBoundingClientRect();
    const ev = new WheelEvent("wheel", Object.assign({ bubbles: true, cancelable: true, composed: true,
      clientX: pos ? pos.x : r.left + r.width / 2, clientY: pos ? pos.y : r.top + r.height / 2 }, i));
    svg.dispatchEvent(ev);
    return ev.defaultPrevented;
  }, [init, at || null]);

  // 14a. The + button zooms in, the whole-map button zooms back out.
  {
    const p = await open();
    const c = p.locator("netorbit-card");
    const whole = await viewW(p);
    await c.locator(".zin").click();
    const zoomed = await viewW(p);
    assert.ok(zoomed < whole - 1, `the + button zooms in (${whole} -> ${zoomed})`);
    await c.locator(".zfit").click();
    assert.strictEqual(await viewW(p), whole, "the whole-map button zooms back out");
    console.log("zoom buttons ok");
    await p.close();
  }

  // 14b. The zoom survives a Home Assistant update that redraws the map.
  {
    const p = await open();
    const c = p.locator("netorbit-card");
    await c.locator(".zin").click(); await c.locator(".zin").click();
    const vb = await viewBox(p);
    const lamp = await keyOfIn(p, "Lamp");
    await relabel(p, "Lamp", "Zed");
    await p.waitForFunction(([k]) => document.querySelector("netorbit-card").shadowRoot.querySelector(`.node[data-key="${CSS.escape(k)}"] text`).textContent.startsWith("Zed"), [lamp]);
    assert.strictEqual(await viewBox(p), vb, "the zoom survives a redraw from a hass update");
    console.log("zoom survives hass update ok");
    await p.close();
  }

  // 14c. The zoom survives toggling Edit layout.
  {
    const p = await open();
    const c = p.locator("netorbit-card");
    await c.locator(".zin").click(); await c.locator(".zin").click();
    const vb = await viewBox(p);
    await c.locator(".editbtn").click();
    assert.ok(await c.locator(".banner").isVisible(), "edit mode is on");
    assert.strictEqual(await viewBox(p), vb, "the zoom survives turning Edit layout on");
    await c.locator(".editbtn").click();
    assert.strictEqual(await viewBox(p), vb, "the zoom survives turning Edit layout off");
    console.log("zoom survives edit toggle ok");
    await p.close();
  }

  // 14d. Dragging a device onto a hub while zoomed in sends assign_device for that hub.
  {
    const p = await open();
    const c = p.locator("netorbit-card");
    await c.locator(".editbtn").click();
    const plugKey = await keyOfIn(p, "Smart Plug");
    const plugAt = await centerIn(p, `.node[data-key="${plugKey}"] circle.disc`), hubAt = await centerIn(p, '.node[data-key="hub:m1"] circle.disc');
    // Zoom in on the spot between the two.
    const mid = { x: (plugAt.x + hubAt.x) / 2, y: (plugAt.y + hubAt.y) / 2 };
    const whole = await viewW(p);
    await wheelAt(p, { deltaY: -40, ctrlKey: true }, mid);
    await wheelAt(p, { deltaY: -40, ctrlKey: true }, mid);
    assert.ok((await viewW(p)) < whole * 0.5, "zoomed in");
    const box = await mapBox(p);
    const inside = (pt) => pt.x > box.x + 8 && pt.x < box.x + box.width - 8 && pt.y > box.y + 8 && pt.y < box.y + box.height - 8;
    const dev = { k: plugKey, pt: await centerIn(p, `.node[data-key="${plugKey}"] circle.disc`) };
    assert.ok(inside(dev.pt), "the device is on screen while zoomed in");
    const hub = await centerIn(p, '.node[data-key="hub:m1"] circle.disc');
    assert.ok(inside(hub), "the hub is on screen while zoomed in");
    const before = (await p.evaluate(() => window.calls)).length;
    await p.mouse.move(dev.pt.x, dev.pt.y); await p.mouse.down();
    await p.mouse.move((dev.pt.x + hub.x) / 2, (dev.pt.y + hub.y) / 2, { steps: 6 });
    await p.mouse.move(hub.x, hub.y, { steps: 6 });
    assert.ok(await c.locator('.node.hub.hot[data-key="hub:m1"]').count(), "the hub highlights while dragging when zoomed");
    await p.mouse.up();
    const calls = await p.evaluate(() => window.calls);
    assert.strictEqual(calls.length, before + 1, "one call was sent");
    assert.deepStrictEqual(calls.at(-1).slice(0, 2), ["netorbit", "assign_device"]);
    assert.strictEqual(calls.at(-1)[2].hub, "m1", "the device went to the hub it was dropped on");
    console.log("zoomed drag ok:", JSON.stringify(calls.at(-1)[2]));
    await p.close();
  }

  // 14e. A mouse button released just outside the map must not leave it panning, or hold back redraws.
  {
    const p = await open();
    const c = p.locator("netorbit-card");
    await c.locator(".zin").click(); await c.locator(".zin").click();
    const vb = await viewBox(p);
    const box = await mapBox(p);
    const y = box.y + box.height / 2;
    await p.mouse.move(box.x + box.width - 2, y);
    await p.mouse.down();
    await p.mouse.move(box.x + box.width + 3, y);
    await p.mouse.up();
    // Button up now. Moving the mouse across the map must not pan it.
    await p.mouse.move(box.x + box.width - 40, y, { steps: 4 });
    await p.mouse.move(box.x + box.width / 2, y + 60, { steps: 8 });
    assert.strictEqual(await viewBox(p), vb, "a mouse moving with no button down does not pan");
    const lamp = await keyOfIn(p, "Lamp");
    await relabel(p, "Lamp", "Yak");
    await p.waitForFunction(([k]) => document.querySelector("netorbit-card").shadowRoot.querySelector(`.node[data-key="${CSS.escape(k)}"] text`).textContent.startsWith("Yak"), [lamp]);
    console.log("stuck mouse pan ok");
    await p.close();
  }

  // 14f. An update that arrives during a plain tap or press is drawn when the finger lifts.
  {
    const p = await open();
    const lamp = await keyOfIn(p, "Lamp");
    const bg = await backgroundPoint(p);
    assert.ok(bg, "found a spot on the map background");
    await p.mouse.move(bg.x, bg.y);
    await p.mouse.down();
    await relabel(p, "Lamp", "Xen");
    await settle(p);
    assert.ok(!(await labelOf(p, lamp)).startsWith("Xen"), "nothing is redrawn under the finger");
    await p.mouse.up();
    await p.waitForFunction(([k]) => document.querySelector("netorbit-card").shadowRoot.querySelector(`.node[data-key="${CSS.escape(k)}"] text`).textContent.startsWith("Xen"), [lamp]);
    console.log("update held during a tap is drawn on release ok");
    await p.close();
  }

  // 14g. Ctrl or Cmd with the wheel zooms, a plain wheel does not. Firefox reports lines instead of pixels.
  {
    const whole = await (async () => { const p = await open(); const w = await viewW(p); await p.close(); return w; })();
    const p = await open();
    assert.strictEqual(await wheelAt(p, { deltaY: -100 }), false, "a plain wheel is left to the page");
    assert.strictEqual(await viewW(p), whole, "a plain wheel does not zoom");
    assert.strictEqual(await wheelAt(p, { deltaY: -10, ctrlKey: true }), true, "Ctrl+wheel is taken by the map");
    const px = await viewW(p);
    assert.ok(px < whole - 1, "Ctrl+wheel zooms in");
    await p.close();
    const q = await open();
    assert.strictEqual(await wheelAt(q, { deltaY: -1, deltaMode: 1, metaKey: true }), true, "Cmd+wheel is taken by the map");
    const lines = await viewW(q);
    await q.close();
    // One line of scroll is a notch of about 16 px: it zooms like -16 pixels, and far more than a single pixel would.
    const r = await open();
    await wheelAt(r, { deltaY: -16, ctrlKey: true });
    const sixteen = await viewW(r);
    await r.close();
    assert.ok(Math.abs(lines - sixteen) < 2, `one wheel line zooms like 16 pixels (${lines} vs ${sixteen})`);
    assert.ok(lines < whole * 0.95, "one wheel line is a visible zoom step");
    console.log("wheel zoom ok:", whole, "->", px, "(10 px),", lines, "(1 line),", sixteen, "(16 px)");
  }

  // 14h. Double-tap on the background zooms back out to the whole map when zoomed in.
  {
    const p = await open();
    const c = p.locator("netorbit-card");
    const whole = await viewBox(p);
    await c.locator(".zin").click(); await c.locator(".zin").click();
    assert.notStrictEqual(await viewBox(p), whole, "zoomed in");
    const bg = await backgroundPoint(p);
    assert.ok(bg, "found a spot on the map background");
    await p.mouse.dblclick(bg.x, bg.y);
    assert.strictEqual(await viewBox(p), whole, "a double-tap returns to the whole map");
    await p.mouse.dblclick(bg.x, bg.y);
    assert.ok((await viewW(p)) < Number(whole.split(" ")[2]) - 1, "and a double-tap on the whole map zooms in");
    console.log("double-tap zoom ok");
    await p.close();
  }

  // 14i. A phone with a real touch screen: a one-finger swipe scrolls the page, a tap on a device opens its details,
  //      a pinch zooms. The events go through Chrome's DevTools protocol so the browser applies touch-action itself.
  if (IS_WEBKIT) {
    const p = await open({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    const tvKey = await keyOfIn(p, "Bedroom TV");
    await p.locator("netorbit-card").locator(`.node[data-key="${tvKey}"] circle.disc`).tap();
    const details = p.locator("netorbit-card").locator(".pop .info");
    await details.waitFor();
    assert.ok(await details.isVisible(), "a tap on a device opens its details on a phone");
    await p.locator("netorbit-card").locator(".pop .x").tap();
    console.log("phone tap ok (WebKit; swipe and pinch need Chrome's DevTools protocol and run in Chromium only)");
    await p.close();
  } else {
    const p = await open({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    await p.evaluate(() => { document.body.style.paddingBottom = "2400px"; });
    const cdp = await p.context().newCDPSession(p);
    const touch = (type, pts) => cdp.send("Input.dispatchTouchEvent", { type, touchPoints: pts.map((q, i) => ({ x: q.x, y: q.y, id: i })) });
    const wait = (ms) => p.waitForTimeout(ms);
    const whole = await viewBox(p);
    const box = await mapBox(p);
    const bg = await backgroundPoint(p);
    assert.ok(bg, "found a spot on the map background");
    // Touches that reach the page are counted at the document, where dashboards that swipe between views listen.
    await p.evaluate(() => { window.pageTouches = 0; ["touchstart", "touchmove"].forEach((t) => document.addEventListener(t, () => window.pageTouches++)); });
    const pageTouches = () => p.evaluate(() => window.pageTouches);
    const resetPageTouches = () => p.evaluate(() => { window.pageTouches = 0; });

    // A tap on a device (the page has not scrolled yet).
    const tvKey = await keyOfIn(p, "Bedroom TV");
    const tv = await centerIn(p, `.node[data-key="${tvKey}"] circle.disc`);
    await touch("touchStart", [tv]); await wait(40); await touch("touchEnd", []); await wait(250);
    const details = p.locator("netorbit-card").locator(".pop .info");
    await details.waitFor();
    assert.ok(await details.isVisible(), "a tap on a device opens its details on a phone");
    assert.strictEqual(await viewBox(p), whole, "a tap does not move the map");
    await p.locator("netorbit-card").locator(".pop .x").tap(); // back to the plain map for the swipe and pinch below

    // One finger swiping up over the whole map scrolls the page.
    assert.strictEqual(await p.evaluate(() => window.scrollY), 0);
    let y = bg.y;
    await touch("touchStart", [{ x: bg.x, y }]);
    for (let i = 0; i < 12; i++) { y -= 14; await touch("touchMove", [{ x: bg.x, y }]); await wait(16); }
    await touch("touchEnd", []);
    // Wait for the fling to come to rest: scrollY is the same on three animation frames in a row.
    await p.waitForFunction(() => {
      const w = window, y = w.scrollY;
      if (w.__lastY === y) w.__still = (w.__still || 0) + 1; else w.__still = 0;
      w.__lastY = y;
      return w.__still >= 3;
    }, null, { polling: "raf" });
    assert.ok((await p.evaluate(() => window.scrollY)) > 60, "a one-finger swipe over the whole map scrolls the page");
    assert.strictEqual(await viewBox(p), whole, "and leaves the map alone");
    assert.ok((await pageTouches()) > 0, "at the whole map, touches on the map reach the page");
    await p.evaluate(() => window.scrollTo(0, 0));
    await wait(100);

    // At the whole map a sideways swipe over the map reaches the page too (a dashboard may change views on it) and
    // moves nothing here: there is nothing to pan.
    await resetPageTouches();
    await touch("touchStart", [bg]);
    for (let i = 1; i <= 8; i++) { await touch("touchMove", [{ x: bg.x - i * 12, y: bg.y }]); await wait(16); }
    await touch("touchEnd", []);
    await wait(200);
    assert.ok((await pageTouches()) > 0, "at the whole map, a sideways swipe over the map reaches the page");
    assert.strictEqual(await viewBox(p), whole, "and leaves the map alone");

    // A pinch over the map zooms it.
    const b2 = await mapBox(p);
    const cx = b2.x + b2.width / 2, cy = b2.y + b2.height / 2;
    await touch("touchStart", [{ x: cx - 20, y: cy }, { x: cx + 20, y: cy }]);
    for (let i = 1; i <= 10; i++) { await touch("touchMove", [{ x: cx - 20 - i * 9, y: cy }, { x: cx + 20 + i * 9, y: cy }]); await wait(16); }
    await touch("touchEnd", []);
    await wait(200);
    assert.ok((await viewW(p)) < Number(whole.split(" ")[2]) * 0.7, "a pinch zooms the map");
    assert.ok(Math.abs(await p.evaluate(() => window.scrollY)) < 5, "and does not scroll the page");

    // Zoomed in, one finger pans the map instead of the page. A drag of 120 px should move the view by about
    // 120 px worth of map units, whether it starts on the background or on a device circle.
    const vbOf = async () => (await viewBox(p)).split(" ").map(Number);
    const pan = async (from, label) => {
      const before = await vbOf();
      const bx = await mapBox(p);
      const unitsPerPx = Math.max(before[2] / bx.width, before[3] / bx.height);
      let x = from.x;
      await touch("touchStart", [{ x, y: from.y }]);
      for (let i = 0; i < 10; i++) { x -= 12; await touch("touchMove", [{ x, y: from.y }]); await wait(16); }
      await touch("touchEnd", []);
      await wait(200);
      const after = await vbOf();
      const want = 120 * unitsPerPx, got = after[0] - before[0];
      assert.ok(got > want * 0.5, `${label}: one finger pans the map by about the finger distance (moved ${got.toFixed(1)} of ${want.toFixed(1)} units)`);
      assert.ok(Math.abs(after[2] - before[2]) < 0.01, `${label}: and does not change the zoom`);
      assert.ok(Math.abs(await p.evaluate(() => window.scrollY)) < 5, `${label}: and the page stays put`);
    };
    // A device circle well inside the visible map, with room to drag 120 px to the left of it.
    const onDevice = await p.evaluate(() => {
      const root = document.querySelector("netorbit-card").shadowRoot, r = root.querySelector("svg.map").getBoundingClientRect();
      for (const c of root.querySelectorAll(".node circle.disc")) {
        const b = c.getBoundingClientRect(), x = b.x + b.width / 2, y = b.y + b.height / 2;
        if (x > r.left + 140 && x < r.right - 20 && y > r.top + 20 && y < r.bottom - 20 && y < innerHeight - 20) {
          const hit = root.elementFromPoint(x, y);
          if (hit && hit.closest && hit.closest(".node")) return { x, y };
        }
      }
      return null;
    });
    assert.ok(onDevice, "found a device circle inside the zoomed map");
    await resetPageTouches();
    await pan(onDevice, "from a device");
    const bg2 = await backgroundPoint(p);
    assert.ok(bg2, "found a background spot in the zoomed map");
    await pan({ x: Math.max(bg2.x, (await mapBox(p)).x + 140), y: bg2.y }, "from the background");
    // Zoomed in, those touches stopped at the map: a dashboard that swipes between views never saw them. A swipe over
    // the card's header still reaches the page.
    assert.strictEqual(await pageTouches(), 0, "zoomed in, touches on the map stop at the map");
    const head = await centerIn(p, ".head");
    await touch("touchStart", [head]);
    for (let i = 1; i <= 8; i++) { await touch("touchMove", [{ x: head.x - i * 12, y: head.y }]); await wait(16); }
    await touch("touchEnd", []);
    assert.ok((await pageTouches()) > 0, "a swipe over the card's header reaches the page");
    console.log("phone touch ok: swipe scrolls, tap opens details, pinch zooms, drag pans, map touches stop at the map only while zoomed");
    await p.close();
  }

  // 15. Card height: a number is pixels, a CSS length is used as given. (A CSS length needs the noHeight helper.)
  {
    const src = fs.readFileSync("custom_components/netorbit/frontend/netorbit-card.js", "utf8");
    const maxH = async (cfg) => {
      const p = await open({ viewport: { width: 1008, height: 1000 } }, "&cfg=" + encodeURIComponent(JSON.stringify(cfg)));
      const v = await p.evaluate(() => getComputedStyle(document.querySelector("netorbit-card").shadowRoot.querySelector("svg.map")).maxHeight);
      await p.close();
      return v;
    };
    assert.strictEqual(await maxH({ height: 600 }), "600px", "height: 600 is 600 px");
    if (src.includes("noHeight")) {
      assert.strictEqual(await maxH({ height: "80vh" }), "800px", "height: 80vh is 80% of the window");
      assert.strictEqual(await maxH({ height: "40rem" }), "640px", "height: 40rem is 40 rem");
      console.log("height ok: 600, 80vh, 40rem");
    } else {
      console.log("height ok: 600 (CSS lengths skipped, noHeight is not in the card yet)");
    }
  }

  // 16. Move a hub under another hub with "Connected to" (move a switch from the router to an access point).
  {
    const hp = await browser.newPage({ viewport: { width: 1008, height: 1100 } });
    hp.on("pageerror", (e) => { console.error("PAGE ERROR", e.message); process.exitCode = 1; });
    await hp.goto(BASE + "/scripts/preview/index.html?s=full");
    await hp.waitForFunction(() => window.ready);
    const c7 = hp.locator("netorbit-card");
    await c7.locator(".editbtn").click();
    const opts = async () => c7.locator(".pop select.parent option").evaluateAll((o) => o.map((x) => x.value).sort());
    // Click a hub and wait for its popup. Right after a redraw (closing a popup redraws the map) the hub is still
    // moving for a few frames, and a click that lands on it mid-move goes to the map behind it and opens nothing.
    // So the click waits until the hub has held still for 5 frames, is made once, and the popup must follow it.
    // There is no retry: a tap that opens nothing on a settled map is a failure.
    const openHub = async (key) => {
      const sel = `.node.hub[data-key="hub:${key}"] circle.disc`;
      await hp.evaluate((sel) => new Promise((resolve, reject) => {
        const root = document.querySelector("netorbit-card").shadowRoot;
        const t0 = performance.now();
        const pos = () => { const d = root.querySelector(sel); if (!d) return null; const b = d.getBoundingClientRect(); return [b.x, b.y, b.width].map((v) => v.toFixed(2)).join(); };
        let last = null, same = 0;
        const tick = () => {
          const now = pos();
          same = now !== null && now === last ? same + 1 : 0;
          last = now;
          if (same >= 5) resolve();
          else if (performance.now() - t0 > 10000) reject(new Error("the hub never held still: " + sel));
          else requestAnimationFrame(tick);
        };
        tick();
      }), sel);
      await c7.locator(sel).click({ force: true });
      await c7.locator(".pop input.name").waitFor({ timeout: 10000 });
    };
    // The router has no parent to pick.
    await openHub("gateway");
    assert.strictEqual(await c7.locator(".pop select.parent").count(), 0, "the router has no Connected to picker");
    await c7.locator(".pop .x").click();
    // A hub's own descendants are not offered, and neither is the hub itself.
    await openHub("core");
    assert.deepStrictEqual(await opts(), ["gateway"], "a switch is offered only hubs that are not below it");
    await c7.locator(".pop .x").click();
    // Office Switch hangs off Core Switch. Move it under Hallway AP.
    await openHub("office");
    await c7.locator(".pop label", { hasText: "Connected to" }).waitFor({ timeout: 10000 });
    assert.strictEqual(await c7.locator(".pop label", { hasText: "Connected to" }).count(), 1, "picker is labelled Connected to");
    await c7.locator(".pop select.parent").waitFor({ timeout: 10000 });
    assert.strictEqual(await c7.locator(".pop select.parent").inputValue(), "core", "current parent is selected");
    assert.deepStrictEqual(await opts(), ["core", "down", "garage", "gateway", "up"], "every other real hub is offered, no group or New devices hub");
    await c7.locator(".pop select.parent").selectOption("up");
    await c7.locator(".pop .save").click();
    const hc = await hp.evaluate(() => window.calls);
    assert.deepStrictEqual(hc.at(-1).slice(1), ["update_hub", { hub: "office", parent: "up", config_entry_id: "preview" }]);
    // Saving without touching Connected to sends no parent.
    await openHub("office");
    await c7.locator(".pop input.name").fill("Desk Switch");
    await c7.locator(".pop .save").click();
    const hc2 = await hp.evaluate(() => window.calls);
    assert.deepStrictEqual(hc2.at(-1).slice(1), ["update_hub", { hub: "office", name: "Desk Switch", config_entry_id: "preview" }]);
    // Two hubs with the same name are told apart by their address.
    await hp.evaluate(() => { const st = Object.values(window.card._hass.states).find((x) => x.attributes.node_key === "hub:down"); st.attributes.label = "Hallway AP"; window.pushHass(); });
    await openHub("office");
    const names = await c7.locator(".pop select.parent option").evaluateAll((o) => o.map((x) => x.textContent));
    assert.strictEqual(names.filter((t) => t.startsWith("Hallway AP (192.0.2.")).length, 2, "same-name hubs show their address: " + names.join("|"));
    assert.ok(names.includes("Core Switch"), "a unique name stays plain");
    await c7.locator(".pop .x").click();
    // A hub whose parent no longer exists shows the router, and saving without a change sends no parent.
    await hp.evaluate(() => { const st = Object.values(window.card._hass.states).find((x) => x.attributes.node_key === "hub:office"); st.attributes.link = "hub:ghost"; window.pushHass(); });
    await openHub("office");
    assert.strictEqual(await c7.locator(".pop select.parent").inputValue(), "gateway", "a missing parent falls back to the router");
    await c7.locator(".pop input.name").fill("Desk Switch 2");
    await c7.locator(".pop .save").click();
    const hc3 = await hp.evaluate(() => window.calls);
    assert.deepStrictEqual(hc3.at(-1).slice(1), ["update_hub", { hub: "office", name: "Desk Switch 2", config_entry_id: "preview" }]);
    // Bad data with a loop (Core under Office, Office under Core) still opens the picker, and a hub in the loop is not offered itself.
    await hp.evaluate(() => { const find = (k) => Object.values(window.card._hass.states).find((x) => x.attributes.node_key === k); find("hub:office").attributes.link = "hub:core"; find("hub:core").attributes.link = "hub:office"; window.pushHass(); });
    await openHub("up");
    assert.ok((await opts()).includes("gateway"), "the picker opens on looped data");
    await c7.locator(".pop .x").click();
    await openHub("core");
    assert.ok(!(await opts()).includes("core") && !(await opts()).includes("office"), "a looped hub is not offered itself or its loop partner");
    await c7.locator(".pop .x").click();
    console.log("hub parent picker ok:", JSON.stringify(hc.at(-1)[2]));
    await hp.close();
  }

  // 17. Rename a device from its menu, and tell similar devices apart.
  {
    const rp = await browser.newPage({ viewport: { width: 1008, height: 1100 } });
    rp.on("pageerror", (e) => { console.error("PAGE ERROR", e.message); process.exitCode = 1; });
    await rp.goto(BASE + "/scripts/preview/index.html?s=novice&live=1");
    await rp.waitForFunction(() => window.ready);
    const c8 = rp.locator("netorbit-card");
    await c8.locator(".editbtn").click();
    const tvk = await rp.evaluate(() => Object.values(window.NETORBIT_SCENARIOS.novice).find((s) => s.attributes.label === "Bedroom TV").attributes.node_key);
    const tvEntity = await rp.evaluate((k) => Object.values(window.NETORBIT_SCENARIOS.novice).find((s) => s.attributes.node_key === k).entity_id, tvk);
    const tvMac = await rp.evaluate((k) => Object.values(window.NETORBIT_SCENARIOS.novice).find((s) => s.attributes.node_key === k).attributes.mac, tvk);
    const open = async () => c8.locator(`.node[data-key="${tvk}"] circle.disc`).click({ force: true });
    const calls = () => rp.evaluate(() => window.calls);
    const ws = () => rp.evaluate(() => window.wsCalls);
    const shows = (text) => rp.waitForFunction(([k, t]) => document.querySelector("netorbit-card").shadowRoot.querySelector(`.node[data-key="${k}"]`).textContent.includes(t), [tvk, text]);

    // The menu shows IP, MAC, maker and last seen even though show_ip is off.
    await open();
    assert.strictEqual(await c8.locator(".pop input.name").inputValue(), "Bedroom TV", "the Name field starts with the current name");
    const facts = await c8.locator(".pop .facts").innerText();
    assert.ok(/IP\s*192\.0\.2\./.test(facts), "IP shown in the menu with show_ip off: " + facts);
    assert.ok(facts.includes(tvMac), "MAC shown in the menu");
    assert.ok(/Last seen/.test(facts), "last seen shown");
    assert.strictEqual(await c8.locator(".pop .note").count(), 0, "no private MAC note for a normal MAC");

    // Saving sends NetOrbit's name (by MAC). The card does not write a Home Assistant entity name.
    await c8.locator(".pop input.name").fill("  Bike  ");
    await c8.locator(".pop .rename").click();
    assert.deepStrictEqual((await calls()).at(-1), ["netorbit", "track_device", { name: "Bike", mac: tvMac, config_entry_id: "preview" }]);
    await shows("Bike");
    assert.strictEqual((await ws()).length, 0, "no entity registry write when no entity name was set in Home Assistant");
    console.log("rename ok");

    // Enter saves too. An unchanged name sends nothing.
    await open();
    assert.strictEqual(await c8.locator(".pop input.name").inputValue(), "Bike");
    const before = (await calls()).length;
    await c8.locator(".pop .rename").click();
    assert.strictEqual((await calls()).length, before, "an unchanged name sends nothing");
    await open();
    await c8.locator(".pop input.name").fill("Tread");
    await c8.locator(".pop input.name").press("Enter");
    assert.strictEqual((await calls()).at(-1)[2].name, "Tread", "Enter saves the name");
    await shows("Tread");

    // A name changed elsewhere (settings, a service, an AI assistant) shows on the map, since the card set no entity name.
    await rp.evaluate((k) => { const st = Object.values(window.card._hass.states).find((x) => x.attributes.node_key === k); st.attributes.label = "From Assistant"; window.pushHass(); }, tvk);
    await shows("From Assistant");

    // An empty name goes back to the automatic name.
    await open();
    await c8.locator(".pop input.name").fill("   ");
    await c8.locator(".pop .rename").click();
    assert.deepStrictEqual((await calls()).at(-1), ["netorbit", "track_device", { name: "", mac: tvMac, config_entry_id: "preview" }]);
    await shows("Bedroom TV");
    assert.strictEqual((await ws()).length, 0, "clearing writes no entity name either");
    console.log("clear ok");

    // HTML in a name is text, in the menu and on the map.
    const evil = '<img src=x onerror="window.pwned=1"><b>"\'';
    await open();
    await c8.locator(".pop input.name").fill(evil);
    await c8.locator(".pop .rename").click();
    await shows("<img");
    await open();
    assert.strictEqual(await c8.locator(".pop input.name").inputValue(), evil.slice(0, 64), "the name survives the menu unchanged");
    assert.strictEqual(await c8.locator(".pop img").count(), 0, "no HTML from the name in the menu");
    assert.ok(!(await rp.evaluate(() => window.pwned)), "no script from the name ran");
    await c8.locator(".pop .x").click();

    // A very long name is cut at 64 characters, and the menu stays on the map.
    await open();
    await c8.locator(".pop input.name").evaluate((el) => { el.maxLength = 1000; el.value = "W".repeat(300); });
    await c8.locator(".pop .rename").click();
    assert.strictEqual((await calls()).at(-1)[2].name.length, 64, "a long name is cut to 64");

    // Saving a menu whose automatic name is longer than the field allows renames nothing.
    await rp.evaluate((k) => { Object.keys(window.card._hass.entities).forEach((e) => delete window.card._hass.entities[e]); const st = Object.values(window.card._hass.states).find((x) => x.attributes.node_key === k); st.attributes.label = "n".repeat(100); window.pushHass(); }, tvk);
    await open();
    const callsBefore = (await calls()).length;
    await c8.locator(".pop .rename").click();
    assert.strictEqual((await calls()).length, callsBefore, "an untouched long automatic name is not renamed");
    await open();
    await c8.locator(".pop input.name").press("Enter");
    assert.strictEqual((await calls()).length, callsBefore, "Enter on an untouched long name renames nothing");

    // Someone set an entity name in Home Assistant's settings: it wins on the map, so a rename from the card changes it too.
    await rp.evaluate(([k, e]) => { const st = Object.values(window.card._hass.states).find((x) => x.attributes.node_key === k); st.attributes.label = "Bedroom TV"; window.card._hass.entities[e] = { name: "Den TV" }; window.pushHass(); }, [tvk, tvEntity]);
    await shows("Den TV");
    await open();
    assert.strictEqual(await c8.locator(".pop input.name").inputValue(), "Den TV");
    await c8.locator(".pop input.name").fill("Study TV");
    await c8.locator(".pop .rename").click();
    await rp.waitForFunction(() => window.wsCalls.length === 1);
    assert.deepStrictEqual((await ws()).at(-1), { type: "config/entity_registry/update", entity_id: tvEntity, name: "Study TV" });
    assert.strictEqual((await calls()).at(-1)[2].name, "Study TV", "NetOrbit's own name is saved as well");
    await shows("Study TV");
    await open();
    await c8.locator(".pop input.name").fill("");
    await c8.locator(".pop .rename").click();
    await rp.waitForFunction(() => window.wsCalls.length === 2);
    assert.strictEqual((await ws()).at(-1).name, null, "clearing also clears the name set in Home Assistant");
    await shows("Bedroom TV");

    // A private (random) MAC gets a one-line note.
    await rp.evaluate((k) => { const st = Object.values(window.card._hass.states).find((x) => x.attributes.node_key === k); st.attributes.mac = "02:00:5E:00:53:99"; /* example-ok: a private MAC */ window.pushHass(); }, tvk);
    await open();
    assert.ok((await c8.locator(".pop .note").innerText()).includes("private MAC"), "private MAC note shown");
    await c8.locator(".pop .x").click();

    // A failed save tells you, and a name Home Assistant refused is reported too.
    const notes = [];
    await rp.evaluate(() => { window.notes = []; window.card.addEventListener("hass-notification", (e) => window.notes.push(e.detail.message)); });
    await rp.evaluate(([k, e]) => { window.card._hass.entities[e] = { name: "Den TV" }; window.pushHass(); window.wsFail = "not allowed"; }, [tvk, tvEntity]);
    await open();
    await c8.locator(".pop input.name").fill("Cam");
    await c8.locator(".pop .rename").click();
    await rp.waitForFunction(() => window.notes.length === 1);
    assert.ok((await rp.evaluate(() => window.notes[0])).includes("not allowed"), "a failed entity rename is reported");
    await rp.evaluate(() => { window.wsFail = null; window.callFail = "boom"; });
    const wsBefore = (await ws()).length;
    await open();
    await c8.locator(".pop input.name").fill("Cam 2");
    await c8.locator(".pop .rename").click();
    await rp.waitForFunction(() => window.notes.length === 2);
    assert.strictEqual((await ws()).length, wsBefore, "no entity rename when NetOrbit's own save failed");
    console.log("rename errors ok");

    // The details popup outside Edit layout renames a device the same way, after saving its fields.
    await rp.evaluate(() => { window.callFail = null; });
    await c8.locator(".editbtn").click();
    const wsNow = (await ws()).length;
    await open();
    await c8.locator(".pop .ed").click();
    await c8.locator(".pop input.name").fill("Lounge TV");
    await c8.locator(".pop .save").click();
    await rp.waitForFunction((n) => window.wsCalls.length === n + 1, wsNow);
    const sent = (await calls()).slice(-2);
    assert.deepStrictEqual(sent.map((c) => c[1]), ["update_device", "track_device"], "details Edit saves the fields, then renames");
    assert.strictEqual(sent[1][2].name, "Lounge TV", "NetOrbit's own name is saved");
    assert.strictEqual((await ws()).at(-1).name, "Lounge TV", "the name set in Home Assistant follows");
    await shows("Lounge TV");
    const untouched = (await calls()).length;
    await open();
    await c8.locator(".pop .ed").click();
    await c8.locator(".pop .save").click();
    assert.strictEqual((await calls()).length, untouched + 1, "an untouched name sends only the fields");
    assert.strictEqual((await calls()).at(-1)[1], "update_device");
    await c8.locator(".editbtn").click();
    console.log("details rename ok");

    // On a phone the menu, with its Name field, fits on the map.
    const rph = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
    await rph.goto(BASE + "/scripts/preview/index.html?s=novice");
    await rph.waitForFunction(() => window.ready);
    const c9 = rph.locator("netorbit-card");
    await c9.locator(".editbtn").click();
    await c9.locator(`.node[data-key="${tvk}"] circle.disc`).tap();
    const fits = await rph.evaluate(() => {
      const root = document.querySelector("netorbit-card").shadowRoot;
      const p = root.querySelector(".pop").getBoundingClientRect(), w = root.querySelector(".wrap").getBoundingClientRect();
      return { top: p.top - w.top, bottom: w.bottom - p.bottom, left: p.left - w.left, right: w.right - p.right };
    });
    assert.ok(fits.top >= 0 && fits.left >= 0 && fits.right >= 0, "the menu is inside the map on a phone: " + JSON.stringify(fits));
    assert.ok(await c9.locator(".pop input.name").isVisible() && await c9.locator(".pop .rename").isVisible(), "Name field and Save name show on a phone");
    console.log("phone menu ok");
    await rph.close();
    await rp.close();
  }

  // 18. Balloon layout and branches: the Radial | Balloon switch (remembered), long-press a hub for its branch, the
  //     grey hub above it and the row under the header lead back up, and Share follows the layout on show.
  {
    const bp = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
    bp.on("pageerror", (e) => { console.error("PAGE ERROR", e.message); process.exitCode = 1; });
    await bp.goto(BASE + "/scripts/preview/index.html?s=chain");
    await bp.waitForFunction(() => window.ready);
    const cb = bp.locator("netorbit-card");
    const key = (l) => bp.evaluate((x) => Object.values(window.NETORBIT_SCENARIOS.chain).find((s) => s.attributes.label === x).attributes.node_key, l);
    const crumbs = () => cb.locator(".crumbs").count().then((n) => (n ? cb.locator(".crumbs").innerText().then((t) => t.replace(/\s+/g, " ").trim()) : ""));
    const press = async (label) => {
      const b = await cb.locator(`.node[data-key="${await key(label)}"] circle.disc`).boundingBox();
      await bp.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
      await bp.mouse.down();
      await bp.waitForTimeout(750);
      await bp.mouse.up();
      await bp.waitForTimeout(300);
    };
    const viewBox = () => cb.locator("svg.map").getAttribute("viewBox").then((v) => v.split(" ").map(Number).join(" "));
    assert.ok(await cb.locator(".lay button[data-l=radial].on").count(), "radial by default");
    assert.strictEqual(await viewBox(), "-70 -40 1140 1090");
    await cb.locator(".lay button[data-l=balloon]").click();
    assert.ok(await cb.locator(".lay button[data-l=balloon].on").count(), "balloon picked");
    assert.notStrictEqual(await viewBox(), "-70 -40 1140 1090", "the balloon map has a view of its own");
    assert.strictEqual(await cb.locator(".ring").count(), 0, "no router ring on the balloon map");
    const saved = () => bp.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("netorbit-layout")).map((k) => [k, localStorage.getItem(k)]));
    const picks = await saved();
    assert.strictEqual(picks.length, 1, "one saved pick");
    assert.ok(picks[0][0] !== "netorbit-layout" && picks[0][1] === "balloon", "remembered for this card, not site-wide");
    // Reloaded, the same card remembers it.
    await bp.reload();
    await bp.waitForFunction(() => window.ready);
    assert.ok(await cb.locator(".lay button[data-l=balloon].on").count(), "balloon remembered after a reload");
    // The drag ghost waits off the map, which in the balloon layout runs into negative coordinates.
    const ghost = await cb.locator(".ghost").evaluate((g) => [Number(g.getAttribute("cx")), Number(g.getAttribute("cy"))]);
    const [vx, vy] = (await viewBox()).split(" ").map(Number);
    assert.ok(ghost[0] < vx && ghost[1] < vy, "drag ghost off the map");
    // Share follows the layout on show.
    const share = await bp.evaluate(() => document.querySelector("netorbit-card").shareSvg(true));
    assert.ok(!share.includes('class="ring"') && !share.includes('viewBox="-70 -40 1140 1090"'), "the share image is the balloon map");
    // Long-press a hub: just its branch, with the hub above it in grey.
    await press("Rack Switch");
    assert.strictEqual(await crumbs(), "Whole map Router › Rack Switch");
    assert.ok(await cb.locator(`.node.up[data-key="${await key("Router")}"]`).count(), "the router hangs off the branch in grey");
    assert.strictEqual(await cb.locator(`.node[data-key="${await key("Downstairs AP")}"]`).count(), 0, "other branches left out");
    assert.strictEqual(await bp.evaluate(() => (window.calls || []).length), 0, "a long-press opens nothing");
    await press("Shed Switch");
    assert.strictEqual(await crumbs(), "Whole map Router › Rack Switch › Shed Switch");
    // The tap straight after a long-press is a real tap: it opens the device's details (and More info there opens the
    // device), not swallowed by the press before it.
    await bp.evaluate(() => { window.moreInfo = null; document.addEventListener("hass-more-info", (e) => (window.moreInfo = e.detail.entityId)); });
    await cb.locator(`.node[data-key="${await key("Shed Pi")}"] circle.disc`).click();
    const shedInfo = cb.locator(".pop .info");
    await shedInfo.waitFor({ timeout: 3000 }).catch(() => {});
    assert.ok(await shedInfo.count(), "a tap right after a long-press opens the device's details");
    await shedInfo.click();
    assert.ok(await bp.evaluate(() => window.moreInfo), "a tap right after a long-press opens the device");
    // Long-press the grey hub to go up a level; the row under the header goes back to the whole map.
    await press("Rack Switch");
    assert.strictEqual(await crumbs(), "Whole map Router › Rack Switch");
    await cb.locator(".crumbs .cr.back").click();
    assert.strictEqual(await crumbs(), "", "whole map again");
    // The radial map has branches too.
    await cb.locator(".lay button[data-l=radial]").click();
    await press("Shed Switch");
    assert.strictEqual(await crumbs(), "Whole map Router › Rack Switch › Shed Switch");
    assert.strictEqual(await viewBox(), "-70 -40 1140 1090");
    await cb.locator(".lay button[data-l=balloon]").click();
    // Another card, set to radial with no switch, stays radial whatever was picked on the first one.
    await bp.goto(BASE + "/scripts/preview/index.html?s=chain&cfg=" + encodeURIComponent(JSON.stringify({ layout: "radial", layout_toggle: false })));
    await bp.waitForFunction(() => window.ready);
    assert.strictEqual(await cb.locator(".lay").count(), 0, "no switch");
    assert.strictEqual(await viewBox(), "-70 -40 1140 1090", "the card's own layout wins");
    // A card whose `layout` changes starts from it, not from a pick made before.
    await bp.goto(BASE + "/scripts/preview/index.html?s=chain&cfg=" + encodeURIComponent(JSON.stringify({ layout: "balloon" })));
    await bp.waitForFunction(() => window.ready);
    assert.ok(await cb.locator(".lay button[data-l=balloon].on").count(), "layout: balloon shows balloon");
    console.log("balloon layout and branches ok");
    await bp.close();
  }

  await browser.close();
  console.log("ALL INTERACTIONS PASSED");
})().catch((e) => { console.error(e); process.exit(1); });
