"""End-to-end generic navigation and controls against a simulated daemon."""
import copy
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import unittest
from PyQt6.QtWidgets import QApplication, QPushButton
from barracuda_gui import Window
from openrazer_backend import OpenRazerController, TYPES, ENDPOINTS
from openrazer_gui import ArgumentEditor, DevicePage
from test_openrazer import FakeOpenRazer, DPI, BRIGHT, CHROMA


class GenericGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.transport = FakeOpenRazer()
        self.window = Window(autorefresh=False,
                             openrazer_factory=lambda device: OpenRazerController(device, lambda: self.transport),
                             headset_scanner=lambda: {"devices": []})
        self.window.resize(980, 700)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.wait()
        self.window.close()
        self.app.processEvents()

    def wait(self):
        until = time.monotonic()+5
        while self.window.busy and time.monotonic() < until:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()
        self.assertFalse(self.window.busy)

    def scan(self):
        self.window.scan_devices()
        self.wait()

    def open_trinity(self):
        self.scan()
        self.window.open_device(self.window.inventory[0])
        self.wait()
        return self.window.device_pages["device:TRINITY"]

    def test_home_is_opening_page_and_sidebar_lists_types_not_modules(self):
        self.assertEqual(self.window.current_page, "home")
        self.assertEqual(set(self.window.nav), {"home", "diagnostics"} | {"type:"+x for x in TYPES})
        self.assertEqual(self.transport.calls, [])

    def test_home_scan_populates_individual_devices_and_is_read_only(self):
        self.scan()
        self.assertIn("device:TRINITY", self.window.nav)
        self.assertIn("device:KEYBOARD", self.window.nav)
        self.assertEqual(self.window.nav["device:TRINITY"].text(), "Naga Trinity")
        self.assertEqual(self.transport.writes(), [])
        self.assertIn("2 devices", self.window.discovery_pages["home"].summary.text())

    def test_device_page_reads_caps_and_edits_never_write_until_apply(self):
        page = self.open_trinity()
        spec = next(s for s in page.snapshot["controls"] if s["method"] == "setDPI")
        editor = ArgumentEditor(spec, page.snapshot)
        editor.fields[0][1].setValue(800)
        editor.fields[1][1].setValue(900)
        self.assertEqual(self.transport.writes(), [])
        page.apply(spec, editor)
        self.wait()
        self.assertEqual(self.transport.writes()[-1][-1], (800,900))

    def test_unplug_rescan_removes_page_and_stale_sidebar_entry(self):
        page = self.open_trinity()
        del self.transport.devices["TRINITY"]
        self.scan()
        self.assertNotIn("device:TRINITY", self.window.nav)
        self.assertNotIn("device:TRINITY", self.window.device_pages)
        self.assertEqual(self.window.current_page, "home")

    def test_scan_is_still_available_when_daemon_missing_and_headset_scan_runs(self):
        self.transport.unavailable = True
        self.window.headset_scanner = lambda: {"devices": [{"path":"/dev/hidraw10", "capabilities":{"vendor": True}}]}
        self.scan()
        self.assertEqual(self.window.inventory[0]["source"], "barracuda")
        self.assertEqual(self.window.inventory[0]["type"], "headset")
        self.assertIn("OpenRazer", self.window.discovery_pages["home"].scan_result["errors"])

    def test_failed_refresh_disables_previous_device_controls(self):
        page = self.open_trinity()
        self.transport.unavailable = True
        page.refresh()
        self.wait()
        self.assertIsNone(page.snapshot)
        self.assertTrue(all(not b.isEnabled() for b, _ in page.apply_buttons))

    def test_duplicate_names_keep_distinct_serial_entries(self):
        self.transport.devices["SECOND"] = copy.deepcopy(self.transport.devices["TRINITY"])
        self.scan()
        self.assertNotEqual(self.window.nav["device:TRINITY"].text(), self.window.nav["device:SECOND"].text())

    def test_capability_refresh_preserves_draft_editors(self):
        page = self.open_trinity()
        editors = page.findChildren(ArgumentEditor)
        dpi = next(e for e in editors if e.spec["method"] == "setDPI")
        dpi.fields[0][1].setValue(900)
        page.refresh()
        self.wait()
        self.assertEqual(dpi.fields[0][1].value(), 900)
        self.assertEqual(self.transport.writes(), [])

    def test_sidebar_scrolls_and_device_page_fits_deck_minimum_width(self):
        page = self.open_trinity()
        scroll = self.window.pages["device:TRINITY"][0]
        self.assertLessEqual(scroll.widget().width(), scroll.viewport().width())
        self.assertGreater(scroll.viewport().width(), 600)

    def test_all_public_scalar_and_structured_control_editors_construct(self):
        page = self.open_trinity()
        for spec in ENDPOINTS.values():
            if spec["method"] == "setKeyRow": continue
            if spec["method"].startswith("set") or spec["method"] in ("addMacro", "deleteMacro", "triggerReactive"):
                editor = ArgumentEditor(spec, page.snapshot)
                # Empty string fields need user input; construction and value
                # extraction exercise every published control shape.
                editor.values()
                editor.deleteLater()
        self.assertEqual(self.transport.writes(), [])

    def test_sync_disables_lighting_until_explicit_home_preference_change(self):
        self.transport.sync = True
        page = self.open_trinity()
        self.assertTrue(all(not b.isEnabled() for b, lighting in page.apply_buttons if lighting))
        home = self.window.discovery_pages["home"]
        home.sync.setChecked(False)
        self.assertEqual(self.transport.writes(), [])
        home.apply_preferences()
        self.wait()
        self.assertFalse(self.transport.sync)
        self.assertIsNone(page.snapshot)


if __name__ == "__main__": unittest.main()
