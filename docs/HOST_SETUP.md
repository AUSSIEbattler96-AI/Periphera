# Host setup

The Flatpak contains the GUI, Python bindings and application code. Device
drivers and udev permission rules belong on the host Linux system.

## Barracuda X Chroma

Use the 2.4 GHz USB dongle (`1532:0574`). If you already installed this
project's permission rule, keep it; no change is needed.

For a new installation, download `install-permissions.sh` and
`70-barracuda-x-chroma.rules` from the same release into one directory. Open
a terminal there and run, as your normal desktop user:

```sh
bash install-permissions.sh
```

Unplug and reconnect the dongle. Launch Periphera from your desktop
menu. Diagnostics → Check device access should show readable/writable true.
The rule grants access to the active local user and is restricted to the
headset's USB ID. The app itself must run without sudo.

## Naga V2 Pro

Install **OpenRazer 3.10.3 or newer** using the instructions for your host
distribution at <https://openrazer.github.io/#download>. Its kernel driver,
device permissions, and user-session daemon must all be working. A Flatpak
cannot install a host kernel module. Use the matching kernel headers if your
distribution uses DKMS; follow OpenRazer's distro instructions for groups and
session restart requirements.

On Arch/CachyOS, use the OpenRazer Arch instructions and headers for the
kernel you actually run; do not substitute generic `linux-headers` for a
CachyOS or LTS kernel. The GUI talks to `org.razer` on your **session** bus.
It does not need OpenRazer's Python client installed inside the Flatpak.

Connect either the USB cable (`1532:00a7`) or original 2.4 GHz receiver
(`1532:00a8`), wake the mouse, open **Naga V2 Pro**, and click **Scan for mouse**.
If more than one is found, choose the serial/connection you want. No settings
are applied during scanning.

Bluetooth and connections through Mouse Dock Pro are not supported by this
adapter. No mouse is needed for **Preview without a mouse**; it cannot send
commands. Mouse support has not been tested on a physical Naga V2 Pro by this
project.

If OpenRazer lighting synchronization is enabled, disable it in your
OpenRazer configuration before using per-mouse lighting. The app will refuse
lighting changes while sync is on, because sync may affect other peripherals.
It does not change that global setting automatically.

## Flatpak permissions

- `--device=all` exposes hidraw nodes needed by the existing headset backend.
  The USB portal alone does not provide this hidraw access. Host permissions
  still apply. This is broad device visibility; it is not a narrowly isolated
  USB sandbox.
- `--talk-name=org.razer` grants access to the host OpenRazer session service.
- Wayland, fallback X11 and IPC allow the desktop interface to display.
- No home-directory, network, full session-bus or system-bus permission is
  requested. OpenRazer can control other Razer devices, but this adapter
  restricts writes to the two Naga V2 Pro USB IDs and the selected serial.

To use the mouse alone with less device exposure:

```sh
flatpak override --user --nodevice=all io.github.AUSSIEbattler96_AI.Periphera
```

This disables direct headset access. To restore the packaged permissions:

```sh
flatpak override --user --reset io.github.AUSSIEbattler96_AI.Periphera
```
