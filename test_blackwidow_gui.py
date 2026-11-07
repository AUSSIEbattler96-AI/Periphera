"""Keyboard UI tests with simulated OpenRazer; no hardware access."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QMessageBox
from barracuda_gui import Window
from blackwidow import BlackWidowController, MODELS
from keyboard_macros import shortcut_events
from test_blackwidow import FakeKeyboardTransport


class BlackWidowGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.t = FakeKeyboardTransport()
        factory = lambda serial: BlackWidowController(serial, lambda: self.t, macro_checker=lambda: None)
        self.window = Window(autorefresh=False, keyboard_factory=factory)
        self.window.show()
        self.window.navigate("keyboard")
        self.page = self.window.keyboard_page
        self.page.settings = QSettings(str(Path(self.directory.name) / "settings.ini"), QSettings.Format.IniFormat)
        self.app.processEvents()

    def tearDown(self):
        self.wait()
        self.window.close()
        self.app.processEvents()
        self.directory.cleanup()

    def wait(self):
        deadline = time.monotonic() + 4
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertFalse(self.window.busy)

    def scan(self):
        self.window.refresh_current()
        self.wait()

    def test_navigation_and_both_previews_never_open_transport_or_send_commands(self):
        self.assertFalse(self.t.calls)
        self.assertTrue(all(not b.isEnabled() for b in self.page.apply_buttons.values()))
        self.page.preview.setChecked(True)
        for pid in MODELS:
            self.page.preview_model.setCurrentIndex(self.page.preview_model.findData(pid))
            self.app.processEvents()
            self.assertEqual([len(self.page.colors), len(self.page.colors[0])], [6, 22])
            self.assertEqual(self.page.tabs.isTabVisible(2), pid == 0x0293)
            self.assertFalse(self.page.apply_brightness())
            self.assertFalse(self.page.apply_effect())
            self.assertFalse(self.page.apply_custom())
            self.assertFalse(self.page.save_macro())
            self.assertFalse(self.page.delete_macro())
            self.assertFalse(self.page.restore_macros())
        self.assertFalse(self.t.calls)

    def test_scan_is_read_only_and_key_painting_sends_only_on_apply(self):
        self.scan()
        self.assertEqual(self.page.serial, "KEYBOARD")
        self.page.paint_color.setText("FF0000")
        self.page.paint_slot(2, 2)
        self.assertEqual(self.page.colors[2][2], "#ff0000")
        self.assertFalse(self.t.writes())
        self.page.apply_custom()
        self.assertFalse(self.page.devices.isEnabled())
        self.wait()
        self.assertEqual([w[2] for w in self.t.writes()], ["setKeyRow", "setCustom"])

    def test_v3_hides_macro_controls_but_keeps_full_rgb(self):
        self.t.devices["KEYBOARD"] = 0x1532, 0x024E
        self.scan()
        self.assertFalse(self.page.tabs.isTabVisible(2))
        self.assertTrue(self.page.apply_buttons["custom"].isEnabled())
        self.assertFalse(self.page.save_macro())

    def test_brightness_colours_and_unsaved_macro_steps_survive_refresh(self):
        self.scan()
        self.page.brightness.setValue(20)
        self.page.paint_color.setText("123456")
        self.page.paint_slot(1, 1)
        self.page.set_steps(shortcut_events("CTRL+C"), dirty=True)
        self.scan()
        self.assertEqual(self.page.brightness.value(), 20)
        self.assertEqual(self.page.colors[1][1], "#123456")
        self.assertEqual(self.page.read_steps(), shortcut_events("CTRL+C"))
        self.assertFalse(self.t.writes())

    def test_save_persists_only_after_readback_and_restore_recovers_after_daemon_restart(self):
        self.scan()
        events = shortcut_events("CTRL+SHIFT+V")
        self.page.set_steps(events, dirty=True)
        self.page.save_macro()
        self.wait()
        self.assertEqual(self.page.saved_macros(), {"M1": events})
        self.t.macros.clear()
        self.scan()
        self.assertTrue(self.page.restore_bindings.isEnabled())
        self.page.restore_macros()
        self.wait()
        self.assertIn("M1", self.t.macros)
        self.page.delete_macro()
        self.wait()
        self.assertEqual(self.page.saved_macros(), {})
        self.assertEqual(self.t.macros, {})

    def test_unbalanced_macro_and_failed_readback_do_not_save_locally(self):
        self.scan()
        self.page.set_steps([{"key": "CTRL", "state": "DOWN", "delay_ms": 0}], dirty=True)
        self.assertFalse(self.page.save_macro())
        self.assertFalse(self.t.writes())
        self.page.set_steps(shortcut_events("A"), dirty=True)
        self.t.mismatch = True
        self.page.save_macro()
        self.wait()
        self.assertEqual(self.page.saved_macros(), {})
        self.assertTrue(self.page.macro_dirty)

    def test_other_bindings_are_preserved_when_replace_confirmation_is_cancelled(self):
        self.t.macros["M1"] = [{"type": "MacroURL", "url": "https://example.com"}]
        self.scan()
        self.page.set_steps(shortcut_events("A"), dirty=True)
        with patch("blackwidow_gui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.page.save_macro())
        self.assertFalse(self.t.writes())

    def test_disconnected_keyboard_clears_all_controls_and_stale_example_values(self):
        self.scan()
        del self.t.devices["KEYBOARD"]
        self.scan()
        self.assertIsNone(self.page.serial)
        self.assertEqual(self.page.colors, [])
        self.assertTrue(all(not b.isEnabled() for b in self.page.apply_buttons.values()))

    def test_multiple_keyboards_need_selection_and_writes_target_the_selected_device(self):
        self.t.devices["SECOND"] = 0x1532, 0x024E
        self.scan()
        self.assertIsNone(self.page.serial)
        self.page.devices.setCurrentIndex(self.page.devices.findData("SECOND"))
        self.wait()
        self.page.effect.setCurrentIndex(self.page.effect.findData("spectrum"))
        self.page.apply_effect()
        self.wait()
        self.assertEqual(self.t.writes()[-1][0], "/org/razer/device/SECOND")

    def test_lighting_sync_blocks_rgb_but_does_not_disable_macro_editor(self):
        self.t.sync = True
        self.scan()
        for name in ("brightness", "effects", "custom"):
            self.assertFalse(self.page.apply_buttons[name].isEnabled())
        self.assertTrue(self.page.apply_buttons["macros"].isEnabled())

    def test_controls_fit_at_the_minimum_window_width(self):
        self.window.resize(980, 700)
        self.page.preview.setChecked(True)
        for index in range(3):
            self.page.tabs.setCurrentIndex(index)
            self.app.processEvents()
            self.assertLessEqual(self.page.minimumSizeHint().width(), self.page.width())


if __name__ == "__main__":
    unittest.main()
