# Periphera

A charcoal-and-green Linux desktop controller for the **Razer Barracuda X
Chroma** headset and **Razer Naga V2 Pro** mouse. GUI release **0.3.0**.

![Naga V2 Pro page in read-only preview mode](previews/naga-performance.png)

This is an independent project, not an official Razer application or full
Synapse compatibility. The mouse adapter is **experimental and has not been
tested on a physical Naga V2 Pro**. Preview values are examples, not live
device readings.

## What's included

- Barracuda: battery/status, EQ, microphone monitoring, power saving and
  six-zone lighting, using the existing direct HID backend.
- Naga V2 Pro: DPI, polling rate, battery, power settings and separate
  logo/thumb-grid lighting through a host OpenRazer daemon.
- No-device mouse preview, explicit Apply actions, capability detection and
  diagnostic responses.
- Flatpak manifest, desktop integration, tests and GitHub release workflow.

The original headset owner confirmed status, RGB, EQ preset switching and
sidetone. Mouse tests use simulated responses. See [support details](docs/SUPPORT.md)
for the exact boundaries and missing features.

## Update your existing native installation

Close the GUI and replace the files in your `barracuda-linux` directory with
this source archive. Your installed `python-pyqt6` package and headset udev
rule remain suitable. Launch as before:

```sh
python3 barracuda.py gui
```

Select **Naga V2 Pro** in the sidebar. Enable **Preview without a mouse** to
explore it without installing OpenRazer or connecting a mouse. Preview mode
cannot send commands.

For a new native installation on Arch/CachyOS, install `python-pyqt6` first.
Other distributions may package `PyQt6.QtDBus` separately. The headset CLI
still needs only Python's standard library; see the [headset guide](docs/HEADSET_CLI.md).

## Install a Flatpak release

Download `periphera.flatpak` from [GitHub Releases](https://github.com/AUSSIEbattler96-AI/Periphera/releases).
Version 0.3.0 is an experimental prerelease. Install Flatpak with your
distribution's package manager, then:

```sh
flatpak install --user ./periphera.flatpak
flatpak run io.github.AUSSIEbattler96_AI.Periphera
```

The application also appears as **Periphera** in your desktop menu.
This is a standalone GitHub-distributed bundle, not a Flathub listing or an
automatic-update repository. Download and install a newer bundle to update.

**Host setup still matters:** [HOST_SETUP.md](docs/HOST_SETUP.md) covers the
headset permission rule and OpenRazer 3.10.3+ for mouse control. Drivers
cannot be installed inside the Flatpak. Existing headset users keep their
current rule. The package requests broad device access for headset hidraw
and a narrowly named D-Bus permission for OpenRazer; it requests no network
or home-directory access.

Use the headset's 2.4 GHz dongle (`1532:0574`). The Naga adapter accepts the
mouse's USB cable (`1532:00a7`) or original receiver (`1532:00a8`). Bluetooth
and Mouse Dock Pro configuration are not supported.

## Build locally

On a normal Linux desktop with Flatpak and flatpak-builder installed:

```sh
bash scripts/build-flatpak.sh
```

This installs the KDE 6.10 SDK/runtime and PyQt BaseApp into the user's
Flatpak installation, runs the tests inside the SDK, and creates
`dist/periphera.flatpak` plus `dist/SHA256SUMS`. It does not install
host drivers, write udev rules or change device settings. The first build
downloads the SDK and can take a while. The GitHub workflow builds x86_64;
other architectures have not been validated.

## GitHub builds and releases

The **Test and build Flatpak** workflow runs on `main`, pull requests, tags
and manual dispatch. It tests the backend/UI, verifies real D-Bus wire
types against a simulated service, validates metadata, builds the bundle,
tests the installed application, and uploads a downloadable artifact.

After the workflow is green, create the first release tag:

```sh
git tag v0.3.0
git push origin v0.3.0
```

A successful tag build creates a **draft prerelease**, containing the
Flatpak, source ZIP, host setup files and checksums. Review it in GitHub
Releases before publishing. Mouse hardware testing is still required even
when all CI tests pass.

## Development and license

```sh
QT_QPA_PLATFORM=offscreen python3 -m unittest -v test_barracuda.py test_gui.py test_naga.py test_naga_gui.py
```

Read [SUPPORT.md](docs/SUPPORT.md) and [VALIDATION.txt](VALIDATION.txt) for
what was actually tested. The [first successful build](https://github.com/AUSSIEbattler96-AI/Periphera/actions/runs/40892218019)
passed all 65 tests on Ubuntu and inside the Flatpak SDK, the real D-Bus
integration test against a simulated service, desktop metadata validation,
and an installation/startup check of the built Flatpak. Physical Naga V2 Pro
testing is still outstanding.

Licensed under [GPL-3.0-or-later](LICENSE), compatible with the GPL edition
of PyQt6 used by this package. OpenRazer is a separate host dependency. Razer,
Barracuda, Naga and Chroma are trademarks of their respective owner; this
project is not affiliated with or endorsed by Razer.
