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
license. `SHA256SUMS` covers the release downloads. This release is created as
a **draft prerelease** so its successful workflow result can be reviewed before
publication.
