"""Generic OpenRazer contracts, including wired Trinity and non-mouse devices."""
import copy
import json
import unittest
from xml.sax.saxutils import escape

from naga import MouseError, ROOT, MISC
from openrazer_backend import OpenRazerController, ENDPOINTS, CHROMA, TYPES, plain_value

DPI = "razer.device.dpi"
BRIGHT = "razer.device.lighting.brightness"


class FakeOpenRazer:
    def __init__(self):
        self.devices = {
            "TRINITY": {"name": "Razer Naga Trinity", "type": "mouse", "ids": [0x1532, 0x0067]},
            "KEYBOARD": {"name": "Razer BlackWidow Chroma", "type": "keyboard", "ids": [0x1532, 0x0203]},
        }
        self.signatures = {
            (MISC, "getVidPid"): (), (MISC, "getDeviceName"): (), (MISC, "getDeviceType"): (),
            (MISC, "hasMatrix"): (), (MISC, "getMatrixDimensions"): (),
            (DPI, "setDPI"): ("q", "q"), (DPI, "getDPI"): (), (DPI, "maxDPI"): (),
            (MISC, "setPollRate"): ("q",), (MISC, "getPollRate"): (),
            (MISC, "getSupportedPollRates"): (),
            (BRIGHT, "setBrightness"): ("d",), (BRIGHT, "getBrightness"): (),
            (CHROMA, "setStatic"): ("y", "y", "y"), (CHROMA, "setSpectrum"): (),
            (CHROMA, "setKeyRow"): ("ay",), (CHROMA, "setCustom"): (),
        }
        self.values = {(DPI, "getDPI"): [1600, 1600], (DPI, "maxDPI"): 16000,
                       (MISC, "getPollRate"): 1000, (MISC, "getSupportedPollRates"): [125, 500, 1000],
                       (BRIGHT, "getBrightness"): 75.0, (MISC, "hasMatrix"): True,
                       (MISC, "getMatrixDimensions"): [2, 3]}
        self.calls, self.sync, self.sleep = [], False, False
        self.unavailable = False
        self.mismatch = False
        self.fail_read = None

    def close(self): pass

    def xml(self):
        groups = {}
        for (iface, method), signatures in self.signatures.items():
            args = "".join(f'<arg type="{escape(s)}" direction="in"/>' for s in signatures)
            groups.setdefault(iface, []).append(f'<method name="{method}">{args}</method>')
        return "<node>" + "".join(f'<interface name="{k}">{"".join(v)}</interface>' for k, v in groups.items()) + "</node>"

    def call(self, path, interface, method, signatures=(), values=()):
        self.calls.append((path, interface, method, tuple(signatures), tuple(values)))
        if self.unavailable: raise MouseError("org.razer unavailable")
        if path == ROOT:
            if method == "getDevices": return list(self.devices)
            if method == "version": return "3.10.3"
            if method == "getSyncEffects": return self.sync
            if method == "getOffOnScreensaver": return self.sleep
            if method == "syncEffects": self.sync = values[0]; return []
            if method == "enableTurnOffOnScreensaver": self.sleep = values[0]; return []
        serial = path.rsplit("/", 1)[-1]
        if serial not in self.devices: raise MouseError("device unplugged")
        device = self.devices[serial]
        if device.get("broken"): raise MouseError("device read failed")
        if method == "getVidPid": return list(device["ids"])
        if method == "getDeviceName": return device["name"]
        if method == "getDeviceType": return device["type"]
        if method == "Introspect": return self.xml()
        if (interface, method) == self.fail_read: raise MouseError("reading failed")
        if method.startswith("set"):
            getter = interface, "get" + method[3:]
            if getter in self.values and not self.mismatch:
                self.values[getter] = values[0] if len(values) == 1 else list(values)
            return []
        if method.startswith(("add", "delete", "trigger")): return []
        if (interface, method) not in self.values: raise MouseError("No simulated reading")
        return copy.deepcopy(self.values[interface, method])

    def writes(self):
        return [c for c in self.calls if c[2].startswith(("set", "add", "delete", "trigger")) or c[2] in ("syncEffects", "enableTurnOffOnScreensaver")]


