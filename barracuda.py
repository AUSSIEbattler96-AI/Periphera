#!/usr/bin/env python3
"""Experimental Linux controller for Barracuda X Chroma USB dongle 1532:0574.

Original implementation based on public protocol observations, not Razer code.
See README.md for sources, limitations and the first hardware-validation step.
Python 3.10+; stdlib backend, optional PyQt6 GUI. Linux x86-64 / AArch64 ioctl ABI.
"""
from __future__ import annotations

import argparse
import colorsys
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import struct
import sys
import time
from dataclasses import dataclass
from functools import reduce
from operator import xor

VERSION = "0.1.0-experimental"
VID, PID = 0x1532, 0x0574
PRESETS = {"custom": 0xFF, "game": 7, "music": 8, "movie": 9}
PROPERTIES = {
    0x21: "battery_percent", 0x2A: "charging", 0x13: "eq_preset",
    0x15: "eq_gains", 0x18: "sidetone_enabled", 0x19: "sidetone_level",
    0x2C: "sleep_minutes",
}
EVENTS = {**PROPERTIES, 0x20: "dongle_link", 0x27: "do_not_disturb",
          0x40: "lighting_state", 0x55: "mic_muted"}
MUTABLE = {0x13, 0x15, 0x18, 0x19, 0x2C}


class DeviceError(Exception):
    pass


def checksum(data):
    return reduce(xor, data, 0)


def ioctl_number(direction, number, size):
    return (direction << 30) | (size << 16) | (ord("H") << 8) | number


def parse_descriptor(data):
    """Parse only report layout: global PUSH/POP, pages, widths, local usages.

    Refuse malformed descriptors. Main items retain their actual field ordering;
    merely matching byte lengths is insufficient to permit hardware writes.
    """
    g = {"page": 0, "size": 0, "count": 0, "id": 0}
    stack, usages, reports = [], [], {}
    i = 0
    while i < len(data):
        prefix = data[i]
        i += 1
        if prefix == 0xFE:
            raise DeviceError("Unsupported long HID item; capture descriptor for review.")
        size = (0, 1, 2, 4)[prefix & 3]
        if i + size > len(data):
            raise DeviceError("Truncated HID descriptor.")
        value = int.from_bytes(data[i:i + size], "little")
        i += size
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        if kind == 1:
            field = {0: "page", 7: "size", 8: "id", 9: "count"}.get(tag)
            if field:
                g[field] = value
            elif tag == 10:
                stack.append(g.copy())
            elif tag == 11:
                if not stack:
                    raise DeviceError("Unbalanced HID global stack.")
                g = stack.pop()
        elif kind == 2 and tag == 0:
            usages.append(value)
        elif kind == 0:
            if tag in (8, 9, 11):
                if not 0 < g["size"] <= 64 or not 0 < g["count"] <= 4096:
                    raise DeviceError("Invalid HID field size/count.")
                key = ({8: "input", 9: "output", 11: "feature"}[tag], g["id"])
                reports.setdefault(key, []).append(
                    (g["page"], g["size"], g["count"], tuple(usages)))
            usages = []
    if stack:
        raise DeviceError("Unbalanced HID global stack.")
    return reports


def report_length(fields, report_id):
    return (sum(size * count for _, size, count, _ in fields) + 7) // 8 + bool(report_id)


def capabilities(descriptor):
    r = parse_descriptor(descriptor)
    vendor = all(r.get((direction, 2)) == [(0xFF14, 8, 63, (0,))]
                 for direction in ("input", "output"))
    rgb = (
        r.get(("feature", 0x31)) == [(0x59, 16, 1, (3,)),
                                     (0x59, 32, 5, (4, 5, 6, 7, 8))]
        and r.get(("feature", 0x34)) == [
            (0x59, 8, 2, (3, 0x55)), (0x59, 16, 8, (0x21,)),
            (0x59, 8, 32, (0x51, 0x52, 0x53, 0x54) * 8)]
        and r.get(("feature", 0x36)) == [(0x59, 8, 1, (0x71,))]
    )
    return {"vendor": vendor, "rgb": rgb}


