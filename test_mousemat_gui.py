"""Mouse-mat UI integration with a simulated OpenRazer transport."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import unittest

from PyQt6.QtWidgets import QApplication
from barracuda_gui import Window
from mousemat import MouseMatController, MODELS
from naga import CHROMA
from test_mousemat import FakeMatTransport


class MouseMatGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.t = FakeMatTransport()
        factory = lambda serial: MouseMatController(serial, lambda: self.t)
        self.window = Window(autorefresh=False, mat_factory=factory)
        self.window.show()
        self.window.navigate("mousemat")
        self.page = self.window.mat_page
        self.app.processEvents()

    def tearDown(self):
        self.wait()
        self.window.close()
        self.app.processEvents()

    def wait(self):
        until = time.monotonic() + 3
        while self.window.busy and time.monotonic() < until:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(self.window.busy)

    def scan(self):
        self.window.refresh_current()
        self.wait()

    def test_navigation_does_not_open_hardware_or_show_example_values(self):
        self.assertEqual(self.t.calls, [])
        self.assertEqual(self.page.current_brightness.text(), "Current: —")
        self.assertTrue(all(not b.isEnabled() for b in self.page.apply_buttons.values()))
        self.assertIn("MOUSE MATS", self.window.device_category.text())

    def test_all_model_previews_cannot_open_transport_or_write(self):
        self.page.preview.setChecked(True)
        for pid, model in MODELS.items():
            self.page.preview_model.setCurrentIndex(self.page.preview_model.findData(pid))
            self.app.processEvents()
            self.assertEqual(len(self.page.slot_colors), model["columns"])
            self.assertEqual(self.page.effect.findData("wave") >= 0, model["wave"])
            self.assertFalse(self.page.apply_brightness())
            self.assertFalse(self.page.apply_effect())
            self.assertFalse(self.page.apply_custom())
            self.assertFalse(self.page.trigger_reactive())
            self.assertFalse(self.page.refresh())
            self.assertTrue(all(not b.isEnabled() for b in self.page.apply_buttons.values()))
        self.assertEqual(self.t.calls, [])
        self.assertIn("PREVIEW", self.page.connection.text())

    def test_scan_only_reads_and_populates_live_layout(self):
        self.scan()
        self.assertEqual(self.page.serial, "MAT")
        self.assertEqual(len(self.page.slot_colors), 19)
        self.assertTrue(self.page.apply_buttons["effect"].isEnabled())
        self.assertFalse(self.t.writes())

    def test_brightness_apply_keeps_controls_locked_until_completion(self):
        self.scan()
        self.page.brightness.setValue(35)
        self.assertFalse(self.t.writes())
        self.page.apply_buttons["brightness"].click()
        self.assertFalse(self.page.devices.isEnabled())
        self.assertFalse(self.page.preview.isEnabled())
        self.assertFalse(self.page.preview_model.isEnabled())
        self.wait()
        self.assertEqual(self.t.writes()[-1][0], "/org/razer/device/MAT")
        self.assertEqual(self.page.current_brightness.text(), "Current: 35%")

    def test_unsent_brightness_and_colours_survive_refresh(self):
        self.scan()
        self.page.brightness.setValue(12)
        self.page.slot_colors[0].setText("FF0000")
        self.page.effect.setCurrentIndex(self.page.effect.findData("wave"))
        self.scan()
        self.assertEqual(self.page.brightness.value(), 12)
        self.assertEqual(self.page.slot_colors[0].text(), "FF0000")
        self.assertEqual(self.page.effect.currentData(), "wave")
        self.assertFalse(self.t.writes())

    def test_effect_and_custom_apply_use_correct_selected_mat(self):
        self.scan()
        self.page.color.setText("123456")
        self.page.apply_buttons["effect"].click()
        self.wait()
        self.assertEqual(self.t.writes()[-1][2:], ("setStatic", ("y",) * 3, (18, 52, 86)))
        self.page.fill_button.click()
        self.page.apply_buttons["custom"].click()
        self.wait()
        self.assertEqual(self.t.writes()[-2][2], "setKeyRow")
        self.assertEqual(self.t.writes()[-1][2], "setCustom")

    def test_invalid_colour_blocks_effect_and_matrix(self):
        self.scan()
        self.page.color.setText("whoops")
        self.assertFalse(self.page.apply_effect())
        self.page.slot_colors[-1].setText("bad")
        self.assertFalse(self.page.apply_custom())
        self.assertFalse(self.t.writes())

    def test_no_colour_effect_does_not_require_valid_unused_rgb(self):
        self.scan()
        self.page.color.setText("bad")
        self.page.effect.setCurrentIndex(self.page.effect.findData("spectrum"))
        self.assertTrue(self.page.apply_effect())
        self.wait()
        self.assertEqual(self.t.writes()[-1][2], "setSpectrum")

    def test_sync_enabled_or_unknown_disables_every_apply_button(self):
        for sync in (True, None):
            self.t.sync = sync
            self.scan()
            self.assertTrue(all(not b.isEnabled() for b in self.page.apply_buttons.values()))
            self.assertFalse(self.page.apply_effect())
        self.assertFalse(self.t.writes())

    def test_missing_capability_disables_custom_and_effect(self):
        del self.t.signatures[CHROMA, "setKeyRow"]
        for key in list(self.t.signatures):
            if key[0] == CHROMA: del self.t.signatures[key]
        self.scan()
        self.assertFalse(self.page.apply_buttons["effect"].isEnabled())
        self.assertFalse(self.page.apply_buttons["custom"].isEnabled())
        self.assertTrue(self.page.apply_buttons["brightness"].isEnabled())

    def test_unplug_scan_clears_stale_values_and_buttons(self):
        self.scan()
        del self.t.devices["MAT"]
        self.scan()
        self.assertIsNone(self.page.serial)
        self.assertEqual(self.page.current_brightness.text(), "Current: —")
        self.assertEqual(self.page.slot_colors, [])
        self.assertTrue(all(not b.isEnabled() for b in self.page.apply_buttons.values()))

    def test_multiple_mats_require_explicit_selection(self):
        self.t.devices["SECOND"] = (0x1532, 0x0C01)
        self.scan()
        self.assertIsNone(self.page.serial)
        self.page.devices.setCurrentIndex(self.page.devices.findData("SECOND"))
        self.wait()
        self.assertEqual(self.page.serial, "SECOND")
        self.assertEqual(len(self.page.slot_colors), 1)
        self.page.apply_buttons["effect"].click()
        self.wait()
        self.assertEqual(self.t.writes()[-1][0], "/org/razer/device/SECOND")

    def test_failed_brightness_keeps_previous_reading_and_dirty_edit(self):
        self.scan()
        self.t.mismatch = True
        self.page.brightness.setValue(20)
        self.page.apply_buttons["brightness"].click()
        self.wait()
        self.assertEqual(self.page.current_brightness.text(), "Current: 75%")
        self.assertIn("brightness", self.page.dirty)
        self.assertIn("readback", self.window.log.toPlainText())

    def test_leaving_preview_clears_example_values(self):
        self.page.preview.setChecked(True)
        self.page.preview.setChecked(False)
        self.assertIsNone(self.page.serial)
        self.assertEqual(self.page.current_brightness.text(), "Current: —")
        self.assertEqual(self.page.slot_colors, [])

    def test_minimum_window_width_does_not_clip_mat_controls(self):
        self.window.resize(980, 700)
        self.page.preview.setChecked(True)
        self.page.preview_model.setCurrentIndex(self.page.preview_model.findData(0x0C05))
        self.app.processEvents()
        self.assertLessEqual(self.page.minimumSizeHint().width(), self.page.width())


if __name__ == "__main__":
    unittest.main()
