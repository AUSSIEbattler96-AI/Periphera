"""Host-side hardware checks and a narrowly scoped, explicit repair operation.

This file uses only the standard library. The GUI passes its source as a Python
argument through flatpak-spawn, so checks describe the real host, not the SDK.
No command uses a shell; probing never installs, starts services or opens HID.
"""
import argparse
import fcntl
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import subprocess
import tempfile

MIN_OPENRAZER = (3, 10, 3)
SYSTEM_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
RULE_NAME = "70-barracuda-x-chroma.rules"
HEADSET_RULE = ('# Periphera: access for the active local desktop user.\n'
                'ACTION=="add|change", SUBSYSTEM=="hidraw", KERNEL=="hidraw*", '
                'SUBSYSTEMS=="usb", ATTRS{idVendor}=="1532", '
                'ATTRS{idProduct}=="0574", TAG+="uaccess"\n')
TARGETS = ("headset", "openrazer", "all")


class SetupError(RuntimeError):
    pass


def command(args, timeout=10):
    """Bounded, read-only subprocess helper used by probing and preflight."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                env={**os.environ, "LC_ALL": "C", "PATH": SYSTEM_PATH})
        return result.returncode, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def read(path):
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return ""


def os_release():
    result = {}
    for line in read("/etc/os-release").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            result[key] = value.strip().strip('"').strip("'")
    return result


def version_tuple(value):
    match = re.search(r"(?:\d+:)?(\d+)\.(\d+)\.(\d+)", value)
    return tuple(map(int, match.groups())) if match else ()


def desktop_user():
    # pkexec supplies the authenticated caller's UID. Never accept a username
    # argument for a privileged group-membership operation.
    uid = int(os.environ.get("PKEXEC_UID", os.getuid())) if os.geteuid() == 0 else os.getuid()
    return pwd.getpwuid(uid)


def required_group(distro):
    for directory in ("/etc/udev/rules.d", "/usr/lib/udev/rules.d", "/lib/udev/rules.d"):
        for path in sorted(Path(directory).glob("*razer*.rules")):
            match = re.search(r'GROUP\s*[:+]?=\s*[\"\'](openrazer|plugdev)[\"\']', read(path))
            if match:
                return match.group(1)
    # Older SteamOS packages use upstream plugdev; current Arch packages use
    # openrazer. Inspect the installed daemon when its rule has no group.
    for directory in ("/usr/lib", "/usr/lib64"):
        for pattern in ("python*/site-packages/razer/__init__.py", "python*/dist-packages/razer/__init__.py"):
            for path in Path(directory).glob(pattern):
                source = read(path)
                if re.search(r"getgrnam\([\"']plugdev[\"']\)", source):
                    return "plugdev"
                if re.search(r"getgrnam\([\"']openrazer[\"']\)", source):
                    return "openrazer"
    return "openrazer" if distro.get("ID") in ("arch", "cachyos", "endeavouros", "manjaro") else "plugdev"


def matching_headers(kernel):
    build = Path("/usr/lib/modules") / kernel / "build"
    release = read(build / "include/config/kernel.release")
    if not release:
        match = re.search(r'UTS_RELEASE\s+"([^"]+)"', read(build / "include/generated/utsrelease.h"))
        release = match.group(1) if match else ""
    return release == kernel


def host_devices():
    devices = []
    for path in sorted(Path("/sys/bus/usb/devices").glob("*")):
        if read(path / "idVendor").lower() == "1532":
            devices.append({"usb_id": "1532:" + read(path / "idProduct").lower(),
                            "name": read(path / "product") or "Razer device"})
    return devices


def headset_access():
    nodes = []
    for path in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        if "HID_ID=0003:00001532:00000574" in read(path / "device/uevent").upper():
            node = Path("/dev") / path.name
            nodes.append({"path": str(node), "readable": os.access(node, os.R_OK),
                          "writable": os.access(node, os.W_OK)})
    return nodes


def repair_plan(info, target):
    if target not in TARGETS:
        raise SetupError("Unknown hardware-support target")
    plan = {"target": target, "kernel": info["kernel"], "os_id": info["os_id"],
            "manager": info["manager"], "packages": [], "blocked": "",
            "headset_rule": target in ("headset", "all"),
            "steam_readonly": info["steam_readonly"]}
    if not info["pkexec"] or not info["udevadm"]:
        plan["blocked"] = "Host polkit (pkexec) and udev tools are required for guided repair."
    if target in ("openrazer", "all"):
        if not re.fullmatch(r"[A-Za-z0-9._+\-]+", info["kernel"]):
            plan["blocked"] = "The running kernel name could not be validated."
        if info["manager"] == "pacman":
            plan["packages"] = ["openrazer-daemon", "openrazer-driver-dkms", "dkms"]
            base = info["kernel_package"]
            if not info["headers_match"]:
                if not re.fullmatch(r"linux[A-Za-z0-9._+\-]*", base):
                    plan["blocked"] = "Cannot identify headers for this kernel. Install its exact matching headers, then check again."
                else:
                    plan["packages"].append(base + "-headers")
        elif info["manager"] == "apt-get":
            plan["packages"] = ["openrazer-daemon", "openrazer-driver-dkms", "dkms"]
            if not info["headers_match"]:
                plan["packages"].append("linux-headers-" + info["kernel"])
        else:
            plan["blocked"] = "Automatic OpenRazer installation currently supports Arch/CachyOS/SteamOS and Debian/Ubuntu. Use your distribution's OpenRazer packages, then check again."
        if info["steam"] and info["steam_readonly"] == "unknown":
            plan["blocked"] = "SteamOS read-only status could not be confirmed. No system files will be changed."
    return plan


def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def readonly_state(returncode, output):
    # SteamOS versions may use a nonzero status to indicate writable mode.
    # Warnings or ambiguous output (for example with sysexts) remain unknown.
    value = output.lower().strip()
    return value if returncode in (0, 1) and value in ("enabled", "disabled") else "unknown"


def checks_for(info):
    checks = []
    def add(label, state, detail):
        checks.append({"label": label, "state": state, "detail": detail})
    add("Linux system", "pass", info["name"] + " · " + info["kernel"])
    daemon_ok = version_tuple(info["daemon_version"]) >= MIN_OPENRAZER
    add("OpenRazer installed", "pass" if daemon_ok else "missing",
        info["daemon_version"] if daemon_ok else "OpenRazer 3.10.3 or newer is required. " +
        ("Found " + info["daemon_version"] if info["daemon_version"] else "Not installed."))
    module_ok = version_tuple(info["driver_version"]) >= MIN_OPENRAZER
    add("Driver for this kernel", "pass" if module_ok else "missing",
        info["driver_version"] if module_ok else "A current OpenRazer mouse module is needed for the running kernel.")
    loaded = info.get("loaded_driver_version", "")
    if loaded and version_tuple(loaded) != version_tuple(info["driver_version"]):
        add("Driver update", "restart", "An older driver is still loaded. Reboot to load the installed driver before testing controls.")
    add("Matching kernel headers", "pass" if info["headers_match"] else "info",
        "Exact running-kernel headers found." if info["headers_match"] else
        "Needed to build or rebuild the driver; repair checks for the exact package.")
    add("Device permission group", "pass" if info["group_active"] else "restart" if info["group_configured"] else "missing",
        info["group"] + (" is active in this session." if info["group_active"] else
        " is configured. Sign out of the desktop and back in, or reboot." if info["group_configured"] else
        " membership is required by the installed OpenRazer package."))
    add("OpenRazer service", "pass" if info["service_running"] else "missing",
        "The device service is running." if info["service_running"] else
        "Start the device service after installation and any required sign-in.")
    rule_ok = info["headset_rule"] or (info["headset_nodes"] and all(n["readable"] and n["writable"] for n in info["headset_nodes"]))
    add("Headset permissions", "pass" if rule_ok else "missing",
        "Headset access rule or working device access found." if rule_ok else
        "Install the headset access rule, then reconnect its USB dongle.")
    nodes = info["headset_nodes"]
    add("Headset USB access", "pass" if nodes and all(n["readable"] and n["writable"] for n in nodes) else "info" if not nodes else "missing",
        "Dongle can be read and written." if nodes and all(n["readable"] and n["writable"] for n in nodes) else
        "No headset dongle detected. Connect it to check access." if not nodes else
        "Dongle detected, but access is denied. Repair permissions and reconnect it.")
    if info["steam"]:
        add("SteamOS updates", "info", "Driver support depends on the running SteamOS kernel. Recheck here after OS updates; persistence is not guaranteed.")
    return checks


def probe():
    distro = os_release()
    kernel = os.uname().release
    family = set((distro.get("ID", "") + " " + distro.get("ID_LIKE", "")).split())
    manager = "pacman" if family.intersection({"arch", "cachyos", "steamos"}) else "apt-get" if family.intersection({"debian", "ubuntu"}) else ""
    if manager and not shutil.which(manager, path=SYSTEM_PATH):
        manager = ""
    steam = distro.get("ID") in ("steamos", "holo") or distro.get("VARIANT_ID") == "steamdeck"
    readonly = "not-applicable"
    if steam:
        rc, output = command(["steamos-readonly", "status"])
        readonly = readonly_state(rc, output)
    _, daemon = command(["openrazer-daemon", "--version"])
    if not version_tuple(daemon):
        daemon = ""
    rc, module = command(["modinfo", "-k", kernel, "-F", "version", "razermouse"])
    group = required_group(distro)
    user = desktop_user()
    try:
        entry = grp.getgrnam(group)
        configured = user.pw_name in entry.gr_mem or user.pw_gid == entry.gr_gid
        active = entry.gr_gid in set(os.getgroups()) | {os.getgid()}
    except KeyError:
        configured = active = False
    rc_bus, bus = command(["busctl", "--user", "--no-pager", "--no-legend", "list"])
    rc_service, service = command(["systemctl", "--user", "is-active", "openrazer-daemon.service"])
    info = {"name": distro.get("PRETTY_NAME", distro.get("ID", "Linux")),
            "os_id": distro.get("ID", ""), "kernel": kernel, "manager": manager,
            "steam": steam, "steam_readonly": readonly,
            "kernel_package": read(Path("/usr/lib/modules") / kernel / "pkgbase"),
            "headers_match": matching_headers(kernel), "daemon_version": daemon,
            "driver_version": module if rc == 0 else "", "group": group,
            "loaded_driver_version": read("/sys/module/razermouse/version"),
            "group_configured": configured, "group_active": active,
            "service_running": (rc_bus == 0 and any(line.split()[0] == "org.razer" for line in bus.splitlines() if line.split())) or (rc_service == 0 and service == "active"),
            "headset_rule": "1532" in read(Path("/etc/udev/rules.d") / RULE_NAME) and "0574" in read(Path("/etc/udev/rules.d") / RULE_NAME),
            "headset_nodes": headset_access(), "devices": host_devices(),
            "pkexec": bool(shutil.which("pkexec", path=SYSTEM_PATH)),
            "udevadm": bool(shutil.which("udevadm", path=SYSTEM_PATH))}
    info["checks"] = checks_for(info)
    info["plans"] = {target: repair_plan(info, target) for target in TARGETS}
    return info


def run_change(args):
    print("Running: " + " ".join(args), flush=True)
    result = subprocess.run(args, env={**os.environ, "LC_ALL": "C", "PATH": SYSTEM_PATH})
    if result.returncode:
        raise SetupError(f"{args[0]} failed (exit {result.returncode}). See the output above; no package-manager locks or signature checks were bypassed.")


def preflight(plan):
    """Resolve every package before changing SteamOS's read-only state."""
    for package in plan["packages"]:
        args = ["pacman", "-Si", package] if plan["manager"] == "pacman" else ["apt-cache", "policy", package]
        rc, output = command(args, timeout=20)
        if rc or (plan["manager"] == "apt-get" and not re.search(r"Candidate:\s+(?!\(none\))\S+", output)):
            raise SetupError(f"{package} is unavailable in the configured repositories. Update using your distribution's normal updater and recheck. On SteamOS, wait for matching kernel headers; generic Arch headers will not be substituted.")
        if package == "openrazer-daemon":
            candidate = re.search(r"(?:Version\s*:|Candidate:)\s*(\S+)", output)
            if not candidate or version_tuple(candidate.group(1)) < MIN_OPENRAZER:
                raise SetupError("The configured repositories do not offer OpenRazer 3.10.3 or newer. Follow the distribution's OpenRazer instructions, then recheck.")


