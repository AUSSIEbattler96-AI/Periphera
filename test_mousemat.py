"""Mouse-mat contract tests against OpenRazer's public D-Bus endpoints."""
import unittest

from naga import ROOT, MISC, CHROMA, BRIGHTNESS, typed_arguments
from mousemat import MouseMatController, MouseMatError, MODELS
from test_naga import introspection

SIGNATURES = {
    (MISC, "getMatrixDimensions"): (), (MISC, "triggerReactive"): (),
    (BRIGHTNESS, "getBrightness"): (), (BRIGHTNESS, "setBrightness"): ("d",),
    (CHROMA, "setStatic"): ("y", "y", "y"), (CHROMA, "setSpectrum"): (),
    (CHROMA, "setNone"): (), (CHROMA, "setBreathSingle"): ("y", "y", "y"),
    (CHROMA, "setBreathDual"): ("y",) * 6, (CHROMA, "setBreathRandom"): (),
    (CHROMA, "setWave"): ("i",), (CHROMA, "setReactive"): ("y",) * 4,
    (CHROMA, "setCustom"): (), (CHROMA, "setKeyRow"): ("ay",),
}


class FakeMatTransport:
    def __init__(self, pid=0x0C04):
        self.devices = {"OTHER": (0x1532, 0x0067), "MAT": (0x1532, pid)}
        self.types = {}
        self.signatures = dict(SIGNATURES)
        self.calls, self.closed = [], False
        self.sync, self.mismatch, self.failed_get = False, False, None
        self.brightness = {"MAT": 75.0}
        self.dims = None

    def close(self):
        self.closed = True

    def methods(self, serial):
        methods = dict(self.signatures)
        if not MODELS.get(self.devices[serial][1], {}).get("wave"):
            methods.pop((CHROMA, "setWave"), None)
        return methods

    def call(self, path, interface, method, signatures=(), values=()):
        self.calls.append((path, interface, method, signatures, tuple(values)))
        if method == "getDevices": return list(self.devices)
        if method == "version": return "3.12.4-simulated"
        if method == "getSyncEffects":
            if self.failed_get == method: raise MouseMatError("sync state unavailable")
            return self.sync
        serial = path.rsplit("/", 1)[-1]
        if method == "getVidPid": return self.devices[serial]
        if method == "getDeviceType": return self.types.get(serial, "mousemat")
        if method == "Introspect": return introspection(self.methods(serial))
        if method == self.failed_get: raise MouseMatError("simulated unavailable getter")
        expected = self.methods(serial).get((interface, method))
        if expected != tuple(signatures):
            raise AssertionError(f"Wrong endpoint or signature: {interface}.{method}{signatures}")
        if method == "getBrightness": return self.brightness.get(serial, 75.0)
        if method == "getMatrixDimensions": return self.dims if self.dims is not None else [1, MODELS[self.devices[serial][1]]["columns"]]
        if method == "setBrightness" and not self.mismatch: self.brightness[serial] = values[0]

    def writes(self):
        return [call for call in self.calls if call[2].startswith("set") or call[2] == "triggerReactive"]


