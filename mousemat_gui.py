"""Capability-aware RGB mouse-mat controls and hardware-free previews."""
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen, QLinearGradient
from PyQt6.QtWidgets import QWidget, QComboBox, QLineEdit, QCheckBox, QSpinBox, QGridLayout

from barracuda import color_value
from barracuda_gui import GREEN, MUTED, button, card, column, row, text
from mousemat import MouseMatController, MODELS, EFFECTS


def preview_status(pid):
    model = MODELS[pid]
    device = {"serial": "PREVIEW", "name": model["name"],
              "usb_id": f"1532:{pid:04x}", "connection": "USB"}
    return {"daemon_version": "Preview", "devices": [device], "device": device,
            "values": {"brightness": 75, "matrix_dimensions": [1, model["columns"]], "sync_effects": False},
            "capabilities": {"brightness": True, "custom": True, "trigger_reactive": True,
                             "effects": [key for key in EFFECTS if key != "wave" or model["wave"]]},
            "errors": {}, "hardware_tested": False}


class MatArt(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setMinimumSize(220, 155)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width() / 370, self.height() / 220)
        p.translate((self.width() - 370 * scale) / 2, (self.height() - 220 * scale) / 2)
        p.scale(scale, scale)
        colors = self.page.preview_colors()
        gradient = QLinearGradient(QPointF(30, 85), QPointF(340, 155))
        for i, color in enumerate(colors):
            gradient.setColorAt(i / max(1, len(colors) - 1), QColor(color))
        rect = QRectF(24, 48, 322, 148)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((23, 14), (12, 30)):
            glow = QColor(colors[0]); glow.setAlpha(alpha)
            p.setPen(QPen(glow, width))
            p.drawRoundedRect(rect, 14, 14)
        p.setBrush(QColor("#151b18"))
        p.setPen(QPen(gradient, 4))
        p.drawRoundedRect(rect, 14, 14)
        p.setPen(QPen(QColor("#212b24"), 1))
        for y in range(65, 183, 6):
            p.drawLine(QPointF(38, y), QPointF(331, y))
        p.setPen(QPen(QColor("#576b57"), 4))
        p.drawLine(QPointF(47, 48), QPointF(47, 15))
        p.setPen(QPen(QColor("#759471"), 2))
        for x, height in ((290, 8), (297, 15), (304, 11)):
            p.drawLine(QPointF(x, 80), QPointF(x, 80 + height))


