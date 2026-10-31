"""Exercise host-install boundaries without installing packages or changing Linux."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, mock_open, patch

import hardware_setup as setup
from scripts.prepare_testing import prepare, STABLE_ID, TEST_ID


def host_info(**changes):
    return {"name": "SteamOS", "os_id": "steamos", "kernel": "6.16.12-valve24.5-1-neptune-616",
            "manager": "pacman", "steam": True, "steam_readonly": "enabled",
            "kernel_package": "linux-neptune-616", "headers_match": False,
            "pkexec": True, "udevadm": True, "daemon_version": "", "driver_version": "",
            "group": "plugdev", "group_configured": False, "group_active": False,
            "headset_rule": False, "headset_nodes": [], "devices": [], "service_running": False, **changes}


class HostSetupTests(unittest.TestCase):
    def test_readonly_status_accepts_writable_exit_status_and_rejects_ambiguity(self):
        self.assertEqual(setup.readonly_state(0, "enabled\n"), "enabled")
        self.assertEqual(setup.readonly_state(0, "disabled\n"), "disabled")
        self.assertEqual(setup.readonly_state(1, "disabled\n"), "disabled")
        self.assertEqual(setup.readonly_state(1, "permission denied"), "unknown")
        self.assertEqual(setup.readonly_state(0, "enabled\nWarning: sysexts loaded"), "unknown")

    def test_steam_headers_are_derived_from_running_kernel_package(self):
        plan = setup.repair_plan(host_info(), "openrazer")
        self.assertIn("linux-neptune-616-headers", plan["packages"])
        self.assertNotIn("linux-headers", plan["packages"])
        self.assertFalse(plan["blocked"])

    def test_missing_or_injected_kernel_identity_blocks_driver_repair(self):
        for changes in ({"kernel_package": ""}, {"kernel_package": "linux; touch /tmp/no"},
                        {"kernel": "bad kernel;cmd"}, {"steam_readonly": "unknown"}):
            with self.subTest(changes=changes):
                self.assertTrue(setup.repair_plan(host_info(**changes), "openrazer")["blocked"])

    def test_exact_existing_headers_do_not_install_a_different_package(self):
        plan = setup.repair_plan(host_info(headers_match=True, kernel_package=""), "openrazer")
        self.assertFalse(plan["blocked"])
        self.assertEqual(plan["packages"], ["openrazer-daemon", "openrazer-driver-dkms", "dkms"])

    def test_debian_headers_match_the_running_release(self):
        plan = setup.repair_plan(host_info(manager="apt-get", steam=False), "openrazer")
        self.assertEqual(plan["packages"][-1], "linux-headers-6.16.12-valve24.5-1-neptune-616")

    def test_headset_only_setup_needs_no_package_manager_or_headers(self):
        plan = setup.repair_plan(host_info(manager="", kernel_package=""), "headset")
        self.assertFalse(plan["blocked"])
        self.assertEqual(plan["packages"], [])
        self.assertTrue(plan["headset_rule"])

    def test_unsupported_distribution_gets_guidance_without_install_commands(self):
        plan = setup.repair_plan(host_info(manager="", steam=False), "openrazer")
        self.assertTrue(plan["blocked"])
        self.assertEqual(plan["packages"], [])

    def test_unknown_target_is_rejected(self):
        with self.assertRaises(setup.SetupError):
            setup.repair_plan(host_info(), "arbitrary-command")

    def test_probe_uses_only_read_operations(self):
        commands = []
        def read_command(args, **kwargs):
            commands.append(args)
            return 1, ""
        with patch.object(setup, "command", side_effect=read_command), \
             patch.object(setup, "run_change") as changes, \
             patch.object(setup, "install_rule") as install:
            report = setup.probe()
        changes.assert_not_called()
        install.assert_not_called()
        self.assertIn("checks", report)
        self.assertTrue(all(args[0] in ("steamos-readonly", "openrazer-daemon", "modinfo", "busctl", "systemctl") for args in commands))
        self.assertFalse(any("restart" in args or "install" in args or "disable" in args for args in commands))

    def test_service_refuses_to_start_with_an_inactive_permission_group(self):
        with patch.object(setup, "probe", return_value=host_info(group_configured=True)), \
             patch.object(setup, "command") as command:
            with self.assertRaisesRegex(setup.SetupError, "Sign out"):
                setup.restart_service()
        command.assert_not_called()

    def test_group_added_but_not_active_is_reported_as_restart(self):
        checks = setup.checks_for(host_info(group_configured=True))
        group = next(c for c in checks if c["label"] == "Device permission group")
        self.assertEqual(group["state"], "restart")

    def test_unavailable_packages_and_old_daemons_stop_preflight(self):
        plan = setup.repair_plan(host_info(), "openrazer")
        for response in ((1, "package not found"), (0, "Version : 3.7.0-1")):
            with self.subTest(response=response), patch.object(setup, "command", return_value=response):
                with self.assertRaises(setup.SetupError):
                    setup.preflight(plan)

    def test_debian_without_a_package_candidate_stops_preflight(self):
        plan = setup.repair_plan(host_info(manager="apt-get"), "openrazer")
        with patch.object(setup, "command", return_value=(0, "Candidate: (none)")):
            with self.assertRaises(setup.SetupError):
                setup.preflight(plan)

    def privileged_context(self, info):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(setup.os, "geteuid", return_value=0))
        stack.enter_context(patch.dict(os.environ, {"PKEXEC_UID": "1000"}))
        stack.enter_context(patch.object(setup, "desktop_user", return_value=SimpleNamespace(pw_uid=1000, pw_name="deck")))
        stack.enter_context(patch("builtins.open", mock_open()))
        stack.enter_context(patch.object(setup.fcntl, "flock"))
        stack.enter_context(patch.object(setup.signal, "signal"))
        stack.enter_context(patch.object(setup, "probe", return_value=info))
        return stack

    def test_changed_plan_is_rejected_before_any_host_change(self):
        self.privileged_context(host_info())
        with patch.object(setup, "preflight") as preflight, patch.object(setup, "run_change") as changes:
            with self.assertRaisesRegex(setup.SetupError, "plan changed"):
                setup.apply_plan("all", "wrong-fingerprint")
        preflight.assert_not_called()
        changes.assert_not_called()

    def test_unavailable_header_package_leaves_steamos_read_only(self):
        info = host_info()
        self.privileged_context(info)
        with patch.object(setup, "preflight", side_effect=setup.SetupError("headers unavailable")), \
             patch.object(setup, "run_change") as changes:
            with self.assertRaisesRegex(setup.SetupError, "headers unavailable"):
                setup.apply_plan("all", setup.fingerprint(setup.repair_plan(info, "all")))
        changes.assert_not_called()

    def test_read_only_mode_is_restored_when_package_installation_fails(self):
        info = host_info()
        self.privileged_context(info)
        def change(args):
            if args[0] == "pacman":
                raise setup.SetupError("package failure")
        with patch.object(setup, "preflight"), patch.object(setup, "run_change", side_effect=change) as changes:
            with self.assertRaisesRegex(setup.SetupError, "package failure"):
                setup.apply_plan("all", setup.fingerprint(setup.repair_plan(info, "all")))
        self.assertEqual(changes.call_args_list[0], call(["steamos-readonly", "disable"]))
        self.assertEqual(changes.call_args_list[-1], call(["steamos-readonly", "enable"]))

    def test_headset_repair_does_not_unlock_steamos_or_install_openrazer(self):
        info = host_info()
        self.privileged_context(info)
        with patch.object(setup, "preflight"), patch.object(setup, "run_change") as changes, \
             patch.object(setup, "install_rule") as rule:
            result = setup.apply_plan("headset", setup.fingerprint(setup.repair_plan(info, "headset")))
        self.assertTrue(result["ok"])
        rule.assert_called_once_with()
        self.assertEqual(changes.call_args_list, [call(["udevadm", "control", "--reload-rules"])])

    def test_unauthenticated_root_cannot_choose_an_account_for_group_changes(self):
        with patch.object(setup.os, "geteuid", return_value=0), \
             patch.dict(os.environ, {}, clear=True), patch.object(setup, "run_change") as changes:
            with self.assertRaises(setup.SetupError):
                setup.apply_plan("all", "anything")
        changes.assert_not_called()

    def test_testing_manifest_has_independent_identity_and_host_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packaging = root / "packaging"
            packaging.mkdir()
            for suffix in (".json", ".desktop", ".metainfo.xml", ".png"):
                (packaging / (STABLE_ID + suffix)).write_bytes((Path("packaging") / (STABLE_ID + suffix)).read_bytes())
            manifest = json.loads(prepare(root).read_text())
            self.assertEqual(manifest["app-id"], TEST_ID)
            self.assertEqual(manifest["command"], "periphera-testing")
            self.assertIn("--talk-name=org.freedesktop.Flatpak", manifest["finish-args"])
            self.assertIn("hardware_setup.py", manifest["modules"][0]["build-commands"][0])
            desktop = (packaging / (TEST_ID + ".desktop")).read_text()
            self.assertIn("Name=Periphera Testing\n", desktop)
            self.assertIn("Exec=periphera-testing\n", desktop)
            self.assertIn("StartupWMClass=periphera-testing\n", desktop)
            self.assertEqual(json.loads((packaging / (STABLE_ID + ".json")).read_text())["app-id"], STABLE_ID)


if __name__ == "__main__":
    unittest.main()
