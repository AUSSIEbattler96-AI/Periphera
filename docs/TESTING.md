# Periphera BlackWidow test

Version: **0.4.2-test.2**. Branch: **testing/blackwidow-v4x-v3**.

This build starts from the restored 0.4.1 device backends. It adds guided Linux
hardware setup and adds dedicated BlackWidow V4 X/V3 controls. It does not
restore the withdrawn generic 0.5.0 integration. See [BLACKWIDOW.md](BLACKWIDOW.md).

## Download from GitHub

Download `periphera-testing.flatpak` from the
[testing prerelease](https://github.com/AUSSIEbattler96-AI/Periphera/releases/tag/v0.4.2-test.2)
and open it in Discover, or run:

```sh
flatpak install --user ./periphera-testing.flatpak
flatpak run io.github.AUSSIEbattler96_AI.Periphera.Testing
```

The desktop launcher is **Periphera Testing**, with a separate Flatpak ID and
testing branch. Installing it does not replace the regular 0.4.1 Flatpak.
The first install may download the shared KDE runtime automatically.

Pushes to `testing/**` build artifacts. A changed, explicit
`.github/testing-release.json` request can publish a version-matched testing
prerelease from its named branch only, after tests and Flatpak verification.
The release is marked prerelease and never replaces the latest stable release.
It does not update `main` or the normal release downloads. Actions artifacts
are retained for 30 days. There is no automatic update feed for this bundle.

## Try the setup flow

1. Launch **Periphera Testing**. Its opening setup check reads the real host's
   kernel, OpenRazer version, driver, permission group and service status.
2. Choose **Mouse and mouse mats**, **BlackWidow keyboard + macros**,
   **Barracuda headset**, or all devices.
3. Click **Install / repair**. Review the package and permission changes and
   approve the desktop's administrator prompt when you want to install them.
4. Follow the displayed reconnect or sign-out instructions. Group membership
   added to your account does not become active in an existing login session.
5. Start the device service from the setup page, then scan the mouse or mat.
6. Apply a setting and confirm the physical device changes. Copy setup details
   if a check or repair fails.

The installer uses configured package repositories and never replaces SteamOS's
kernel headers with generic Arch headers. It restores SteamOS read-only mode
after a driver install, including normal install failures. OS updates can still
remove or invalidate host driver support; open Hardware setup to recheck.

Host drivers and permissions are shared with the regular app and other hardware
tools. The separate testing identity isolates the application installation, not
these system-wide support components. No device settings are applied during
checks, repair or service restart. The helper does not clear driver state,
disable lighting sync, change firmware, remove package locks, bypass signatures,
initialize package signing keys, add repositories or perform a full OS upgrade.

## What was checked

Automated tests cover the existing device controllers and previews, exact-kernel
header planning, missing/old packages, permission-group restart guidance,
cancelled repair, changed plans and restoring SteamOS read-only mode after a
simulated package failure. GUI checks render the setup page without hardware.
GitHub Actions also builds, installs and starts the actual testing Flatpak.

No physical Steam Deck, Naga V2 Pro or mouse mat is attached to CI. A successful
build does not establish that the earlier mouse DPI readback problem is fixed,
or that every distribution's driver install works on real hardware.

## Build it yourself

```sh
bash scripts/build-flatpak.sh
```

This branch builds only `dist/periphera-testing.flatpak`. To remove the test app:

```sh
flatpak uninstall --user io.github.AUSSIEbattler96_AI.Periphera.Testing
```

Uninstalling the Flatpak does not remove shared host drivers or permission rules.
