# Host setup

## Guided setup in the testing build

The `testing/hardware-setup` branch opens **Hardware setup** on launch and checks
the real host's kernel, OpenRazer, permission group, device service and headset
USB access. Checks are read-only. Choose the device type and **Install / repair**
to review the plan and authenticate through the desktop's administrator prompt.

Automatic OpenRazer installation supports Arch/CachyOS/SteamOS and Debian/Ubuntu
when suitable packages are available in configured repositories. No repositories,
signing keys or package-manager locks are changed. Kernel headers are matched to
the running kernel; generic Arch headers are not substituted for SteamOS or
CachyOS headers. Missing packages or headers stop repair with guidance.

SteamOS is made writable only when driver packages must be installed, and its
previous read-only state is restored after completion or a normal failure.
Drivers may need repair after an OS update. New group membership requires a new
desktop sign-in or reboot. After that, use **Start / restart device service**,
then scan your mouse or mat. Reconnect the headset dongle after installing its
rule. This does not establish that every hardware command works; device testing
is still required.

The testing app has a separate Flatpak ID, but installed host drivers, device
groups and permission rules are shared with the regular app. The testing package
allows `org.freedesktop.Flatpak` host execution so its setup helper can run outside
the sandbox. The host helper is included in the app and passed directly to the
system Python interpreter; it does not download and execute remote installer code.

See [TESTING.md](TESTING.md) for the download and install steps. The manual setup
below remains available for the regular 0.4.1 release.

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

## RGB mouse mats

Install a **current OpenRazer release** on the host using the same upstream
instructions above. Older releases may lack newer mats. Connect the mat by
USB, open **Mouse mats**, click **Scan for mats**, then choose the
intended mat if several are connected. Read [MOUSE_MATS.md](MOUSE_MATS.md)
for the eight supported models, exact USB IDs and lighting controls.

The mat page uses the existing `org.razer` session-service permission.
No additional udev rule from Periphera is needed for mouse mats; OpenRazer
owns their drivers and permissions. Disable OpenRazer lighting sync before
per-mat lighting changes. Hardware-free previews need no OpenRazer install.

## Flatpak permissions

- `--device=all` exposes hidraw nodes needed by the existing headset backend.
  The USB portal alone does not provide this hidraw access. Host permissions
  still apply. This is broad device visibility; it is not a narrowly isolated
  USB sandbox.
- `--talk-name=org.razer` grants access to the host OpenRazer session service.
- Wayland, fallback X11 and IPC allow the desktop interface to display.
- No home-directory, network, full session-bus or system-bus permission is
  requested. OpenRazer can control other Razer devices, but this adapter
  restricts mouse writes to the two Naga V2 Pro USB IDs. Mouse-mat writes
  require one of the eight listed USB IDs, the selected serial, and a
  daemon object identified as a mouse mat.

To use only the mouse and/or mats with less device exposure:

```sh
flatpak override --user --nodevice=all io.github.AUSSIEbattler96_AI.Periphera
```

This disables direct headset access. To restore the packaged permissions:

```sh
flatpak override --user --reset io.github.AUSSIEbattler96_AI.Periphera
```

