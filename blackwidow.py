"""BlackWidow V4 X and V3 adapter using the host OpenRazer service."""
import json
import re

from naga import QtTransport, MouseError as KeyboardError, ROOT, MISC, CHROMA, BRIGHTNESS, checked_int, parse_methods
from mousemat import rgb_value, brightness_value
from keyboard_macros import decode_macro, host_check, macro_payload, validate_events

CUSTOM = "razer.device.lighting.custom"
MACRO = "razer.device.macro"
MODELS = {0x0293: {"name": "Razer BlackWidow V4 X", "dimensions": [6, 22], "macros": True},
          0x024E: {"name": "Razer BlackWidow V3", "dimensions": [6, 22], "macros": False}}
MACRO_KEYS = tuple(f"M{i}" for i in range(1, 7))
# Exact upstream input signatures; never send a command with a mismatched type.
EFFECTS = {
    "static": ("Static", CHROMA, "setStatic", ("y",) * 3),
    "spectrum": ("Spectrum cycle", CHROMA, "setSpectrum", ()),
    "breathing": ("Breathing · one colour", CHROMA, "setBreathSingle", ("y",) * 3),
    "breathing_dual": ("Breathing · two colours", CHROMA, "setBreathDual", ("y",) * 6),
    "breathing_random": ("Breathing · random", CHROMA, "setBreathRandom", ()),
    "wave": ("Wave", CHROMA, "setWave", ("i",)),
    "wheel": ("Wheel", CHROMA, "setWheel", ("i",)),
    "reactive": ("Reactive", CHROMA, "setReactive", ("y",) * 4),
    "starlight": ("Starlight · one colour", CHROMA, "setStarlightSingle", ("y",) * 4),
    "starlight_dual": ("Starlight · two colours", CHROMA, "setStarlightDual", ("y",) * 7),
    "starlight_random": ("Starlight · random", CHROMA, "setStarlightRandom", ("y",)),
    "ripple": ("Ripple · one colour", CUSTOM, "setRipple", ("y", "y", "y", "d")),
    "ripple_random": ("Ripple · random", CUSTOM, "setRippleRandomColour", ("d",)),
    "off": ("Off", CHROMA, "setNone", ()),
}


