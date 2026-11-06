# Contributing to NetOrbit

Pull requests are welcome, from a one-word typo fix to a new feature. You don't need to ask first or be added to the project. Open a PR and we'll take it from there.

## How credit works

GitHub only lets the maintainer push to this repository, so everyone else contributes through a fork. That's the normal GitHub flow and it doesn't cost you any credit:

- PRs are squash-merged, and the squashed commit keeps you as its author. You show up in the commit history and in the repository's Contributors list.
- For that to link to your profile, the email on your commits has to be one GitHub knows is yours. If you use GitHub's private address (`<id>+<username>@users.noreply.github.com`, under Settings → Emails), you're covered.
- If we change your PR before merging, or build on your idea in a separate PR, you're added as a `Co-authored-by:` on the commit so you still get credit.

## The quick path

1. Fork the repo on GitHub (the **Fork** button, top right).
2. Make a branch in your fork, for example `fix/zoom-on-ipad`.
3. Make your change and run the checks below.
4. Open a pull request against `main` here. Say what it changes and how you tested it. Screenshots help for anything on the card.

Small and focused PRs get reviewed fastest. If you're planning something big, opening an issue first to talk it over can save you rework, but it's not required.

## What happens after you open it

- **CI runs on every PR.** The checks are hacs, hassfest, tests, examples, secrets, and an end-to-end test that starts a real Home Assistant in Docker and drives the card in Chromium and WebKit. All of them except the Home Assistant beta run must pass before a merge.
- **First-time contributors:** GitHub may hold your CI runs until the maintainer clicks "Approve and run". That's a GitHub safety setting for new accounts, and it stops after your first merged PR.
- **Review:** expect comments or a merge within a few days. If we ask for changes, push more commits to the same branch. No need to squash or force-push; we squash on merge.
- **Release:** merged changes go out in the next version. It ships as a pre-release first, then becomes Latest once it's been checked on a real install. Your PR is listed in the changelog.

## Running the checks locally

The tests need Python 3.14.2 or newer, like current Home Assistant.

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
node --test tests/card.test.js
python scripts/check_examples.py
```

For card changes, preview the card with fake data: `npm i @mdi/js@7.4.47`, copy `node_modules/@mdi/js/mdi.js` to `scripts/preview/`, serve the repo root (`python -m http.server 8766`), and open `http://localhost:8766/scripts/preview/index.html?s=full` (or `mesh`, `flat`, `novice`). `node scripts/preview/interact.js` drives edit mode in a real browser with Playwright (set `NETORBIT_PREVIEW` if the server is not on port 8766).

The README describes the network simulator (`tests/test_simulation.py`), which checks placement across hundreds of generated networks. Run it if you touch how devices are found or placed.

## House rules

- **No real network data.** Examples, tests and docs only use the address ranges reserved for documentation: `192.0.2.x` for IPs and `00:00:5e:00:53:xx` for MACs. No real hostnames, device names or SNMP communities either. `scripts/check_examples.py` enforces the address part, and CI runs it.
- **Never commit secrets.** CI scans the full history and fails the PR if it finds one.
- **Older browsers matter.** The card runs in the Home Assistant iOS and Android apps, so avoid very new JavaScript syntax such as `??` and `??=`. The WebKit run in CI catches some of this, not all.
- **Add a test** for bug fixes and new behavior where you can.
- **Update the docs** (README, `docs/SETUP.md`) when you change something a user sees. A line for `CHANGELOG.md` is welcome; if you skip it, we'll write it.

## Bugs and ideas

Not up for writing code? [Open an issue](https://github.com/the-scott-davis/netorbit/issues/new/choose). For bugs, the Home Assistant version, your network gear, and the NetOrbit diagnostics download (Settings → Devices & services → NetOrbit → ⋮ → Download diagnostics) help the most. The download replaces addresses and names with placeholders, so it's safe to attach.
