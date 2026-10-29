# Support and validation boundaries

This is an independent experimental controller, not an official Razer app
and not full Synapse compatibility. The release is intended for community
testing, not a claim of complete device support.

| Device | Transport | Implemented controls | Validation |
| --- | --- | --- | --- |
| Barracuda X Chroma `1532:0574` | Direct hidraw through 2.4 GHz dongle | Battery/status, EQ presets/curve, sidetone, sleep timeout, six-zone RGB and host-generated effects | Owner confirmed status, RGB, EQ preset changes and sidetone in the original backend. Custom EQ/sleep writes and effects still need owner testing. |
| Naga V2 Pro `1532:00a7` / `1532:00a8` | Host OpenRazer session D-Bus, cable/original receiver | X/Y DPI, polling rate, battery, sleep seconds, low-battery threshold, logo/thumb-grid brightness and static/spectrum/breathing/off | Adapter and UI tested with simulated responses; no physical mouse test. |

The app does not configure the Naga Trinity or BlackWidow V4 X. They can
remain connected; they are filtered out by the mouse adapter. Existing
headset behavior is preserved.

## Mouse behavior

- DPI is limited by the live daemon maximum, capped at 30,000; this editor's
  lower limit is 100. Polling choices are 125, 500 and 1,000 Hz.
- Sleep is 60–900 **seconds**. Low-battery threshold is 5–50%. These are
  intentionally bounded controls, not claims about every firmware mode.
- Introspection determines which methods exist and their wire types. Missing
  capabilities are disabled. A successful getter is required before a
  numerical setter; a follow-up getter must match (with small quantization
  tolerance for brightness/threshold).
- OpenRazer getters may return daemon-cached data. “OpenRazer readback
  matched” does not prove an independent physical hardware readback.
- Effect commands have no color/effect readback. Confirm them visually.
- DPI stages, button remapping/macros, onboard profile management,
  HyperScroll feel/tension tuning, Bluetooth configuration, Mouse Dock Pro
  pairing, and firmware updates are not implemented here.

## Tests

```sh
QT_QPA_PLATFORM=offscreen python3 -m unittest -v test_barracuda.py test_gui.py test_naga.py test_naga_gui.py
QT_QPA_PLATFORM=offscreen python3 scripts/smoke_gui.py
```

These tests use simulated devices and do not access your hardware. A separate
CI check uses a private D-Bus session and a simulated OpenRazer service:

```sh
QT_QPA_PLATFORM=offscreen dbus-run-session -- python3 scripts/test_dbus_wire.py
```

It needs PyQt6.QtDBus, dbus-python, and PyGObject. The GUI needs only PyQt6;
the Barracuda command-line backend still uses Python's standard library.

The development environment used for this update blocks D-Bus socket creation
and bubblewrap namespaces. Therefore the real D-Bus integration check and
complete Flatpak build have **not run there**. GitHub Actions runs them before
producing a release artifact. See the workflow run for its actual result;
the existence of a manifest does not mean a bundle has built successfully.

## Owner testing

On the first mouse test, scan and inspect Diagnostics before changing a
setting. Check DPI, then polling, power, and lighting separately. Report the
USB ID, connection mode, OpenRazer version, requested value, and observed
behavior. Remove serial numbers before publishing diagnostic output.

## Upstream references checked for this implementation

- [OpenRazer 3.10.3 mouse device definitions](https://github.com/openrazer/openrazer/blob/v3.10.3/daemon/openrazer_daemon/hardware/mouse.py)
- [OpenRazer 3.12.4 mouse device definitions](https://github.com/openrazer/openrazer/blob/v3.12.4/daemon/openrazer_daemon/hardware/mouse.py)
- [DPI, polling and power endpoints](https://github.com/openrazer/openrazer/blob/v3.10.3/daemon/openrazer_daemon/dbus_services/dbus_methods/mamba.py)
- [Logo lighting endpoints](https://github.com/openrazer/openrazer/blob/v3.10.3/daemon/openrazer_daemon/dbus_services/dbus_methods/nagahexv2.py)
- [Thumb-grid/general Chroma endpoints](https://github.com/openrazer/openrazer/blob/v3.10.3/daemon/openrazer_daemon/dbus_services/dbus_methods/chroma_keyboard.py)
- [Qt D-Bus Python support](https://www.riverbankcomputing.com/static/Docs/PyQt6/dbus.html)
- [Flatpak sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html)
- [PyQt BaseApp 6.10](https://github.com/flathub/com.riverbankcomputing.PyQt.BaseApp/tree/branch/6.10)
- [Original Barracuda protocol discussion](https://github.com/openrazer/openrazer/issues/2704)

The mouse adapter is new application code using the public D-Bus interface;
it does not bundle or fork OpenRazer's driver/daemon.