def discover():
    result = []
    for item in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        try:
            attrs = dict(line.split("=", 1) for line in
                         (item / "device/uevent").read_text().splitlines() if "=" in line)
            bus, vendor, product = [int(x, 16) for x in attrs.get("HID_ID", "").split(":")]
            if (bus, vendor, product) != (3, VID, PID):
                continue
            descriptor = (item / "device/report_descriptor").read_bytes()
            result.append({"path": str(Path("/dev") / item.name),
                           "name": attrs.get("HID_NAME", "Barracuda X Chroma"),
                           "descriptor": descriptor})
        except (OSError, ValueError):
            continue
    return result


def validate_value(prop, payload, writing=False):
    if prop == 0x15:
        if len(payload) != 10:
            raise DeviceError("Expected ten EQ gains.")
        gains = struct.unpack("10b", payload)
        # Deliberate first-release guardrail, not a claim about firmware limits.
        if writing and any(abs(x) > 6 for x in gains):
            raise DeviceError("This build limits custom EQ gains to -6 through +6.")
        return
    if len(payload) != 1:
        raise DeviceError("Expected a one-byte setting.")
    value = payload[0]
    valid = True
    if prop in (0x2A, 0x18, 0x20, 0x27, 0x55):
        valid = value in (0, 1)
    elif prop == 0x21:
        valid = value <= 100
    elif prop == 0x13:
        valid = value in PRESETS.values()
    elif prop == 0x19:
        valid = value <= 15
    elif prop == 0x2C:
        valid = value in ((0, 15, 30) if writing else (0, 5, 15, 30, 45, 60))
    elif prop == 0x40:
        valid = value in (0, 12)
    if not valid:
        raise DeviceError(f"Unexpected value {value} for property 0x{prop:02x}.")


def request_report(prop, payload=None):
    if prop not in PROPERTIES:
        raise DeviceError("Unsupported property: refusing to probe unknown commands.")
    setting = payload is not None
    if setting:
        if prop not in MUTABLE:
            raise DeviceError("This property is read-only.")
        validate_value(prop, payload, writing=True)
    data = bytearray(64)
    data[0], data[2], data[9] = 2, 0x60, 0x80
    # LEN=4+payload length is inferred from the published GET/reply lengths.
    # It needs real-device validation; all SET operations require readback.
    data[6] = 4 + (len(payload) if setting else 0)
    data[10] = prop | (0x80 if setting else 0)
    if setting:
        data[12] = len(payload)
        data[13:13 + len(payload)] = payload
    data[62] = checksum(data[:62])
    return bytes(data)


@dataclass(frozen=True)
class Message:
    kind: str
    prop: int
    payload: bytes
    checksum_style: str


def parse_message(data):
    if len(data) != 64 or data[0] != 2 or data[2] != 0x60 or data[63] != 0:
        return None
    if data[4:6] != b"\0\0" or data[7:10] != b"\0\x80\x80":
        return None
    n, prop = data[12], data[10]
    if data[6] != 4 + n or n not in (1, 10) or prop not in EVENTS:
        return None
    if any(data[13 + n:62]):
        return None
    if data[1] == 0x0A and data[11] == 2:
        if n != 1 or checksum(data[1:62]) != data[62]:
            return None
        kind, style = "event", "without_report_id"
    elif data[1] == 2 and data[11] == 1 and prop in PROPERTIES:
        # The source does not give reply CRC coverage. Accept either documented
        # checksum coverage (host requests vs events), report which matched.
        if checksum(data[1:62]) == data[62]:
            style = "without_report_id"
        elif checksum(data[:62]) == data[62]:
            style = "with_report_id"
        else:
            return None
        kind = "reply"
    else:
        return None
    try:
        validate_value(prop, data[13:13 + n])
    except DeviceError:
        return None
    return Message(kind, prop, bytes(data[13:13 + n]), style)


def decode_value(prop, data):
    if prop == 0x15:
        return list(struct.unpack("10b", data))
    if prop == 0x13:
        return next(name for name, value in PRESETS.items() if value == data[0])
    if prop in (0x2A, 0x18, 0x20, 0x27, 0x55):
        return bool(data[0])
    return data[0]


def lamp_report(colors, brightness=100):
    if len(colors) != 6 or not 0 <= brightness <= 100:
        raise DeviceError("Expected six RGB colors and brightness 0..100.")
    data = bytearray(51)
    data[:3] = bytes((0x34, 6, 1))
    for i, color in enumerate(colors):
        if len(color) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in color):
            raise DeviceError("Each color must contain three integers in 0..255.")
        struct.pack_into("<H", data, 3 + 2 * i, i)
        data[19 + 4 * i:23 + 4 * i] = bytes((*color, round(brightness * 255 / 100)))
    return bytes(data)


