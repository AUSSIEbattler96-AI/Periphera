"""Razer RGB mouse mats through the host OpenRazer session service.

The registry follows upstream mouse_mat.py. Live introspection determines
available effects; matrix dimensions always come from the selected daemon
device. OpenRazer readback may be cached and is not hardware verification.
"""
import math
import re

from naga import (QtTransport, MouseError as MouseMatError, parse_methods,
                  checked_int, ROOT, MISC, CHROMA, BRIGHTNESS)

# Dimensions are for the no-device preview only. In particular the Firefly
# V2 Pro's driver has 17 matrix slots, not its advertised 15 lighting zones.
MODELS = {
    0x0C00: {"name": "Razer Firefly", "columns": 15, "wave": True},
    0x0068: {"name": "Razer Firefly HyperFlux", "columns": 17, "wave": False},
    0x0C04: {"name": "Razer Firefly V2", "columns": 19, "wave": True},
    0x0C08: {"name": "Razer Firefly V2 Pro", "columns": 17, "wave": True},
    0x0C01: {"name": "Razer Goliathus Chroma", "columns": 1, "wave": False},
    0x0C02: {"name": "Razer Goliathus Extended Chroma", "columns": 1, "wave": False},
    0x0C06: {"name": "Razer Goliathus Chroma 3XL", "columns": 1, "wave": False},
    0x0C05: {"name": "Razer Strider Chroma", "columns": 19, "wave": True},
}
EFFECTS = {
    "static": ("Static", "setStatic"),
    "spectrum": ("Spectrum cycle", "setSpectrum"),
    "breathing": ("Breathing · one colour", "setBreathSingle"),
    "breathing_dual": ("Breathing · two colours", "setBreathDual"),
    "breathing_random": ("Breathing · random", "setBreathRandom"),
    "wave": ("Wave", "setWave"),
    "reactive": ("Reactive", "setReactive"),
    "off": ("Off", "setNone"),
}


def rgb_value(value):
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError("RGB needs three values")
    return [checked_int(v, 0, 255, "RGB") for v in value]


def matrix_dimensions(value):
    if (not isinstance(value, (tuple, list)) or len(value) != 2
            or value[0] != 1 or isinstance(value[0], bool)):
        raise MouseMatError("This mouse-mat editor requires a one-row LED matrix")
    checked_int(value[1], 1, 64, "Matrix columns")
    return list(value)


def brightness_value(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= 100):
        raise MouseMatError("OpenRazer returned an invalid brightness reading")
    return value


