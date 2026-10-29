"""Qt UI checks with a simulated controller; no hardware commands are sent."""
import copy
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import time
import unittest

from PyQt6.QtWidgets import QApplication
from barracuda import DeviceError, PRESETS
from barracuda_gui import Window

SAMPLE = {
    "device": "/dev/hidraw1",
    "values": {"battery_percent": 81, "charging": False, "eq_preset": "music",
               "eq_gains": [0]*10, "sidetone_enabled": False,
               "sidetone_level": 3, "sleep_minutes": 15},
    "errors": {}, "link_event": None,
    "reply_checksum_styles": ["without_report_id"],
}


class FakeController:
    calls = []
    failure = False
    gate = None

    def __init__(self, device=None):
        self.calls.append(("open", device))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.calls.append(("close",))

    def status(self):
        self.calls.append(("status",))
        if self.gate:
            self.gate.wait(2)
        if self.failure:
            raise DeviceError("simulated unplug")
        return copy.deepcopy(SAMPLE)

    def set(self, prop, data):
        self.calls.append(("set", prop, data))
        if self.failure:
            raise DeviceError("simulated write/readback failure")
        if prop == 0x13:
            value = next(k for k, v in PRESETS.items() if v == data[0])
        elif prop == 0x18:
            value = bool(data[0])
        else:
            value = data[0]
        return {"result": "readback_matched", "value": value}

    def set_curve(self, values):
        self.calls.append(("curve", values))
        return {"result": "readback_matched", "value": values}

    def rgb(self, colors, brightness):
        self.calls.append(("rgb", colors, brightness))

    def release_rgb(self):
        self.calls.append(("release_rgb",))


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")

    def setUp(self):
        FakeController.calls = []
        FakeController.failure = False
        FakeController.gate = None
        self.window = Window(controller_factory=FakeController, autorefresh=False)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        if FakeController.gate:
            FakeController.gate.set()
        self.wait_idle()
        self.window.close()
        self.app.processEvents()

    def wait_idle(self):
        end = time.monotonic()+3
        while self.window.busy and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(.01)
        self.assertFalse(self.window.busy, "GUI operation did not finish")

    def click(self, title):
        found = [b for b in self.window.actions if b.text() == title]
        self.assertEqual(len(found), 1)
        found[0].click()
        self.wait_idle()

    def writes(self):
        return [x for x in FakeController.calls if x[0] in ("set", "curve", "rgb", "release_rgb")]

    def test_launch_and_read_refresh_never_write(self):
        self.assertEqual(FakeController.calls, [])
        self.window.refresh()
        self.wait_idle()
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.window.stat["battery"][0].text(), "81%")
        self.assertEqual(self.window.sidetone.value(), 20)
        self.assertFalse(self.window.monitoring.isChecked())
        self.assertEqual(self.window.dirty, set())

    def test_refresh_preserves_unsent_edits(self):
        self.window.select_preset("movie")
        self.window.gains[0].setValue(4)
        self.window.sidetone.setValue(55)
        self.window.sleep.setCurrentIndex(2)
        self.window.refresh()
        self.wait_idle()
        self.assertEqual(self.window.draft_preset, "movie")
        self.assertEqual(self.window.gains[0].value(), 4)
        self.assertEqual(self.window.sidetone.value(), 55)
        self.assertEqual(self.window.sleep.currentData(), 30)
        self.assertEqual(self.writes(), [])
        self.assertIn("Music", self.window.eq_current.text())

    def test_preset_button_sends_correct_payload(self):
        self.window.preset_buttons["game"].click()
        self.assertEqual(self.writes(), [])
        self.click("Apply preset")
        self.assertEqual(self.writes(), [("set", 0x13, b"\x07")])
        self.assertEqual(self.window.data["eq_preset"], "game")
        self.assertNotIn("preset", self.window.dirty)

    def test_curve_is_not_sent_until_apply(self):
        self.window.gains[0].setValue(2)
        self.window.gains[9].setValue(-3)
        self.assertEqual(self.writes(), [])
        self.click("Apply curve")
        self.assertEqual(self.writes(), [("curve", [2,0,0,0,0,0,0,0,0,-3])])
        self.assertEqual(self.window.data["eq_preset"], "custom")

    def test_monitor_switch_and_level_are_separate(self):
        self.window.sidetone.setValue(20)
        self.click("Apply level")
        self.assertEqual(self.writes(), [("set", 0x19, b"\x03")])
        self.window.monitoring.click()
        self.wait_idle()
        self.assertEqual(self.writes()[-1], ("set", 0x18, b"\x01"))
        self.assertTrue(self.window.data["sidetone_enabled"])

    def test_monitor_switch_reverts_on_failed_write(self):
        self.window.receive_status(copy.deepcopy(SAMPLE))
        FakeController.failure = True
        self.window.monitoring.click()
        self.wait_idle()
        self.assertFalse(self.window.monitoring.isChecked())
        self.assertIn("Operation failed", self.window.notice.text())
        self.assertIn("simulated write", self.window.log.toPlainText())

    def test_color_edits_are_previews_and_apply_uses_snapshot(self):
        self.window.all_colors("FF0000")
        self.window.brightness.setValue(25)
        self.assertEqual(FakeController.calls, [])
        self.click("Apply colors")
        self.assertEqual(self.writes(), [("rgb", [(255,0,0)]*6, 25)])

    def test_invalid_color_never_opens_device(self):
        self.window.colors[1].setText("invalid")
        self.assertFalse(self.window.apply_rgb())
        self.assertEqual(FakeController.calls, [])
        self.assertIn("six-digit", self.window.notice.text())

    def test_power_selection_never_sends_index_instead_of_minutes(self):
        self.window.sleep.setCurrentIndex(2)
        self.click("Apply timeout")
        self.assertEqual(self.writes(), [("set", 0x2C, b"\x1e")])

    def test_failed_refresh_clears_old_status(self):
        self.window.receive_status(copy.deepcopy(SAMPLE))
        FakeController.failure = True
        self.window.refresh()
        self.wait_idle()
        self.assertEqual(self.window.data, {})
        self.assertEqual(self.window.stat["battery"][0].text(), "—")
        self.assertIn("Unavailable", self.window.connection.text())

    def test_busy_and_close_wait_for_existing_operation(self):
        FakeController.gate = threading.Event()
        self.window.refresh()
        self.assertFalse(self.window.apply_preset())
        self.window.close()
        self.assertTrue(self.window.closing)
        self.assertTrue(self.window.isVisible())
        FakeController.gate.set()
        self.wait_idle()
        self.app.processEvents()
        self.assertFalse(self.window.isVisible())
        self.assertEqual(self.writes(), [])

    def test_all_pages_fit_width_and_are_scrollable_at_minimum_size(self):
        self.window.resize(980, 700)
        for name, (scroll, layout, title) in self.window.pages.items():
            self.window.navigate(name)
            self.app.processEvents()
            self.assertLessEqual(scroll.widget().width(), scroll.viewport().width())
            self.assertGreater(scroll.viewport().width(), 600)
            bar = scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            self.app.processEvents()
            self.assertEqual(bar.value(), bar.maximum())


if __name__ == "__main__":
    unittest.main(verbosity=2)

