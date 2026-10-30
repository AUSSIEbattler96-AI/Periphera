# Razer RGB mouse mats

Periphera 0.5.0 discovers all mouse mats reported by OpenRazer. The models below are also included in the hardware-free preview selector.
The app uses the host's `org.razer` session service, with no direct mouse-mat
USB packets, extra kernel module or additional Flatpak permissions.

| Model | USB ID | Wave in upstream driver |
| --- | --- | --- |
| Firefly | `1532:0c00` | Yes |
| Firefly HyperFlux | `1532:0068` | No |
| Firefly V2 | `1532:0c04` | Yes |
| Firefly V2 Pro | `1532:0c08` | Yes |
| Goliathus Chroma | `1532:0c01` | No |
| Goliathus Extended Chroma | `1532:0c02` | No |
| Goliathus Chroma 3XL | `1532:0c06` | No |
| Strider Chroma | `1532:0c05` | Yes |

Surface, colour and special editions are covered when they report the same
USB ID and the driver exposes them as a mouse mat. The generic discovery path
also accepts newer models when the host daemon supports them. HyperFlux's mouse
object appears under Mice even though it can share the mat's product ID.
Passive mats without RGB, such as Gigantus V2,
Atlas and ordinary Strider, have no RGB settings to control.

## Setup

1. Install a current OpenRazer release for your host distribution using
   [the upstream instructions](https://openrazer.github.io/#download).
   Its driver, permissions and desktop-session daemon must work before
   Periphera can find a mat. Older versions may lack newer models.
2. Connect the mat by USB and launch Periphera as your normal desktop user.
3. Open **Home** and click **Scan for devices**. Select your individual mat
   under **Mouse mats** in the sidebar before applying a setting.
4. Turn off shared lighting on Home and explicitly apply that preference if
   needed. Per-device actions never change that global setting; they block writes
   when synchronization is on or its state cannot be read.

No mat is needed for **Home → Mouse-mat previews**. Select a model from the
preview list to explore its layout. Preview values are examples, all hardware
commands are disabled, and leaving preview clears the example readings.

## Controls

- **Brightness:** 0–100%. Apply explicitly; the app checks daemon readback.
- **Effects:** static, spectrum cycle, single/dual/random breathing, off,
  and wave/reactive when the installed driver exposes them.
- **Wave:** choose the direction. It is absent on Goliathus and HyperFlux
  in the current upstream device definitions.
- **Reactive:** choose a colour and speed, apply the effect, then use
  **Apply trigger reactive lighting**. Automatic reactions to mouse clicks are not
  implemented; the app does not capture desktop input.
- **Custom colours:** pick a colour and click individual driver LED slots.
  **Fill with colour** edits all slots locally; **Apply LED colours** uploads
  the complete frame and activates custom mode.

The Goliathus family exposes one shared colour for its RGB edge. Other mats
use multiple matrix slots. Live dimensions come from the daemon, rather
than being guessed from the marketing zone count. For example, OpenRazer
exposes 17 slots for Firefly V2 Pro, including driver-specific positions;
that does not mean the product has 17 advertised physical lighting zones.
The illustration is a colour preview, not an exact physical slot map.

Editing colours, changing a preview model, navigating or scanning does not
change hardware. Refresh preserves unapplied edits for the same selected
mat. Unplugging or switching devices disables stale controls. Every write
rechecks the selected device's USB ID, mouse-mat type and driver capabilities.

## Validation

Mouse-mat integration is experimental and has been tested with simulated
OpenRazer responses, not physical mats. Effect and custom colour commands
have no independent hardware readback: confirm the result visually.
Brightness readback may be daemon-cached. Charging, pairing and firmware
updates are outside these lighting controls.

Upstream contracts checked on 30 October 2026:

- [Supported models and matrix dimensions](https://github.com/openrazer/openrazer/blob/master/daemon/openrazer_daemon/hardware/mouse_mat.py)
- [Effect and brightness endpoints](https://github.com/openrazer/openrazer/blob/master/daemon/openrazer_daemon/dbus_services/dbus_methods/chroma_keyboard.py)
- [Device type and matrix introspection](https://github.com/openrazer/openrazer/blob/master/daemon/openrazer_daemon/dbus_services/dbus_methods/all.py)
- [Public client matrix framing and activation order](https://github.com/openrazer/openrazer/blob/master/pylib/openrazer/client/fx.py)
