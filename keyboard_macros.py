"""Validated keyboard sequences and a host uinput player for Wayland and X11.

OpenRazer watches the six physical macro keys. Its MacroScript endpoint invokes
this standard-library helper as the desktop user; no keystroke listener or root
playback process is added. The player accepts key events only, never commands.
"""
import base64
import fcntl
import json
import os
from pathlib import Path
import shlex
import socket
import stat
import struct
import subprocess
import sys
import time

# Linux input-event-codes.h; physical key positions follow the active layout.
KEYS = {
    "ESC": 1, **{str(i): i + 1 for i in range(1, 10)}, "0": 11,
    "MINUS": 12, "EQUAL": 13, "BACKSPACE": 14, "TAB": 15,
    **dict(zip("QWERTYUIOP", range(16, 26))), "LEFTBRACE": 26, "RIGHTBRACE": 27,
    "ENTER": 28, "CTRL": 29, **dict(zip("ASDFGHJKL", range(30, 39))),
    "SEMICOLON": 39, "APOSTROPHE": 40, "GRAVE": 41, "SHIFT": 42, "BACKSLASH": 43,
    **dict(zip("ZXCVBNM", range(44, 51))), "COMMA": 51, "DOT": 52, "SLASH": 53,
    "RIGHTSHIFT": 54, "KPSTAR": 55, "ALT": 56, "SPACE": 57, "CAPSLOCK": 58,
    **{f"F{i}": 58 + i for i in range(1, 11)}, "NUMLOCK": 69, "SCROLLLOCK": 70,
    "KP7": 71, "KP8": 72, "KP9": 73, "KPMINUS": 74, "KP4": 75, "KP5": 76,
    "KP6": 77, "KPPLUS": 78, "KP1": 79, "KP2": 80, "KP3": 81, "KP0": 82,
    "KPDOT": 83, "F11": 87, "F12": 88, "KPENTER": 96, "RIGHTCTRL": 97,
    "KPSLASH": 98, "PRINT": 99, "RIGHTALT": 100, "HOME": 102, "UP": 103,
    "PAGEUP": 104, "LEFT": 105, "RIGHT": 106, "END": 107, "DOWN": 108,
    "PAGEDOWN": 109, "INSERT": 110, "DELETE": 111, "MUTE": 113,
    "VOLUMEDOWN": 114, "VOLUMEUP": 115, "PAUSE": 119, "SUPER": 125,
    "RIGHTSUPER": 126, "MENU": 127, "NEXTSONG": 163, "PLAYPAUSE": 164,
    "PREVIOUSSONG": 165, **{f"F{i}": 170 + i for i in range(13, 25)},
}
ALIASES = {"CONTROL": "CTRL", "META": "SUPER", "WIN": "SUPER", "ESCAPE": "ESC",
           "RETURN": "ENTER", "DEL": "DELETE", "PGUP": "PAGEUP", "PGDN": "PAGEDOWN"}
LAUNCHER = "import base64,sys;exec(compile(base64.b64decode(sys.argv[1]),'<periphera-macros>','exec'))"
MARKER = "--periphera-events-v1"


def validate_events(events):
    if not isinstance(events, list) or not 1 <= len(events) <= 512:
        raise ValueError("A macro needs 1–512 key or wait steps")
    pressed, result, duration = set(), [], 0
    for event in events:
        if not isinstance(event, dict) or set(event) != {"key", "state", "delay_ms"}:
            raise ValueError("Invalid macro step")
        key, state_, delay = event["key"], event["state"], event["delay_ms"]
        if type(delay) is not int or not 0 <= delay <= 60000:
            raise ValueError("Step delays must be 0–60,000 milliseconds")
        duration += delay
        if duration > 120000:
            raise ValueError("A macro may last at most two minutes")
        if state_ == "WAIT":
            if key != "" or not delay:
                raise ValueError("Wait steps need a positive delay and no key")
        elif not isinstance(key, str) or key not in KEYS or state_ not in ("DOWN", "UP"):
            raise ValueError("Choose a supported key and a down/up action")
        elif state_ == "DOWN":
            if key in pressed:
                raise ValueError(f"{key} is already held; release it before pressing it again")
            pressed.add(key)
        elif key not in pressed:
            raise ValueError(f"{key} must be pressed before it can be released")
        else:
            pressed.remove(key)
        result.append(dict(event))
    if pressed:
        raise ValueError("Release all held keys before saving the macro")
    if not any(e["state"] == "DOWN" for e in result):
        raise ValueError("A macro needs at least one key press")
    return result


