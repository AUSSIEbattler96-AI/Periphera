"""Capability-aware Naga V2 Pro page. Preview mode cannot send commands."""
import copy
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget, QSpinBox, QComboBox, QLineEdit, QCheckBox, QStackedWidget

from barracuda import color_value
from barracuda_gui import GREEN, MUTED, TEXT, RED, button, card, column, row, text, divider
from naga import NagaController

PREVIEW = {
    "daemon_version": "Preview", "hardware_tested": False,
    "devices": [{"serial": "PREVIEW", "name": "Razer Naga V2 Pro", "usb_id": "1532:00a8",
                 "connection": "2.4 GHz receiver"}],
    "device": {"serial": "PREVIEW", "connection": "2.4 GHz receiver", "usb_id": "1532:00a8"},
    "values": {"dpi": [1600, 1600], "max_dpi": 30000, "poll_rate": 1000,
               "poll_rates": [125, 500, 1000], "battery_percent": 76, "charging": False,
               "idle_seconds": 300, "low_battery_percent": 15,
               "logo_brightness": 75, "thumb_brightness": 75, "sync_effects": False},
    "capabilities": {"dpi": True, "poll_rate": True, "idle_seconds": True,
                     "low_battery_percent": True, "logo_brightness": True, "thumb_brightness": True,
                     "logo_effects": ["static", "spectrum", "breathing", "off"],
                     "thumb_effects": ["static", "spectrum", "breathing", "off"]},
    "errors": {},
}