def matrix_dimensions(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise KeyboardError("OpenRazer returned an invalid keyboard layout")
    return [checked_int(value[0], 1, 16, "Matrix rows"), checked_int(value[1], 1, 64, "Matrix columns")]


class BlackWidowController:
    def __init__(self, serial=None, transport_factory=QtTransport, macro_checker=host_check):
        self.serial, self.transport_factory, self.macro_checker = serial, transport_factory, macro_checker
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
        except KeyboardError as exc:
            raise KeyboardError("OpenRazer is unavailable. Open Hardware setup to install or start it. " + str(exc)) from exc
        devices, errors = [], {}
        for serial in serials:
            if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9_]+", serial):
                continue
            path = ROOT + "/device/" + serial
            try:
                vid, pid = self.transport.call(path, MISC, "getVidPid")
                if vid != 0x1532 or pid not in MODELS or self.transport.call(path, MISC, "getDeviceType") != "keyboard":
                    continue
                devices.append({"serial": serial, "name": MODELS[pid]["name"],
                                "usb_id": f"{vid:04x}:{pid:04x}", "pid": pid, "connection": "USB"})
            except (KeyboardError, TypeError, ValueError) as exc:
                errors[serial] = str(exc)
        return {"daemon_version": str(version), "devices": devices, "discovery_errors": errors}

    def select(self):
        found = self.discover()
        if self.serial is None and len(found["devices"]) == 1:
            self.serial = found["devices"][0]["serial"]
        self.device = next((d for d in found["devices"] if d["serial"] == self.serial), None)
        if self.device is None:
            raise KeyboardError("Select a connected BlackWidow V4 X or BlackWidow V3, then scan again.")
        self.path = ROOT + "/device/" + self.serial
        self.methods = parse_methods(self.transport.call(self.path, "org.freedesktop.DBus.Introspectable", "Introspect"))
        return found

    def has(self, interface, method, signature=()):
        return self.methods.get((interface, method)) == signature

    def call(self, interface, method, *values):
        if (interface, method) not in self.methods:
            raise KeyboardError(f"OpenRazer does not expose {method} for this keyboard")
        return self.transport.call(self.path, interface, method, self.methods[interface, method], values)

    def capabilities(self):
        return {
            "brightness": self.has(BRIGHTNESS, "getBrightness") and self.has(BRIGHTNESS, "setBrightness", ("d",)),
            "effects": [key for key, (_, interface, method, signature) in EFFECTS.items()
                        if self.has(interface, method, signature)],
            "custom": self.has(MISC, "getMatrixDimensions") and self.has(CHROMA, "setCustom") and self.has(CHROMA, "setKeyRow", ("ay",)),
            "macros": bool(self.device and MODELS[self.device["pid"]]["macros"] and
                           self.has(MACRO, "getMacros") and self.has(MACRO, "addMacro", ("s", "s")) and
                           self.has(MACRO, "deleteMacro", ("s",))),
        }

    def status(self):
        found = self.select()
        values, errors = {}, {}
        for key, interface, method, validate in (
            ("brightness", BRIGHTNESS, "getBrightness", brightness_value),
            ("matrix_dimensions", MISC, "getMatrixDimensions", matrix_dimensions),
        ):
            if self.has(interface, method):
                try:
                    values[key] = validate(self.call(interface, method))
                except (KeyboardError, ValueError) as exc:
                    errors[key] = str(exc)
        try:
            values["sync_effects"] = self.sync_enabled()
        except KeyboardError as exc:
            errors["sync_effects"] = str(exc)
        caps = self.capabilities()
        caps["custom"] = caps["custom"] and "matrix_dimensions" in values
        if caps["macros"]:
            try:
                values["macros"] = self.get_macros()
                values["macro_events"] = {k: decode_macro(v) for k, v in values["macros"].items() if k in MACRO_KEYS}
            except (KeyboardError, ValueError) as exc:
                errors["macros"] = str(exc)
                caps["macros"] = False
        return {**found, "device": self.device, "values": values, "capabilities": caps,
                "errors": errors, "hardware_tested": False}

    def sync_enabled(self):
        value = self.root("razer.devices", "getSyncEffects")
        if type(value) is not bool:
            raise KeyboardError("Cannot determine OpenRazer lighting synchronization state")
        return value

    def check_lighting_sync(self):
        if self.sync_enabled():
            raise KeyboardError("Turn off OpenRazer lighting synchronization before editing this keyboard's lighting.")

    def set_brightness(self, value):
        value = checked_int(value, 0, 100, "Brightness")
        self.select()
        if not self.capabilities()["brightness"]:
            raise KeyboardError("Brightness is unavailable for this keyboard")
        self.check_lighting_sync()
        before = brightness_value(self.call(BRIGHTNESS, "getBrightness"))
        if before == value:
            return {"result": "already_set", "value": value}
        self.call(BRIGHTNESS, "setBrightness", float(value))
        after = brightness_value(self.call(BRIGHTNESS, "getBrightness"))
        if abs(value - after) > 1:
            raise KeyboardError(f"Brightness was sent but OpenRazer readback was {after}; requested {value}")
        return {"result": "daemon_readback_matched", "value": after}

    def set_effect(self, effect, color=None, secondary=None, direction=1, speed=2):
        if effect not in EFFECTS:
            raise ValueError("Unknown keyboard effect")
        args = []
        if effect in ("static", "breathing", "breathing_dual", "reactive", "starlight", "starlight_dual", "ripple"):
            args = rgb_value(color)
        if effect in ("breathing_dual", "starlight_dual"):
            args += rgb_value(secondary)
        if effect in ("wave", "wheel"):
            args = [checked_int(direction, 1, 2, "Direction")]
        elif effect in ("reactive", "starlight", "starlight_dual", "starlight_random"):
            args.append(checked_int(speed, 1, 4 if effect == "reactive" else 3, "Effect speed"))
        elif effect in ("ripple", "ripple_random"):
            args.append(0.05)  # OpenRazer client's documented refresh interval.
        self.select()
        if effect not in self.capabilities()["effects"]:
            raise KeyboardError("This effect is unavailable in the installed OpenRazer driver")
        self.check_lighting_sync()
        _, interface, method, _ = EFFECTS[effect]
        self.call(interface, method, *args)
        return {"result": "sent_to_openrazer", "effect": effect}

    def set_custom(self, colors):
        if not isinstance(colors, list) or not 1 <= len(colors) <= 16:
            raise ValueError("Supply the keyboard's complete colour matrix")
        frame = []
        for row in colors:
            if not isinstance(row, list) or not 1 <= len(row) <= 64:
                raise ValueError("Every matrix row needs one RGB value per column")
            frame.append([rgb_value(color) for color in row])
        self.select()
        if not self.capabilities()["custom"]:
            raise KeyboardError("Individual key colours are unavailable in this driver")
        rows, columns = matrix_dimensions(self.call(MISC, "getMatrixDimensions"))
        if len(frame) != rows or any(len(row) != columns for row in frame):
            raise ValueError(f"The selected keyboard needs a {rows} × {columns} colour matrix; scan again")
        self.check_lighting_sync()
        payload = b"".join(bytes([index, 0, columns - 1] + [v for color in row for v in color])
                           for index, row in enumerate(frame))
        self.call(CHROMA, "setKeyRow", payload)
        self.call(CHROMA, "setCustom")
        return {"result": "sent_to_openrazer", "matrix_dimensions": [rows, columns]}

    def get_macros(self):
        value = json.loads(self.call(MACRO, "getMacros"))
        if not isinstance(value, dict) or any(not isinstance(v, list) for v in value.values()):
            raise KeyboardError("OpenRazer returned invalid macro data")
        return value

    def macro_target(self, key):
        if key not in MACRO_KEYS:
            raise ValueError("Choose one of the V4 X's six macro keys, M1–M6")
        self.select()
        if not self.capabilities()["macros"]:
            raise KeyboardError("Macro editing is available only for the BlackWidow V4 X with supported OpenRazer endpoints")

    def set_macro(self, key, events):
        events = validate_events(events)
        self.macro_target(key)
        self.get_macros()  # A successful preflight read is required.
        self.macro_checker()
        self.call(MACRO, "addMacro", key, json.dumps(macro_payload(events)))
        after = self.get_macros()
        if decode_macro(after.get(key)) != events:
            raise KeyboardError("Macro was sent, but OpenRazer readback did not match")
        return {"result": "daemon_readback_matched", "key": key, "events": events}

    def delete_macro(self, key):
        self.macro_target(key)
        before = self.get_macros()
        if key not in before:
            return {"result": "already_removed", "key": key}
        self.call(MACRO, "deleteMacro", key)
        if key in self.get_macros():
            raise KeyboardError("Macro deletion was sent, but OpenRazer still reports the binding")
        return {"result": "daemon_readback_matched", "key": key}
