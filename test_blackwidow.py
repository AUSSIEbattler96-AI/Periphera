"""BlackWidow identity, effect, matrix and macro D-Bus contracts."""
import copy
import json
import unittest

from blackwidow import (BlackWidowController, KeyboardError, MODELS, EFFECTS, MACRO,
                       CUSTOM, MACRO_KEYS, matrix_dimensions)
from naga import ROOT, MISC, CHROMA, BRIGHTNESS
from test_naga import introspection
from keyboard_macros import decode_macro, shortcut_events

SIGNATURES = {(interface, method): signature for _, interface, method, signature in EFFECTS.values()}
SIGNATURES.update({(MISC, "getMatrixDimensions"): (), (BRIGHTNESS, "getBrightness"): (),
                   (BRIGHTNESS, "setBrightness"): ("d",), (CHROMA, "setKeyRow"): ("ay",),
                   (CHROMA, "setCustom"): (), (MACRO, "getMacros"): (),
                   (MACRO, "addMacro"): ("s", "s"), (MACRO, "deleteMacro"): ("s",)})


class FakeKeyboardTransport:
    def __init__(self, pid=0x0293):
        self.devices = {"KEYBOARD": (0x1532, pid)}
        self.types, self.calls, self.macros = {}, [], {}
        self.signatures = dict(SIGNATURES)
        self.sync, self.brightness, self.dims = False, 75.0, [6, 22]
        self.failed_get, self.mismatch, self.closed = None, False, False

    def close(self):
        self.closed = True

    def call(self, path, interface, method, signatures=(), values=()):
        self.calls.append((path, interface, method, signatures, tuple(values)))
        if method == "getDevices": return list(self.devices)
        if method == "version": return "3.12.4-simulated"
        if method == self.failed_get: raise KeyboardError("simulated unavailable getter")
        if method == "getSyncEffects": return self.sync
        serial = path.rsplit("/", 1)[-1]
        if method == "getVidPid": return self.devices[serial]
        if method == "getDeviceType": return self.types.get(serial, "keyboard")
        methods = dict(self.signatures)
        if self.devices[serial][1] == 0x024E:
            methods.pop((CHROMA, "setWheel"), None)
        if method == "Introspect": return introspection(methods)
        if methods.get((interface, method)) != tuple(signatures):
            raise AssertionError(f"Wrong signature for {interface}.{method}: {signatures}")
        if method == "getBrightness": return self.brightness
        if method == "setBrightness" and not self.mismatch: self.brightness = values[0]
        if method == "getMatrixDimensions": return self.dims
        if method == "getMacros": return json.dumps(self.macros)
        if method == "addMacro" and not self.mismatch:
            self.macros[values[0]] = json.loads(values[1])
            for event in self.macros[values[0]]:
                if event["type"] == "MacroScript": event["args"] = ""
        if method == "deleteMacro" and not self.mismatch: self.macros.pop(values[0], None)

    def writes(self):
        return [call for call in self.calls if call[2].startswith("set") or call[2] in ("addMacro", "deleteMacro")]


