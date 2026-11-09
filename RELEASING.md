# Releasing

1. Bump `version` in `custom_components/netorbit/manifest.json`, `VERSION` in `custom_components/netorbit/const.py` and `NETORBIT_VERSION` in `custom_components/netorbit/frontend/netorbit-card.js`. Move the `CHANGELOG.md` Unreleased entries into a section for the version. Nothing checks that the three match, so check by hand.
2. Push and wait for the Validate workflow to pass: HACS action, hassfest, tests, secret scan. The HACS action must pass with nothing ignored.
3. Create a GitHub **release** (a tag alone isn't enough; the Marketplace and HACS read releases). The tag must be the manifest version with a `v` in front. New versions go out as a pre-release first, never straight to Latest, so tick "Set as a pre-release".
4. The Release workflow checks the tag matches the manifest, builds `netorbit.zip` from the contents of `custom_components/netorbit` with the files at the zip root, attaches it to the release and checks it's there. It fails if the upload did not happen.
5. Every release must have `netorbit.zip` attached before it is promoted to Latest. If the workflow failed, don't promote. Once the manual checks below pass, promote it by unticking pre-release and ticking "Set as the latest release".

## Betas

A beta uses the same number in the manifest and the tag: manifest `0.3.1b1`, tag `v0.3.1b1`. A tag like `v0.3.1-beta.1` against that manifest fails the version check. When the beta is good, bump to `0.3.1` and release that the same way, as a pre-release first, so the Latest version never carries a beta number. That means running the release flow twice.

## Why the zip matters

The Downloads number in HACS and the Marketplace comes from GitHub's `download_count` on files attached to a release. HACS and the Marketplace unpack `netorbit.zip` into `custom_components/netorbit`, so the files must sit at the zip root. A badly built zip breaks every install. The Release workflow runs from the tagged commit, so a fix to it needs a new tag. Re-running the workflow is safe, because the upload uses `--clobber`. To go back to source installs, remove `zip_release` and `filename` from `hacs.json` in a later release.

## Known risks

- The first release with the zip is the first real test of the upload and verify steps. A failed run leaves a published pre-release with no zip, which breaks it for beta users until fixed.
- Releases up to 0.3.0 have no `netorbit.zip`. The HACS and Marketplace code reads `hacs.json` at the version being installed, so those releases should keep installing from source, and merging alone changes nothing for them. The Marketplace's non-catalog install path was not read, so test this on the beta.
- Promoting a pre-release does not protect the Latest slot. Until a release with the zip is promoted, 0.3.0 stays Latest. Only people who opted into betas can test the pre-release, so the first test for everyone else is the promotion itself.
- Picking 0.3.0 from the version menu should still work, for the reason above. If it fails on the beta, attach a zip built from the old tag by hand.
- The Marketplace supports `zip_release` and pre-releases. From the code, a missing asset fails the install and restores the previous files. Its Downloads number appears to come from the one asset on one release, so it may restart with each version. How the catalog builds the number it shows was not checked.
- The Validate HACS action may not exercise the new setting, so a green check on the PR is weak evidence.

## Repository settings the Marketplace and HACS check

- Public repository with a description, issues enabled, and topics (for example `home-assistant`, `hacs`, `home-assistant-integration`, `network`, `network-map`, `snmp`).
- A license GitHub can identify (MIT).
- Brand icon at `custom_components/netorbit/brand/icon.png` (Home Assistant 2026.3 and newer show it; older versions show a generic icon).
- Immutable releases off. The Release workflow uploads after publishing, which fails if that setting is on.

## Default list

NetOrbit has been in the default list since November 2, 2026 (hacs/default#12978), so people find it by searching the Marketplace or HACS. New releases need no extra step there.

## Manual checks before promoting to Latest

The browser tests cover Chromium and WebKit, but a few things need real devices:

- iPhone, in the Home Assistant iOS app: pinch to zoom the map, then drag while zoomed in.
- Desktop Safari: trackpad pinch over the map.
- Share image and video, in Safari and in the iOS app (Share arrives with PR #16).
- The first-scan animation on a fresh install.
- Install the pre-release through the Marketplace after taking a backup, with the Pre-release switch on, updating from the current version without reinstalling. Check the map loads and the log has no NetOrbit errors.
- From the version menu, pick 0.3.0, then go back to the pre-release. Both should install.
- Check `download_count` on `netorbit.zip` is above 0, and check the Marketplace number a day later.
