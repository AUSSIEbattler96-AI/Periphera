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

## All OpenRazer peripherals

Install **OpenRazer 3.10.3 or newer** using the instructions for your host
distribution at <https://openrazer.github.io/#download>. Install a newer release
if it introduced your device. Its kernel driver, device permissions and
user-session daemon must all work on the host. A Flatpak cannot install a host
kernel module. Use headers matching the exact kernel you run.

Follow the package's device permission group instructions and fully restart the
desktop session after changing group membership. Arch packages changed from
`plugdev` to `openrazer` in November 2025; SteamOS can ship an older package using
`plugdev`. The daemon's own error message identifies the group it requires.

Periphera communicates with `org.razer` on your **session** bus. It includes its
own D-Bus client; OpenRazer's Python client does not need installing inside the
Flatpak. Run the app and daemon as your normal desktop user.

Open **Home → Scan for devices**. Each device reported by OpenRazer appears
under its type in the sidebar. Select it to read capabilities and controls.
Naga Trinity (`1532:0067`) is included. Connection support follows OpenRazer:
Bluetooth or a dock cannot be configured unless the host driver exposes that
connection. The older Naga V2 Pro adapter is no longer the discovery boundary.

For independent lighting, turn off **Share lighting effects across devices**
on Home and choose **Apply OpenRazer preferences**, then refresh the device.
This is an explicit global preference; per-device Apply actions never change it.

## Steam Deck / SteamOS

Installing the Flatpak in Discover installs the app and runtime, not OpenRazer's
host driver. SteamOS needs its own Neptune kernel headers, not generic Arch
`linux-headers`. For example, the tested package lookup on SteamOS 3.8.16 with
kernel `6.16.12-valve24.5-1-neptune-616-gb2f7cfe85e45` offered
`linux-neptune-616-headers` version `6.16.12.valve24.5-1` and OpenRazer 3.10.3.
Check the packages for your actual SteamOS/kernel version before installing.
Do not switch SteamOS repositories or disable package signature checking to
work around a mismatched package. System updates can remove host additions.

To identify a setup problem in Desktop Mode, open Konsole and run:

```sh
cat /etc/os-release
uname -r
id -nG
openrazer-daemon --foreground --verbose
```

- **command not found**: the host daemon is unavailable; install the host packages.
- **not a member of plugdev**: for the older package above, run
  `sudo gpasswd -a deck plugdev`, then fully restart the Deck. Closing Konsole
  alone does not update the desktop session's supplementary groups.
- **unable to lock on the pidfile**: another daemon instance may already run.
- Driver/module errors need the exact kernel, headers version and DKMS build log;
  reinstalling only the Flatpak cannot fix a missing kernel module.

If foreground startup succeeds, leave Konsole open while testing a device scan.
Hardware-free previews are available from Home without any driver setup.

## Flatpak permissions

- `--device=all` exposes hidraw nodes needed by the existing headset backend.
  The USB portal alone does not provide this hidraw access. Host permissions
  still apply. This is broad device visibility; it is not a narrowly isolated
  USB sandbox.
- `--talk-name=org.razer` grants access to the host OpenRazer session service.
- Wayland, fallback X11 and IPC allow the desktop interface to display.
- No home-directory, network, full session-bus or system-bus permission is
  requested. OpenRazer can control other Razer devices, and Periphera uses the selected device identity and its live
  capabilities to scope writes. It does not grant access to unrelated D-Bus names.

To use only the mouse and/or mats with less device exposure:

```sh
flatpak override --user --nodevice=all io.github.AUSSIEbattler96_AI.Periphera
```

This disables direct headset access. To restore the packaged permissions:

```sh
flatpak override --user --reset io.github.AUSSIEbattler96_AI.Periphera
```
