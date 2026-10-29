"""Run under dbus-run-session on CI; asserts real D-Bus types, not hardware.

Requires python3-dbus/python3-gi for the simulated service and PyQt6.QtDBus
for the client. This deliberately fails if the private message bus cannot run.
"""
from pathlib import Path
import os
import select
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def service():
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    name = dbus.service.BusName("org.razer", bus=bus)

    class Manager(dbus.service.Object):
        @dbus.service.method("razer.devices", out_signature="as")
        def getDevices(self): return ["WIRETEST"]

        @dbus.service.method("razer.daemon", out_signature="s")
        def version(self): return "3.12.4-simulated"

        @dbus.service.method("razer.devices", out_signature="b")
        def getSyncEffects(self): return False

    class Mouse(dbus.service.Object):
        dpi, rate, idle, low, brightness = [1600, 1600], 1000, 300, 15, 75.0

        @dbus.service.method("razer.device.misc", out_signature="ai")
        def getVidPid(self): return [0x1532, 0x00A8]

        @dbus.service.method("razer.device.dpi", out_signature="i")
        def maxDPI(self): return 30000

        @dbus.service.method("razer.device.dpi", out_signature="ai")
        def getDPI(self): return self.dpi

        @dbus.service.method("razer.device.dpi", in_signature="qq")
        def setDPI(self, x, y):
            assert isinstance(x, dbus.UInt16) and isinstance(y, dbus.UInt16)
            self.dpi = [x, y]

        @dbus.service.method("razer.device.misc", out_signature="i")
        def getPollRate(self): return self.rate

        # Recent daemon versions may advertise i rather than q.
        @dbus.service.method("razer.device.misc", in_signature="i")
        def setPollRate(self, value):
            assert isinstance(value, dbus.Int32)
            self.rate = value

        @dbus.service.method("razer.device.power", out_signature="d")
        def getBattery(self): return 80.0

        @dbus.service.method("razer.device.power", out_signature="b")
        def isCharging(self): return False

        @dbus.service.method("razer.device.power", out_signature="q")
        def getIdleTime(self): return self.idle

        @dbus.service.method("razer.device.power", in_signature="q")
        def setIdleTime(self, value):
            assert isinstance(value, dbus.UInt16)
            self.idle = value

        @dbus.service.method("razer.device.power", out_signature="y")
        def getLowBatteryThreshold(self): return self.low

        @dbus.service.method("razer.device.power", in_signature="y")
        def setLowBatteryThreshold(self, value):
            assert isinstance(value, dbus.Byte)
            self.low = value

        @dbus.service.method("razer.device.lighting.logo", out_signature="d")
        def getLogoBrightness(self): return self.brightness

        @dbus.service.method("razer.device.lighting.logo", in_signature="d")
        def setLogoBrightness(self, value):
            assert isinstance(value, dbus.Double)
            self.brightness = value

        @dbus.service.method("razer.device.lighting.logo", in_signature="yyy")
        def setLogoStatic(self, red, green, blue):
            assert all(isinstance(v, dbus.Byte) for v in (red, green, blue))
            assert (red, green, blue) == (68, 214, 44)

        @dbus.service.method("razer.device.lighting.chroma")
        def setSpectrum(self): pass

    manager = Manager(name, "/org/razer")
    mouse = Mouse(name, "/org/razer/device/WIRETEST")
    print("ready", flush=True)
    GLib.MainLoop().run()


def client():
    from PyQt6.QtCore import QCoreApplication
    from naga import NagaController
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("Run this test using dbus-run-session")
    app = QCoreApplication([])
    process = subprocess.Popen([sys.executable, __file__, "--service"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        readable, _, _ = select.select([process.stdout], [], [], 10)
        if not readable or process.stdout.readline().strip() != "ready":
            raise RuntimeError("Simulated D-Bus service did not start")
        with NagaController() as mouse:
            status = mouse.status()
            assert status["device"]["serial"] == "WIRETEST"
            assert status["values"]["dpi"] == [1600, 1600]
            for field, value in (("dpi", [800, 900]), ("poll_rate", 500),
                                 ("idle_seconds", 120), ("low_battery_percent", 20),
                                 ("logo_brightness", 50)):
                assert mouse.set_value(field, value)["result"] == "daemon_readback_matched"
            mouse.set_lighting("logo", "static", (68, 214, 44))
            mouse.set_lighting("thumb", "spectrum", (0, 0, 0))
        print("Real session-bus test passed: uint16 DPI/time, byte RGB/threshold, int32 polling, double brightness.")
    finally:
        process.terminate()
        try:
            _, errors = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            _, errors = process.communicate()
        if errors:
            print(errors, file=sys.stderr)


if __name__ == "__main__":
    service() if "--service" in sys.argv else client()
