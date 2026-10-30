"""Device-independent OpenRazer client. The host daemon owns device support.

Only documented public controls are writable, and only when live introspection
advertises their wire signature. Scans and status reads never change settings.
Endpoint metadata is recorded in openrazer_catalog.json with upstream provenance.
"""
import json
import math
from pathlib import Path
import re

from naga import MouseError, ROOT, MISC, parse_methods

TYPES = {"mouse": "Mice", "keyboard": "Keyboards", "keypad": "Keypads",
         "headset": "Headsets", "mousemat": "Mouse mats", "accessory": "Accessories",
         "core": "PC cases & eGPUs", "monitor": "Monitors", "other": "Other peripherals"}
CATALOG = json.loads(Path(__file__).with_name("openrazer_catalog.json").read_text())
ENDPOINTS = {(e["interface"], e["method"]): e for e in CATALOG["endpoints"]}
INTROSPECT = "org.freedesktop.DBus.Introspectable"
CHROMA = "razer.device.lighting.chroma"


def plain_value(value):
    """Keep D-Bus byte arrays JSON-safe without losing their component values."""
    if isinstance(value, (bytes, bytearray)):
        return list(value)
    if isinstance(value, tuple):
        return tuple(plain_value(v) for v in value)
    if isinstance(value, list):
        return [plain_value(v) for v in value]
    if isinstance(value, dict):
        return {k: plain_value(v) for k, v in value.items()}
    return value


class DBusTransport:
    """One blocking session-bus connection, created and closed in its worker.

    Jeepney supports OpenRazer's full signatures, including DPI-stage structs.
    No Python OpenRazer package is needed inside the Flatpak.
    """
    def __init__(self):
        from jeepney.io.blocking import open_dbus_connection
        try:
            self.connection = open_dbus_connection(bus="SESSION")
        except Exception as exc:
            raise MouseError(f"Cannot access your desktop session bus: {exc}") from exc

    def close(self):
        self.connection.close()

    def call(self, path, interface, method, signatures=(), values=()):
        from jeepney import DBusAddress, new_method_call, MessageType, HeaderFields
        try:
            address = DBusAddress(path, bus_name="org.razer", interface=interface)
            reply = self.connection.send_and_get_reply(
                new_method_call(address, method, "".join(signatures), tuple(values)), timeout=3)
            if reply.header.message_type == MessageType.error:
                raise MouseError(f"{method}: {reply.header.fields.get(HeaderFields.error_name)}: {reply.body}")
            return plain_value(reply.body[0] if len(reply.body) == 1 else list(reply.body))
        except MouseError:
            raise
        except Exception as exc:
            raise MouseError(f"{method}: {exc}") from exc


def words(value):
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value).replace("_", " ")
    return value.replace("DPI", "DPI ").replace("LED", "LED ").strip()


def category(interface):
    if ".lighting." in interface:
        return "Lighting"
    if ".power" in interface:
        return "Power"
    if ".macro" in interface or ".led." in interface:
        return "Keys & macros"
    return "Performance"


def control_label(spec):
    name = spec["method"]
    if name.startswith("set"):
        name = name[3:]
    zone = spec["interface"].rsplit(".", 1)[-1]
    prefix = "".join(x.title() for x in zone.split("_"))
    if category(spec["interface"]) == "Lighting" and name.startswith(prefix) and len(name) > len(prefix):
        name = name[len(prefix):]
    labels = {"None": "Off", "BreathMono": "Breathing", "BreathSingle": "Breathing · one colour",
              "BreathDual": "Breathing · two colours", "BreathTriple": "Breathing · three colours",
              "BreathRandom": "Breathing · random", "StarlightSingle": "Starlight · one colour",
              "StarlightDual": "Starlight · two colours", "StarlightRandom": "Starlight · random",
              "RippleRandomColour": "Ripple · random", "DPI": "Sensitivity (DPI)",
              "DPIStages": "DPI stages", "PollRate": "Polling rate", "IdleTime": "Idle timeout",
              "LowBatteryThreshold": "Low battery warning", "Custom": "Colour & intensity"}
    labels.update({"addMacro": "Save macro", "deleteMacro": "Delete macro", "triggerReactive": "Trigger reactive lighting"})
    label = labels.get(name, words(name))
    if category(spec["interface"]) == "Lighting" and any(x in spec["method"] for x in ("Brightness", "Active")) and zone not in ("brightness", "chroma"):
        label = words(zone).title() + " " + label.lower()
    return label


def is_effect(spec):
    return (category(spec["interface"]) == "Lighting" and
            not any(x in spec["method"] for x in ("Brightness", "Active", "LED", "ChannelSize", "ChargeEffect", "ChargeColour")))


