# BlackWidow keyboard testing

Periphera **0.4.2-test.2**, branch `testing/blackwidow-v4x-v3`.

| Keyboard | USB ID | Controls |
| --- | --- | --- |
| BlackWidow V4 X | `1532:0293` | RGB effects, brightness, individual key colours, M1–M6 macros |
| BlackWidow V3 (full-size wired model) | `1532:024e` | RGB effects, brightness, individual key colours |

Other V3/V4 variants have different USB IDs and are not part of this adapter.
Controls follow the installed OpenRazer driver's live capabilities.

## Install and connect

Download `periphera-testing.flatpak` from the
[testing prerelease](https://github.com/AUSSIEbattler96-AI/Periphera/releases/tag/v0.4.2-test.2).

```sh
flatpak install --user ./periphera-testing.flatpak
flatpak run io.github.AUSSIEbattler96_AI.Periphera.Testing
```

This installs **Periphera Testing** alongside the normal app.
In **Hardware setup**, check Linux setup. For RGB alone, the normal OpenRazer
support is sufficient. For V4 X macros, select **BlackWidow keyboard + macros**
and **Install / repair**. The helper installs the host OpenRazer packages and
matching running-kernel driver, loads `razerkbd`, and sets up `uinput` for macro
playback. Sign out and back in if the permission group changed, then start the
device service. Open **BlackWidow**, scan, and select your keyboard.

## RGB controls

- **Lighting:** brightness, static, spectrum, single/dual/random breathing,
  wave, reactive, single/dual/random starlight, single/random ripple and off.
  The V4 X also exposes wheel; V3 does not.
- **Key colours:** choose a paint colour, click individual keys, fill a row or
  all keys, then **Apply key colours**. Matrix dimensions come from the daemon;
  both reference devices have a 6 × 22 matrix. Labels follow OpenRazer's standard
  keyboard layout; ISO/ANSI/regional layouts can differ. All slots are editable.
- Turn off OpenRazer lighting synchronization before changing RGB, so a command
  cannot propagate to other devices. Unknown sync state also blocks RGB writes.
- **Preview** supports both models and all editor tabs without hardware.
  Hardware commands and macro saving remain disabled in preview.

Colour editing and scanning do not write to the device. Effects require Apply.
Brightness requires successful daemon readback; effects and custom frames need
visual confirmation because OpenRazer does not provide independent LED readback.

## V4 X macros

Open **V4 X macros**, choose M1–M6 and add shortcuts such as `CTRL+C`,
`CTRL+SHIFT+V`, `SUPER+E` or `ENTER`. Add waits between shortcuts to build a
sequence. The table also allows editing/reordering individual DOWN, UP and WAIT
steps. Delays are milliseconds before each step. A macro must release every
key it presses; invalid sequences cannot be saved. Save binds the sequence to
the selected physical macro key and stores a local copy only after OpenRazer
readback matches. Delete removes that binding and its saved copy.

OpenRazer watches the physical M1–M6 keys. Its macro endpoint invokes a bundled
standard-library Python player on the host as your normal desktop user. The
player emits Linux virtual keyboard events through `/dev/uinput`, so playback
does not depend on X11 or `xte`. It accepts validated keyboard events only.
The active local desktop user receives uinput access via a udev `uaccess` rule;
the helper loads uinput at boot. RGB alone does not need this permission.

The first macro after startup (or ten idle minutes) waits about one second for
the compositor to attach the virtual keyboard. Further macros reuse the device.
Playback follows the active keyboard layout and sends input to the focused app.
Bindings stay active while OpenRazer is running even if Periphera is closed.
After a reboot or daemon restart, scan and click **Restore saved macros**.
Existing bindings managed by other tools require confirmation before replacement.

These are **host macros**, not hardware/onboard profiles. The editor supports
up to 512 steps and two minutes per macro. Arbitrary command/script editing,
mouse actions, global recording, repeat/hold loops, firmware management and
Synapse profile import are not included.

## Validation

Controller and UI tests cover discovery, both USB IDs, feature gating, typed
effect arguments, all six matrix rows, unplugging, multiple-device selection,
macro save/delete/readback, local restore, timing and cleanup of held keys.
CI additionally runs a real private D-Bus session against a simulated OpenRazer
service and builds, installs and starts the actual Flatpak.

No physical BlackWidow is attached to the build environment. RGB placement,
macro triggering and playback still need an owner test on the real keyboards.

Reference contracts:

- [OpenRazer keyboard devices](https://github.com/openrazer/openrazer/blob/master/daemon/openrazer_daemon/hardware/keyboards.py)
- [OpenRazer RGB endpoints](https://github.com/openrazer/openrazer/blob/master/daemon/openrazer_daemon/dbus_services/dbus_methods/chroma_keyboard.py)
- [OpenRazer macro endpoints](https://github.com/openrazer/openrazer/blob/master/daemon/openrazer_daemon/dbus_services/dbus_methods/macro.py)
- [OpenRazer macro objects and playback](https://github.com/openrazer/openrazer/blob/master/daemon/openrazer_daemon/misc/macro.py)
- [Linux uinput interface](https://www.kernel.org/doc/html/latest/input/uinput.html)
