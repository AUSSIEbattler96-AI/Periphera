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

Once the GitHub workflow has produced a bundle and its draft prerelease has
been published, download `periphera.flatpak` from Releases. Install
Flatpak with your distribution's package manager, then:

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

## Put this project on GitHub

Keep the `.github/` directory when uploading this source. With Git and the
GitHub CLI authenticated, run these commands from the project directory:

```sh
git init -b main
git add .
git commit -m "Add Barracuda controls, experimental Naga support and Flatpak builds"
gh repo create Periphera --public --source=. --remote=origin --push
```

Git may first ask you to configure your commit name and email. If you
already have a repository, commit and push there instead of creating another.

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
when all CI tests pass. No release has been published by these source files
alone.

## Development and license

```sh
QT_QPA_PLATFORM=offscreen python3 -m unittest -v test_barracuda.py test_gui.py test_naga.py test_naga_gui.py
```

Read [SUPPORT.md](docs/SUPPORT.md) and [VALIDATION.txt](VALIDATION.txt) for
what was actually tested. The Flatpak and real D-Bus integration checks
could not run in the source-preparation environment because Linux namespace
and socket creation are restricted; their workflow results are not yet known.

Licensed under [GPL-3.0-or-later](LICENSE), compatible with the GPL edition
of PyQt6 used by this package. OpenRazer is a separate host dependency. Razer,
Barracuda, Naga and Chroma are trademarks of their respective owner; this
project is not affiliated with or endorsed by Razer.