def color_value(text):
    text = text.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        raise ValueError("Use a six-digit RGB color, for example 00FF80.")
    return tuple(bytes.fromhex(text))


class Controller:
    def __init__(self, path=None, passive=False):
        matches = discover()
        if path:
            matches = [x for x in matches if x["path"] == path]
        if not matches:
            raise DeviceError("Dongle 1532:0574 not found. Use the 2.4 GHz USB dongle, not Bluetooth.")
        if len(matches) != 1:
            raise DeviceError("Multiple matching HID interfaces; use --device /dev/hidrawN after diagnose.")
        self.path = matches[0]["path"]
        self.fd = None
        self.passive = passive
        self.link = None
        self.observed = {}
        self.reply_checksums = set()
        self.interval, self.last_frame, self.rgb_ready = 0.02, 0.0, False
        try:
            mode = os.O_RDONLY if passive else os.O_RDWR
            self.fd = os.open(self.path, mode | os.O_NONBLOCK | os.O_CLOEXEC)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            info = bytearray(8)
            fcntl.ioctl(self.fd, ioctl_number(2, 3, 8), info, True)
            if struct.unpack("<IHH", info) != (3, VID, PID):
                raise DeviceError("Opened node no longer identifies the supported USB dongle.")
            length = bytearray(4)
            fcntl.ioctl(self.fd, ioctl_number(2, 1, 4), length, True)
            count = struct.unpack("<I", length)[0]
            if not 0 < count <= 4096:
                raise DeviceError("Invalid report descriptor length.")
            descriptor = bytearray(4100)
            descriptor[:4] = length
            fcntl.ioctl(self.fd, ioctl_number(2, 2, 4100), descriptor, True)
            self.caps = capabilities(bytes(descriptor[4:4 + count]))
        except PermissionError:
            self.close()
            raise DeviceError("No HID permission. Install the supplied udev rule, replug the dongle, then run without sudo.")
        except BlockingIOError:
            self.close()
            raise DeviceError("Another copy of this controller already has the headset open.")
        except Exception:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _require(self, capability, writing=False):
        if not self.caps.get(capability):
            raise DeviceError(f"Unrecognised {capability} report layout; run diagnose and stop here.")
        if writing and self.passive:
            raise DeviceError("Cannot write from a passive connection.")

    def _read(self, timeout):
        if not select.select([self.fd], [], [], max(0, timeout))[0]:
            return None
        try:
            data = os.read(self.fd, 4096)
        except BlockingIOError:
            return None
        if not data:
            raise DeviceError("USB device disconnected.")
        msg = parse_message(data)
        if msg:
            if msg.prop == 0x20:
                self.link = bool(msg.payload[0])
                self.observed.clear()
            if self.link is not False:
                self.observed[msg.prop] = (time.monotonic(), msg.payload)
        return data

    def _drain(self):
        for _ in range(256):
            if self._read(0) is None:
                return
        raise DeviceError("HID traffic did not settle; close other headset control apps.")

    def _output(self, report):
        self._require("vendor", writing=True)
        if os.write(self.fd, report) != len(report):
            raise DeviceError("Short USB output write.")

    def get(self, prop, timeout=1.2):
        report = request_report(prop)
        self._require("vendor", writing=True)
        self._drain()
        if self.link is False:
            raise DeviceError("Headset is unavailable through the dongle (off or using Bluetooth).")
        self._output(report)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            data = self._read(end - time.monotonic())
            if data is None:
                continue
            if self.link is False:
                raise DeviceError("Headset lost its dongle connection.")
            msg = parse_message(data)
            if msg and msg.kind == "reply" and msg.prop == prop:
                self.reply_checksums.add(msg.checksum_style)
                return msg.payload
        raise DeviceError(f"No valid reply for {PROPERTIES[prop]}. No setting was sent by this GET. "
                          "Check 2.4 GHz mode, close competing controllers, or collect a passive watch.")

    def set(self, prop, payload):
        report = request_report(prop, payload)
        before = self.get(prop)  # Refuse a SET unless that property's GET works.
        if before == payload:
            return {"result": "already_set", "value": decode_value(prop, payload)}
        self._output(report)
        # No blind retries of writes; GET retries only for firmware settling.
        time.sleep(0.08)
        try:
            after = self.get(prop)
            if after != payload:
                time.sleep(0.15)
                after = self.get(prop)
        except DeviceError as exc:
            raise DeviceError(f"A setting write was sent; its result is UNKNOWN. {exc}") from exc
        if after != payload:
            raise DeviceError(f"Setting write was not confirmed. Before={decode_value(prop, before)!r}, "
                              f"requested={decode_value(prop, payload)!r}, readback={decode_value(prop, after)!r}.")
        return {"result": "readback_matched", "value": decode_value(prop, after)}

    def set_curve(self, gains):
        if len(gains) != 10 or any(type(x) is not int or abs(x) > 6 for x in gains):
            raise DeviceError("Enter ten integer EQ gains, each from -6 to +6.")
        payload = struct.pack("10b", *gains)
        self.get(0x15)  # Preflight before potentially switching the preset.
        self.set(0x13, bytes((PRESETS["custom"],)))
        try:
            return self.set(0x15, payload)
        except DeviceError as exc:
            raise DeviceError(f"Custom preset was selected, but the curve operation failed: {exc}") from exc

    def status(self):
        values, errors = {}, {}
        for prop, name in PROPERTIES.items():
            try:
                values[name] = decode_value(prop, self.get(prop))
            except DeviceError as exc:
                errors[name] = str(exc)
        if self.link is False:
            values.clear()
        return {"device": self.path, "values": values, "errors": errors,
                "link_event": self.link,
                "reply_checksum_styles": sorted(self.reply_checksums)}

    def _feature(self, data, get=False):
        self._require("rgb", writing=not get)
        buffer = bytearray(data)
        result = fcntl.ioctl(self.fd, ioctl_number(3, 7 if get else 6, len(buffer)), buffer, True)
        if result != len(buffer):
            raise DeviceError("Short HID feature transfer.")
        return bytes(buffer)

    def rgb_attributes(self):
        data = self._feature(bytes((0x31,)) + bytes(22), get=True)
        rid, count, width, height, depth, kind, interval = struct.unpack("<BHIIIII", data)
        if rid != 0x31 or count != 6 or kind != 11 or not 1 <= interval <= 1_000_000:
            raise DeviceError("LampArray attributes differ from the documented six-zone headset.")
        self.interval = max(0.02, interval / 1_000_000)
        self.rgb_ready = True
        return {"lamps": count, "kind": kind, "minimum_interval_us": interval}

    def _rgb_gap(self):
        time.sleep(max(0, self.last_frame + self.interval - time.monotonic()))

    def rgb(self, colors, brightness=100):
        report = lamp_report(colors, brightness)  # Validate before any SET_REPORT.
        if not self.rgb_ready:
            self.rgb_attributes()
        self._rgb_gap()
        self._feature(bytes((0x36, 0)))
        self._feature(report)
        self.last_frame = time.monotonic()

    def release_rgb(self):
        if not self.rgb_ready:
            self.rgb_attributes()
        self._rgb_gap()
        self._feature(bytes((0x36, 1)))
        self.last_frame = time.monotonic()