class MouseMatController:
    def __init__(self, serial=None, transport_factory=QtTransport):
        self.serial, self.transport_factory = serial, transport_factory
        self.transport, self.path, self.device = None, None, None
        self.methods = {}

    def __enter__(self):
        self.transport = self.transport_factory()
        return self

    def __exit__(self, *_):
        self.transport.close()

    def root(self, interface, method):
        return self.transport.call(ROOT, interface, method)

    def discover(self):
        try:
            serials = self.root("razer.devices", "getDevices")
            version = self.root("razer.daemon", "version")
        except MouseMatError as exc:
            raise MouseMatError("OpenRazer is unavailable. Install the current OpenRazer release on "
                                "the host and start its desktop-session daemon. " + str(exc)) from exc
        devices, errors = [], {}
        for serial in serials:
            if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9_]+", serial):
                continue
            path = ROOT + "/device/" + serial
            try:
                vid, pid = self.transport.call(path, MISC, "getVidPid")
                if vid != 0x1532 or pid not in MODELS:
                    continue
                # HyperFlux shares its USB ID with its mouse. Verify the daemon
                # object is a mat, rather than accepting the product ID alone.
                if self.transport.call(path, MISC, "getDeviceType") != "mousemat":
                    continue
                devices.append({"serial": serial, "name": MODELS[pid]["name"],
                                "usb_id": f"{vid:04x}:{pid:04x}", "connection": "USB"})
            except (MouseMatError, ValueError, TypeError) as exc:
                errors[serial] = str(exc)
        return {"daemon_version": str(version), "devices": devices, "discovery_errors": errors}

    def select(self):
        found = self.discover()
        if self.serial is None and len(found["devices"]) == 1:
            self.serial = found["devices"][0]["serial"]
        self.device = next((d for d in found["devices"] if d["serial"] == self.serial), None)
        if self.device is None:
            raise MouseMatError("No selected Razer RGB mouse mat is available. Connect it by USB, "
                                "scan again, and select a mat if more than one is connected.")
        self.path = ROOT + "/device/" + self.serial
        xml = self.transport.call(self.path, "org.freedesktop.DBus.Introspectable", "Introspect")
        self.methods = parse_methods(xml)
        return found

    def has(self, interface, *methods):
        return all((interface, method) in self.methods for method in methods)

    def call(self, interface, method, *values):
        if not self.has(interface, method):
            raise MouseMatError(f"The installed OpenRazer driver does not expose {method} for this mat")
        return self.transport.call(self.path, interface, method, self.methods[interface, method], values)

    def capabilities(self):
        return {"brightness": self.has(BRIGHTNESS, "getBrightness", "setBrightness"),
                "effects": [key for key, (_, method) in EFFECTS.items() if self.has(CHROMA, method)],
                "custom": (self.has(MISC, "getMatrixDimensions") and self.has(CHROMA, "setCustom")
                           and self.methods.get((CHROMA, "setKeyRow")) == ("ay",)),
                "trigger_reactive": self.has(MISC, "triggerReactive")}

    def status(self):
        found = self.select()
        values, errors = {}, {}
        for key, interface, method in (("brightness", BRIGHTNESS, "getBrightness"),
                                       ("matrix_dimensions", MISC, "getMatrixDimensions")):
            if self.has(interface, method):
                try:
                    value = self.call(interface, method)
                    values[key] = brightness_value(value) if key == "brightness" else matrix_dimensions(value)
                except (MouseMatError, ValueError) as exc:
                    errors[key] = str(exc)
        try:
            values["sync_effects"] = self.sync_enabled()
        except MouseMatError as exc:
            errors["sync_effects"] = str(exc)
        caps = self.capabilities()
        caps["custom"] = caps["custom"] and "matrix_dimensions" in values
        return {**found, "device": self.device, "values": values, "errors": errors,
                "capabilities": caps, "hardware_tested": False}

    def sync_enabled(self):
        value = self.root("razer.devices", "getSyncEffects")
        if not isinstance(value, bool):
            raise MouseMatError("Cannot determine OpenRazer's lighting synchronization state")
        return value

    def check_lighting_sync(self):
        if self.sync_enabled():
            raise MouseMatError("OpenRazer lighting sync is enabled. Turn it off in your OpenRazer "
                                "settings before changing this mat; sync can affect other devices.")

    def set_brightness(self, value):
        checked_int(value, 0, 100, "Brightness")
        self.select()  # Revalidate USB ID, device type and selected serial before every write.
        if not self.capabilities()["brightness"]:
            raise MouseMatError("Brightness is unavailable in this OpenRazer driver")
        self.check_lighting_sync()
        before = brightness_value(self.call(BRIGHTNESS, "getBrightness"))
        if before == value:
            return {"result": "already_set", "value": before}
        self.call(BRIGHTNESS, "setBrightness", float(value))
        after = brightness_value(self.call(BRIGHTNESS, "getBrightness"))
        if abs(after - value) > 1:
            raise MouseMatError(f"Brightness was sent, but daemon readback was {after!r}; requested {value}")
        return {"result": "daemon_readback_matched", "value": after}

    def set_effect(self, effect, color=None, secondary=None, direction=1, speed=2):
        if effect not in EFFECTS:
            raise ValueError("Unknown mouse-mat effect")
        args = []
        if effect in ("static", "breathing", "breathing_dual", "reactive"):
            args = rgb_value(color)
        if effect == "breathing_dual":
            args += rgb_value(secondary)
        elif effect == "wave":
            args = [checked_int(direction, 1, 2, "Wave direction")]
        elif effect == "reactive":
            args += [checked_int(speed, 1, 4, "Reactive speed")]
        self.select()
        if effect not in self.capabilities()["effects"]:
            raise MouseMatError(f"{EFFECTS[effect][0]} is unavailable for this mat and OpenRazer version")
        self.check_lighting_sync()
        self.call(CHROMA, EFFECTS[effect][1], *args)
        return {"result": "sent_to_openrazer", "effect": effect,
                "note": "Confirm the lighting visually; no independent effect readback is available."}

    def set_custom(self, colors):
        if not isinstance(colors, (list, tuple)) or not 1 <= len(colors) <= 64:
            raise ValueError("Supply one RGB colour per driver matrix slot")
        colors = [rgb_value(color) for color in colors]
        self.select()
        if not self.capabilities()["custom"]:
            raise MouseMatError("Custom matrix colours are unavailable for this OpenRazer driver")
        dims = matrix_dimensions(self.call(MISC, "getMatrixDimensions"))
        if len(colors) != dims[1]:
            raise ValueError(f"The selected mat needs {dims[1]} RGB colours, not {len(colors)}")
        self.check_lighting_sync()
        # Same row/start/end framing and upload-before-activation order as
        # OpenRazer's public client Frame.row_binary() and RazerAdvancedFX._draw().
        payload = bytes([0, 0, dims[1] - 1] + [component for color in colors for component in color])
        self.call(CHROMA, "setKeyRow", payload)
        self.call(CHROMA, "setCustom")
        return {"result": "sent_to_openrazer", "matrix_dimensions": dims,
                "note": "Custom colours sent; confirm their physical placement on the mat."}

    def trigger_reactive(self):
        self.select()
        if not self.has(MISC, "triggerReactive"):
            raise MouseMatError("Reactive triggering is unavailable for this OpenRazer driver")
        self.check_lighting_sync()
        self.call(MISC, "triggerReactive")
        return {"result": "sent_to_openrazer", "note": "Reactive pulse triggered on the selected mat."}