class MouseMatPage(QWidget):
    def __init__(self, host, factory=MouseMatController):
        super().__init__()
        self.host, self.factory = host, factory
        self.serial, self.data, self.caps = None, {}, {}
        self.loading, self.dirty = False, set()
        self.slot_colors, self.apply_buttons = [], {}
        outer = column(self, 14)
        hero, box = card(True)
        line = row(18)
        self.art = MatArt(self)
        line.addWidget(self.art, 3)
        words = column(spacing=8)
        words.addWidget(text("CHROMA RGB MOUSE MATS", 10, GREEN, 600))
        self.model_title = text("LIGHT UP YOUR DESK", 25, weight=700, wrap=True)
        words.addWidget(self.model_title)
        words.addWidget(text("A little colour. Your whole setup.", 13, MUTED))
        words.addWidget(text("EXPERIMENTAL · OWNER TESTING NEEDED", 10, "#dbbd76", 600, wrap=True))
        self.connection = text("Connect a mat by USB, or explore the preview.", 11, MUTED, wrap=True)
        words.addWidget(self.connection)
        line.addLayout(words, 5)
        box.addLayout(line)
        bar = row()
        self.devices = QComboBox()
        self.devices.setAccessibleName("Razer RGB mouse mat")
        self.devices.addItem("No mat selected", None)
        self.devices.currentIndexChanged.connect(self.change_device)
        bar.addWidget(self.devices, 1)
        self.scan_button = self.host.action("Scan for mats", self.refresh)
        bar.addWidget(self.scan_button)
        self.preview = QCheckBox("Preview without a mat")
        self.preview.toggled.connect(self.preview_changed)
        bar.addWidget(self.preview)
        box.addLayout(bar)
        self.preview_model = QComboBox()
        self.preview_model.setAccessibleName("Mouse-mat preview model")
        for pid, model in MODELS.items():
            self.preview_model.addItem(model["name"], pid)
        self.preview_model.setVisible(False)
        self.preview_model.currentIndexChanged.connect(self.change_preview_model)
        box.addWidget(self.preview_model)
        box.addWidget(text("Illustrative colour preview · not a live LED reading", 10, MUTED))
        outer.addWidget(hero)

        panel, box = card()
        bar = row()
        bar.addWidget(text("BRIGHTNESS", 11, MUTED, 600), 1)
        self.current_brightness = text("Current: —", 12, MUTED)
        bar.addWidget(self.current_brightness)
        self.brightness = QSpinBox()
        self.brightness.setRange(0, 100)
        self.brightness.setValue(75)
        self.brightness.setSuffix("%")
        self.brightness.setAccessibleName("Mouse-mat brightness")
        self.brightness.valueChanged.connect(self.brightness_changed)
        bar.addWidget(self.brightness)
        bar.addWidget(self.apply_button("brightness", "Apply brightness", self.apply_brightness))
        box.addLayout(bar)
        outer.addWidget(panel)

        panel, box = card()
        box.addWidget(text("LIGHTING EFFECT", 11, MUTED, 600))
        self.effect = QComboBox()
        self.effect.setAccessibleName("Mouse-mat lighting effect")
        self.effect.currentIndexChanged.connect(self.effect_changed)
        box.addWidget(self.effect)
        bar = row()
        self.color, self.secondary = QLineEdit("44D62C"), QLineEdit("9146FF")
        for field, label in ((self.color, "Primary RGB colour"), (self.secondary, "Secondary RGB colour")):
            field.setMaxLength(7)
            field.setAccessibleName(label)
            field.setPlaceholderText(label)
            field.textChanged.connect(lambda _: self.art.update())
            bar.addWidget(field, 1)
        self.direction = QComboBox()
        self.direction.addItem("Wave →", 1)
        self.direction.addItem("Wave ←", 2)
        self.direction.setAccessibleName("Mouse-mat wave direction")
        bar.addWidget(self.direction)
        self.speed = QComboBox()
        for value in range(1, 5):
            self.speed.addItem(f"Reactive speed {value}", value)
        self.speed.setCurrentIndex(1)
        self.speed.setAccessibleName("Mouse-mat reactive speed")
        bar.addWidget(self.speed)
        box.addLayout(bar)
        bar = row()
        bar.addWidget(self.apply_button("effect", "Apply effect", self.apply_effect))
        bar.addWidget(self.apply_button("trigger_reactive", "Test reactive pulse", self.trigger_reactive, "ghost"))
        bar.addStretch()
        box.addLayout(bar)
        box.addWidget(text("Reactive pulses are triggered manually here. Automatic mouse-click reactions are not included.", 11, MUTED, wrap=True))
        outer.addWidget(panel)

        panel, box = card()
        bar = row()
        bar.addWidget(text("CUSTOM COLOURS", 11, MUTED, 600), 1)
        self.fill_button = button("Fill with primary colour", self.fill_colors, "ghost")
        bar.addWidget(self.fill_button)
        box.addLayout(bar)
        self.matrix_note = text("Scan a mat to load its lighting layout.", 11, MUTED, wrap=True)
        box.addWidget(self.matrix_note)
        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        box.addLayout(self.grid)
        bar = row()
        bar.addWidget(self.apply_button("custom", "Apply custom colours", self.apply_custom))
        bar.addStretch()
        box.addLayout(bar)
        outer.addWidget(panel)
        self.help = text("Requires a current OpenRazer installation on the host. Connect the mat by USB.", 11, MUTED, wrap=True)
        outer.addWidget(self.help)
        outer.addWidget(text("Firefly · Firefly HyperFlux · Firefly V2 / V2 Pro · Goliathus Chroma / Extended / 3XL · Strider Chroma", 10, "#75847a", wrap=True))
        self.update_enabled()

    def apply_button(self, key, title, callback, kind="primary"):
        widget = self.host.action(title, callback, kind)
        self.apply_buttons[key] = widget
        return widget

    def brightness_changed(self, _):
        if not self.loading:
            self.dirty.add("brightness")
        self.art.update()

    def effect_changed(self, _=None):
        if not hasattr(self, "color"):
            return
        effect = self.effect.currentData()
        editable = bool(self.caps.get("effects")) and not self.host.busy
        self.color.setEnabled(editable and effect in ("static", "breathing", "breathing_dual", "reactive"))
        self.secondary.setEnabled(editable and effect == "breathing_dual")
        self.direction.setVisible(effect == "wave")
        self.direction.setEnabled(editable)
        self.speed.setVisible(effect == "reactive")
        self.speed.setEnabled(editable)
        if "trigger_reactive" in self.apply_buttons:
            self.apply_buttons["trigger_reactive"].setEnabled(self.can_apply("trigger_reactive") and effect == "reactive")
        self.art.update()

    def can_apply(self, field):
        capability = "effects" if field == "effect" else field
        return bool(self.serial and self.caps.get(capability) and not self.preview.isChecked()
                    and not self.host.busy and self.data.get("sync_effects") is False)

    def update_enabled(self):
        preview = self.preview.isChecked()
        for field, widget in self.apply_buttons.items():
            widget.setEnabled(self.can_apply(field))
            widget.setToolTip("Preview only — hardware commands are disabled" if preview else
                              "Select a connected mat with this feature and turn off OpenRazer lighting sync")
        self.brightness.setEnabled(bool(self.caps.get("brightness")) and not self.host.busy)
        self.effect.setEnabled(bool(self.caps.get("effects")) and not self.host.busy)
        for field in self.slot_colors:
            field.setEnabled(bool(self.caps.get("custom")) and not self.host.busy)
        self.fill_button.setEnabled(bool(self.caps.get("custom")) and not self.host.busy)
        self.devices.setEnabled(not preview and not self.host.busy)
        self.scan_button.setEnabled(not preview and not self.host.busy)
        self.preview.setEnabled(not self.host.busy)
        self.preview_model.setEnabled(preview and not self.host.busy)
        self.effect_changed()

    def preview_changed(self, enabled):
        self.preview_model.setVisible(enabled)
        self.clear("Preview ended. Scan for a connected mat.")
        if enabled:
            self.change_preview_model()
        else:
            self.host.notify("Mouse-mat preview ended. Scan for a connected mat.")

    def change_preview_model(self, _=None):
        if self.preview.isChecked():
            self.clear("")
            self.receive(preview_status(self.preview_model.currentData()))
            self.host.notify("Mouse-mat preview: example values. Hardware commands are disabled.")

    def rebuild_slots(self, count):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.slot_colors = []
        for index in range(count):
            field = QLineEdit("44D62C")
            field.setMaxLength(7)
            field.setAccessibleName(f"Mouse-mat matrix slot {index + 1} RGB colour")
            field.setToolTip(f"Driver matrix slot {index + 1} · six-digit RGB colour")
            field.textChanged.connect(lambda _: self.art.update())
            label = text(str(index + 1).zfill(2), 10, MUTED)
            self.grid.addWidget(label, (index // 4) * 2, index % 4)
            self.grid.addWidget(field, (index // 4) * 2 + 1, index % 4)
            self.slot_colors.append(field)

    def clear(self, message):
        self.serial, self.data, self.caps = None, {}, {}
        self.dirty.clear()
        self.loading = True
        self.devices.clear()
        self.devices.addItem("No mat selected", None)
        self.effect.clear()
        self.loading = False
        self.model_title.setText("LIGHT UP YOUR DESK")
        self.current_brightness.setText("Current: —")
        self.connection.setText(message)
        self.matrix_note.setText("Scan a mat to load its lighting layout.")
        self.rebuild_slots(0)
        self.update_enabled()

    def change_device(self, _):
        if self.loading:
            return
        serial = self.devices.currentData()
        self.serial, self.data, self.caps = None, {}, {}
        self.dirty.clear()
        self.current_brightness.setText("Current: —")
        self.update_enabled()
        if serial:
            self.refresh()

    def refresh(self):
        if self.preview.isChecked():
            self.host.notify("Mouse-mat preview is active. Uncheck it to scan real devices.")
            return False
        serial = self.devices.currentData()
        def scan(controller):
            found = controller.discover()
            if serial and any(d["serial"] == serial for d in found["devices"]):
                controller.serial = serial
            elif len(found["devices"]) == 1:
                controller.serial = found["devices"][0]["serial"]
            else:
                return found
            return controller.status()
        return self.host.run("Scanning OpenRazer for RGB mouse mats", scan, self.receive,
                             lambda: self.clear("Mat unavailable. See Diagnostics for the error."),
                             controller_factory=self.factory, device=serial)

    def receive(self, result):
        selected = result.get("device", {})
        serial = selected.get("serial")
        changed = serial != self.serial
        if changed:
            self.dirty.clear()
        self.serial = serial
        self.data, self.caps = result.get("values", {}), result.get("capabilities", {})
        self.loading = True
        try:
            self.devices.clear()
            if not serial:
                self.devices.addItem("Choose a mat" if result["devices"] else "No Razer RGB mat detected", None)
            for device in result["devices"]:
                self.devices.addItem(device["name"].removeprefix("Razer ") + " · " + device["serial"], device["serial"])
            if serial:
                self.devices.setCurrentIndex(self.devices.findData(serial))
            current = None if changed else self.effect.currentData()
            self.effect.clear()
            for key in self.caps.get("effects", []):
                self.effect.addItem(EFFECTS[key][0], key)
            self.effect.setCurrentIndex(max(0, self.effect.findData(current)))
            if "brightness" in self.data and "brightness" not in self.dirty:
                self.brightness.setValue(round(self.data["brightness"]))
            count = self.data.get("matrix_dimensions", [1, 0])[1] if self.caps.get("custom") else 0
            if changed or count != len(self.slot_colors):
                self.rebuild_slots(count)
            self.matrix_note.setText("One colour controls the whole RGB edge." if count == 1 else
                                     f"{count} driver matrix slots. Their order and visible placement depend on the mat." if count else
                                     "Custom colours are unavailable in this driver.")
        finally:
            self.loading = False
        self.model_title.setText(selected.get("name", "LIGHT UP YOUR DESK").removeprefix("Razer ").upper())
        level = self.data.get("brightness")
        self.current_brightness.setText(f"Current: {round(level)}%" if level is not None else "Current: —")
        self.connection.setText("PREVIEW · EXAMPLE VALUES · COMMANDS DISABLED" if self.preview.isChecked() else
                                selected.get("usb_id", "Select or connect a mat") +
                                (" · OpenRazer " + result["daemon_version"] if serial else ""))
        sync = self.data.get("sync_effects")
        self.help.setText("Turn off OpenRazer lighting sync before applying mat lighting; sync can affect other devices."
                          if sync is True else "Lighting sync state is unavailable. Refresh before applying lighting."
                          if serial and sync is not False else
                          "Requires a current OpenRazer installation on the host. Connect the mat by USB.")
        self.update_enabled()
        if not self.preview.isChecked():
            self.host.notify("Mat status read from OpenRazer." if serial and not result.get("errors") else
                             "Partial mat status; see Diagnostics." if serial else "Select a mat, connect one, or use Preview without a mat.")

    def preview_colors(self):
        if not hasattr(self, "color"):
            return [GREEN, GREEN]
        effect = self.effect.currentData()
        if effect == "off":
            return ["#263329", "#263329"]
        if effect in ("spectrum", "wave", "breathing_random"):
            return ["#44D62C", "#24C8CE", "#9146FF", "#EC4793"]
        try:
            first = "#" + bytes(color_value(self.color.text())).hex()
            second = "#" + bytes(color_value(self.secondary.text())).hex() if effect == "breathing_dual" else first
            return [first, second]
        except ValueError:
            return [GREEN, GREEN]

    def fill_colors(self):
        try:
            value = bytes(color_value(self.color.text())).hex().upper()
        except ValueError:
            self.host.notify("Use a six-digit primary RGB colour, for example 44D62C.", error=True)
            return False
        for field in self.slot_colors:
            field.setText(value)
        return True

    def apply_brightness(self):
        if not self.can_apply("brightness"):
            return False
        value = self.brightness.value()
        def done(result):
            self.data["brightness"] = result["value"]
            self.dirty.discard("brightness")
            self.current_brightness.setText(f"Current: {round(result['value'])}%")
            self.host.notify("Mat brightness applied. OpenRazer readback matched.")
        return self.host.run("Applying mat brightness", lambda c: c.set_brightness(value), done,
                             controller_factory=self.factory, device=self.serial)

    def apply_effect(self):
        if not self.can_apply("effect"):
            return False
        mode = self.effect.currentData()
        try:
            color = color_value(self.color.text()) if mode in ("static", "breathing", "breathing_dual", "reactive") else None
            secondary = color_value(self.secondary.text()) if mode == "breathing_dual" else None
        except ValueError:
            self.host.notify("Use six-digit RGB colours, for example 44D62C.", error=True)
            return False
        direction, speed = self.direction.currentData(), self.speed.currentData()
        return self.send("Applying mat lighting", lambda c: c.set_effect(mode, color, secondary, direction, speed))

    def apply_custom(self):
        if not self.can_apply("custom"):
            return False
        try:
            colors = [color_value(field.text()) for field in self.slot_colors]
        except ValueError:
            self.host.notify("Every matrix slot needs a six-digit RGB colour.", error=True)
            return False
        return self.send("Applying custom mat colours", lambda c: c.set_custom(colors))

    def trigger_reactive(self):
        if not self.can_apply("trigger_reactive") or self.effect.currentData() != "reactive":
            return False
        return self.send("Triggering mat reactive pulse", lambda c: c.trigger_reactive())

    def send(self, title, operation):
        return self.host.run(title, operation,
                             lambda _: self.host.notify("Mat lighting command accepted by OpenRazer. Confirm it visually."),
                             controller_factory=self.factory, device=self.serial)
