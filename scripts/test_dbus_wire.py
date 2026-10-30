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
        sync, screensaver = False, False
        @dbus.service.method("razer.devices", out_signature="as")
        def getDevices(self): return ["WIRETEST", "MATWIRETEST", "TRINITY", "KRAKEN"]

        @dbus.service.method("razer.daemon", out_signature="s")
        def version(self): return "3.12.4-simulated"

        @dbus.service.method("razer.devices", out_signature="b")
        def getSyncEffects(self): return self.sync

        @dbus.service.method("razer.devices", in_signature="b")
        def syncEffects(self, value): self.sync = bool(value)

        @dbus.service.method("razer.devices", out_signature="b")
        def getOffOnScreensaver(self): return self.screensaver

        @dbus.service.method("razer.devices", in_signature="b")
        def enableTurnOffOnScreensaver(self, value): self.screensaver = bool(value)

    class Mouse(dbus.service.Object):
        dpi, rate, idle, low, brightness = [1600, 1600], 1000, 300, 15, 75.0

        @dbus.service.method("razer.device.misc", out_signature="ai")
        def getVidPid(self): return [0x1532, 0x00A8]

        @dbus.service.method("razer.device.misc", out_signature="s")
        def getDeviceName(self): return "Razer Naga V2 Pro"

        @dbus.service.method("razer.device.misc", out_signature="s")
        def getDeviceType(self): return "mouse"

        @dbus.service.method("razer.device.misc", out_signature="b")
        def hasMatrix(self): return False

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

    class Mat(dbus.service.Object):
        brightness, frame = 75.0, None

        @dbus.service.method("razer.device.misc", out_signature="ai")
        def getVidPid(self): return [0x1532, 0x0C08]

        @dbus.service.method("razer.device.misc", out_signature="s")
        def getDeviceType(self): return "mousemat"

        @dbus.service.method("razer.device.misc", out_signature="s")
        def getDeviceName(self): return "Razer Firefly V2 Pro"

        @dbus.service.method("razer.device.misc", out_signature="b")
        def hasMatrix(self): return True

        @dbus.service.method("razer.device.misc", out_signature="ai")
        def getMatrixDimensions(self): return [1, 17]

        @dbus.service.method("razer.device.lighting.brightness", out_signature="d")
        def getBrightness(self): return self.brightness

        @dbus.service.method("razer.device.lighting.brightness", in_signature="d")
        def setBrightness(self, value):
            assert isinstance(value, dbus.Double)
            self.brightness = value

        @dbus.service.method("razer.device.lighting.chroma", in_signature="yyy")
        def setStatic(self, red, green, blue):
            assert all(isinstance(v, dbus.Byte) for v in (red, green, blue))
            assert (red, green, blue) == (68, 214, 44)

        @dbus.service.method("razer.device.lighting.chroma", in_signature="yyyyyy")
        def setBreathDual(self, red, green, blue, red2, green2, blue2):
            colors = (red, green, blue, red2, green2, blue2)
            assert all(isinstance(v, dbus.Byte) for v in colors)
            assert tuple(colors) == (68, 214, 44, 145, 70, 255)

        @dbus.service.method("razer.device.lighting.chroma", in_signature="i")
        def setWave(self, direction):
            assert isinstance(direction, dbus.Int32) and direction == 2

        @dbus.service.method("razer.device.lighting.chroma", in_signature="yyyy")
        def setReactive(self, red, green, blue, speed):
            assert all(isinstance(v, dbus.Byte) for v in (red, green, blue, speed))
            assert (red, green, blue, speed) == (68, 214, 44, 3)

        @dbus.service.method("razer.device.misc")
        def triggerReactive(self): pass

        @dbus.service.method("razer.device.lighting.chroma", in_signature="ay", byte_arrays=True)
        def setKeyRow(self, payload):
            assert isinstance(payload, dbus.ByteArray)
            self.frame = bytes(payload)
            assert self.frame == bytes([0, 0, 16]) + bytes([68, 214, 44]) * 17

        @dbus.service.method("razer.device.lighting.chroma")
        def setCustom(self):
            assert self.frame is not None, "Upload the frame before activating custom mode"

    class Trinity(Mouse):
        stages = (1, [(800, 800), (1600, 1600)])

        @dbus.service.method("razer.device.misc", out_signature="ai")
        def getVidPid(self): return [0x1532, 0x0067]

        @dbus.service.method("razer.device.misc", out_signature="s")
        def getDeviceName(self): return "Razer Naga Trinity"

        @dbus.service.method("razer.device.dpi", out_signature="(ya(qq))")
        def getDPIStages(self): return self.stages

        @dbus.service.method("razer.device.dpi", in_signature="ya(qq)")
        def setDPIStages(self, active, stages):
            assert isinstance(active, dbus.Byte)
            assert all(isinstance(v, dbus.UInt16) for pair in stages for v in pair)
            self.stages = (active, stages)

        @dbus.service.method("razer.device.macro", in_signature="ss")
        def addMacro(self, bind, sequence):
            import json
            assert bind == "M1" and json.loads(sequence)[0]["type"] == "MacroKey"

    class Kraken(dbus.service.Object):
        @dbus.service.method("razer.device.misc", out_signature="ai")
        def getVidPid(self): return [0x1532, 0x0504]

        @dbus.service.method("razer.device.misc", out_signature="s")
        def getDeviceName(self): return "Razer Kraken 7.1 Chroma"

        @dbus.service.method("razer.device.misc", out_signature="s")
        def getDeviceType(self): return "headset"

        @dbus.service.method("razer.device.lighting.kraken", in_signature="ai")
        def setCustom(self, components):
            assert all(isinstance(v, dbus.Int32) for v in components)
            assert list(components) == [68, 214, 44, 255]

    manager = Manager(name, "/org/razer")
    mouse = Mouse(name, "/org/razer/device/WIRETEST")
    mat = Mat(name, "/org/razer/device/MATWIRETEST")
    trinity = Trinity(name, "/org/razer/device/TRINITY")
    kraken = Kraken(name, "/org/razer/device/KRAKEN")
    print("ready", flush=True)
    GLib.MainLoop().run()