class GenericControllerTests(unittest.TestCase):
    def setUp(self):
        self.transport = FakeOpenRazer()
        self.controller = OpenRazerController("TRINITY", lambda: self.transport)
        self.controller.__enter__()

    def tearDown(self): self.controller.__exit__()

    def test_discovery_includes_trinity_and_every_type_without_product_whitelist(self):
        for i, kind in enumerate(TYPES):
            self.transport.devices[kind] = {"name": "Future " + kind, "type": kind, "ids": [0x4321, 200+i]}
        found = self.controller.discover()
        self.assertEqual(len(found["devices"]), len(TYPES)+2)
        self.assertEqual(found["devices"][0]["usb_id"], "1532:0067")
        self.assertEqual({d["type"] for d in found["devices"]}, set(TYPES))
        self.assertEqual(self.transport.writes(), [])

    def test_dbus_byte_arrays_and_nested_structs_remain_json_safe(self):
        value = plain_value({"colours": bytes([68,214,44]), "nested": (1, [bytes([2,3])])})
        self.assertEqual(value["colours"], [68,214,44])
        self.assertEqual(json.loads(json.dumps(value))["nested"], [1, [[2,3]]])

    def test_faulty_device_does_not_hide_other_devices(self):
        self.transport.devices["KEYBOARD"]["broken"] = True
        found = self.controller.discover()
        self.assertEqual([d["serial"] for d in found["devices"]], ["TRINITY"])
        self.assertIn("KEYBOARD", found["errors"])

    def test_monitor_and_future_types_are_classified(self):
        self.transport.devices["TRINITY"].update(ids=[0x1532, 0x0F12], type="accessory")
        self.assertEqual(self.controller.discover()["devices"][0]["type"], "monitor")
        self.transport.devices["TRINITY"].update(ids=[0x4321, 1], type="new-kind")
        self.assertEqual(self.controller.discover()["devices"][0]["type"], "other")

    def test_status_is_read_only_and_uses_live_capabilities(self):
        result = self.controller.status()
        self.assertEqual(result["device"]["name"], "Razer Naga Trinity")
        self.assertEqual(result["matrix_dimensions"], [2, 3])
        self.assertEqual(self.transport.writes(), [])
        del self.transport.signatures[DPI, "setDPI"]
        self.assertNotIn(DPI + "|setDPI", [s["id"] for s in self.controller.status()["controls"]])

    def test_wrong_signature_and_unknown_writers_are_not_exposed(self):
        self.transport.signatures[DPI, "setDPI"] = ("s",)
        self.transport.signatures[MISC, "setDeviceMode"] = ("y", "y")
        result = self.controller.status()
        self.assertNotIn(DPI + "|setDPI", [s["id"] for s in result["controls"]])
        with self.assertRaises(MouseError): self.controller.apply(MISC + "|setDeviceMode", [3, 0])
        self.assertEqual(self.transport.writes(), [])

    def test_dpi_applies_to_only_selected_device(self):
        self.controller.apply(DPI + "|setDPI", [800, 900])
        self.assertEqual(self.transport.writes()[-1][0], ROOT + "/device/TRINITY")
        self.assertEqual(self.transport.writes()[-1][-1], (800, 900))

    def test_mismatched_daemon_readback_is_reported(self):
        self.transport.mismatch = True
        with self.assertRaisesRegex(MouseError, "readback differed"):
            self.controller.apply(DPI + "|setDPI", [800, 900])

    def test_invalid_dpi_or_poll_rate_never_writes(self):
        for key, values in ((DPI + "|setDPI", [17000, 17000]), (MISC + "|setPollRate", [2000])):
            with self.assertRaises(ValueError): self.controller.apply(key, values)
        self.assertEqual(self.transport.writes(), [])

    def test_single_axis_legacy_dpi_is_supported(self):
        self.transport.signatures[DPI, "availableDPI"] = ()
        self.transport.values[DPI, "availableDPI"] = [400, 800, 1600]
        self.controller.apply(DPI + "|setDPI", [800, 0])
        with self.assertRaises(ValueError): self.controller.apply(DPI + "|setDPI", [800, 800])

    def test_dpi_stage_structs_are_validated(self):
        self.transport.signatures[DPI, "setDPIStages"] = ("y", "a(qq)")
        self.controller.apply(DPI + "|setDPIStages", [1, [(800, 800), (1600, 1600)]])
        with self.assertRaises(ValueError): self.controller.apply(DPI + "|setDPIStages", [2, [(800, 800)]])
        with self.assertRaises(ValueError): self.controller.apply(DPI + "|setDPIStages", [0, [(800, 800)]])

    def test_disconnected_or_changed_identity_cannot_receive_writes(self):
        identity = self.controller.discover()["devices"][0]
        self.controller.expected = identity
        self.transport.devices["TRINITY"]["ids"] = [0x1532, 0x00A7]
        with self.assertRaises(MouseError): self.controller.apply(DPI + "|setDPI", [800, 800])
        del self.transport.devices["TRINITY"]
        with self.assertRaises(MouseError): self.controller.apply(DPI + "|setDPI", [800, 800])
        self.assertEqual(self.transport.writes(), [])

    def test_sync_blocks_all_per_device_lighting_writes(self):
        self.transport.sync = True
        with self.assertRaises(MouseError): self.controller.apply(BRIGHT + "|setBrightness", [25.0])
        with self.assertRaises(MouseError): self.controller.set_matrix([[(0,0,0)]*3]*2)
        self.assertEqual(self.transport.writes(), [])

    def test_global_preferences_require_explicit_supported_action(self):
        self.controller.global_setting("syncEffects", True)
        self.assertTrue(self.transport.sync)
        with self.assertRaises(ValueError): self.controller.global_setting("stop", True)

    def test_matrix_uploads_every_row_before_activation(self):
        self.controller.set_matrix([[(68,214,44)]*3, [(145,70,255)]*3])
        writes = self.transport.writes()
        self.assertEqual([x[2] for x in writes], ["setKeyRow", "setKeyRow", "setCustom"])
        self.assertEqual(writes[0][-1][0], bytes([0,0,2])+bytes([68,214,44])*3)
        self.assertEqual(writes[1][-1][0], bytes([1,0,2])+bytes([145,70,255])*3)

    def test_bad_matrix_rejected_before_upload(self):
        for colors in ([[(0,0,0)]*3], [[(0,0,256)]*3]*2):
            with self.assertRaises(ValueError): self.controller.set_matrix(colors)
        self.assertEqual(self.transport.writes(), [])

    def test_non_matrix_devices_do_not_show_a_false_reading_error(self):
        self.transport.values[MISC, "hasMatrix"] = False
        result = self.controller.status()
        self.assertIsNone(result["matrix_dimensions"])
        self.assertEqual(result["errors"], {})

    def test_macro_payload_is_structured_and_validated(self):
        self.transport.signatures["razer.device.macro", "addMacro"] = ("s", "s")
        sequence = [{"type": "MacroKey", "key_id": "A", "state": "DOWN", "pre_pause": 0}]
        self.controller.apply("razer.device.macro|addMacro", ["M1", json.dumps(sequence)])
        with self.assertRaises(ValueError): self.controller.apply("razer.device.macro|addMacro", ["M1", "{}"])

    def test_kraken_rgb_intensity_array(self):
        self.transport.signatures["razer.device.lighting.kraken", "setCustom"] = ("ai",)
        self.controller.apply("razer.device.lighting.kraken|setCustom", [[68,214,44,255]])
        self.assertEqual(self.transport.writes()[-1][-1], ([68,214,44,255],))

    def test_scalar_types_nan_and_colour_bounds_are_checked(self):
        for value in (float("nan"), float("inf"), True, -1, 101):
            with self.assertRaises(ValueError): self.controller.apply(BRIGHT + "|setBrightness", [value])
        with self.assertRaises(ValueError): self.controller.apply(CHROMA + "|setStatic", [256, 0, 0])
        self.assertEqual(self.transport.writes(), [])

    def test_safe_serial_validation_prevents_object_path_injection(self):
        self.transport.devices["../TRINITY"] = self.transport.devices["TRINITY"]
        result = self.controller.discover()
        self.assertIn("../TRINITY", result["errors"])


if __name__ == "__main__": unittest.main()
