"""Simulated OpenRazer contract tests. These do not prove hardware support."""
import copy
import unittest
from xml.sax.saxutils import escape

from naga import (NagaController, MouseError, parse_methods, typed_arguments, normalize_reply,
                  ROOT, MISC, DPI, POWER, LOGO, CHROMA, BRIGHTNESS)

# Wire signatures checked against OpenRazer 3.10.3's endpoint declarations.
SIGNATURES = {
    (DPI, "maxDPI"): (), (DPI, "getDPI"): (), (DPI, "setDPI"): ("q", "q"),
    (MISC, "getPollRate"): (), (MISC, "setPollRate"): ("q",),
    (POWER, "getBattery"): (), (POWER, "isCharging"): (),
    (POWER, "getIdleTime"): (), (POWER, "setIdleTime"): ("q",),
    (POWER, "getLowBatteryThreshold"): (), (POWER, "setLowBatteryThreshold"): ("y",),
    (LOGO, "getLogoBrightness"): (), (LOGO, "setLogoBrightness"): ("d",),
    (BRIGHTNESS, "getBrightness"): (), (BRIGHTNESS, "setBrightness"): ("d",),
    (LOGO, "setLogoStatic"): ("y", "y", "y"), (CHROMA, "setStatic"): ("y", "y", "y"),
    (LOGO, "setLogoSpectrum"): (), (CHROMA, "setSpectrum"): (),
    (LOGO, "setLogoNone"): (), (CHROMA, "setNone"): (),
    (LOGO, "setLogoBreathSingle"): ("y", "y", "y"), (CHROMA, "setBreathSingle"): ("y", "y", "y"),
}


def introspection(signatures):
    parts = ["<node>"]
    for iface in sorted({key[0] for key in signatures}):
        parts.append(f'<interface name="{escape(iface)}">')
        for (interface, method), sig in signatures.items():
            if interface == iface:
                parts.append(f'<method name="{method}">')
                parts.extend(f'<arg type="{s}" direction="in"/>' for s in sig)
                parts.append('<arg type="s" direction="out"/></method>')
        parts.append("</interface>")
    return "".join(parts) + "</node>"


class FakeTransport:
    def __init__(self):
        self.devices = {"OTHER": (0x1532, 0x0067), "NAGA": (0x1532, 0x00A8)}
        self.signatures = dict(SIGNATURES)
        self.values = {"maxDPI": 30000, "getDPI": [1600, 1600], "getPollRate": 1000,
                       "getBattery": 81.5, "isCharging": False, "getIdleTime": 300,
                       "getLowBatteryThreshold": 15, "getLogoBrightness": 75.0,
                       "getBrightness": 75.0}
        self.calls, self.closed = [], False
        self.sync, self.mismatch, self.failed_get = False, False, None

    def close(self):
        self.closed = True

    def call(self, path, interface, method, signatures=(), values=()):
        self.calls.append((path, interface, method, signatures, tuple(values)))
        if method == "getDevices": return list(self.devices)
        if method == "version": return "3.10.3"
        if method == "getVidPid": return self.devices[path.rsplit("/", 1)[-1]]
        if method == "Introspect": return introspection(self.signatures)
        if method == "getSyncEffects": return self.sync
        if method == self.failed_get: raise MouseError("simulated unavailable getter")
        if method in self.values: return copy.deepcopy(self.values[method])
        self.assert_endpoint(interface, method, signatures)
        if not self.mismatch:
            targets = {"setDPI": "getDPI", "setPollRate": "getPollRate", "setIdleTime": "getIdleTime",
                       "setLowBatteryThreshold": "getLowBatteryThreshold",
                       "setLogoBrightness": "getLogoBrightness", "setBrightness": "getBrightness"}
            if method in targets:
                self.values[targets[method]] = list(values) if method == "setDPI" else values[0]

    def assert_endpoint(self, interface, method, signatures):
        if self.signatures.get((interface, method)) != tuple(signatures):
            raise AssertionError(f"Wrong endpoint/signature: {interface}.{method}{signatures}")

    def writes(self):
        return [call for call in self.calls if call[2].startswith("set")]