def shortcut_events(shortcut):
    keys = [ALIASES.get(s.strip().upper(), s.strip().upper()) for s in shortcut.split("+")]
    if not keys or len(set(keys)) != len(keys) or any(key not in KEYS for key in keys):
        raise ValueError("Use key names such as CTRL+C, CTRL+SHIFT+V, ENTER or F5")
    return ([{"key": k, "state": "DOWN", "delay_ms": 0} for k in keys]
            + [{"key": k, "state": "UP", "delay_ms": 0} for k in reversed(keys)])


def encoded_source():
    return base64.b64encode(Path(__file__).read_bytes()).decode("ascii")


def macro_payload(events):
    data = base64.b64encode(json.dumps(validate_events(events), separators=(",", ":")).encode()).decode("ascii")
    script = shlex.join(["/usr/bin/python3", "-c", LAUNCHER, encoded_source(), MARKER, data])
    return [{"type": "MacroScript", "script": script, "args": None}]


def decode_macro(value):
    """Recognize only commands produced by this player; preserve other macros."""
    try:
        if not isinstance(value, list) or len(value) != 1 or value[0].get("type") != "MacroScript":
            return None
        if value[0].get("args") not in (None, "", " "):
            return None
        args = shlex.split(value[0]["script"])
        if len(args) != 6 or args[:3] != ["/usr/bin/python3", "-c", LAUNCHER] or args[3] != encoded_source() or args[4] != MARKER:
            return None
        return validate_events(json.loads(base64.b64decode(args[5], validate=True)))
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def host_check():
    command = ["/usr/bin/python3", "-c", LAUNCHER, encoded_source(), "--check"]
    if os.environ.get("FLATPAK_ID"):
        command = ["flatpak-spawn", "--host", *command]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError("Keyboard macro playback needs host uinput access. Open Hardware setup, "
                           "choose BlackWidow keyboard + macros, install support, then sign in again if requested. "
                           + result.stderr[-500:].strip())


class VirtualKeyboard:
    """uinput v5 on Linux, following linux/uinput.h and input/uinput.rst."""
    def __enter__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self.fd, 0x40045564, 1)  # UI_SET_EVBIT, EV_KEY
            for code in sorted(set(KEYS.values())):
                fcntl.ioctl(self.fd, 0x40045565, code)  # UI_SET_KEYBIT
            setup = struct.pack("HHHH80sI", 3, 0x1, 0x1, 1, b"Periphera macro keyboard", 0)
            fcntl.ioctl(self.fd, 0x405C5503, setup)  # UI_DEV_SETUP
            fcntl.ioctl(self.fd, 0x5501)  # UI_DEV_CREATE
            # Only once per player lifetime. Let the compositor attach before
            # accepting playback; subsequent macros reuse this virtual device.
            time.sleep(1)
            return self
        except BaseException:
            os.close(self.fd)
            raise

    def emit(self, key, value):
        payload = struct.pack("llHHi", 0, 0, 1, KEYS[key], value)
        payload += struct.pack("llHHi", 0, 0, 0, 0, 0)  # EV_SYN/SYN_REPORT
        if os.write(self.fd, payload) != len(payload):
            raise OSError("Incomplete virtual keyboard write")

    def __exit__(self, *_):
        try:
            fcntl.ioctl(self.fd, 0x5502)  # UI_DEV_DESTROY
        finally:
            os.close(self.fd)