def client():
    from PyQt6.QtCore import QCoreApplication
    from naga import NagaController
    from mousemat import MouseMatController
    from openrazer_backend import OpenRazerController
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("Run this test using dbus-run-session")
    app = QCoreApplication([])
    process = subprocess.Popen([sys.executable, __file__, "--service"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        readable, _, _ = select.select([process.stdout], [], [], 10)
        if not readable or process.stdout.readline().strip() != "ready":
            raise RuntimeError("Simulated D-Bus service did not start")
        with NagaController("WIRETEST") as mouse:
            status = mouse.status()
            assert status["device"]["serial"] == "WIRETEST"
            assert status["values"]["dpi"] == [1600, 1600]
            for field, value in (("dpi", [800, 900]), ("poll_rate", 500),
                                 ("idle_seconds", 120), ("low_battery_percent", 20),
                                 ("logo_brightness", 50)):
                assert mouse.set_value(field, value)["result"] == "daemon_readback_matched"
            mouse.set_lighting("logo", "static", (68, 214, 44))
            mouse.set_lighting("thumb", "spectrum", (0, 0, 0))
        with MouseMatController() as mat:
            status = mat.status()
            assert status["device"]["serial"] == "MATWIRETEST"
            assert status["values"]["matrix_dimensions"] == [1, 17]
            assert mat.set_brightness(40)["result"] == "daemon_readback_matched"
            mat.set_effect("static", (68, 214, 44))
            mat.set_effect("breathing_dual", (68, 214, 44), (145, 70, 255))
            mat.set_effect("wave", direction=2)
            mat.set_effect("reactive", (68, 214, 44), speed=3)
            mat.trigger_reactive()
            mat.set_custom([(68, 214, 44)] * 17)
        with OpenRazerController() as generic:
            found = generic.discover()
            assert {d["type"] for d in found["devices"]} == {"mouse", "mousemat", "headset"}
            assert len(found["devices"]) == 4 and not found["errors"]
            generic.global_setting("syncEffects", False)
            generic.global_setting("enableTurnOffOnScreensaver", True)
        with OpenRazerController("TRINITY") as trinity:
            assert trinity.status()["device"]["name"] == "Razer Naga Trinity"
            trinity.apply("razer.device.dpi|setDPI", [800,900])
            result = trinity.apply("razer.device.dpi|setDPIStages", [1, [(400,400),(800,900)]])
            assert result["readback"] == (1, [(400,400),(800,900)])
            trinity.apply("razer.device.macro|addMacro", ["M1", '[{"type":"MacroKey","key_id":"A","state":"DOWN","pre_pause":0}]'])
        with OpenRazerController("KRAKEN") as kraken:
            kraken.apply("razer.device.lighting.kraken|setCustom", [[68,214,44,255]])
        with OpenRazerController("MATWIRETEST") as generic_mat:
            generic_mat.set_matrix([[(68,214,44)]*17])
        print("Real session-bus test passed: Qt and Jeepney, generic discovery, Trinity DPI stages, macros, Kraken arrays, lighting and matrix frames.")
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
