#!/usr/bin/env bash
set -euo pipefail
if (( EUID == 0 )); then
    echo 'Run this script as your normal desktop user. It uses sudo only for the udev rule.' >&2
    exit 1
fi
barracuda_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
sudo install -m 0644 -- "$barracuda_dir/70-barracuda-x-chroma.rules" /etc/udev/rules.d/70-barracuda-x-chroma.rules
sudo udevadm control --reload-rules
echo 'Unplug and reconnect the USB dongle, then open Diagnostics in Periphera.'
echo 'For a native source install you can also run: python3 barracuda.py diagnose'
echo 'The controller runs as your normal user; no reboot is required.'
