"""Validate playback input, cleanup, timing, and the host command boundary."""
import base64
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

import keyboard_macros as macros


class MacroTests(unittest.TestCase):
    def test_shortcut_expands_in_order_with_reverse_releases(self):
        events = macros.shortcut_events("control+shift+v")
        self.assertEqual([(e["state"], e["key"]) for e in events],
                         [("DOWN", "CTRL"), ("DOWN", "SHIFT"), ("DOWN", "V"),
                          ("UP", "V"), ("UP", "SHIFT"), ("UP", "CTRL")])
        self.assertEqual(macros.validate_events(events), events)

    def test_no_commands_unknown_keys_or_unbalanced_sequences_are_accepted(self):
        for shortcut in ("CTRL+CTRL", "CTRL+; echo hello", "A\nB", "", "CTRL+", "$(id)"):
            with self.assertRaises(ValueError): macros.shortcut_events(shortcut)
        invalid = [[], [{"key": "CTRL", "state": "DOWN", "delay_ms": 0}],
                   [{"key": "A", "state": "UP", "delay_ms": 0}],
                   [{"key": "A", "state": "DOWN", "delay_ms": True}],
                   [{"key": "", "state": "WAIT", "delay_ms": 0}],
                   [{"type": "MacroScript", "script": "bad"}]]
        for events in invalid:
            with self.subTest(events=events), self.assertRaises(ValueError): macros.validate_events(events)

    def test_event_and_duration_limits(self):
        with self.assertRaises(ValueError): macros.validate_events(macros.shortcut_events("A") * 257)
        events = macros.shortcut_events("A") + [{"key": "", "state": "WAIT", "delay_ms": 60000}] * 3
        with self.assertRaises(ValueError): macros.validate_events(events)

    def test_generated_script_is_shell_quoted_and_recognized_without_execution(self):
        events = macros.shortcut_events("SUPER+E")
        payload = macros.macro_payload(events)
        self.assertEqual(macros.decode_macro(payload), events)
        args = shlex.split(payload[0]["script"])
        self.assertEqual(args[:3], ["/usr/bin/python3", "-c", macros.LAUNCHER])
        self.assertEqual(base64.b64decode(args[3]), Path(macros.__file__).read_bytes())
        self.assertEqual(json.loads(base64.b64decode(args[5])), events)
        payload[0]["args"] = "; touch /tmp/bad"
        self.assertIsNone(macros.decode_macro(payload))
        self.assertIsNone(macros.decode_macro([{"type": "MacroScript", "script": "echo nope"}]))

    def test_playback_honors_delay_and_waits_with_balanced_key_events(self):
        events = macros.shortcut_events("CTRL+C")
        events.insert(2, {"key": "", "state": "WAIT", "delay_ms": 125})
        keyboard, sleep = Mock(), Mock()
        macros.play_events(events, keyboard, sleep)
        self.assertEqual([c.args for c in keyboard.emit.call_args_list], [("CTRL", 1), ("C", 1), ("C", 0), ("CTRL", 0)])
        self.assertIn((0.125,), [c.args for c in sleep.call_args_list])

    def test_interrupted_playback_releases_held_modifiers(self):
        keyboard = Mock()
        def emit(key, state):
            if key == "C" and state == 1: raise OSError("simulated I/O failure")
        keyboard.emit.side_effect = emit
        with self.assertRaises(OSError): macros.play_events(macros.shortcut_events("CTRL+C"), keyboard, Mock())
        self.assertEqual([c.args for c in keyboard.emit.call_args_list][-2:], [("C", 0), ("CTRL", 0)])

    def test_uinput_setup_and_native_input_structs_match_linux_abi(self):
        self.assertEqual(struct.calcsize("HHHH80sI"), 92)
        with patch.object(macros.os, "open", return_value=10), patch.object(macros.os, "close"), \
             patch.object(macros.fcntl, "ioctl") as ioctl, patch.object(macros.time, "sleep"), \
             patch.object(macros.os, "write", side_effect=lambda fd, payload: len(payload)) as write:
            with macros.VirtualKeyboard() as keyboard:
                keyboard.emit("CTRL", 1)
        self.assertIn((10, 0x405C5503), [c.args[:2] for c in ioctl.call_args_list])
        payload = write.call_args.args[1]
        size = struct.calcsize("llHHi")
        self.assertEqual(struct.unpack("llHHi", payload[:size]), (0, 0, 1, 29, 1))
        self.assertEqual(struct.unpack("llHHi", payload[size:]), (0, 0, 0, 0, 0))

    def test_host_preflight_uses_argv_without_shell_and_explains_missing_permission(self):
        result = Mock(returncode=1, stderr="permission denied")
        with patch.dict(os.environ, {"FLATPAK_ID": "example.Testing"}), \
             patch.object(macros.subprocess, "run", return_value=result) as run:
            with self.assertRaisesRegex(RuntimeError, "Hardware setup"): macros.host_check()
        self.assertEqual(run.call_args.args[0][:5], ["flatpak-spawn", "--host", "/usr/bin/python3", "-c", macros.LAUNCHER])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_embedded_player_executes_a_read_only_preflight_as_a_real_host_process(self):
        # Use a private runtime dir and replace only the uinput open. Everything
        # else is the actual embedded/compiled helper running under python -c.
        with tempfile.TemporaryDirectory() as directory:
            source = Path(macros.__file__).read_text().replace('os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)', 'os.open("/dev/null", os.O_WRONLY)')
            encoded = base64.b64encode(source.encode()).decode()
            result = subprocess.run(["/usr/bin/python3", "-c", macros.LAUNCHER, encoded, "--check"],
                                    capture_output=True, text=True, env={**os.environ, "XDG_RUNTIME_DIR": directory}, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(directory) / "periphera-macros-v1").is_dir())

    def test_runtime_directory_rejects_shared_or_symlink_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shared"
            path.mkdir(mode=0o755)
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(path)}), self.assertRaises(RuntimeError): macros.runtime_directory()
            link = Path(directory) / "linked"
            link.symlink_to(Path(directory))
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(link)}), self.assertRaises(RuntimeError): macros.runtime_directory()

    def test_real_shell_launcher_socket_and_player_with_simulated_uinput(self):
        try:
            probe = socket.socket(socket.AF_UNIX)
            probe.close()
        except PermissionError:
            if os.environ.get("PERIPHERA_REQUIRE_SOCKET_TEST") == "1":
                raise
            self.skipTest("This local sandbox forbids Unix sockets; required on CI and inside the Flatpak SDK")
        # Exercise the complete OpenRazer-style launch -> detached player ->
        # private socket -> timed key sequence. Only the uinput writer is fake.
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "events.jsonl"
            fake = ("class TestKeyboard:\n"
                    " def __enter__(self): return self\n"
                    " def __exit__(self,*args): pass\n"
                    " def emit(self,key,value):\n"
                    "  with open(" + repr(str(trace)) + ",'a') as f: f.write(json.dumps([key,value])+'\\n')\n"
                    "VirtualKeyboard=TestKeyboard\n")
            source = Path(macros.__file__).read_text().replace('if __name__ == "__main__":', fake + '\nif __name__ == "__main__":')
            source = source.replace("server.settimeout(600)", "server.settimeout(0.2)")
            encoded = base64.b64encode(source.encode()).decode()
            events = macros.shortcut_events("CTRL+C")
            payload = base64.b64encode(json.dumps(events).encode()).decode()
            script = shlex.join(["/usr/bin/python3", "-c", macros.LAUNCHER, encoded, macros.MARKER, payload])
            result = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True,
                                    env={**os.environ, "XDG_RUNTIME_DIR": directory}, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual([json.loads(line) for line in trace.read_text().splitlines()],
                             [["CTRL", 1], ["C", 1], ["C", 0], ["CTRL", 0]])


if __name__ == "__main__":
    unittest.main()
