# Support and validation boundaries

Periphera 0.5.0 discovers all devices returned by the host OpenRazer daemon.
It is an independent experimental controller, not full Synapse compatibility.

| Device source | Discovery | Controls | Validation |
| --- | --- | --- | --- |
| Host OpenRazer | Every returned device, including Naga Trinity, keyboards, mice, keypads, headsets, mats, cases, monitors and accessories | Public controls whose method and signature are advertised by the live device | Simulated controllers, GUI tests and real D-Bus wire tests; new controls still need physical owner testing |
| Barracuda X Chroma `1532:0574` | Existing direct HID discovery through its 2.4 GHz dongle | Original status, EQ, microphone monitoring, sleep timeout and six-zone RGB | Original owner-confirmed status, RGB, EQ preset switching and sidetone; further controls need owner testing |

## Device controls

Periphera no longer excludes the Trinity or other models with a fixed USB-ID
allowlist. Host OpenRazer determines which devices and connection modes exist.
A device absent from that daemon cannot be added by the Flatpak UI alone.

Live introspection is intersected with documented public control metadata in
`openrazer_catalog.json`. This supplies lighting, sensitivity, DPI stages,
polling, power, scroll, key/macro and accessory controls across device types.
Missing methods and incompatible wire signatures are omitted. New upstream
control APIs may require an app update even when device discovery already works.
Low-level device lifecycle, firmware updating and arbitrary Synapse-only features
are not provided by this interface.

- DPI and polling options follow the selected daemon device. Legacy single-axis
  DPI devices use their discrete choices and a zero Y-axis value.
- DPI stages use the typed byte/array-of-uint16-pairs API, with up to five stages.
- Lighting colours, brightness, effects, charging zones and ARGB controls are
  presented only where advertised. Driver slots may differ from marketing zones.
- Custom LED frames use each device's live rows and columns, upload every row,
  then activate custom mode. The editor does not infer physical key labels.
- Macro editing sends key presses/releases, URL actions and host script paths to
  OpenRazer. Execution depends on the host daemon, its key mappings and desktop
  input support; Wayland may constrain upstream macro playback.
- HyperPolling pairing/LED controls and scroll options appear only where the
  installed daemon exposes them. No extra support is claimed for other docks.

## Selection and writes

Home scans and refreshes are read-only. Settings change only through an explicit
Apply action. Device identity and live method signatures are checked again for
writes. Rescans remove disconnected entries and invalidate opened device pages;
failed status reads disable controls. Duplicate names keep separate serial IDs.
Draft edits survive a refresh while the device's control layout stays the same.

Shared lighting must be off for per-device lighting changes. Unknown sync state
also blocks those writes. Home exposes explicit global sync/screensaver controls;
Periphera never changes them automatically. Daemon readback may be cached, so a
successful command needs physical confirmation. Diagnostics records errors and
responses; remove serial numbers before publishing logs.

## Tests

```sh
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -v
QT_QPA_PLATFORM=offscreen python3 scripts/smoke_gui.py
QT_QPA_PLATFORM=offscreen dbus-run-session -- python3 scripts/test_dbus_wire.py
```

The full suite uses simulated devices. The wire check requires PyQt6.QtDBus,
dbus-python, PyGObject and Jeepney; the desktop app uses PyQt6 and Jeepney.
The Barracuda CLI continues to use only the Python standard library.
CI builds the Flatpak and tests its installed contents before release.
See [VALIDATION.txt](../VALIDATION.txt) for recorded results.

## Host setup and sources

- [Host setup, including SteamOS diagnostics](HOST_SETUP.md)
- [OpenRazer supported devices and installation](https://openrazer.github.io/)
- [Public endpoint metadata source](https://github.com/openrazer/openrazer/tree/477f4d6d3ab7e9deb6310d5bd3742560c5cbe80d/daemon/openrazer_daemon/dbus_services/dbus_methods)
- [Device type and identity API](https://github.com/openrazer/openrazer/blob/477f4d6d3ab7e9deb6310d5bd3742560c5cbe80d/daemon/openrazer_daemon/dbus_services/dbus_methods/all.py)
- [Matrix framing in the upstream client](https://github.com/openrazer/openrazer/blob/477f4d6d3ab7e9deb6310d5bd3742560c5cbe80d/pylib/openrazer/client/fx.py)
- [Jeepney D-Bus transport](https://jeepney.readthedocs.io/en/latest/integrate.html)

OpenRazer's kernel driver and daemon remain separate host dependencies; they are
not bundled or forked by this application.
