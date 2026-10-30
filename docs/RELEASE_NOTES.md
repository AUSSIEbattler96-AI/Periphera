Periphera 0.3.0 adds an experimental Naga V2 Pro page alongside the
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
