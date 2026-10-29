"""Mouse UI integration against the simulated OpenRazer transport."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import unittest
from PyQt6.QtWidgets import QApplication
from barracuda_gui import Window
from naga import NagaController, DPI
from test_naga import FakeTransport


class MouseGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.t = FakeTransport()
        factory = lambda serial: NagaController(serial, lambda: self.t)
        self.window = Window(autorefresh=False, mouse_factory=factory)
        self.window.show()
        self.window.navigate("mouse")
        self.page = self.window.mouse_page
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
        self.page.refresh()
        self.wait()

    def test_default_page_does_not_display_fake_values(self):
        self.assertEqual(self.page.stats["battery_percent"].text(), "—")
        self.assertFalse(self.page.apply_buttons["dpi"].isEnabled())
        self.assertEqual(self.t.calls, [])

    def test_preview_cannot_open_transport_or_write(self):
        self.page.preview.setChecked(True)
        self.page.x.setValue(1200)
        self.page.apply_buttons["dpi"].click()
        self.assertFalse(self.page.apply_value("dpi", [1200, 1200]))
        self.assertFalse(self.page.apply_effect("logo"))
        self.window.refresh_current()
        self.assertEqual(self.t.calls, [])
        self.assertIn("PREVIEW", self.page.connection.text())
        self.assertTrue(all(not b.isEnabled() for b in self.page.apply_buttons.values()))

    def test_scan_only_reads_and_selects_correct_model(self):
        self.scan()
        self.assertEqual(self.page.serial, "NAGA")
        self.assertEqual(self.page.devices.count(), 1)
        self.assertTrue(self.page.apply_buttons["dpi"].isEnabled())
        self.assertEqual(self.page.stats["dpi"].text(), "1,600")
        self.assertFalse(self.t.writes())

    def test_dpi_apply_targets_selected_mouse(self):
        self.scan()
        self.page.x.setValue(800)
        self.page.y.setValue(900)
        self.assertFalse(self.t.writes())
        self.page.apply_buttons["dpi"].click()
        self.assertFalse(self.page.devices.isEnabled())
        self.assertFalse(self.page.preview.isEnabled())
        self.wait()
        self.assertEqual(self.t.writes()[-1][0], "/org/razer/device/NAGA")
        self.assertEqual(self.t.writes()[-1][-1], (800, 900))
        self.assertEqual(self.page.stats["dpi"].text(), "800 / 900")

    def test_unsent_dpi_survives_status_refresh(self):
        self.scan()
        self.page.x.setValue(400)
        self.scan()
        self.assertEqual(self.page.x.value(), 400)
        self.assertEqual(self.page.stats["dpi"].text(), "1,600")
        self.assertFalse(self.t.writes())

    def test_unsupported_capability_disables_its_controls(self):
        del self.t.signatures[DPI, "setDPI"]
        self.scan()
        self.assertFalse(self.page.apply_buttons["dpi"].isEnabled())
        self.assertFalse(self.page.x.isEnabled())
        self.assertFalse(self.page.apply_value("dpi", [800, 800]))

    def test_unplug_scan_clears_stale_status_and_buttons(self):
        self.scan()
        del self.t.devices["NAGA"]
        self.scan()
        self.assertIsNone(self.page.serial)
        self.assertEqual(self.page.stats["dpi"].text(), "—")
        self.assertFalse(self.page.apply_buttons["dpi"].isEnabled())

    def test_multiple_devices_require_selection_and_do_not_write(self):
        self.t.devices["SECOND"] = (0x1532, 0x00A7)
        self.scan()
        self.assertIsNone(self.page.serial)
        self.assertFalse(self.page.apply_buttons["dpi"].isEnabled())
        self.page.devices.setCurrentIndex(self.page.devices.findData("SECOND"))
        self.wait()
        self.assertEqual(self.page.serial, "SECOND")
        self.assertFalse(self.t.writes())

    def test_failed_apply_keeps_previous_reading_and_reports_error(self):
        self.scan()
        self.t.mismatch = True
        self.page.x.setValue(800)
        self.page.apply_buttons["dpi"].click()
        self.wait()
        self.assertEqual(self.page.stats["dpi"].text(), "1,600")
        self.assertIn("readback", self.window.log.toPlainText())
        self.assertIn("Operation failed", self.window.notice.text())

    def test_preview_exit_clears_example_data(self):
        self.page.preview.setChecked(True)
        self.page.preview.setChecked(False)
        self.assertEqual(self.page.stats["battery_percent"].text(), "—")
        self.assertEqual(self.page.devices.currentData(), None)
        self.assertFalse(self.page.apply_buttons["dpi"].isEnabled())


if __name__ == "__main__":
    unittest.main()
