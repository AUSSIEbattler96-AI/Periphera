"""Verify setup actions cannot accidentally run while checking or cancelling."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QMessageBox
from barracuda_gui import Window
from hardware_setup import checks_for, repair_plan, TARGETS
from hardware_setup_gui import decode_result, host_command
from test_hardware_setup import host_info


def report():
    info = host_info()
    info["checks"] = checks_for(info)
    info["plans"] = {target: repair_plan(info, target) for target in TARGETS}
    return info


class SetupGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = Window(autorefresh=False)
        self.page = self.window.setup_page

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def test_install_is_disabled_until_a_host_report_is_available(self):
        self.assertFalse(self.page.install_button.isEnabled())
        self.assertFalse(self.page.service_button.isEnabled())

    def test_cancelled_repair_starts_no_process(self):
        self.page.render_report(report())
        with patch("hardware_setup_gui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel), \
             patch.object(self.page, "start") as start:
            self.page.confirm_repair()
        start.assert_not_called()

    def test_confirmed_repair_uses_the_reviewed_plan_and_privileged_helper(self):
        self.page.render_report(report())
        with patch("hardware_setup_gui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(self.page, "start") as start:
            self.page.confirm_repair()
        args = start.call_args
        self.assertEqual(args.args[0], "repair")
        self.assertEqual(args.args[1][:3], ["--apply", "openrazer", "--expected-plan"])
        self.assertTrue(args.kwargs["privileged"])

    def test_blocked_host_disables_repair_but_allows_checks(self):
        info = report()
        info["plans"]["openrazer"]["blocked"] = "Exact headers unavailable"
        self.page.render_report(info)
        self.assertFalse(self.page.install_button.isEnabled())
        self.assertTrue(self.page.check_button.isEnabled())
        self.assertIn("Exact headers", self.page.plan_note.text())

    def test_host_command_uses_argv_with_no_shell_or_writable_script(self):
        with patch.dict(os.environ, {"FLATPAK_ID": "example.Testing"}):
            args = host_command(["--probe"])
            root_args = host_command(["--apply", "headset"], privileged=True)
        self.assertEqual(args[:4], ["flatpak-spawn", "--host", "/usr/bin/python3", "-c"])
        self.assertEqual(args[-1], "--probe")
        self.assertEqual(root_args[:5], ["flatpak-spawn", "--host", "/usr/bin/pkexec", "/usr/bin/python3", "-c"])
        self.assertNotIn("sh", args)

    def test_only_structured_helper_results_are_accepted(self):
        self.assertEqual(decode_result('package output\nPERIPHERA_RESULT={"ok":true}\n'), {"ok": True})
        for output in ("plain stdout", 'PERIPHERA_RESULT=[]', 'PERIPHERA_RESULT=oops'):
            with self.assertRaises(ValueError):
                decode_result(output)


if __name__ == "__main__":
    unittest.main()