def diagnose():
    devices = []
    for item in discover():
        d = item["descriptor"]
        row = {"path": item["path"], "name": item["name"],
               "usb_id": "1532:0574", "descriptor_bytes": len(d),
               "descriptor_sha256": hashlib.sha256(d).hexdigest(),
               "readable": os.access(item["path"], os.R_OK),
               "writable": os.access(item["path"], os.W_OK)}
        try:
            row["capabilities"] = capabilities(d)
            row["report_lengths"] = {f"{kind}:0x{rid:02x}": report_length(fields, rid)
                                     for (kind, rid), fields in parse_descriptor(d).items()}
        except DeviceError as exc:
            row["descriptor_error"] = str(exc)
        devices.append(row)
    return {"version": VERSION, "scan": "sysfs only; no headset commands",
            "devices": devices,
            "hint": "Use the 2.4 GHz dongle. If empty, also send lsusb -d 1532:."}


def watch(controller, seconds):
    controller._require("vendor")
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        raw = controller._read(min(0.5, end - time.monotonic()))
        if raw is None or raw[0] != 2:
            continue
        msg = parse_message(raw)
        # Known vendor interface only; no audio, keyboard or serial-number logging.
        out = {"received": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "report": raw.hex(" ")}
        if msg:
            out.update(property=EVENTS[msg.prop], value=decode_value(msg.prop, msg.payload))
        print(json.dumps(out), flush=True)


