"""BlackWidow lighting, matrix painting and six-key macro editing."""
import json

from PyQt6.QtCore import Qt, QRectF, QSettings
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QWidget, QComboBox, QCheckBox, QLineEdit, QSpinBox,
                            QColorDialog, QTabWidget, QTableWidget, QTableWidgetItem,
                            QAbstractItemView, QHeaderView, QMessageBox)

from barracuda import color_value
from barracuda_gui import APP_ID, GREEN, MUTED, button, card, column, row, text
from blackwidow import BlackWidowController, MODELS, EFFECTS, MACRO_KEYS
from keyboard_macros import shortcut_events, validate_events

# OpenRazer's standard 6x22 keyboard matrix. All slots stay paintable for
# regional/firmware layouts; labels are a guide, never a claimed hardware read.
LABEL_ROWS = [
    "M6 Esc · F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11 F12 Prt Scr Pause · · Logo JP",
    "M1 ` 1 2 3 4 5 6 7 8 9 0 - = Back Ins Home PgUp Num / * -",
    "M2 Tab Q W E R T Y U I O P [ ] · Del End PgDn 7 8 9 +",
    "M3 Caps A S D F G H J K L ; ' # Enter · · · 4 5 6 ·",
    "M4 Shift \\ Z X C V B N M , . / JP Shift · ↑ · 1 2 3 Ent",
    "M5 Ctrl Win Alt · · · Space · · · Alt Fn Menu Ctrl ← ↓ → · 0 . ·",
]


def preview_status(pid):
    model = MODELS[pid]
    effects = [key for key in EFFECTS if key != "wheel" or pid == 0x0293]
    device = {"serial": "PREVIEW", "name": model["name"], "pid": pid,
              "usb_id": f"1532:{pid:04x}", "connection": "Preview"}
    return {"devices": [device], "device": device, "daemon_version": "Preview",
            "values": {"brightness": 75, "matrix_dimensions": model["dimensions"],
                       "sync_effects": False, "macros": {}, "macro_events": {}},
            "capabilities": {"brightness": True, "effects": effects, "custom": True, "macros": model["macros"]},
            "errors": {}, "hardware_tested": False}


class KeyboardMatrix(QWidget):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setMinimumSize(620, 210)
        self.setAccessibleName("Individual keyboard colour matrix")
        self.setToolTip("Click a slot to paint it with the chosen colour. Changes are sent only when you click Apply.")

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.page.colors:
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Scan a keyboard or open the preview to paint keys.")
            return
        rows, columns = len(self.page.colors), len(self.page.colors[0])
        width, height = self.width() / columns, self.height() / rows
        font = painter.font()
        font.setPixelSize(9)
        painter.setFont(font)
        for r in range(rows):
            for c in range(columns):
                color = QColor(self.page.colors[r][c])
                rect = QRectF(c * width + 2, r * height + 2, width - 4, height - 4)
                painter.setPen(QPen(QColor("#edf1ed") if (r, c) == self.page.selected_slot else color, 2))
                painter.setBrush(color.darker(300))
                painter.drawRoundedRect(rect, 4, 4)
                labels = LABEL_ROWS[r].split() if rows == 6 and columns == 22 else []
                label = labels[c] if len(labels) == columns else f"{r},{c}"
                if c == 0 and self.page.current_pid() == 0x024E:
                    label = "·"
                painter.setPen(QColor("#edf1ed"))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def mousePressEvent(self, event):
        if not self.isEnabled() or not self.page.colors or event.button() != Qt.MouseButton.LeftButton:
            return
        rows, columns = len(self.page.colors), len(self.page.colors[0])
        r = min(rows - 1, int(event.position().y() * rows / self.height()))
        c = min(columns - 1, int(event.position().x() * columns / self.width()))
        if r >= 0 and c >= 0:
            self.page.paint_slot(r, c)