class MouseArt(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(210, 180)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = min(self.width()/330, self.height()/240)
        p.translate((self.width()-330*s)/2, (self.height()-240*s)/2)
        p.scale(s, s)
        glow = QRadialGradient(QPointF(170, 130), 150)
        glow.setColorAt(0, QColor(68, 214, 44, 24))
        glow.setColorAt(1, QColor(68, 214, 44, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(10, 0, 310, 240))
        body = QPainterPath(QPointF(125, 22))
        body.cubicTo(100, 23, 82, 55, 83, 108)
        body.cubicTo(65, 163, 84, 217, 151, 226)
        body.cubicTo(205, 228, 251, 214, 251, 172)
        body.cubicTo(253, 126, 232, 88, 222, 51)
        body.cubicTo(214, 21, 180, 16, 125, 22)
        p.setPen(QPen(QColor("#505b51"), 2))
        p.setBrush(QColor("#222b25"))
        p.drawPath(body)
        p.setPen(QPen(QColor("#0b100d"), 3))
        p.drawLine(QPointF(166, 24), QPointF(170, 118))
        p.drawLine(QPointF(101, 117), QPointF(226, 112))
        p.setBrush(QColor("#0a110b"))
        p.setPen(QPen(QColor("#637263"), 1))
        p.drawRoundedRect(QRectF(154, 40, 23, 45), 7, 7)
        p.setPen(QPen(QColor(GREEN), 1.5))
        for y in (48, 55, 62, 69, 76):
            p.drawLine(QPointF(159, y), QPointF(172, y))
        p.setBrush(QColor("#101912"))
        for y in range(4):
            for x in range(3):
                p.drawRoundedRect(QRectF(86+x*15, 125+y*18, 11, 13), 2, 2)
        p.setPen(QPen(QColor(GREEN), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for x, h in ((174, 13), (182, 23), (190, 17)):
            p.drawLine(QPointF(x, 173-h/2), QPointF(x, 173+h/2))


class MousePage(QWidget):
    def __init__(self, window, factory=NagaController):
        super().__init__()
        self.host, self.factory = window, factory
        self.data, self.caps, self.dirty = {}, {}, set()
        self.serial, self.loading = None, False
        self.control_groups, self.apply_buttons = {}, {}
        outer = column(self, 14)
        hero, layout = card(True)
        line = row(16)
        line.addWidget(MouseArt(), 3)
        words = column(spacing=6)
        words.addWidget(text("WIRELESS MMO GAMING MOUSE", 10, GREEN, 600))
        words.addWidget(text("NAGA V2 PRO", 32, weight=700))
        words.addWidget(text("Precision, on your terms.", 13, MUTED))
        words.addSpacing(10)
        words.addWidget(text("EXPERIMENTAL · OWNER TESTING NEEDED", 10, "#dbbd76", 600))
        self.connection = text("Connect a mouse, or explore the preview.", 12, MUTED, wrap=True)
        words.addWidget(self.connection)
        line.addLayout(words, 5)
        layout.addLayout(line)
        bar = row()
        self.devices = QComboBox()
        self.devices.setMinimumWidth(200)
        self.devices.setAccessibleName("Naga V2 Pro device")
        self.devices.addItem("No mouse selected", None)
        self.devices.currentIndexChanged.connect(self.change_device)
        bar.addWidget(self.devices, 1)
        self.scan_button = self.host.action("Scan for mouse", self.refresh)
        bar.addWidget(self.scan_button)
        self.preview = QCheckBox("Preview without a mouse")
        self.preview.toggled.connect(self.preview_changed)
        bar.addWidget(self.preview)
        layout.addLayout(bar)
        outer.addWidget(hero)

        stats = row(14)
        self.stats = {}
        for key, title in (("battery_percent", "BATTERY"), ("dpi", "SENSITIVITY"), ("poll_rate", "POLLING RATE")):
            panel, box = card()
            box.setContentsMargins(18, 12, 18, 12)
            box.addWidget(text(title, 10, MUTED, 600))
            label = text("—", 25, GREEN if key == "battery_percent" else TEXT, 600)
            box.addWidget(label)
            self.stats[key] = label
            stats.addWidget(panel, 1)
        outer.addLayout(stats)

        tabs = row(7)
        self.tabs, self.panels = {}, QStackedWidget()
        for i, name in enumerate(("Performance", "Lighting", "Power")):
            b = button(name, lambda _=False, n=i: self.tab(n), "preset", True)
            self.tabs[i] = b
            tabs.addWidget(b)
        tabs.addStretch()
        outer.addLayout(tabs)
        outer.addWidget(self.panels)
        self.performance()
        self.lighting()
        self.power()
        self.tab(0)
        self.help = text("Requires OpenRazer 3.10.3+ on the host. Use the USB cable or original 2.4 GHz receiver.", 11, MUTED, wrap=True)
        outer.addWidget(self.help)
        outer.addWidget(text("Button remapping, onboard profiles and HyperScroll tuning are not included.", 11, "#75847a", wrap=True))
        self.update_enabled()

    def tab(self, index):
        self.panels.setCurrentIndex(index)
        for i, button_ in self.tabs.items():
            button_.setChecked(i == index)

    def spin(self, low, high, value, suffix, field):
        s = QSpinBox()
        s.setRange(low, high)
        s.setValue(value)
        s.setSuffix(suffix)
        s.setAccessibleName(field.replace("_", " "))
        s.valueChanged.connect(lambda _: self.mark_dirty(field))
        return s

    def mark_dirty(self, field):
        if not self.loading:
            self.dirty.add(field)

    def register(self, field, widgets, callback, caption="Apply"):
        b = self.host.action(caption, callback, "primary")
        self.apply_buttons[field] = b
        self.control_groups[field] = widgets
        return b

    def performance(self):
        panel, box = card()
        box.addWidget(text("SENSITIVITY", 11, MUTED, 600))
        line = row()
        self.x = self.spin(100, 30000, 1600, " DPI", "dpi")
        self.y = self.spin(100, 30000, 1600, " DPI", "dpi")
        line.addWidget(text("X", 12, MUTED))
        line.addWidget(self.x, 1)
        line.addWidget(text("Y", 12, MUTED))
        line.addWidget(self.y, 1)
        line.addWidget(self.register("dpi", [self.x, self.y], lambda: self.apply_value("dpi", [self.x.value(), self.y.value()]), "Apply DPI"))
        box.addLayout(line)
        box.addWidget(text("Separate X/Y sensitivity · 100–30,000 DPI · Apply when ready", 11, MUTED))
        box.addWidget(divider())
        line = row()
        line.addWidget(text("POLLING RATE", 11, MUTED, 600), 1)
        self.poll_rate = QComboBox()
        for value in (125, 500, 1000):
            self.poll_rate.addItem(f"{value} Hz", value)
        self.poll_rate.setCurrentIndex(2)
        self.poll_rate.setAccessibleName("Mouse polling rate")
        self.poll_rate.currentIndexChanged.connect(lambda _: self.mark_dirty("poll_rate"))
        line.addWidget(self.poll_rate)
        line.addWidget(self.register("poll_rate", [self.poll_rate], lambda: self.apply_value("poll_rate", self.poll_rate.currentData()), "Apply rate"))
        box.addLayout(line)
        self.panels.addWidget(panel)

    def lighting(self):
        panel, box = card()
        self.zone_effects, self.zone_colors, self.zone_brightness = {}, {}, {}
        for zone, name in (("logo", "LOGO"), ("thumb", "THUMB GRID")):
            box.addWidget(text(name, 11, MUTED, 600))
            line = row()
            mode = QComboBox()
            for effect in ("static", "spectrum", "breathing", "off"):
                mode.addItem(effect.title(), effect)
            color = QLineEdit("44D62C")
            color.setMaxLength(7)
            color.setMaximumWidth(110)
            color.setAccessibleName(name + " hex color")
            level = self.spin(0, 100, 75, "%", zone + "_brightness")
            self.zone_effects[zone], self.zone_colors[zone], self.zone_brightness[zone] = mode, color, level
            mode.currentIndexChanged.connect(lambda _, z=zone: self.effect_changed(z))
            line.addWidget(mode, 1)
            line.addWidget(color)
            line.addWidget(self.register(zone + "_effects", [mode, color], lambda _=False, z=zone: self.apply_effect(z), "Apply effect"))
            line.addWidget(level)
            line.addWidget(self.register(zone + "_brightness", [level], lambda _=False, z=zone: self.apply_value(z + "_brightness", self.zone_brightness[z].value()), "Set level"))
            box.addLayout(line)
        box.addWidget(text("Hex color is used for Static and Breathing. Confirm lighting visually after applying.", 11, MUTED, wrap=True))
        self.panels.addWidget(panel)

    def power(self):
        panel, box = card()
        for field, name, widget in (
            ("idle_seconds", "SLEEP AFTER", self.spin(60, 900, 300, " sec", "idle_seconds")),
            ("low_battery_percent", "LOW BATTERY THRESHOLD", self.spin(5, 50, 15, "%", "low_battery_percent"))):
            setattr(self, field, widget)
            line = row()
            line.addWidget(text(name, 11, MUTED, 600), 1)
            line.addWidget(widget)
            line.addWidget(self.register(field, [widget], lambda _=False, f=field, w=widget: self.apply_value(f, w.value())))
            box.addLayout(line)
        box.addWidget(text("Mouse sleep is measured in seconds. Battery readings can be unavailable while asleep.", 11, MUTED, wrap=True))
        self.panels.addWidget(panel)

    def update_enabled(self):
        preview = hasattr(self, "preview") and self.preview.isChecked()
        for field, controls in self.control_groups.items():
            available = bool(self.caps.get(field))
            for control in controls:
                control.setEnabled(available and not self.host.busy)
            self.apply_buttons[field].setEnabled(available and bool(self.serial) and not preview and not self.host.busy)
            self.apply_buttons[field].setToolTip("Preview only — commands are disabled" if preview else
                                                "Unavailable until the driver reports this feature" if not available else "Apply to selected mouse")
        self.devices.setEnabled(not preview and not self.host.busy)
        self.preview.setEnabled(not self.host.busy)
        self.scan_button.setEnabled(not self.host.busy and not preview)
        for zone in self.zone_colors:
            self.effect_changed(zone)

    def effect_changed(self, zone):
        enabled = bool(self.caps.get(zone + "_effects")) and not self.host.busy
        self.zone_colors[zone].setEnabled(enabled and self.zone_effects[zone].currentData() in ("static", "breathing"))

    def preview_changed(self, enabled):
        self.dirty.clear()
        self.serial = None
        if enabled:
            self.receive(copy.deepcopy(PREVIEW))
            self.host.notify("Mouse preview: example values. Hardware commands are disabled.")
        else:
            self.clear("Preview ended. Scan for a connected mouse.")
            self.host.notify("Preview ended. Scan for a connected mouse.")

    def clear(self, message):
        self.serial, self.data, self.caps = None, {}, {}
        self.loading = True
        self.devices.clear()
        self.devices.addItem("No mouse selected", None)
        self.loading = False
        for label in self.stats.values():
            label.setText("—")
        self.connection.setText(message)
        self.update_enabled()

    def change_device(self, _):
        if self.loading:
            return
        self.serial = self.devices.currentData()
        self.dirty.clear()
        self.data, self.caps = {}, {}
        self.update_enabled()
        if self.serial:
            self.refresh()

    def refresh(self):
        if self.preview.isChecked():
            self.host.notify("Mouse preview is active. Uncheck it to scan real devices.")
            return False
        serial = self.devices.currentData()
        def scan(c):
            found = c.discover()
            choices = found["devices"]
            if serial and any(d["serial"] == serial for d in choices):
                c.serial = serial
            elif len(choices) == 1:
                c.serial = choices[0]["serial"]
            else:
                return found
            return c.status()
        return self.host.run("Scanning OpenRazer for Naga V2 Pro", scan, self.receive,
                             lambda: self.clear("Mouse unavailable. See Diagnostics for the error."),
                             controller_factory=self.factory, device=serial)

    def receive(self, result):
        selected = result.get("device", {})
        serial = selected.get("serial")
        if serial != self.serial:
            self.dirty.clear()
        self.serial, self.data, self.caps = serial, result.get("values", {}), result.get("capabilities", {})
        self.loading = True
        try:
            self.devices.clear()
            if not serial:
                self.devices.addItem("Choose a mouse" if result["devices"] else "No Naga V2 Pro detected", None)
            for device in result["devices"]:
                self.devices.addItem(device["connection"] + " · " + device["serial"], device["serial"])
            if serial:
                self.devices.setCurrentIndex(self.devices.findData(serial))
            dpi = self.data.get("dpi")
            if dpi and "dpi" not in self.dirty:
                self.x.setValue(dpi[0]); self.y.setValue(dpi[1])
            if "poll_rate" in self.data and "poll_rate" not in self.dirty:
                self.poll_rate.setCurrentIndex(self.poll_rate.findData(self.data["poll_rate"]))
            for field in ("idle_seconds", "low_battery_percent", "logo_brightness", "thumb_brightness"):
                if field in self.data and field not in self.dirty:
                    control = self.zone_brightness[field.split("_")[0]] if field.endswith("brightness") else getattr(self, field)
                    control.setValue(round(self.data[field]))
            for zone, combo in self.zone_effects.items():
                current = combo.currentData()
                combo.clear()
                for effect in self.caps.get(zone + "_effects", []):
                    combo.addItem(effect.title(), effect)
                idx = combo.findData(current)
                combo.setCurrentIndex(max(0, idx))
        finally:
            self.loading = False
        self.paint_values()
        preview = self.preview.isChecked()
        self.connection.setText("PREVIEW · EXAMPLE VALUES · COMMANDS DISABLED" if preview else
                                selected.get("connection", "Select or connect a mouse") +
                                (" · OpenRazer " + result["daemon_version"] if serial else ""))
        self.help.setText("Turn off OpenRazer lighting sync before applying per-mouse lighting; sync can affect other devices."
                          if self.data.get("sync_effects") else
                          "Requires OpenRazer 3.10.3+ on the host. Use the USB cable or original 2.4 GHz receiver.")
        self.update_enabled()
        if not preview:
            self.host.notify("Mouse status read from OpenRazer." if serial and not result.get("errors") else
                             "Partial mouse status; see Diagnostics." if serial else
                             "No Naga V2 Pro selected. Connect one or use Preview without a mouse.")

    def paint_values(self):
        battery = self.data.get("battery_percent")
        dpi, rate = self.data.get("dpi"), self.data.get("poll_rate")
        self.stats["battery_percent"].setText(f"{round(battery)}%" if battery is not None else "—")
        self.stats["dpi"].setText(f"{dpi[0]:,}" if dpi and dpi[0] == dpi[1] else f"{dpi[0]} / {dpi[1]}" if dpi else "—")
        self.stats["poll_rate"].setText(f"{rate:,} Hz" if rate is not None else "—")

    def apply_value(self, field, value):
        if self.preview.isChecked() or not self.serial or not self.caps.get(field):
            return False
        def done(result):
            self.data[field] = result["value"]
            self.dirty.discard(field)  # Inputs are disabled throughout the operation.
            self.paint_values()
            self.host.notify("Mouse setting applied. OpenRazer readback matched; hardware testing is still needed.")
        return self.host.run("Applying mouse setting", lambda c: c.set_value(field, value), done,
                             controller_factory=self.factory, device=self.serial)

    def apply_effect(self, zone):
        if self.preview.isChecked() or not self.serial or not self.caps.get(zone + "_effects"):
            return False
        try:
            color = color_value(self.zone_colors[zone].text())
        except ValueError:
            self.host.notify("Use a six-digit RGB color, for example 44D62C.", error=True)
            return False
        mode = self.zone_effects[zone].currentData()
        return self.host.run("Applying mouse lighting", lambda c: c.set_lighting(zone, mode, color),
                             lambda _: self.host.notify("Lighting command accepted by OpenRazer. Confirm it on the mouse."),
                             controller_factory=self.factory, device=self.serial)
