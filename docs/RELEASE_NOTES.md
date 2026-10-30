# Periphera 0.4.0 — RGB mouse mats

Adds all eight mouse-mat models currently supported by OpenRazer:
Firefly, Firefly HyperFlux, Firefly V2, Firefly V2 Pro, Goliathus Chroma,
Goliathus Extended Chroma, Goliathus Chroma 3XL and Strider Chroma.

- Dedicated **Mouse mats** page with explicit selection for multiple mats.
- Brightness, supported static/spectrum/breathing/wave/reactive/off effects,
  manual reactive triggering and custom matrix colours.
- Hardware-free preview for every model, with all hardware commands disabled.
- Runtime feature detection and live matrix layout, plus device-type checks
  for HyperFlux's shared USB ID and lighting-sync protection.
- Both new modules and their tests included in Flatpak packaging and smoke checks.
- See [MOUSE_MATS.md](MOUSE_MATS.md) for setup, variants and limitations.

**Mouse-mat support needs physical owner testing.** Effect availability
depends on the installed OpenRazer release. The host needs a current
OpenRazer driver and desktop-session daemon; preview mode needs neither.
Automatic mouse-click reactions, charging configuration and firmware updates
are not included. The existing headset HID backend is unchanged.

Install the v0.4.0 bundle using `flatpak install --user ./periphera.flatpak`.
See `HOST_SETUP.md` and `MOUSE_MATS.md` for host drivers and setup. The release
includes the source archive, host setup files and `SHA256SUMS`.

Validation passed for the mouse-mat implementation: 100 automated tests on
Ubuntu and inside the Flatpak SDK, real D-Bus wire checks against a simulated
service, metadata validation and Flatpak installation/startup checks.
Release requests now have eight additional tests to prevent unintended
publication. The release workflow verifies the attached files' checksums.

## Previous release: 0.3.0

Periphera 0.3.0 added an experimental Naga V2 Pro page alongside the
existing Barracuda X Chroma controls.

- DPI, polling, battery, power and logo/thumb-grid lighting through host OpenRazer.
- Read-only mouse preview for users without the device.
- Flatpak desktop launcher, metadata and GitHub build workflow.
- The existing headset HID backend is unchanged.

**Mouse support needs physical owner testing.** This is not full Synapse
compatibility. Button remapping, onboard profile management and HyperScroll
tuning are not included.

Install `periphera.flatpak` with:

```sh
flatpak install --user ./periphera.flatpak
```

Read `HOST_SETUP.md`: mouse control requires OpenRazer 3.10.3+ on the host;
headset control requires the included udev rule if it is not already installed.
The Flatpak requests broad device visibility for headset hidraw access.

The source ZIP contains the full application, tests, build manifest and GPL
license. `SHA256SUMS` covers the release downloads.

Validation passed: all 65 tests on Ubuntu and inside the Flatpak SDK, a real
D-Bus integration test against a simulated OpenRazer service, desktop metadata
validation, and installation/startup of the built Flatpak. Hardware control
inside the sandbox still needs owner testing. Version 0.3.0 remains a
**prerelease** while physical Naga V2 Pro testing is outstanding.