class NagaTests(unittest.TestCase):
    def setUp(self):
        self.t = FakeTransport()
        self.c = NagaController(transport_factory=lambda: self.t)
        self.c.__enter__()

    def tearDown(self):
        self.c.__exit__()

    def test_scan_filters_exact_ids_and_status_does_not_write(self):
        self.t.devices["WIRED"] = (0x1532, 0x00A7)
        self.t.devices["HYPERSPEED"] = (0x1532, 0x00B4)
        self.t.devices["OTHER_VENDOR"] = (0x9999, 0x00A8)
        found = self.c.discover()
        self.assertEqual([d["serial"] for d in found["devices"]], ["NAGA", "WIRED"])
        self.c.serial = "NAGA"
        state = self.c.status()
        self.assertEqual(state["values"]["dpi"], [1600, 1600])
        self.assertEqual(self.t.writes(), [])
        self.assertFalse(state["hardware_tested"])

    def test_unrelated_mouse_cannot_be_written(self):
        self.c.serial = "OTHER"
        with self.assertRaises(MouseError): self.c.set_value("dpi", [800, 800])
        self.assertFalse(self.t.writes())

    def test_multiple_mice_require_explicit_selection(self):
        self.t.devices["SECOND"] = (0x1532, 0x00A8)
        with self.assertRaises(MouseError): self.c.set_value("dpi", [800, 800])
        self.assertFalse(self.t.writes())

    def test_dpi_wire_types_and_daemon_readback(self):
        result = self.c.set_value("dpi", [800, 900])
        self.assertEqual(result["result"], "daemon_readback_matched")
        self.assertEqual(self.t.writes()[-1], (ROOT+"/device/NAGA", DPI, "setDPI", ("q", "q"), (800, 900)))

    def test_newer_poll_signature_is_taken_from_introspection(self):
        self.t.signatures[MISC, "setPollRate"] = ("i",)
        self.c.set_value("poll_rate", 500)
        self.assertEqual(self.t.writes()[-1][3:], (("i",), (500,)))

    def test_power_uses_seconds_and_percent(self):
        self.c.set_value("idle_seconds", 120)
        self.c.set_value("low_battery_percent", 20)
        self.assertEqual(self.t.writes()[0][2:], ("setIdleTime", ("q",), (120,)))
        self.assertEqual(self.t.writes()[1][2:], ("setLowBatteryThreshold", ("y",), (20,)))

    def test_ranges_reject_before_any_write(self):
        for field, value in (("dpi", [0, 100]), ("dpi", [30001, 100]), ("poll_rate", 250),
                             ("poll_rate", True), ("idle_seconds", 15), ("idle_seconds", 901),
                             ("low_battery_percent", 51), ("logo_brightness", -1)):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError): self.c.set_value(field, value)
        self.assertFalse(self.t.writes())

    def test_missing_getter_blocks_setting(self):
        del self.t.signatures[POWER, "getIdleTime"]
        self.assertFalse(self.c.status()["capabilities"]["idle_seconds"])
        with self.assertRaises(MouseError): self.c.set_value("idle_seconds", 120)
        self.assertFalse(self.t.writes())

    def test_preflight_failure_does_not_write(self):
        self.t.failed_get = "getDPI"
        with self.assertRaises(MouseError): self.c.set_value("dpi", [800, 800])
        self.assertFalse(self.t.writes())

    def test_readback_mismatch_is_not_reported_as_success(self):
        self.t.mismatch = True
        with self.assertRaisesRegex(MouseError, "readback"):
            self.c.set_value("dpi", [800, 800])

    def test_already_set_does_not_write(self):
        self.assertEqual(self.c.set_value("dpi", [1600, 1600])["result"], "already_set")
        self.assertFalse(self.t.writes())

    def test_negative_battery_is_unknown_not_zero(self):
        self.t.values["getBattery"] = -1.0
        state = self.c.status()
        self.assertNotIn("battery_percent", state["values"])
        self.assertIn("battery_percent", state["errors"])

    def test_lighting_zones_have_different_interfaces(self):
        self.c.set_lighting("logo", "static", (68, 214, 44))
        self.c.set_lighting("thumb", "spectrum", (0, 0, 0))
        self.assertEqual(self.t.writes()[0][1:], (LOGO, "setLogoStatic", ("y", "y", "y"), (68, 214, 44)))
        self.assertEqual(self.t.writes()[1][1:], (CHROMA, "setSpectrum", (), ()))

    def test_lighting_sync_blocks_both_color_and_brightness(self):
        self.t.sync = True
        with self.assertRaisesRegex(MouseError, "sync"):
            self.c.set_lighting("logo", "static", (1, 2, 3))
        with self.assertRaisesRegex(MouseError, "sync"):
            self.c.set_value("logo_brightness", 20)
        self.assertFalse(self.t.writes())

    def test_brightness_is_double(self):
        self.c.set_value("thumb_brightness", 40)
        self.assertEqual(self.t.writes()[-1][3:], (("d",), (40.0,)))

    def test_qt_wire_types_are_not_plain_int32(self):
        args = typed_arguments(("q", "y", "d", "i"), (1600, 214, 75.0, 500))
        self.assertEqual([a.typeName() for a in args], ["ushort", "uchar", "double", "int"])

    def test_introspection_ignores_output_arguments(self):
        self.assertEqual(parse_methods(introspection(SIGNATURES)), SIGNATURES)

    def test_byte_replies_are_normalized_without_changing_arrays(self):
        self.assertEqual(normalize_reply("y", [b"\x0f"]), 15)
        self.assertEqual(normalize_reply("y", [15]), 15)
        self.assertEqual(normalize_reply("ai", [[800, 900]]), [800, 900])

    def test_context_closes_transport_after_failure(self):
        with self.assertRaises(MouseError):
            with NagaController("OTHER", lambda: self.t) as c:
                c.status()
        self.assertTrue(self.t.closed)


if __name__ == "__main__":
    unittest.main()
