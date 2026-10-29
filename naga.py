"""Naga V2 Pro adapter for the host OpenRazer session D-Bus service.

No mouse USB packets or kernel modules are implemented here. Introspection
determines the methods and wire types; only 1532:00a7/00a8 are accepted.
OpenRazer getters can return cached state, so readback is called daemon
readback, never independent hardware verification.
"""
import math
import re
import uuid
import xml.etree.ElementTree as ET

SERVICE = "org.razer"
ROOT = "/org/razer"
MISC = "razer.device.misc"
DPI = "razer.device.dpi"
POWER = "razer.device.power"
LOGO = "razer.device.lighting.logo"
CHROMA = "razer.device.lighting.chroma"
BRIGHTNESS = "razer.device.lighting.brightness"
PRODUCTS = {0x00A7: "USB cable", 0x00A8: "2.4 GHz receiver"}
EFFECTS = {"static": "Static", "spectrum": "Spectrum", "breathing": "BreathSingle", "off": "None"}


class MouseError(RuntimeError):
    pass


def parse_methods(xml):
    """Return input signatures, including explicit zero-argument methods."""
    root = ET.fromstring(xml)
    return {(iface.attrib["name"], method.attrib["name"]):
            tuple(arg.attrib["type"] for arg in method.findall("arg")
                  if arg.get("direction", "in") == "in")
            for iface in root.findall("interface") for method in iface.findall("method")}


def typed_arguments(signatures, values):
    # Plain Python ints marshal as int32, which is wrong for OpenRazer's
    # uint16 DPI and byte RGB endpoints. Preserve the advertised wire type.
    from PyQt6.QtCore import QMetaType, QVariant
    types = {"y": QMetaType.Type.UChar, "q": QMetaType.Type.UShort,
             "i": QMetaType.Type.Int, "u": QMetaType.Type.UInt,
             "d": QMetaType.Type.Double, "b": QMetaType.Type.Bool,
             "s": QMetaType.Type.QString}
    if len(signatures) != len(values):
        raise MouseError("D-Bus argument count does not match introspection")
    arguments = []
    for signature, value in zip(signatures, values):
        if signature not in types:
            raise MouseError(f"Unsupported D-Bus argument type: {signature}")
        variant = QVariant(value)
        if not variant.convert(QMetaType(types[signature].value)):
            raise MouseError(f"Cannot encode D-Bus argument as {signature}")
        arguments.append(variant)
    return arguments


def normalize_reply(signature, arguments):
    # PyQt represents Qt's uchar as a one-byte bytes object on some versions.
    # OpenRazer exposes low-battery percentage as a D-Bus byte, not a string.
    if signature == "y" and len(arguments) == 1:
        value = arguments[0]
        if isinstance(value, bytes) and len(value) == 1:
            return value[0]
    return arguments[0] if len(arguments) == 1 else arguments if arguments else None


class QtTransport:
    """A private connection owned and closed by the worker that creates it."""
    def __init__(self):
        from PyQt6.QtDBus import QDBusConnection
        self.name = "barracuda-" + uuid.uuid4().hex
        self.bus = QDBusConnection.connectToBus(QDBusConnection.BusType.SessionBus, self.name)
        if not self.bus.isConnected():
            self.close()
            raise MouseError("Cannot access the desktop session bus. Run as your normal desktop user.")

    def close(self):
        from PyQt6.QtDBus import QDBusConnection
        QDBusConnection.disconnectFromBus(self.name)

    def call(self, path, interface, method, signatures=(), values=()):
        from PyQt6.QtDBus import QDBus, QDBusMessage
        msg = QDBusMessage.createMethodCall(SERVICE, path, interface, method)
        msg.setArguments(typed_arguments(signatures, values))
        reply = self.bus.call(msg, QDBus.CallMode.Block, 3000)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            raise MouseError(f"{method}: {reply.errorName()}: {reply.errorMessage()}")
        return normalize_reply(reply.signature(), reply.arguments())


def checked_int(value, minimum, maximum, label):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