class BlackWidowPage(QWidget):
    def __init__(self, host, factory=BlackWidowController):
        super().__init__()
        self.host, self.factory = host, factory
        self.serial, self.data, self.caps = None, {}, {}
        self.loading, self.brightness_dirty, self.macro_dirty = False, False, False
        self.colors, self.selected_slot, self.apply_buttons = [], (0, 0), {}
        self.settings = QSettings("Periphera", APP_ID)
        outer = column(self, 14)
        hero, box = card(True)
        box.addWidget(text("BLACKWIDOW  /  CHROMA RGB", 10, GREEN, 600))
        self.model_title = text("MAKE EVERY KEY YOURS", 24, weight=700)
        box.addWidget(self.model_title)
        self.connection = text("Connect a BlackWidow V4 X or V3 by USB, then scan.", 12, MUTED, wrap=True)
        box.addWidget(self.connection)
        bar = row()
        self.devices = QComboBox()
        self.devices.setAccessibleName("BlackWidow keyboard")
        self.devices.addItem("No keyboard selected", None)
        self.devices.currentIndexChanged.connect(self.change_device)
        bar.addWidget(self.devices, 1)
        self.scan_button = host.action("Scan keyboards", self.refresh)
        bar.addWidget(self.scan_button)
        self.preview = QCheckBox("Preview")
        self.preview.toggled.connect(self.preview_changed)
        bar.addWidget(self.preview)
        self.preview_model = QComboBox()
        for pid, model in MODELS.items():
            self.preview_model.addItem(model["name"].removeprefix("Razer "), pid)
        self.preview_model.setAccessibleName("BlackWidow preview model")
        self.preview_model.currentIndexChanged.connect(self.change_preview)
        self.preview_model.hide()
        bar.addWidget(self.preview_model)
        box.addLayout(bar)
        outer.addWidget(hero)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget::pane { border:0; } QTabBar::tab { background:#191c1e; padding:12px 22px; } QTabBar::tab:selected { color:#70e55b; border-bottom:2px solid #44d62c; }")
        outer.addWidget(self.tabs)
        self.build_lighting()
        self.build_custom()
        self.build_macros()
        self.help = text("Requires host OpenRazer. Preview and colour editing never send commands. Physical keyboard testing is still needed.", 11, MUTED, wrap=True)
        outer.addWidget(self.help)
        self.update_enabled()

    def add_apply(self, key, label, callback):
        widget = self.host.action(label, callback, "primary")
        self.apply_buttons[key] = widget
        return widget

    def build_lighting(self):
        page = QWidget()
        layout = column(page, 14)
        panel, box = card()
        bar = row()
        bar.addWidget(text("BRIGHTNESS", 11, MUTED, 600), 1)
        self.current_brightness = text("Current: —", 12, MUTED)
        bar.addWidget(self.current_brightness)
        self.brightness = QSpinBox()
        self.brightness.setRange(0, 100)
        self.brightness.setValue(75)
        self.brightness.setSuffix("%")
        self.brightness.valueChanged.connect(self.mark_brightness)
        bar.addWidget(self.brightness)
        bar.addWidget(self.add_apply("brightness", "Apply brightness", self.apply_brightness))
        box.addLayout(bar)
        layout.addWidget(panel)
        panel, box = card()
        box.addWidget(text("LIGHTING EFFECT", 11, MUTED, 600))
        self.effect = QComboBox()
        self.effect.currentIndexChanged.connect(self.effect_changed)
        box.addWidget(self.effect)
        bar = row()
        self.color, self.secondary = QLineEdit("44D62C"), QLineEdit("9146FF")
        for field, label in ((self.color, "Primary colour"), (self.secondary, "Secondary colour")):
            field.setMaxLength(7)
            field.setAccessibleName(label)
            field.setPlaceholderText(label + " (hex)")
            bar.addWidget(field, 1)
            bar.addWidget(button("Choose", lambda _=False, f=field: self.choose_color(f), "ghost"))
        box.addLayout(bar)
        bar = row()
        self.direction = QComboBox()
        self.direction.addItem("Right →", 1)
        self.direction.addItem("Left ←", 2)
        self.speed = QSpinBox()
        self.speed.setRange(1, 4)
        self.speed.setValue(2)
        self.speed.setPrefix("Speed ")
        bar.addWidget(self.direction)
        bar.addWidget(self.speed)
        bar.addStretch()
        bar.addWidget(self.add_apply("effects", "Apply effect", self.apply_effect))
        box.addLayout(bar)
        box.addWidget(text("Reactive and ripple effects respond to keyboard input through OpenRazer. Confirm the result on the keyboard.", 11, MUTED, wrap=True))
        layout.addWidget(panel)
        self.tabs.addTab(page, "Lighting")

    def build_custom(self):
        page = QWidget()
        layout = column(page, 14)
        panel, box = card()
        box.addWidget(text("INDIVIDUAL KEY COLOURS", 11, MUTED, 600))
        self.matrix_note = text("Scan a keyboard to load its live layout.", 11, MUTED, wrap=True)
        box.addWidget(self.matrix_note)
        self.matrix = KeyboardMatrix(self)
        box.addWidget(self.matrix)
        bar = row()
        self.paint_color = QLineEdit("44D62C")
        self.paint_color.setMaxLength(7)
        self.paint_color.setAccessibleName("Key paint colour")
        bar.addWidget(self.paint_color)
        self.choose_paint = button("Choose colour", lambda: self.choose_color(self.paint_color), "ghost")
        self.fill_row = button("Fill selected row", lambda: self.fill_colors(False), "ghost")
        self.fill_all = button("Fill all keys", lambda: self.fill_colors(True), "ghost")
        for widget in (self.choose_paint, self.fill_row, self.fill_all):
            bar.addWidget(widget)
        box.addLayout(bar)
        self.selected_note = text("Click a key to paint it. Select a row by clicking one of its keys.", 11, MUTED, wrap=True)
        box.addWidget(self.selected_note)
        box.addWidget(self.add_apply("custom", "Apply key colours", self.apply_custom))
        box.addWidget(text("Key labels follow the standard OpenRazer matrix. Regional layouts can differ; every slot remains editable. Dark/unused slots do not add LEDs.", 11, MUTED, wrap=True))
        layout.addWidget(panel)
        self.tabs.addTab(page, "Key colours")

    def build_macros(self):
        self.macro_page = QWidget()
        layout = column(self.macro_page, 14)
        panel, box = card()
        box.addWidget(text("SIX KEYS. YOUR SEQUENCES.", 14, GREEN, 600))
        box.addWidget(text("Bind shortcuts and timed key sequences to M1–M6 on the V4 X. Playback works through Linux virtual input on Wayland and X11.", 12, MUTED, wrap=True))
        bar = row()
        self.macro_key = QComboBox()
        self.macro_key.addItems(MACRO_KEYS)
        self.macro_key.currentIndexChanged.connect(self.load_macro)
        bar.addWidget(self.macro_key)
        self.macro_state = text("Scan the V4 X to read its macros.", 12, MUTED, wrap=True)
        bar.addWidget(self.macro_state, 1)
        box.addLayout(bar)
        self.steps = QTableWidget(0, 3)
        self.steps.setStyleSheet("QTableWidget { background:#111515; color:#edf1ed; gridline-color:#343b36; border:1px solid #343b36; selection-background-color:#294326; selection-color:#edf1ed; } QHeaderView::section { background:#232c26; color:#b7c6bb; border:1px solid #343b36; padding:7px; } QTableCornerButton::section { background:#232c26; border:1px solid #343b36; } QTableWidget:disabled { color:#667168; }")
        self.steps.setHorizontalHeaderLabels(["Action (DOWN / UP / WAIT)", "Key", "Delay before step (ms)"])
        self.steps.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.steps.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.steps.setMinimumHeight(230)
        self.steps.itemChanged.connect(self.mark_macro)
        box.addWidget(self.steps)
        bar = row()
        self.shortcut = QLineEdit()
        self.shortcut.setPlaceholderText("CTRL+C, CTRL+SHIFT+V, ENTER…")
        self.shortcut.setAccessibleName("Macro shortcut")
        bar.addWidget(self.shortcut, 1)
        self.add_shortcut = button("Add shortcut", self.append_shortcut)
        bar.addWidget(self.add_shortcut)
        self.delay = QSpinBox()
        self.delay.setRange(1, 60000)
        self.delay.setValue(100)
        self.delay.setSuffix(" ms")
        bar.addWidget(self.delay)
        self.add_wait = button("Add wait", self.append_wait, "ghost")
        bar.addWidget(self.add_wait)
        box.addLayout(bar)
        bar = row()
        self.remove_steps = button("Remove selected steps", self.remove_selected, "ghost")
        self.move_up = button("Move up", lambda: self.move_step(-1), "ghost")
        self.move_down = button("Move down", lambda: self.move_step(1), "ghost")
        self.clear_steps = button("Clear editor", lambda: self.set_steps([], dirty=True), "ghost")
        for widget in (self.remove_steps, self.move_up, self.move_down, self.clear_steps):
            bar.addWidget(widget)
        bar.addStretch()
        box.addLayout(bar)
        bar = row()
        bar.addWidget(self.add_apply("macros", "Save to macro key", self.save_macro))
        self.delete_binding = self.host.action("Delete binding", self.delete_macro, "ghost")
        self.restore_bindings = self.host.action("Restore saved macros", self.restore_macros, "ghost")
        bar.addWidget(self.delete_binding)
        bar.addWidget(self.restore_bindings)
        box.addLayout(bar)
        box.addWidget(text("Run Hardware setup → BlackWidow keyboard + macros once to allow virtual input. OpenRazer runs the bindings even after this window closes. After a service restart or reboot, scan and choose Restore saved macros. These are host macros, not onboard profiles.", 11, MUTED, wrap=True))
        layout.addWidget(panel)
        self.tabs.addTab(self.macro_page, "V4 X macros")

    def current_pid(self):
        return self.preview_model.currentData() if self.preview.isChecked() else self.data.get("pid")

    def can_apply(self, capability):
        return bool(self.serial and not self.preview.isChecked() and not self.host.busy
                    and self.caps.get(capability) and (capability == "macros" or self.data.get("sync_effects") is False))

    def update_enabled(self):
        busy, preview = self.host.busy, self.preview.isChecked()
        for key, widget in self.apply_buttons.items():
            widget.setEnabled(self.can_apply(key))
        self.devices.setEnabled(not busy and not preview)
        self.scan_button.setEnabled(not busy and not preview)
        self.preview.setEnabled(not busy)
        self.preview_model.setEnabled(not busy and preview)
        self.brightness.setEnabled(not busy and bool(self.caps.get("brightness")))
        self.effect.setEnabled(not busy and bool(self.caps.get("effects")))
        edit = not busy and bool(self.caps.get("custom"))
        for widget in (self.matrix, self.paint_color, self.choose_paint, self.fill_row, self.fill_all):
            widget.setEnabled(edit)
        macros = not busy and bool(self.caps.get("macros"))
        self.tabs.setTabVisible(2, bool(self.caps.get("macros")))
        for widget in (self.macro_key, self.steps, self.shortcut, self.add_shortcut, self.delay, self.add_wait,
                       self.remove_steps, self.move_up, self.move_down, self.clear_steps):
            widget.setEnabled(macros)
        self.delete_binding.setEnabled(self.can_apply("macros") and self.macro_key.currentText() in self.data.get("macros", {}))
        self.restore_bindings.setEnabled(self.can_apply("macros") and bool(self.saved_macros()))
        self.effect_changed()

    def effect_changed(self, _=None):
        if not hasattr(self, "color"):
            return
        effect = self.effect.currentData()
        editable = not self.host.busy and bool(self.caps.get("effects"))
        self.color.setEnabled(editable and effect in ("static", "breathing", "breathing_dual", "reactive", "starlight", "starlight_dual", "ripple"))
        self.secondary.setEnabled(editable and effect in ("breathing_dual", "starlight_dual"))
        self.direction.setVisible(effect in ("wave", "wheel"))
        self.direction.setEnabled(editable)
        self.speed.setVisible(effect in ("reactive", "starlight", "starlight_dual", "starlight_random"))
        self.speed.setMaximum(4 if effect == "reactive" else 3)
        self.speed.setEnabled(editable)

    def mark_brightness(self, _):
        if not self.loading:
            self.brightness_dirty = True

    def mark_macro(self, _=None):
        if not self.loading:
            self.macro_dirty = True

    def choose_color(self, field):
        if not field.isEnabled() or self.host.busy:
            return
        selected = QColorDialog.getColor(QColor("#" + field.text().lstrip("#")), self, "Choose keyboard colour")
        if selected.isValid():
            field.setText(selected.name().lstrip("#").upper())

    def paint_value(self):
        try:
            return "#" + bytes(color_value(self.paint_color.text())).hex()
        except ValueError:
            self.host.notify("Use a six-digit paint colour such as 44D62C.", error=True)
            return None

    def paint_slot(self, r, c):
        color = self.paint_value()
        if color is None or self.host.busy or not self.caps.get("custom"):
            return
        self.selected_slot = r, c
        self.colors[r][c] = color
        self.selected_note.setText(f"Selected matrix row {r}, column {c} · {color.upper()}")
        self.matrix.update()

    def fill_colors(self, all_keys):
        color = self.paint_value()
        if color is None or not self.colors or self.host.busy:
            return
        rows = range(len(self.colors)) if all_keys else [self.selected_slot[0]]
        for r in rows:
            self.colors[r] = [color] * len(self.colors[r])
        self.matrix.update()

    def clear(self, message):
        self.serial, self.data, self.caps, self.colors = None, {}, {}, []
        self.brightness_dirty = self.macro_dirty = False
        self.loading = True
        self.devices.clear()
        self.devices.addItem("No keyboard selected", None)
        self.effect.clear()
        self.loading = False
        self.set_steps([])
        self.model_title.setText("MAKE EVERY KEY YOURS")
        self.connection.setText(message)
        self.current_brightness.setText("Current: —")
        self.matrix_note.setText("Scan a keyboard to load its live layout.")
        self.matrix.update()
        self.update_enabled()

    def preview_changed(self, enabled):
        self.preview_model.setVisible(enabled)
        self.clear("Preview ended. Scan for a connected keyboard.")
        if enabled:
            self.change_preview()

    def change_preview(self, _=None):
        if self.preview.isChecked():
            self.clear("")
            self.receive(preview_status(self.preview_model.currentData()))
            self.host.notify("Keyboard preview: hardware commands and macro saving are disabled.")

    def change_device(self, _=None):
        if self.loading:
            return
        serial = self.devices.currentData()
        self.serial, self.data, self.caps, self.colors = None, {}, {}, []
        self.brightness_dirty = self.macro_dirty = False
        self.set_steps([])
        self.matrix.update()
        self.update_enabled()
        if serial:
            self.refresh()

    def refresh(self):
        if self.preview.isChecked():
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
        return self.host.run("Scanning BlackWidow keyboards", scan, self.receive,
                             lambda: self.clear("Keyboard unavailable. Open Diagnostics for details."),
                             controller_factory=self.factory, device=serial)

    def receive(self, result):
        device = result.get("device", {})
        changed = self.serial != device.get("serial") or self.data.get("pid") != device.get("pid")
        self.serial = device.get("serial")
        self.data = {**result.get("values", {}), "pid": device.get("pid")}
        self.caps = result.get("capabilities", {})
        self.loading = True
        try:
            self.devices.clear()
            if not self.serial:
                self.devices.addItem("Choose a keyboard" if result["devices"] else "No supported keyboard detected", None)
            for found in result["devices"]:
                self.devices.addItem(found["name"].removeprefix("Razer ") + " · " + found["serial"], found["serial"])
            if self.serial:
                self.devices.setCurrentIndex(self.devices.findData(self.serial))
            effect = self.effect.currentData()
            self.effect.clear()
            for key in self.caps.get("effects", []):
                self.effect.addItem(EFFECTS[key][0], key)
            self.effect.setCurrentIndex(max(0, self.effect.findData(effect)))
            if changed:
                self.brightness_dirty = self.macro_dirty = False
            if "brightness" in self.data and not self.brightness_dirty:
                self.brightness.setValue(round(self.data["brightness"]))
            dims = self.data.get("matrix_dimensions") if self.caps.get("custom") else None
            if changed or dims != ([len(self.colors), len(self.colors[0])] if self.colors else None):
                self.colors = [["#44d62c"] * dims[1] for _ in range(dims[0])] if dims else []
                self.selected_slot = (0, 0)
            self.matrix_note.setText(f"{dims[0]} rows × {dims[1]} slots. Click to paint; Apply sends the full frame." if dims else "Individual key colours are unavailable in this driver.")
        finally:
            self.loading = False
        self.model_title.setText(device.get("name", "MAKE EVERY KEY YOURS").removeprefix("Razer ").upper())
        self.connection.setText(("Preview · commands disabled" if self.preview.isChecked() else
                                 f"{device.get('usb_id', '')} · OpenRazer {result.get('daemon_version', '')}") if self.serial else "Connect and select a BlackWidow V4 X or V3.")
        level = self.data.get("brightness")
        self.current_brightness.setText(f"Current: {round(level)}%" if level is not None else "Current: —")
        self.matrix.update()
        if changed or not self.macro_dirty:
            self.load_macro()
        errors = result.get("errors", {})
        self.help.setText("OpenRazer lighting sync is on. Turn it off before editing lighting." if self.data.get("sync_effects") else
                          " · ".join(str(v) for v in errors.values()) if errors else
                          "Changes require Apply. Confirm lighting on the physical keyboard; previews are illustrative.")
        self.update_enabled()

    def apply_brightness(self):
        if not self.can_apply("brightness"):
            return False
        value = self.brightness.value()
        def done(result):
            self.brightness_dirty = False
            self.current_brightness.setText(f"Current: {round(result['value'])}%")
            self.host.notify("Keyboard brightness applied. OpenRazer readback matched.")
        return self.host.run("Applying keyboard brightness", lambda c: c.set_brightness(value), done,
                             controller_factory=self.factory, device=self.serial)

    def apply_effect(self):
        if not self.can_apply("effects"):
            return False
        effect = self.effect.currentData()
        try:
            primary = color_value(self.color.text()) if self.color.isEnabled() else None
            secondary = color_value(self.secondary.text()) if self.secondary.isEnabled() else None
        except ValueError:
            self.host.notify("Use six-digit RGB colours such as 44D62C.", error=True)
            return False
        direction, speed = self.direction.currentData(), self.speed.value()
        return self.host.run("Applying keyboard effect", lambda c: c.set_effect(effect, primary, secondary, direction, speed),
                             lambda _: self.host.notify("Keyboard lighting accepted. Confirm it on the keyboard."),
                             controller_factory=self.factory, device=self.serial)

    def apply_custom(self):
        if not self.can_apply("custom"):
            return False
        colors = [[color_value(color) for color in row] for row in self.colors]
        return self.host.run("Applying individual key colours", lambda c: c.set_custom(colors),
                             lambda _: self.host.notify("Key colours accepted. Confirm their placement on the keyboard."),
                             controller_factory=self.factory, device=self.serial)

    def saved_macros(self):
        if not self.serial or self.preview.isChecked():
            return {}
        try:
            saved = json.loads(self.settings.value("keyboards/" + self.serial + "/macros", "{}"))
            return {key: validate_events(events) for key, events in saved.items() if key in MACRO_KEYS}
        except (ValueError, TypeError, AttributeError):
            return {}

    def persist_macro(self, key, events):
        saved = self.saved_macros()
        if events is None:
            saved.pop(key, None)
        else:
            saved[key] = events
        self.settings.setValue("keyboards/" + self.serial + "/macros", json.dumps(saved))
        self.settings.sync()

    def set_steps(self, events, dirty=False):
        previous, self.loading = self.loading, True
        self.steps.setRowCount(len(events))
        for r, event in enumerate(events):
            for c, value in enumerate((event["state"], event["key"], event["delay_ms"])):
                self.steps.setItem(r, c, QTableWidgetItem(str(value)))
        self.loading = previous
        self.macro_dirty = dirty

    def read_steps(self):
        events = []
        for r in range(self.steps.rowCount()):
            values = [self.steps.item(r, c).text().strip() if self.steps.item(r, c) else "" for c in range(3)]
            try:
                delay = int(values[2])
            except ValueError as exc:
                raise ValueError("Every step needs a whole-number delay in milliseconds") from exc
            events.append({"state": values[0].upper(), "key": values[1].upper(), "delay_ms": delay})
        return events

    def load_macro(self, _=None):
        key = self.macro_key.currentText()
        events = self.data.get("macro_events", {}).get(key)
        bound = key in self.data.get("macros", {})
        if events is None and not bound:
            events = self.saved_macros().get(key)
        self.set_steps(events or [])
        self.macro_state.setText("Active in OpenRazer" if bound and events is not None else
                                 "Binding managed outside this editor; saving will replace it" if bound else
                                 "Saved locally · restore to activate" if events else "No binding on this key")
        self.delete_binding.setEnabled(self.can_apply("macros") and bound)

    def append_shortcut(self):
        try:
            self.set_steps(self.read_steps() + shortcut_events(self.shortcut.text()), dirty=True)
            self.shortcut.clear()
        except ValueError as exc:
            self.host.notify(str(exc), error=True)

    def append_wait(self):
        try:
            self.set_steps(self.read_steps() + [{"key": "", "state": "WAIT", "delay_ms": self.delay.value()}], dirty=True)
        except ValueError as exc:
            self.host.notify(str(exc), error=True)

    def remove_selected(self):
        for r in sorted({i.row() for i in self.steps.selectedIndexes()}, reverse=True):
            self.steps.removeRow(r)
        self.macro_dirty = True

    def move_step(self, offset):
        r = self.steps.currentRow()
        target = r + offset
        if r < 0 or not 0 <= target < self.steps.rowCount():
            return
        try:
            events = self.read_steps()
            events[r], events[target] = events[target], events[r]
            self.set_steps(events, dirty=True)
            self.steps.selectRow(target)
        except ValueError as exc:
            self.host.notify(str(exc), error=True)

    def save_macro(self):
        if not self.can_apply("macros"):
            return False
        try:
            events = validate_events(self.read_steps())
        except ValueError as exc:
            self.host.notify(str(exc), error=True)
            return False
        key = self.macro_key.currentText()
        if key in self.data.get("macros", {}) and self.data.get("macro_events", {}).get(key) is None:
            if QMessageBox.question(self, "Replace macro", f"Replace the existing {key} binding?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
                return False
        def done(result):
            self.persist_macro(key, events)
            self.macro_dirty = False
            self.data.setdefault("macros", {})[key] = True
            self.data.setdefault("macro_events", {})[key] = events
            self.load_macro()
            self.host.notify(f"{key} macro saved. OpenRazer readback matched; press {key} to test it.")
        return self.host.run("Saving " + key + " macro", lambda c: c.set_macro(key, events), done,
                             controller_factory=self.factory, device=self.serial)

    def delete_macro(self):
        if not self.can_apply("macros"):
            return False
        key = self.macro_key.currentText()
        def done(_):
            self.persist_macro(key, None)
            self.data.get("macros", {}).pop(key, None)
            self.data.get("macro_events", {}).pop(key, None)
            self.load_macro()
            self.host.notify(key + " binding removed; OpenRazer readback matched.")
        return self.host.run("Deleting " + key + " binding", lambda c: c.delete_macro(key), done,
                             controller_factory=self.factory, device=self.serial)

    def restore_macros(self):
        if not self.can_apply("macros"):
            return False
        saved = self.saved_macros()
        if not saved:
            return False
        collisions = [key for key in saved if key in self.data.get("macros", {})
                      and self.data.get("macro_events", {}).get(key) != saved[key]]
        if collisions and QMessageBox.question(self, "Restore saved macros", "Replace current bindings on " + ", ".join(collisions) + "?",
                                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                               QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return False
        def restore(controller):
            for key, events in saved.items():
                controller.set_macro(key, events)
            return controller.status()
        def done(result):
            self.macro_dirty = False
            self.receive(result)
            self.host.notify("Saved macros restored. OpenRazer readback matched.")
        return self.host.run("Restoring saved keyboard macros", restore, done,
                             controller_factory=self.factory, device=self.serial)