def install_rule():
    directory = Path("/etc/udev/rules.d")
    directory.mkdir(parents=True, exist_ok=True)
    filename = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as output:
            filename = output.name
            output.write(HEADSET_RULE)
        os.chmod(filename, 0o644)
        os.replace(filename, directory / RULE_NAME)
    finally:
        if filename and os.path.exists(filename):
            os.unlink(filename)


def apply_plan(target, expected):
    if os.geteuid() != 0 or not os.environ.get("PKEXEC_UID") or desktop_user().pw_uid == 0:
        raise SetupError("Use Install / repair in Periphera. Administrator authentication is required, and the app must run as your normal user.")
    os.environ["PATH"] = SYSTEM_PATH
    # A second app window cannot run overlapping repairs.
    with open("/run/lock/periphera-hardware-setup.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SetupError("Another hardware-support repair is already running.") from exc
        info = probe()
        plan = repair_plan(info, target)
        if fingerprint(plan) != expected:
            raise SetupError("The host or repair plan changed. Check again and review the updated plan.")
        if plan["blocked"]:
            raise SetupError(plan["blocked"])
        preflight(plan)
        unlock = bool(plan["packages"]) and info["steam"] and info["steam_readonly"] == "enabled"
        # Restoring the read-only state also happens on a normal interruption.
        def interrupted(signum, _frame):
            raise SetupError(f"Repair interrupted (signal {signum}); restoring SteamOS read-only mode.")
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, interrupted)
        try:
            if unlock:
                run_change(["steamos-readonly", "disable"])
            if plan["packages"]:
                args = (["pacman", "-S", "--needed", "--noconfirm"] if plan["manager"] == "pacman" else
                        ["apt-get", "install", "--yes"])
                run_change(args + plan["packages"])
                if not matching_headers(info["kernel"]):
                    raise SetupError("The installed headers do not match the running kernel. Reboot after your OS update, then check again. No substitute headers will be used.")
                # Build only OpenRazer for this kernel, not unrelated DKMS modules.
                rc, _ = command(["modinfo", "-k", info["kernel"], "razermouse"])
                if rc:
                    _, daemon = command(["openrazer-daemon", "--version"])
                    ver = version_tuple(daemon)
                    version = ".".join(map(str, ver))
                    if not ver or not (Path("/usr/src") / ("openrazer-driver-" + version) / "dkms.conf").is_file():
                        raise SetupError("OpenRazer's DKMS source could not be matched to its daemon. Check the package installation output.")
                    run_change(["dkms", "install", "openrazer-driver/" + version, "-k", info["kernel"]])
                group = required_group(os_release())
                try:
                    grp.getgrnam(group)
                except KeyError:
                    run_change(["groupadd", "--system", group])
                run_change(["usermod", "-a", "-G", group, desktop_user().pw_name])
                run_change(["modprobe", "razermouse"])
                run_change(["modprobe", "razeraccessory"])
            if plan["headset_rule"]:
                install_rule()
            run_change(["udevadm", "control", "--reload-rules"])
        finally:
            if unlock:
                run_change(["steamos-readonly", "enable"])
    return {"ok": True, "message": "Hardware support installed. Reconnect the headset dongle. If OpenRazer group membership changed, sign out and back in or reboot, then start the device service and scan your device. Hardware settings have not been changed."}


def restart_service():
    info = probe()
    if not info["group_active"]:
        raise SetupError("The required device group is not active. Sign out and back in, or reboot, before starting the service.")
    if not info["daemon_version"] or not info["driver_version"]:
        raise SetupError("Install OpenRazer and its running-kernel driver before starting the service.")
    rc, output = command(["systemctl", "--user", "restart", "openrazer-daemon.service"], timeout=30)
    if rc:
        raise SetupError("The device service could not start: " + output)
    return {"ok": True, "message": "Device service restarted. Scan your mouse or mat to load its supported controls."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--probe", action="store_true")
    action.add_argument("--apply", choices=TARGETS)
    action.add_argument("--restart-service", action="store_true")
    parser.add_argument("--expected-plan", default="")
    args = parser.parse_args()
    try:
        result = probe() if args.probe else apply_plan(args.apply, args.expected_plan) if args.apply else restart_service()
        print("PERIPHERA_RESULT=" + json.dumps(result), flush=True)
    except (SetupError, OSError, ValueError) as exc:
        print("PERIPHERA_RESULT=" + json.dumps({"ok": False, "error": str(exc)}), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