def play_events(events, keyboard, sleep=time.sleep):
    events = validate_events(events)
    held = []
    try:
        for event in events:
            sleep(event["delay_ms"] / 1000)
            if event["state"] == "DOWN":
                # Include the key before writing so cleanup also covers a
                # partial write followed by an I/O failure.
                held.append(event["key"])
                keyboard.emit(event["key"], 1)
            elif event["state"] == "UP":
                keyboard.emit(event["key"], 0)
                held.remove(event["key"])
    finally:
        for key in reversed(held):
            try:
                keyboard.emit(key, 0)
            except OSError:
                pass  # Closing/destroying uinput releases its remaining keys.


def runtime_directory():
    root = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("A private desktop runtime directory is required")
    directory = root / "periphera-macros-v1"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("Invalid macro runtime directory")
    return directory


def receive_line(connection):
    data = bytearray()
    while b"\n" not in data:
        chunk = connection.recv(4096)
        if not chunk:
            raise ValueError("Incomplete macro message")
        data.extend(chunk)
        if len(data) > 100000:
            raise ValueError("Macro message is too large")
    return json.loads(data.split(b"\n", 1)[0])


def serve():
    directory = runtime_directory()
    with open(directory / "lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # A concurrent first trigger has already started the player.
        endpoint = directory / "player.sock"
        endpoint.unlink(missing_ok=True)
        try:
            with VirtualKeyboard() as keyboard, socket.socket(socket.AF_UNIX) as server:
                server.bind(str(endpoint))
                os.chmod(endpoint, 0o600)
                server.listen(8)
                server.settimeout(600)  # Exit after ten minutes without a macro.
                while True:
                    try:
                        connection, _ = server.accept()
                    except socket.timeout:
                        break
                    with connection:
                        connection.settimeout(3)
                        _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        if uid != os.getuid():
                            continue
                        try:
                            play_events(receive_line(connection), keyboard)
                            response = {"ok": True}
                        except ValueError as exc:
                            response = {"error": str(exc)}
                        except OSError as exc:
                            # Destroy the virtual device on I/O failure so no
                            # held modifier can survive a broken output stream.
                            try:
                                connection.sendall(json.dumps({"error": str(exc)}).encode() + b"\n")
                            except OSError:
                                pass
                            return
                        try:
                            connection.sendall(json.dumps(response).encode() + b"\n")
                        except OSError:
                            pass
        finally:
            endpoint.unlink(missing_ok=True)


def send_events(events):
    events = validate_events(events)
    endpoint = runtime_directory() / "player.sock"
    started, connection = False, None
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        connection = socket.socket(socket.AF_UNIX)
        try:
            connection.connect(str(endpoint))
            break
        except (FileNotFoundError, ConnectionRefusedError):
            connection.close()
            connection = None
            if not started:
                # Reuse the exact embedded source supplied by the app. No
                # writable host script or third-party Python modules required.
                subprocess.Popen([sys.executable, "-c", LAUNCHER, sys.argv[1], "--serve"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                started = True
            time.sleep(0.1)
    if connection is None:
        raise RuntimeError("Macro player could not start; check host uinput permissions")
    with connection:
        connection.settimeout(125)
        connection.sendall(json.dumps(events).encode() + b"\n")
        result = receive_line(connection)
        if result.get("ok") is not True:
            raise RuntimeError(result.get("error", "Macro playback failed"))


def main():
    if sys.argv[2:] == ["--check"]:
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        runtime_directory()
    elif sys.argv[2:] == ["--serve"]:
        serve()
    elif len(sys.argv) == 4 and sys.argv[2] == MARKER:
        send_events(json.loads(base64.b64decode(sys.argv[3], validate=True)))
    else:
        raise ValueError("Unknown macro player action")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