class BlackWidowTests(unittest.TestCase):
    def setUp(self):
        self.t = FakeKeyboardTransport()
        self.checked = []
        self.c = BlackWidowController(transport_factory=lambda: self.t, macro_checker=lambda: self.checked.append(True))
        self.c.__enter__()

    def tearDown(self):
        self.c.__exit__()

    def test_both_models_read_live_layout_without_writes_and_v3_has_no_macro_editor(self):
        for pid in MODELS:
            self.t.devices["KEYBOARD"] = 0x1532, pid
            state = self.c.status()
            self.assertEqual(state["values"]["matrix_dimensions"], [6, 22])
            self.assertEqual(state["capabilities"]["macros"], pid == 0x0293)
            self.assertEqual("wheel" in state["capabilities"]["effects"], pid == 0x0293)
        self.assertFalse(self.t.writes())

    def test_vendor_product_type_and_serial_are_checked(self):
        self.t.devices.update({"VENDOR": (1, 0x0293), "MOUSE": (0x1532, 0x00A8),
                               "WRONGTYPE": (0x1532, 0x0293), "BAD/NAME": (0x1532, 0x0293)})
        self.t.types["WRONGTYPE"] = "mouse"
        self.assertEqual([d["serial"] for d in self.c.discover()["devices"]], ["KEYBOARD"])

    def test_multiple_keyboards_require_selection_and_every_write_rechecks_it(self):
        self.t.devices["V3"] = 0x1532, 0x024E
        with self.assertRaises(KeyboardError): self.c.set_effect("off")
        self.c.serial = "V3"
        self.c.set_effect("off")
        self.assertEqual(self.t.writes()[-1][0], ROOT + "/device/V3")
        self.t.devices["V3"] = 0x1532, 0x00A8
        with self.assertRaises(KeyboardError): self.c.set_brightness(20)

    def test_all_effect_arguments_match_upstream_including_custom_ripple_interface(self):
        expected = {
            "static": (1, 2, 3), "spectrum": (), "breathing": (1, 2, 3),
            "breathing_dual": (1, 2, 3, 4, 5, 6), "breathing_random": (),
            "wave": (2,), "wheel": (2,), "reactive": (1, 2, 3, 3),
            "starlight": (1, 2, 3, 3), "starlight_dual": (1, 2, 3, 4, 5, 6, 3),
            "starlight_random": (3,), "ripple": (1, 2, 3, 0.05), "ripple_random": (0.05,), "off": (),
        }
        for key, args in expected.items():
            with self.subTest(effect=key):
                self.c.set_effect(key, [1, 2, 3], [4, 5, 6], 2, 3)
                _, interface, method, signature = EFFECTS[key]
                self.assertEqual(self.t.writes()[-1][1:], (interface, method, signature, args))

    def test_absent_or_wrong_signature_effect_is_disabled_and_rejected(self):
        self.t.signatures[CHROMA, "setStatic"] = ("i",) * 3
        del self.t.signatures[CUSTOM, "setRipple"]
        caps = self.c.status()["capabilities"]
        self.assertNotIn("static", caps["effects"])
        self.assertNotIn("ripple", caps["effects"])
        with self.assertRaises(KeyboardError): self.c.set_effect("static", [1, 2, 3])
        self.assertFalse(self.t.writes())

    def test_bad_effect_arguments_and_v3_wheel_do_not_write(self):
        for key, kwargs in (("unknown", {}), ("static", {"color": [256, 1, 2]}),
                            ("wave", {"direction": 3}), ("starlight_random", {"speed": 4}),
                            ("reactive", {"color": [1, 2, 3], "speed": True})):
            with self.assertRaises(ValueError): self.c.set_effect(key, **kwargs)
        self.t.devices["KEYBOARD"] = 0x1532, 0x024E
        with self.assertRaises(KeyboardError): self.c.set_effect("wheel")
        self.assertFalse(self.t.writes())

    def test_matrix_frame_contains_every_row_before_activation(self):
        colors = [[[r, c, 255] for c in range(22)] for r in range(6)]
        self.c.set_custom(colors)
        upload, activate = self.t.writes()
        payload = upload[-1][0]
        self.assertEqual(len(payload), 6 * 69)
        for r in range(6):
            self.assertEqual(payload[r * 69:(r + 1) * 69], bytes([r, 0, 21] + [v for rgb in colors[r] for v in rgb]))
        self.assertEqual(activate[2], "setCustom")

    def test_matrix_uses_live_dimensions_and_rejects_stale_invalid_or_incomplete_frames(self):
        self.t.dims = [2, 3]
        self.c.set_custom([[[1, 2, 3]] * 3 for _ in range(2)])
        self.t.calls.clear()
        for colors in ([], [[[1, 2, 3]] * 22 for _ in range(6)], [[[1, 2, 999]] * 3 for _ in range(2)], [[[1, 2, 3]] * 2 for _ in range(2)]):
            with self.assertRaises(ValueError): self.c.set_custom(colors)
        self.assertFalse(self.t.writes())
        for dims in ([True, 22], [6, 0], [0, 22], [6, 65], "6,22"):
            with self.assertRaises((ValueError, KeyboardError)): matrix_dimensions(dims)

    def test_unknown_matrix_disables_painting(self):
        self.t.failed_get = "getMatrixDimensions"
        self.assertFalse(self.c.status()["capabilities"]["custom"])

    def test_sync_on_unknown_or_failed_blocks_all_lighting(self):
        for sync in (True, None, 1):
            self.t.sync = sync
            for operation in (lambda: self.c.set_effect("off"), lambda: self.c.set_brightness(20),
                              lambda: self.c.set_custom([[[1, 2, 3]] * 22 for _ in range(6)])):
                with self.assertRaises(KeyboardError): operation()
        self.assertFalse(self.t.writes())

    def test_brightness_requires_pre_and_post_readback(self):
        self.assertEqual(self.c.set_brightness(40)["result"], "daemon_readback_matched")
        self.assertEqual(self.t.writes()[-1][1:], (BRIGHTNESS, "setBrightness", ("d",), (40.0,)))
        self.t.mismatch = True
        with self.assertRaisesRegex(KeyboardError, "readback"): self.c.set_brightness(20)
        self.t.brightness = float("nan")
        with self.assertRaises(KeyboardError): self.c.set_brightness(20)

    def test_all_six_macros_round_trip_with_native_wayland_player_and_delete(self):
        events = shortcut_events("CTRL+SHIFT+V")
        for key in MACRO_KEYS:
            result = self.c.set_macro(key, events)
            self.assertEqual(result["result"], "daemon_readback_matched")
            self.assertEqual(decode_macro(self.t.macros[key]), events)
            self.assertEqual(self.t.writes()[-1][1:4], (MACRO, "addMacro", ("s", "s")))
        self.assertEqual(len(self.checked), 6)
        for key in MACRO_KEYS:
            self.c.delete_macro(key)
        self.assertEqual(self.t.macros, {})

    def test_macros_do_not_require_lighting_sync_off(self):
        self.t.sync = True
        self.c.set_macro("M1", shortcut_events("F5"))

    def test_v3_and_absent_macro_capability_reject_macro_writes(self):
        for pid, missing in ((0x024E, False), (0x0293, True)):
            self.t.devices["KEYBOARD"] = 0x1532, pid
            if missing: self.t.signatures.pop((MACRO, "addMacro"))
            with self.assertRaises(KeyboardError): self.c.set_macro("M1", shortcut_events("A"))
            with self.assertRaises(KeyboardError): self.c.delete_macro("M1")
        self.assertFalse(self.t.writes())

    def test_macro_preflight_failure_readback_mismatch_and_unbalanced_keys(self):
        for key in ("F1", "M7", "bad/key"):
            with self.assertRaises(ValueError): self.c.set_macro(key, shortcut_events("A"))
        with self.assertRaises(ValueError): self.c.set_macro("M1", [{"key": "CTRL", "state": "DOWN", "delay_ms": 0}])
        self.t.failed_get = "getMacros"
        with self.assertRaises(KeyboardError): self.c.set_macro("M1", shortcut_events("A"))
        self.assertFalse(self.t.writes())
        self.t.failed_get, self.t.mismatch = None, True
        with self.assertRaisesRegex(KeyboardError, "readback"): self.c.set_macro("M1", shortcut_events("A"))

    def test_host_permission_failure_sends_no_macro_and_other_bindings_are_preserved(self):
        self.c.macro_checker = lambda: (_ for _ in ()).throw(RuntimeError("uinput access denied"))
        self.t.macros["M2"] = [{"type": "MacroURL", "url": "https://example.com"}]
        before = copy.deepcopy(self.t.macros)
        with self.assertRaisesRegex(RuntimeError, "uinput"): self.c.set_macro("M1", shortcut_events("A"))
        self.assertEqual(self.t.macros, before)
        self.assertFalse(self.t.writes())


if __name__ == "__main__":
    unittest.main()