class MouseMatTests(unittest.TestCase):
    def setUp(self):
        self.t = FakeMatTransport()
        self.c = MouseMatController(transport_factory=lambda: self.t)
        self.c.__enter__()

    def tearDown(self):
        self.c.__exit__()

    def test_all_eight_models_discover_and_read_without_writes(self):
        self.assertEqual(len(MODELS), 8)
        for pid, model in MODELS.items():
            with self.subTest(pid=pid):
                self.t.devices["MAT"] = (0x1532, pid)
                state = self.c.status()
                self.assertEqual(state["device"]["name"], model["name"])
                self.assertEqual(state["values"]["matrix_dimensions"], [1, model["columns"]])
                self.assertEqual("wave" in state["capabilities"]["effects"], model["wave"])
                self.assertFalse(state["hardware_tested"])
        self.assertFalse(self.t.writes())

    def test_filters_unrelated_vendor_mouse_keyboard_and_unsafe_serials(self):
        self.t.devices.update({"BADVENDOR": (0x9999, 0x0C04), "MOUSE": (0x1532, 0x00A8),
                               "KEYBOARD": (0x1532, 0x0293), "BAD/NAME": (0x1532, 0x0C04)})
        self.assertEqual([d["serial"] for d in self.c.discover()["devices"]], ["MAT"])

    def test_hyperflux_mouse_object_with_same_usb_id_is_rejected(self):
        self.t.devices["MAMBA"] = (0x1532, 0x0068)
        self.t.types["MAMBA"] = "mouse"
        self.assertEqual([d["serial"] for d in self.c.discover()["devices"]], ["MAT"])
        self.c.serial = "MAMBA"
        with self.assertRaises(MouseMatError): self.c.set_effect("off")
        self.assertFalse(self.t.writes())

    def test_multiple_mats_require_selection(self):
        self.t.devices["SECOND"] = (0x1532, 0x0C08)
        with self.assertRaises(MouseMatError): self.c.set_brightness(20)
        self.assertFalse(self.t.writes())
        self.c.serial = "SECOND"
        self.c.set_brightness(20)
        self.assertEqual(self.t.writes()[-1][0], ROOT + "/device/SECOND")

    def test_disconnect_and_device_type_change_block_every_write(self):
        self.c.status()
        del self.t.devices["MAT"]
        with self.assertRaises(MouseMatError): self.c.set_effect("off")
        self.t.devices["MAT"] = (0x1532, 0x0067)
        with self.assertRaises(MouseMatError): self.c.set_brightness(20)
        self.assertFalse(self.t.writes())

    def test_brightness_is_double_and_readback_is_required(self):
        result = self.c.set_brightness(42)
        self.assertEqual(result["result"], "daemon_readback_matched")
        self.assertEqual(self.t.writes()[-1][1:], (BRIGHTNESS, "setBrightness", ("d",), (42.0,)))
        self.t.mismatch = True
        with self.assertRaisesRegex(MouseMatError, "readback"): self.c.set_brightness(18)

    def test_brightness_preflight_and_noop(self):
        self.assertEqual(self.c.set_brightness(75)["result"], "already_set")
        for value in (-1, 101, True, 2.5):
            with self.assertRaises(ValueError): self.c.set_brightness(value)
        self.t.failed_get = "getBrightness"
        with self.assertRaises(MouseMatError): self.c.set_brightness(20)
        self.assertFalse(self.t.writes())

    def test_invalid_brightness_readings_are_not_success(self):
        for value in (-1, float("nan"), float("inf"), True, "75"):
            with self.subTest(value=value):
                self.t.brightness["MAT"] = value
                state = self.c.status()
                self.assertNotIn("brightness", state["values"])
                self.assertIn("brightness", state["errors"])
                with self.assertRaises(MouseMatError): self.c.set_brightness(20)
        self.assertFalse(self.t.writes())

    def test_every_effect_uses_correct_endpoint_and_arguments(self):
        expected = {"static": ("setStatic", ("y",) * 3, (1, 2, 3)),
                    "spectrum": ("setSpectrum", (), ()),
                    "breathing": ("setBreathSingle", ("y",) * 3, (1, 2, 3)),
                    "breathing_dual": ("setBreathDual", ("y",) * 6, (1, 2, 3, 4, 5, 6)),
                    "breathing_random": ("setBreathRandom", (), ()),
                    "wave": ("setWave", ("i",), (2,)),
                    "reactive": ("setReactive", ("y",) * 4, (1, 2, 3, 4)),
                    "off": ("setNone", (), ())}
        for effect, args in expected.items():
            self.c.set_effect(effect, (1, 2, 3), (4, 5, 6), 2, 4)
            self.assertEqual(self.t.writes()[-1][1:], (CHROMA,) + args)

    def test_missing_effect_and_brightness_are_not_sent(self):
        del self.t.signatures[CHROMA, "setStatic"]
        del self.t.signatures[BRIGHTNESS, "setBrightness"]
        state = self.c.status()
        self.assertNotIn("static", state["capabilities"]["effects"])
        self.assertFalse(state["capabilities"]["brightness"])
        with self.assertRaises(MouseMatError): self.c.set_effect("static", (1, 2, 3))
        with self.assertRaises(MouseMatError): self.c.set_brightness(20)
        self.assertFalse(self.t.writes())

    def test_goliathus_wave_is_hidden_and_rejected(self):
        self.t.devices["MAT"] = (0x1532, 0x0C01)
        self.assertNotIn("wave", self.c.status()["capabilities"]["effects"])
        with self.assertRaises(MouseMatError): self.c.set_effect("wave")
        self.assertFalse(self.t.writes())

    def test_invalid_effect_inputs_do_not_write(self):
        for effect, kwargs in (("other", {}), ("static", {"color": [0, 0, 256]}),
                               ("breathing_dual", {"color": [1, 2, 3]}),
                               ("reactive", {"color": [1, 2, 3], "speed": 0}),
                               ("wave", {"direction": True})):
            with self.subTest(effect=effect):
                with self.assertRaises(ValueError): self.c.set_effect(effect, **kwargs)
        self.assertFalse(self.t.writes())

    def test_sync_true_unknown_or_failed_blocks_all_lighting(self):
        for sync, failed in ((True, None), (None, None), (False, "getSyncEffects")):
            self.t.sync, self.t.failed_get = sync, failed
            for operation in (lambda: self.c.set_brightness(30), lambda: self.c.set_effect("off"),
                              lambda: self.c.set_custom([(1, 2, 3)] * 19), self.c.trigger_reactive):
                with self.assertRaises(MouseMatError): operation()
        self.assertFalse(self.t.writes())

    def test_custom_frames_use_live_dimensions_and_public_client_framing(self):
        for count in (1, 15, 17, 19):
            with self.subTest(count=count):
                self.t.dims = [1, count]
                colors = [(68, 214, 44)] * count
                self.c.set_custom(colors)
                upload, activate = self.t.writes()[-2:]
                self.assertEqual(upload[1:4], (CHROMA, "setKeyRow", ("ay",)))
                self.assertEqual(upload[4], (bytes([0, 0, count - 1]) + bytes([68, 214, 44]) * count,))
                self.assertEqual(activate[1:], (CHROMA, "setCustom", (), ()))

    def test_invalid_and_stale_custom_frames_do_not_write(self):
        for colors in ([], [(1, 2, 3)], [(1, 2, 999)] * 19, [(1, 2, 3)] * 65):
            with self.assertRaises(ValueError): self.c.set_custom(colors)
        self.assertFalse(self.t.writes())

    def test_unknown_matrix_layout_disables_custom(self):
        for dims in ([2, 19], [1, 0], [1, 200], [1, True], None):
            if dims is None:
                self.t.failed_get = "getMatrixDimensions"
            else:
                self.t.dims = dims
            self.assertFalse(self.c.status()["capabilities"]["custom"])
            with self.assertRaises((ValueError, MouseMatError)): self.c.set_custom([(1, 2, 3)] * 19)
        self.assertFalse(self.t.writes())

    def test_wrong_custom_wire_signature_disables_feature(self):
        self.t.signatures[CHROMA, "setKeyRow"] = ("s",)
        self.assertFalse(self.c.status()["capabilities"]["custom"])
        with self.assertRaises(MouseMatError): self.c.set_custom([(1, 2, 3)] * 19)
        self.assertFalse(self.t.writes())

    def test_reactive_trigger_targets_misc_interface(self):
        self.c.trigger_reactive()
        self.assertEqual(self.t.writes()[-1][1:], (MISC, "triggerReactive", (), ()))

    def test_qt_bytearray_retains_binary_nuls(self):
        data = bytes([0, 0, 18, 68, 214, 44])
        arg = typed_arguments(("ay",), (data,))[0]
        self.assertEqual(arg.typeName(), "QByteArray")
        self.assertEqual(bytes(arg.value()), data)
        with self.assertRaises(MouseMatError): typed_arguments(("ay",), ([1, 2, 3],))

    def test_transport_closes_after_failure(self):
        with self.assertRaises(MouseMatError):
            with MouseMatController("OTHER", lambda: self.t) as controller:
                controller.set_effect("off")
        self.assertTrue(self.t.closed)


if __name__ == "__main__":
    unittest.main()
