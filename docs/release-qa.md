# Release QA on a real Home Assistant

This is the maintainer's check of a NetOrbit or Kepler release on a real Home Assistant, after the release is
published and before it is promoted to latest. It is the one time a real instance is used. Automated tests,
CI and agent verification never touch a real instance or a real network; they run on throwaway containers.
Everything a pull request can prove is proved before merge. This covers what only a real install can show:
the upgrade path, a downgrade and back, and the layout on a real network.

It is written as a prompt for an agent driving the maintainer's own browser (Claude in Chrome), already
logged in to Home Assistant. The Home Assistant address is `<HA_URL>`; ask the maintainer if it is not known.

## Ground rules

- Stop at the first failure and report. Don't work around problems: no hand-editing files, no removing and
  reinstalling the integration, no restoring backups unless the maintainer says so.
- Never type passwords or credentials. If a login appears, stop and ask.
- Take a backup before changing anything.
- Anything you report may end up in a public repo. Replace IP addresses, MAC addresses, device names and
  hostnames with placeholders. Report counts and hashes, never the raw device list.
- Write plainly, with no em or en dashes.

## How to drive Home Assistant

Use the UI for anything a user would click (the Marketplace pages). Use the frontend's own websocket
connection, through the javascript tool, to read state and run checks:

```js
const h = document.querySelector('home-assistant').hass;
await h.callWS({type: '...'})
```

Each javascript call times out at 45 s, so keep any wait inside one call to 30 s or less, and poll in several
calls if you need longer.

Websocket calls that work on Home Assistant 2026.11:

- Backup: `backup/generate {agent_ids:['hassio.local'], name, include_homeassistant:true, include_database:true}`,
  then `backup/info` (find it by name, check `failed_agent_ids` is empty and size is above 0)
- Integration version from disk: `manifest/get {integration:'netorbit'}`
- Config entry state: `config_entries/get {domain:'netorbit'}` (want state `loaded`)
- Update entity: `h.states['update.netorbit_update'].attributes.installed_version` / `latest_version`
- Logs: `system_log/list` (filter for the integration's name; ignore the standard "custom integration ...
  not tested by Home Assistant" warning)
- Repairs: `repairs/list_issues` (the Marketplace files `restart_required_<repo id>_tags/<version>` here)
- Dashboards: `lovelace/dashboards/list`, then `lovelace/config {url_path}` to find views using the card
- Frontend resources (Kepler): `lovelace/resources`
- Restart: `h.callService('homeassistant','restart')`. Then poll until `h.connected` is true and
  `h.config.state === 'RUNNING'`. That takes about 1.5 to 2 minutes, and the state passes through
  `NOT_RUNNING`.

The old `hacs/*` websocket commands are gone on 2026.11 ("Unknown command"). Use the Marketplace UI to
install, and the update entity to read versions.

## Marketplace quirks

- Repo page: `<HA_URL>/marketplace/repository/<repo id>`. NetOrbit's repo id is 1439130402. Find Kepler's id
  by searching for it in the Marketplace.
- A new release often doesn't show until you open the top right menu and choose "Refresh information". Wait
  about 10 s.
- That same menu has "Install another version" (version picker) and "Include/Exclude pre-releases".
- After an install, check repairs for `restart_required`. On a downgrade the page may show "Update available"
  with no "Restart required" banner, but the repair is still there.
- The "Downloaded N times" line counts only the latest release's asset (NetOrbit's `netorbit.zip`, Kepler's
  `kepler-card.js`), so it resets with each version. Never download the asset outside this check: every
  download is counted.

## Step 0. Preflight on GitHub (gh api, REST only)

- The release exists, its prerelease flag is what you expect, and `netorbit.zip` (or `kepler-card.js` for
  Kepler) is attached.
- Download the asset into a fresh empty folder and confirm:
  - NetOrbit: its files are at the zip root with no nested folder, `manifest.json` has the right version,
    and the contents match `git archive <tag>` for `custom_components/netorbit` (`diff -rq` is empty)
  - Kepler: `kepler-card.js` matches a build of the tag
- `git diff --stat <previous tag> <tag>`, so you know exactly what changed.

## Step 1. Backup and baseline

- Backup named `pre-<project>-<version>-test`. Confirm it finished.
- Record: Home Assistant version, installed version, config entry state, and repairs for the repo.
- Open the dashboard with the card, hard refresh (cmd+shift+r), wait about 8 s, then record:
  - card element count and whether `customElements.get('<card tag>')` is defined
  - nodes drawn: count elements inside the card's shadowRoot. Walk shadow roots recursively to find the card.
  - any `hui-error-card` text
  - the card JS URL from `performance.getEntriesByType('resource')`. The `?v=` value shows which build the
    browser loaded.
  - NetOrbit error log lines
  - a layout signature: for every NetOrbit sensor with a `node_key` attribute, sort the strings
    `node_key|link|placement|label` and hash them. Also keep separate hashes for keys plus labels, links of
    nodes whose source is `discovered`, and links of the rest, so layout changes can be told apart from
    normal network churn.
  - the online/recent/stale counts from `sensor.netorbit_devices_online`

## Step 2. The upgrade users will do

- From the current latest, use the normal Update button (after Refresh information). Read the update dialog
  and note anything odd in the release notes shown.
- Restart, wait for RUNNING, hard refresh, and rerun every Step 1 check.
- Pass means:
  - manifest version is the new version
  - the entry is loaded
  - the update entity shows installed equal to latest
  - the card JS URL has the new version
  - the same node count as before, with no error cards and no new log errors
  - no leftover repair
  - an unchanged layout signature

## Step 3. Downgrade and back

- Use Install another version to go to the previous release, restart, and check.
- Then go back to the new release, restart, and check.
- This proves that both directions install and that stored data survives them.

## Reading the layout signature

- Device names fill in about a minute after a restart, so take the signature after the map settles. If it
  differs, recheck after 30 to 40 s.
- A drift in discovered links or labels between tests run an hour apart is usually network churn, such as
  Wi-Fi clients roaming. Prove it by comparing old and new versions in the same session. If the two versions
  match each other, the release didn't cause it.
- A change in keys, node count, or the links of manual or hub nodes is a real failure.

## Extra checks for Kepler (Lovelace card, no backend)

- Confirm `lovelace/resources` has the card's URL with the new version. The Marketplace adds this for
  dashboard cards.
- No Home Assistant restart is normally needed. Do a hard refresh, and if the old `?v=` is still served,
  clear the site cache once.
- Confirm the custom element is defined and every dashboard using it renders with no `hui-error-card`.
- Check the browser console for errors from the card (read_console_messages, filtered on the card name).
- Check the card in light and dark theme, and at 375 px wide (resize the window).
- If NetOrbit renders through Kepler, rerun the NetOrbit Step 1 checks too.

## Step 4. Leave it clean

- Leave the new version installed and loaded. Keep the backup. Close the tabs you opened.

## Report (one block the maintainer can paste)

- Pass or fail per step
- Home Assistant version, and the version before and after
- What looked different from a normal update
- Exact text of any error or log line, unparaphrased, with addresses and names replaced by placeholders
- The signature hashes and counts for each step, and how you explained any drift
- What you could not verify, marked "Unverified"