def effect(controller, name, color, brightness, duration, stop=None):
    if name not in ("breathe", "spectrum", "wheel"):
        raise DeviceError("Unknown effect name.")
    lamp_report([color] * 6, brightness)
    start = time.monotonic()
    try:
        while time.monotonic() - start < duration:
            if stop is not None and stop.is_set():
                break
            t = time.monotonic() - start
            if name == "breathe":
                amount = (1 - math.cos(t * math.pi / 2)) / 2
                colors = [color] * 6
                level = round(brightness * amount)
            else:
                colors = [tuple(round(x * 255) for x in colorsys.hsv_to_rgb(
                    (t / 8 + (i / 6 if name == "wheel" else 0)) % 1, 1, 1))
                          for i in range(6)]
                level = brightness
            controller.rgb(colors, level)
            time.sleep(max(0.04, controller.interval))
    finally:
        controller.release_rgb()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--device", help="Explicit matching /dev/hidrawN if more than one")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("diagnose", help="Read sysfs only; no USB commands or changes")
    sub.add_parser("status", help="Query documented properties; no setting changes")
    sub.add_parser("gui", help="Open the Qt desktop controls (requires python-pyqt6)")
    p = sub.add_parser("watch", help="Passive input reports only; press headset buttons to generate events")
    p.add_argument("--seconds", type=int, default=30, choices=range(1, 301), metavar="1..300")
    p = sub.add_parser("preset")
    p.add_argument("name", choices=PRESETS)
    p = sub.add_parser("eq", help="Ten integer gains low to high, -6..+6 (tool limit)")
    p.add_argument("gains", nargs=10, type=int)
    p = sub.add_parser("sidetone", help="Set off, on, or level 0..100 (level alone does not enable)")
    p.add_argument("value")
    p = sub.add_parser("sleep", help="Only captured values in this experimental release")
    p.add_argument("minutes", type=int, choices=(0, 15, 30))
    p = sub.add_parser("rgb", help="One color for all zones, or six separate colors")
    p.add_argument("colors", nargs="+", type=color_value)
    p.add_argument("--brightness", type=int, default=50)
    sub.add_parser("rgb-release", help="Return lighting to firmware control")
    p = sub.add_parser("effect", help="Host-generated effect; releases RGB on completion/Ctrl+C")
    p.add_argument("name", choices=("breathe", "spectrum", "wheel"))
    p.add_argument("--color", type=color_value, default=(0, 255, 128))
    p.add_argument("--brightness", type=int, default=50)
    p.add_argument("--seconds", type=int, default=30, choices=range(1, 3601), metavar="1..3600")
    args = parser.parse_args(argv)
    try:
        if args.command == "diagnose":
            print(json.dumps(diagnose(), indent=2))
            return 0
        if args.command == "gui":
            from barracuda_gui import launch
            launch(args.device)
            return 0
        if args.command in ("rgb", "effect") and not 0 <= args.brightness <= 100:
            raise DeviceError("Brightness must be 0..100.")
        with Controller(args.device, passive=args.command == "watch") as c:
            result = None
            if args.command == "status":
                result = c.status()
            elif args.command == "watch":
                watch(c, args.seconds)
            elif args.command == "preset":
                result = c.set(0x13, bytes((PRESETS[args.name],)))
            elif args.command == "eq":
                result = c.set_curve(args.gains)
            elif args.command == "sleep":
                result = c.set(0x2C, bytes((args.minutes,)))
            elif args.command == "sidetone":
                if args.value in ("off", "on"):
                    result = c.set(0x18, bytes((args.value == "on",)))
                else:
                    value = int(args.value)
                    if not 0 <= value <= 100:
                        raise DeviceError("Sidetone level must be 0..100.")
                    result = c.set(0x19, bytes((round(value * 15 / 100),)))
            elif args.command == "rgb":
                colors = args.colors * 6 if len(args.colors) == 1 else args.colors
                c.rgb(colors, args.brightness)
                result = {"result": "RGB reports sent; visually confirm the headset", "colors": colors}
            elif args.command == "rgb-release":
                c.release_rgb()
                result = {"result": "Firmware lighting control requested; visually confirm"}
            elif args.command == "effect":
                effect(c, args.name, args.color, args.brightness, args.seconds)
            if result is not None:
                print(json.dumps(result, indent=2))
                if args.command == "status" and result["errors"]:
                    return 1
        return 0
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except (DeviceError, OSError, ValueError, ImportError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