class NagaController:
    def __init__(self, serial=None, transport_factory=QtTransport):
        self.serial = serial
        self.transport_factory = transport_factory
        self.transport = None
        self.methods = {}
        self.path = None

    def __enter__(self):
        self.transport = self.transport_factory()
        return self

    def __exit__(self, *_):
        self.transport.close()

    def root(self, interface, method, signatures=(), values=()):
        return self.transport.call(ROOT, interface, method, signatures, values)

    def discover(self):
        try:
            serials = self.root("razer.devices", "getDevices")
            version = self.root("razer.daemon", "version")
        except MouseError as exc:
            raise MouseError("OpenRazer is unavailable. Install OpenRazer 3.10.3 or newer on the host "
                             "and start its daemon in your desktop session. " + str(exc)) from exc
        devices, errors = [], {}
        for serial in serials:
            if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9_]+", serial):
                continue
            path = ROOT + "/device/" + serial
            try:
                vid, pid = self.transport.call(path, MISC, "getVidPid")
                if vid != 0x1532 or pid not in PRODUCTS:
                    continue
                devices.append({"serial": serial, "name": "Razer Naga V2 Pro",
                                "usb_id": f"{vid:04x}:{pid:04x}", "connection": PRODUCTS[pid]})
            except (MouseError, ValueError, TypeError) as exc:
                errors[serial] = str(exc)
        return {"daemon_version": str(version), "devices": devices, "discovery_errors": errors}

    def select(self):
        found = self.discover()
        choices = found["devices"]
        if self.serial is None and len(choices) == 1:
            self.serial = choices[0]["serial"]
        selected = next((d for d in choices if d["serial"] == self.serial), None)
        if selected is None:
            raise MouseError("No selected Naga V2 Pro is available. Connect its USB cable or original "
                             "2.4 GHz receiver, wake the mouse, then scan again. Bluetooth and Mouse Dock Pro "
                             "connections are not supported by this adapter.")
        self.path = ROOT + "/device/" + self.serial
        xml = self.transport.call(self.path, "org.freedesktop.DBus.Introspectable", "Introspect")
        self.methods = parse_methods(xml)
        return found, selected

    def has(self, interface, *methods):
        return all((interface, method) in self.methods for method in methods)

    def call(self, interface, method, *values):
        if not self.has(interface, method):
            raise MouseError(f"The installed OpenRazer driver does not expose {method} for this mouse")
        return self.transport.call(self.path, interface, method, self.methods[interface, method], values)

    def capabilities(self):
        result = {"dpi": self.has(DPI, "getDPI", "setDPI", "maxDPI"),
                  "poll_rate": self.has(MISC, "getPollRate", "setPollRate"),
                  "idle_seconds": self.has(POWER, "getIdleTime", "setIdleTime"),
                  "low_battery_percent": self.has(POWER, "getLowBatteryThreshold", "setLowBatteryThreshold"),
                  "logo_brightness": self.has(LOGO, "getLogoBrightness", "setLogoBrightness"),
                  "thumb_brightness": self.has(BRIGHTNESS, "getBrightness", "setBrightness")}
        for zone, interface, prefix in (("logo", LOGO, "setLogo"), ("thumb", CHROMA, "set")):
            result[zone + "_effects"] = [name for name, suffix in EFFECTS.items()
                                        if self.has(interface, prefix + suffix)]
        return result

    def status(self):
        found, selected = self.select()
        values, errors = {}, {}
        queries = {"dpi": (DPI, "getDPI"), "max_dpi": (DPI, "maxDPI"),
                   "poll_rate": (MISC, "getPollRate"), "poll_rates": (MISC, "getSupportedPollRates"),
                   "battery_percent": (POWER, "getBattery"), "charging": (POWER, "isCharging"),
                   "idle_seconds": (POWER, "getIdleTime"),
                   "low_battery_percent": (POWER, "getLowBatteryThreshold"),
                   "logo_brightness": (LOGO, "getLogoBrightness"),
                   "thumb_brightness": (BRIGHTNESS, "getBrightness")}
        for key, endpoint in queries.items():
            if self.has(*endpoint):
                try:
                    value = self.call(*endpoint)
                    if key == "battery_percent" and (not isinstance(value, (int, float)) or
                                                      not math.isfinite(value) or not 0 <= value <= 100):
                        raise MouseError("Battery unavailable (the mouse may be asleep)")
                    values[key] = value
                except MouseError as exc:
                    errors[key] = str(exc)
        if "poll_rates" not in values:
            values["poll_rates"] = [125, 500, 1000]  # Naga V2 Pro's upstream default.
        try:
            values["sync_effects"] = self.root("razer.devices", "getSyncEffects")
        except MouseError as exc:
            errors["sync_effects"] = str(exc)
        return {**found, "device": selected, "values": values, "errors": errors,
                "capabilities": self.capabilities(), "hardware_tested": False}

    def set_value(self, field, value):
        self.select()  # Revalidate model/serial/capabilities before every write.
        if field == "dpi":
            maximum = min(30000, int(self.call(DPI, "maxDPI")))
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError("DPI needs X and Y values")
            value = [checked_int(v, 100, maximum, "DPI") for v in value]
            endpoint, get, set_, args = DPI, "getDPI", "setDPI", value
        else:
            spec = {
                "poll_rate": (MISC, "getPollRate", "setPollRate", 125, 1000),
                "idle_seconds": (POWER, "getIdleTime", "setIdleTime", 60, 900),
                "low_battery_percent": (POWER, "getLowBatteryThreshold", "setLowBatteryThreshold", 5, 50),
                "logo_brightness": (LOGO, "getLogoBrightness", "setLogoBrightness", 0, 100),
                "thumb_brightness": (BRIGHTNESS, "getBrightness", "setBrightness", 0, 100),
            }
            if field not in spec:
                raise ValueError("Unsupported mouse setting")
            endpoint, get, set_, minimum, maximum = spec[field]
            value = checked_int(value, minimum, maximum, field)
            if field == "poll_rate" and value not in (125, 500, 1000):
                raise ValueError("Naga V2 Pro polling rate must be 125, 500 or 1000 Hz")
            args = (float(value),) if field.endswith("brightness") else (value,)
        if not self.has(endpoint, get, set_):
            raise MouseError(f"{field} is not supported by this OpenRazer version")
        if field.endswith("brightness"):
            self.check_lighting_sync()
        before = self.call(endpoint, get)
        if before == value:
            return {"result": "already_set", "field": field, "value": before}
        self.call(endpoint, set_, *args)
        after = self.call(endpoint, get)
        tolerance = 1 if field.endswith("brightness") or field == "low_battery_percent" else 0
        matched = (abs(after - value) <= tolerance) if tolerance else (after == value)
        if not matched:
            raise MouseError(f"{field} was sent, but daemon readback was {after!r}; requested {value!r}")
        return {"result": "daemon_readback_matched", "field": field, "value": after}

    def check_lighting_sync(self):
        if self.root("razer.devices", "getSyncEffects"):
            raise MouseError("OpenRazer lighting sync is enabled. Turn it off in your OpenRazer settings "
                             "before changing this mouse's lighting; sync can affect other devices.")

    def set_lighting(self, zone, effect, color):
        if zone not in ("logo", "thumb") or effect not in EFFECTS:
            raise ValueError("Invalid lighting zone or effect")
        if not isinstance(color, (tuple, list)) or len(color) != 3:
            raise ValueError("RGB needs three values")
        rgb = [checked_int(v, 0, 255, "RGB") for v in color]
        self.select()
        self.check_lighting_sync()
        interface, prefix = (LOGO, "setLogo") if zone == "logo" else (CHROMA, "set")
        args = rgb if effect in ("static", "breathing") else ()
        self.call(interface, prefix + EFFECTS[effect], *args)
        return {"result": "sent_to_openrazer", "zone": zone, "effect": effect,
                "color": rgb if args else None, "note": "Visually confirm the mouse; no effect readback is available."}