def signature_matches(spec, signature):
    if "".join(signature) == spec["signature"]:
        return True
    return spec["method"] == "setPollRate" and tuple(signature) in (("i",), ("q",))


def valid_dimensions(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2 or
            any(type(v) is not int for v in value) or
            not 1 <= value[0] <= 255 or not 1 <= value[1] <= 255 or value[0]*value[1] > 4096):
        raise MouseError("The device returned invalid lighting-matrix dimensions")
    return list(value)


def number(value, low, high, label, integer=True):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or integer and type(value) is not int or not low <= value <= high):
        raise ValueError(f"{label} must be {'an integer' if integer else 'a number'} between {low} and {high}")
    return value


class OpenRazerController:
    def __init__(self, device=None, transport_factory=DBusTransport):
        self.expected = device if isinstance(device, dict) else None
        self.serial = device.get("serial") if isinstance(device, dict) else device
        self.transport_factory = transport_factory
        self.methods = {}
        self.transport = None

    def __enter__(self):
        self.transport = self.transport_factory()
        return self

    def __exit__(self, *_):
        self.transport.close()

    def root(self, method, *args):
        interface = "razer.daemon" if method == "version" else "razer.devices"
        signatures = ("b",) if method in ("syncEffects", "enableTurnOffOnScreensaver") else ()
        return self.transport.call(ROOT, interface, method, signatures, args)

    def identity(self, serial):
        if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9_]+", serial):
            raise MouseError("Invalid device identifier from OpenRazer")
        path = ROOT + "/device/" + serial
        def read(method):
            return self.transport.call(path, MISC, method)
        ids = read("getVidPid")
        if not isinstance(ids, (list, tuple)) or len(ids) != 2 or any(type(x) is not int or not 0 <= x <= 65535 for x in ids):
            raise MouseError("Invalid USB identity from OpenRazer")
        name, kind = str(read("getDeviceName")), str(read("getDeviceType"))
        # OpenRazer currently calls its Raptor monitor an accessory.
        if ids == [0x1532, 0x0F12] or tuple(ids) == (0x1532, 0x0F12):
            kind = "monitor"
        return {"serial": serial, "name": name, "type": kind if kind in TYPES else "other",
                "daemon_type": kind, "usb_id": f"{ids[0]:04x}:{ids[1]:04x}", "source": "openrazer"}

    def discover(self):
        try:
            serials, version = self.root("getDevices"), self.root("version")
        except MouseError as exc:
            raise MouseError("OpenRazer is unavailable on the host. Install its driver and daemon, "
                             "add your user to the device permission group, then restart your desktop session. " + str(exc)) from exc
        if not isinstance(serials, (list, tuple)):
            raise MouseError("OpenRazer returned an invalid device list")
        devices, errors = [], {}
        for serial in dict.fromkeys(s for s in serials if isinstance(s, str)):
            try:
                devices.append(self.identity(serial))
            except (MouseError, ValueError, TypeError) as exc:
                errors[serial] = str(exc)
        sync, screensaver = None, None
        for method in ("getSyncEffects", "getOffOnScreensaver"):
            try:
                value = self.root(method)
                if type(value) is bool:
                    if method == "getSyncEffects": sync = value
                    else: screensaver = value
            except MouseError:
                pass
        return {"devices": devices, "daemon_version": str(version), "errors": errors,
                "sync_effects": sync, "off_on_screensaver": screensaver}

    def select(self):
        if self.serial not in self.root("getDevices"):
            raise MouseError("This device is disconnected. Scan for devices again.")
        self.device = self.identity(self.serial)
        if self.expected and any(self.device[k] != self.expected.get(k) for k in ("serial", "usb_id", "type")):
            raise MouseError("The selected device changed identity. Scan again before applying settings.")
        self.path = ROOT + "/device/" + self.serial
        self.methods = parse_methods(self.transport.call(self.path, INTROSPECT, "Introspect"))

    def call(self, interface, method, *values):
        key = interface, method
        if key not in self.methods:
            raise MouseError(f"This device does not offer {control_label({'interface': interface, 'method': method})}")
        return self.transport.call(self.path, interface, method, self.methods[key], values)

    def controls(self):
        result = []
        for key, sig in self.methods.items():
            spec = ENDPOINTS.get(key)
            if not spec or not signature_matches(spec, sig):
                continue
            if not (spec["method"].startswith("set") or spec["method"] in ("addMacro", "deleteMacro", "triggerReactive")):
                continue
            if spec["method"] == "setKeyRow" or key == (CHROMA, "setCustom"):
                continue  # Handled as a complete matrix frame, not raw packets.
            result.append({**spec, "id": "|".join(key), "label": control_label(spec),
                           "category": "Lighting" if spec["method"] == "triggerReactive" else category(spec["interface"]), "effect": is_effect(spec)})
        return sorted(result, key=lambda x: (x["category"], x["interface"], x["label"]))

    def status(self):
        self.select()
        readings, errors = {}, {}
        matrix_present = False
        if (MISC, "hasMatrix") in self.methods:
            try:
                matrix_present = self.call(MISC, "hasMatrix") is True
            except MouseError:
                pass
        for (interface, method), signature in self.methods.items():
            known = (interface, method) in ENDPOINTS or (interface.startswith("razer.device.lighting.") and method.startswith("get"))
            if signature or not known or not method.startswith(("get", "is", "has", "max", "available")):
                continue
            if method == "getMatrixDimensions" and not matrix_present:
                continue
            key = interface + "|" + method
            try:
                readings[key] = self.call(interface, method)
            except MouseError as exc:
                errors[key] = str(exc)
        dims = None
        if readings.get(MISC + "|hasMatrix") is True:
            try:
                dims = valid_dimensions(readings.get(MISC + "|getMatrixDimensions"))
            except MouseError as exc:
                errors["matrix"] = str(exc)
        matrix = bool(dims and self.methods.get((CHROMA, "setKeyRow")) == ("ay",) and self.methods.get((CHROMA, "setCustom")) == ())
        try:
            sync = self.root("getSyncEffects")
        except MouseError:
            sync = None
        return {"device": self.device, "controls": self.controls(), "readings": readings,
                "matrix_dimensions": dims if matrix else None, "sync_effects": sync, "errors": errors}

    def check_sync(self):
        state = self.root("getSyncEffects")
        if type(state) is not bool:
            raise MouseError("Cannot determine lighting synchronization. No lighting was changed.")
        if state:
            raise MouseError("OpenRazer lighting sync is on. Turn off shared lighting on Home before editing one device.")

    def validate(self, spec, values):
        types = re.findall(r"a\([^)]*\)|a[yiq]|[yqiusbd]", spec["signature"])
        if len(types) != len(values):
            raise ValueError("The control received the wrong number of values")
        for name, token, value in zip(spec["arguments"], types, values):
            if token in ("y", "q", "i", "u", "d"):
                high = {"y": 255, "q": 65535, "i": 2147483647, "u": 4294967295, "d": 1000000}[token]
                number(value, 0, high, words(name), integer=token != "d")
                if "brightness" in name or name == "threshold": number(value, 0, 100, words(name), False)
                if name == "direction": number(value, 1, 2, "Direction")
                if name == "speed": number(value, 1, 4 if "Reactive" in spec["method"] else 3, "Speed")
                if name == "refresh_rate": number(value, 1, 60, "Refresh rate", False)
                if name == "size": number(value, 0, 255, "LED count")
                if name == "channel":
                    count = self.call(spec["interface"], "getNumChannels")
                    number(value, 1, count, "Channel")
            elif token == "b" and type(value) is not bool:
                raise ValueError("This setting needs an on/off value")
            elif token == "s" and (not isinstance(value, str) or not value.strip() or len(value) > 65536):
                raise ValueError("Enter a valid value for " + words(name))
        method = spec["method"]
        if method in ("setDPI", "setDPIStages"):
            maximum = self.call("razer.device.dpi", "maxDPI")
            pairs = [values] if method == "setDPI" else values[1]
            if not isinstance(pairs, (list, tuple)) or not 1 <= len(pairs) <= 5:
                raise ValueError("Use one to five DPI stages")
            discrete = []
            if ("razer.device.dpi", "availableDPI") in self.methods:
                discrete = self.call("razer.device.dpi", "availableDPI")
            for pair in pairs:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValueError("Each DPI stage needs X and Y sensitivity")
                number(pair[0], 1, maximum, "X DPI")
                number(pair[1], 0 if discrete else 1, maximum, "Y DPI")
                if discrete and (pair[0] not in discrete or pair[1] != 0):
                    raise ValueError("Choose an available DPI value; this mouse uses a single sensitivity axis")
            if method == "setDPIStages": number(values[0], 1, len(pairs), "Active stage")
        if method == "setPollRate":
            rates = self.call(MISC, "getSupportedPollRates") if (MISC, "getSupportedPollRates") in self.methods else [125, 500, 1000]
            if values[0] not in rates: raise ValueError("Choose a polling rate supported by this device")
        if method == "setScrollMode" or method == "setChargeEffect": number(values[0], 0, 1, "Mode")
        if method == "setHyperPollingLED": number(values[0], 1, 3, "Indicator mode")
        if method == "setHyperPollingMultiLEDModes":
            for value in values: number(value, 0, 4, "Indicator mode")
        if method in ("setHyperPollingPair", "setHyperPollingUnpair") and not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{4}", values[0]):
            raise ValueError("Enter the four-digit USB product ID of the intended device")
        if spec["signature"] == "ai":
            if not isinstance(values[0], (list, tuple)) or len(values[0]) not in (3, 4): raise ValueError("Choose RGB colour and intensity")
            for v in values[0]: number(v, 0, 255, "Colour component")
        if method == "addMacro":
            sequence = json.loads(values[1])
            if not isinstance(sequence, list) or not 1 <= len(sequence) <= 256: raise ValueError("Add one to 256 macro actions")
            for item in sequence:
                if not isinstance(item, dict) or item.get("type") not in ("MacroKey", "MacroURL", "MacroScript"):
                    raise ValueError("Unknown macro action")
                if item["type"] == "MacroKey":
                    if not re.fullmatch(r"[A-Za-z0-9_+ -]{1,80}", item.get("key_id", "")) or item.get("state") not in ("UP", "DOWN"):
                        raise ValueError("Choose a valid key and press/release action")
                    number(item.get("pre_pause"), 0, 60000000, "Delay")
                elif item["type"] == "MacroURL":
                    if not isinstance(item.get("url"), str) or not item["url"].startswith(("https://", "http://")): raise ValueError("Use an HTTP or HTTPS URL")
                elif not isinstance(item.get("script"), str) or not item["script"].startswith("/"):
                    raise ValueError("Use the absolute path of a script on the host")

    def apply(self, control_id, values):
        self.select()  # Identity, connection and capability rechecked for every explicit Apply.
        spec = next((c for c in self.controls() if c["id"] == control_id), None)
        if spec is None:
            raise MouseError("This control is no longer available. Refresh the device.")
        self.validate(spec, values)
        if spec["category"] == "Lighting" or spec["method"] == "triggerReactive": self.check_sync()
        self.call(spec["interface"], spec["method"], *values)
        # Readback is daemon state, not proof of the physical hardware result.
        getter = "get" + spec["method"][3:] if spec["method"].startswith("set") else None
        readback = None
        if getter and (spec["interface"], getter) in self.methods:
            args = values[:len(self.methods[spec["interface"], getter])]
            readback = self.call(spec["interface"], getter, *args)
            expected = values[len(args):]
            expected = expected[0] if len(expected) == 1 else expected
            tolerance = 1 if "Brightness" in spec["method"] or "Threshold" in spec["method"] else 0
            equal = (abs(readback-expected) <= tolerance
                     if isinstance(readback, (int, float)) and isinstance(expected, (int, float)) else
                     json.dumps(plain_value(readback)) == json.dumps(plain_value(expected)))
            if not equal:
                raise MouseError(f"Command sent, but OpenRazer readback differed: requested {expected}, returned {readback}. Refresh and confirm on the device.")
        return {"result": "sent_to_openrazer", "control": spec["label"], "readback": readback,
                "note": "Command accepted by OpenRazer. Confirm its effect on the device."}

    def set_matrix(self, colors):
        self.select()
        if self.methods.get((CHROMA, "setKeyRow")) != ("ay",) or self.methods.get((CHROMA, "setCustom")) != ():
            raise MouseError("Custom matrix lighting is unavailable")
        dims = valid_dimensions(self.call(MISC, "getMatrixDimensions"))
        if len(colors) != dims[0] or any(len(row) != dims[1] for row in colors):
            raise ValueError("The lighting layout changed. Refresh before applying colours.")
        for row in colors:
            for color in row:
                if len(color) != 3: raise ValueError("Each LED needs an RGB colour")
                for component in color: number(component, 0, 255, "Colour component")
        self.check_sync()
        for index, row in enumerate(colors):
            payload = bytes([index, 0, dims[1]-1] + [v for color in row for v in color])
            self.call(CHROMA, "setKeyRow", payload)
        self.call(CHROMA, "setCustom")
        return {"result": "sent_to_openrazer", "matrix_dimensions": dims}

    def global_setting(self, name, value):
        if name not in ("syncEffects", "enableTurnOffOnScreensaver") or type(value) is not bool:
            raise ValueError("Unknown OpenRazer setting")
        self.root(name, value)
        getter = "getSyncEffects" if name == "syncEffects" else "getOffOnScreensaver"
        if self.root(getter) != value: raise MouseError("OpenRazer did not confirm the setting")
        return {"setting": name, "value": value}
