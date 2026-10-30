"""Discovery dashboard and capability-driven peripheral controls."""
import json

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
                            QComboBox, QColorDialog, QFormLayout, QTabWidget,
                            QGridLayout, QTableWidget, QHeaderView, QTableWidgetItem,
                            QScrollArea, QSizePolicy, QLayout)
from barracuda_gui import text, row, column, card, button, GREEN, MUTED
from openrazer_backend import TYPES, MISC, CHROMA, category, words


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget(): item.widget().deleteLater()
        elif item.layout(): clear_layout(item.layout())


class ColourInput(QWidget):
    def __init__(self, value="44D62C"):
        super().__init__()
        box = row()
        self.setLayout(box)
        self.entry = QLineEdit(value)
        self.entry.setMaxLength(7)
        self.entry.setMaximumWidth(125)
        self.entry.setAccessibleName("RGB hex colour")
        self.pick = button("Choose", self.choose)
        box.addWidget(self.entry)
        box.addWidget(self.pick)
        box.addStretch()
        self.entry.textChanged.connect(self.paint_colour)
        self.paint_colour()

    def paint_colour(self):
        colour = QColor("#" + self.entry.text().lstrip("#"))
        if colour.isValid():
            self.pick.setStyleSheet(f"border: 2px solid {colour.name()};")

    def choose(self):
        result = QColorDialog.getColor(QColor("#" + self.entry.text().lstrip("#")), self, "Choose colour")
        if result.isValid(): self.entry.setText(result.name()[1:].upper())

    def value(self):
        value = self.entry.text().lstrip("#")
        if len(value) != 6:
            raise ValueError("Enter a six-digit RGB colour")
        try: return [int(value[i:i+2], 16) for i in (0, 2, 4)]
        except ValueError as exc: raise ValueError("Enter a six-digit RGB colour") from exc


class StageEditor(QWidget):
    def __init__(self, maximum, initial=None):
        super().__init__()
        box = column(self)
        self.count = QSpinBox()
        self.count.setRange(1, 5)
        self.active = QComboBox()
        top = row()
        top.addWidget(text("Stages", 12, MUTED))
        top.addWidget(self.count)
        top.addWidget(text("Active stage", 12, MUTED))
        top.addWidget(self.active)
        top.addStretch()
        box.addLayout(top)
        self.table = QTableWidget(5, 2)
        self.table.setHorizontalHeaderLabels(["X DPI", "Y DPI"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setMaximumHeight(265)
        self.table.setMinimumWidth(0)
        self.spins = []
        for y in range(5):
            pair = []
            for x in range(2):
                spin = QSpinBox()
                spin.setRange(1, maximum)
                spin.setValue(800*(y+1))
                spin.setAccessibleName(f"Stage {y+1} {'X' if x == 0 else 'Y'} DPI")
                self.table.setCellWidget(y, x, spin)
                pair.append(spin)
            self.spins.append(pair)
        box.addWidget(self.table)
        self.count.valueChanged.connect(self.update_count)
        if initial and isinstance(initial, (list, tuple)) and len(initial) == 2:
            self.count.setValue(min(5, len(initial[1])))
            for pair, values in zip(self.spins, initial[1]):
                for spin, value in zip(pair, values): spin.setValue(value)
            self.update_count()
            self.active.setCurrentIndex(initial[0]-1)
        else:
            self.count.setValue(3)
            self.update_count()

    def update_count(self):
        selected = self.active.currentIndex()
        self.active.clear()
        self.active.addItems([str(x+1) for x in range(self.count.value())])
        self.active.setCurrentIndex(max(0, min(selected, self.count.value()-1)))
        for y in range(5): self.table.setRowHidden(y, y >= self.count.value())

    def values(self):
        return [self.active.currentIndex()+1, [tuple(s.value() for s in p) for p in self.spins[:self.count.value()]]]


class MacroEditor(QWidget):
    def __init__(self):
        super().__init__()
        box = column(self)
        self.bind = QLineEdit()
        self.bind.setPlaceholderText("Trigger key, e.g. M1, A or 1")
        self.bind.setAccessibleName("Macro trigger key")
        box.addWidget(self.bind)
        box.addWidget(text("Actions run on the host when you press the trigger key. Key names and availability depend on the host's OpenRazer configuration.", 12, MUTED, wrap=True))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Action", "Key, URL or host script path", "Script arguments", "Delay (µs)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setMinimumWidth(0)
        self.table.setMaximumHeight(210)
        box.addWidget(self.table)
        actions = row()
        actions.addWidget(button("Add action", self.add_action))
        actions.addWidget(button("Remove selected", self.remove_action, "ghost"))
        actions.addStretch()
        box.addLayout(actions)
        self.add_action()

    def add_action(self):
        index = self.table.rowCount()
        if index >= 256: return
        self.table.insertRow(index)
        action = QComboBox()
        for title, key in (("Press key", "DOWN"), ("Release key", "UP"), ("Open URL", "url"), ("Run host script", "script")):
            action.addItem(title, key)
        self.table.setCellWidget(index, 0, action)
        self.table.setItem(index, 1, QTableWidgetItem(""))
        self.table.setItem(index, 2, QTableWidgetItem(""))
        pause = QSpinBox()
        pause.setRange(0, 60000000)
        self.table.setCellWidget(index, 3, pause)

    def remove_action(self):
        if self.table.currentRow() >= 0: self.table.removeRow(self.table.currentRow())

    def values(self):
        sequence = []
        for i in range(self.table.rowCount()):
            kind = self.table.cellWidget(i, 0).currentData()
            value = self.table.item(i, 1).text().strip()
            if kind in ("UP", "DOWN"):
                sequence.append({"type": "MacroKey", "key_id": value, "pre_pause": self.table.cellWidget(i, 3).value(), "state": kind})
            elif kind == "url": sequence.append({"type": "MacroURL", "url": value})
            else: sequence.append({"type": "MacroScript", "script": value, "args": self.table.item(i, 2).text()})
        return [self.bind.text().strip(), json.dumps(sequence)]


class ArgumentEditor(QWidget):
    def __init__(self, spec, snapshot):
        super().__init__()
        self.spec, self.fields = spec, []
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        values = snapshot["readings"]
        dpi = "razer.device.dpi"
        maximum = values.get(dpi + "|maxDPI", 65535)
        maximum = maximum if type(maximum) is int and 1 <= maximum <= 65535 else 65535
        initial = values.get(spec["interface"] + "|get" + spec["method"][3:])
        if spec["method"] == "setDPIStages":
            self.special = StageEditor(maximum, initial)
            form.addRow(self.special)
            return
        if spec["method"] == "addMacro":
            self.special = MacroEditor()
            form.addRow(self.special)
            return
        if spec["signature"] == "ai":
            self.colour = ColourInput()
            self.intensity = QSpinBox()
            self.intensity.setRange(0, 255)
            self.intensity.setValue(255)
            form.addRow("Colour", self.colour)
            form.addRow("Intensity", self.intensity)
            return
        names = spec["arguments"]
        # The remaining public controls have only scalar arguments.
        sigs = list(spec["signature"])
        i = 0
        while i < len(names):
            name, sig = names[i], sigs[i]
            if name.startswith("red") and names[i+1:i+3] == [name.replace("red", "green"), name.replace("red", "blue")]:
                widget = ColourInput()
                form.addRow("Colour " + (name[3:] or ""), widget)
                self.fields.append(("rgb", widget))
                i += 3
                continue
            discrete = values.get(dpi + "|availableDPI", [])
            if spec["method"] == "setDPI" and discrete:
                widget = QComboBox()
                if i == 0:
                    for value in discrete: widget.addItem(f"{value:,} DPI", value)
                else:
                    widget.addItem("Shared sensitivity", 0)
                kind = "choice"
            elif spec["method"] == "setPollRate":
                widget = QComboBox()
                rates = values.get(MISC + "|getSupportedPollRates", [125, 500, 1000])
                for value in rates: widget.addItem(f"{value:,} Hz", value)
                kind = "choice"
            elif spec["method"] in ("setHyperPollingLED", "setHyperPollingMultiLEDModes"):
                widget = QComboBox()
                choices = ([("Connection status", 1), ("Battery status", 2), ("Low-battery warning", 3)]
                           if spec["method"] == "setHyperPollingLED" else
                           [("Off", 0), ("Battery status", 1), ("Connection status", 2), ("Polling rate", 3), ("DPI indicator", 4)])
                for title, value in choices: widget.addItem(title, value)
                kind = "choice"
            elif name == "direction" or spec["method"] in ("setScrollMode", "setChargeEffect"):
                widget = QComboBox()
                choices = [("Forward", 1), ("Reverse", 2)] if name == "direction" else (
                    [("Tactile", 0), ("Free spin", 1)] if spec["method"] == "setScrollMode" else [("Current lighting", 0), ("Charging colour", 1)])
                for title, value in choices: widget.addItem(title, value)
                kind = "choice"
            elif sig == "b":
                widget = QCheckBox("Enabled")
                kind = "bool"
            elif sig == "s":
                widget = QLineEdit()
                if name == "pid": widget.setPlaceholderText("Device product ID, e.g. 0x00A5")
                kind = "text"
            else:
                widget = QDoubleSpinBox() if sig == "d" else QSpinBox()
                high = 255 if sig == "y" else 65535
                low, default = 0, 0
                if "brightness" in name or name == "threshold": high, default = 100, 50
                elif name.startswith("dpi_"): low, high, default = 1, maximum, 1600
                elif name == "refresh_rate": low, high, default = 1, 60, 10
                elif name == "speed": low, high, default = 1, 4 if "Reactive" in spec["method"] else 3, 2
                elif name == "channel": low, high, default = 1, values.get(spec["interface"] + "|getNumChannels", 6), 1
                elif name == "size": high, default = 255, 30
                elif name == "idle_time": default = 300
                widget.setRange(low, high)
                widget.setValue(default)
                if "brightness" in name or name == "threshold": widget.setSuffix(" %")
                elif name == "idle_time": widget.setSuffix(" seconds")
                kind = "number"
            widget.setAccessibleName(words(name))
            form.addRow(words(name).capitalize(), widget)
            self.fields.append((kind, widget))
            if initial is not None:
                val = initial[i] if isinstance(initial, (list, tuple)) and i < len(initial) else initial
                try:
                    if kind == "choice": widget.setCurrentIndex(max(0, widget.findData(val)))
                    elif kind == "bool": widget.setChecked(bool(val))
                    elif kind == "number": widget.setValue(val)
                    elif kind == "text": widget.setText(str(val))
                except (TypeError, ValueError): pass
            i += 1

    def values(self):
        if hasattr(self, "special"): return self.special.values()
        if hasattr(self, "colour"): return [self.colour.value() + [self.intensity.value()]]
        values = []
        for kind, widget in self.fields:
            if kind == "rgb": values.extend(widget.value())
            elif kind == "choice": values.append(widget.currentData())
            elif kind == "number": values.append(widget.value())
            elif kind == "bool": values.append(widget.isChecked())
            else: values.append(widget.text().strip())
        return values


class DevicePage(QWidget):
    def __init__(self, host, device):
        super().__init__()
        self.setObjectName("page")
        self.host, self.device = host, dict(device)
        self.snapshot, self.fingerprint = None, None
        self.apply_buttons = []
        self.box = column(self, 16)
        self.box.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        hero, content = card(True)
        content.addWidget(text(TYPES[device["type"]].upper(), 10, GREEN, 600))
        content.addWidget(text(device["name"], 25, weight=700, wrap=True))
        content.addWidget(text(f"{device['usb_id']}  ·  {device['serial']}", 12, MUTED, wrap=True))
        self.status_text = text("Refresh to read this device's controls. Settings change only when you apply them.", 12, MUTED, wrap=True)
        content.addWidget(self.status_text)
        self.refresh_button = button("Refresh device", self.refresh)
        content.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.box.addWidget(hero)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.box.addWidget(self.tabs)
        self.box.addWidget(text("Controls come from your installed OpenRazer driver. Readings may be cached by its daemon; confirm changes on the device.", 11, MUTED, wrap=True))

    def refresh(self):
        return self.host.run("Reading " + self.device["name"], lambda c: c.status(), self.receive,
                             self.failed, controller_factory=self.host.openrazer_factory, device=dict(self.device))

    def failed(self):
        self.snapshot = None
        self.status_text.setText("Device unavailable. Check its connection and host setup, then scan again. See Diagnostics for details.")
        self.update_enabled()

    def receive(self, snapshot):
        self.snapshot = snapshot
        fingerprint = json.dumps([snapshot["controls"], snapshot["matrix_dimensions"]], sort_keys=True)
        if self.fingerprint != fingerprint:
            self.fingerprint = fingerprint
            self.rebuild()
        else:
            for label, spec in self.current_labels:
                label.setText(self.current_value(spec))
        self.status_text.setText("Shared lighting is on. Switch it off on Home to edit one device." if snapshot["sync_effects"] is True else
                                 "Device ready. Edit a control, then choose Apply." if not snapshot["errors"] else
                                 "Some readings failed. Available controls are shown; see Diagnostics for details.")
        self.update_enabled()
        self.host.notify("Device controls updated. No settings were changed.")

    def current_value(self, spec):
        key = spec["interface"] + "|get" + spec["method"][3:]
        value = self.snapshot["readings"].get(key)
        if value is None: return "Current: unavailable" if key in self.snapshot["errors"] else ""
        if isinstance(value, bool): value = "On" if value else "Off"
        elif isinstance(value, (tuple, list, dict)): value = json.dumps(value)
        return "Current: " + str(value)

    def rebuild(self):
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            widget.deleteLater()
        self.apply_buttons, self.current_labels = [], []
        groups = {}
        def group(name):
            if name not in groups:
                pane = QWidget()
                pane.setObjectName("page")
                layout = column(pane, 16, 12)
                layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
                groups[name] = layout
                self.tabs.addTab(pane, name)
            return groups[name]
        zones = {}
        for spec in self.snapshot["controls"]:
            if spec["effect"]:
                zones.setdefault(spec["interface"], []).append(spec)
                continue
            panel, layout = card()
            layout.addWidget(text(spec["label"], 16, weight=600))
            current = text(self.current_value(spec), 12, MUTED, wrap=True)
            layout.addWidget(current)
            self.current_labels.append((current, spec))
            editor = ArgumentEditor(spec, self.snapshot)
            layout.addWidget(editor)
            apply = button("Apply " + spec["label"].lower(), lambda _=False, s=spec, e=editor: self.apply(s, e), "primary")
            layout.addWidget(apply, 0, Qt.AlignmentFlag.AlignLeft)
            self.apply_buttons.append((apply, spec["category"] == "Lighting"))
            group(spec["category"]).addWidget(panel)
        for interface, specs in zones.items():
            panel, layout = card()
            zone = interface.rsplit(".", 1)[-1]
            layout.addWidget(text("Lighting effects" if zone == "chroma" else words(zone).title() + " lighting", 16, weight=600))
            choices = QComboBox()
            for spec in specs: choices.addItem(spec["label"], spec)
            layout.addWidget(choices)
            editor_box = QWidget()
            editor_layout = column(editor_box)
            layout.addWidget(editor_box)
            state = {}
            def change(_=None, combo=choices, content=editor_layout, state=state):
                clear_layout(content)
                state["editor"] = ArgumentEditor(combo.currentData(), self.snapshot)
                content.addWidget(state["editor"])
            choices.currentIndexChanged.connect(change)
            change()
            apply = button("Apply effect", lambda _=False, combo=choices, state=state: self.apply(combo.currentData(), state["editor"]), "primary")
            layout.addWidget(apply, 0, Qt.AlignmentFlag.AlignLeft)
            self.apply_buttons.append((apply, True))
            group("Lighting").addWidget(panel)
        if self.snapshot["matrix_dimensions"]:
            group("Custom colours").addWidget(self.matrix_editor())
        info, layout = card()
        layout.addWidget(text("Device information", 16, weight=600))
        for key, value in self.snapshot["readings"].items():
            if key.split("|")[0] == MISC or "getBattery" in key or "isCharging" in key or "getMacros" in key:
                label = words(key.split("|")[1].removeprefix("get"))
                layout.addWidget(text(f"{label}: {value}", 12, MUTED, wrap=True))
        group("Details").addWidget(info)
        for layout in groups.values(): layout.addStretch()
        order = (["Performance", "Lighting", "Power", "Keys & macros", "Custom colours", "Details"]
                 if self.device["type"] == "mouse" else
                 ["Lighting", "Custom colours", "Performance", "Keys & macros", "Power", "Details"])
        position = 0
        for title in order:
            for index in range(self.tabs.count()):
                if self.tabs.tabText(index) == title:
                    self.tabs.tabBar().moveTab(index, position)
                    position += 1
                    break
        self.tabs.setCurrentIndex(0)

    def matrix_editor(self):
        panel, layout = card()
        rows, cols = self.snapshot["matrix_dimensions"]
        layout.addWidget(text("Individual LED colours", 16, weight=600))
        layout.addWidget(text(f"{rows} rows × {cols} columns reported by OpenRazer. Layout positions are driver slots; they may include unused LEDs.", 12, MUTED, wrap=True))
        colour = ColourInput()
        layout.addWidget(colour)
        self.matrix_colors = [[(68, 214, 44) for _ in range(cols)] for _ in range(rows)]
        cells = QWidget()
        cells.setObjectName("page")
        grid = QGridLayout(cells)
        grid.setSpacing(3)
        self.matrix_buttons = []
        for y in range(rows):
            for x in range(cols):
                cell = button("", lambda _=False, r=y, c=x: self.paint_cell(r, c, colour))
                cell.setFixedSize(24, 24)
                cell.setAccessibleName(f"LED row {y+1}, column {x+1}")
                cell.setToolTip(f"Row {y+1}, column {x+1}")
                cell.setStyleSheet("background:#44d62c; padding:0;")
                grid.addWidget(cell, y, x)
                self.matrix_buttons.append(cell)
        scroll = QScrollArea()
        scroll.setWidget(cells)
        scroll.setMinimumWidth(0)
        scroll.setFixedHeight(min(290, rows*29+30))
        layout.addWidget(scroll)
        actions = row()
        actions.addWidget(button("Fill with colour", lambda: self.fill_matrix(colour)))
        apply = button("Apply LED colours", self.apply_matrix, "primary")
        actions.addWidget(apply)
        actions.addStretch()
        layout.addLayout(actions)
        self.apply_buttons.append((apply, True))
        return panel

    def paint_cell(self, r, c, colour):
        try: value = colour.value()
        except ValueError as exc: self.host.notify(str(exc), True); return
        self.matrix_colors[r][c] = tuple(value)
        self.matrix_buttons[r*len(self.matrix_colors[0])+c].setStyleSheet("background:#%02x%02x%02x; padding:0;" % tuple(value))

    def fill_matrix(self, colour):
        for r, row_values in enumerate(self.matrix_colors):
            for c in range(len(row_values)): self.paint_cell(r, c, colour)

    def apply_matrix(self):
        if not self.snapshot or self.host.busy: return False
        colors = [[tuple(c) for c in row] for row in self.matrix_colors]
        return self.send("Applying LED colours", lambda c: c.set_matrix(colors))

    def apply(self, spec, editor):
        if not self.snapshot or self.host.busy: return False
        try: values = editor.values()
        except (ValueError, TypeError) as exc: self.host.notify(str(exc), True); return False
        return self.send("Applying " + spec["label"], lambda c: c.apply(spec["id"], values))

    def send(self, title, operation):
        def done(result):
            self.host.notify("Command accepted by OpenRazer. Refresh to read current values and confirm on the device.")
        return self.host.run(title, operation, done, self.failed,
                             controller_factory=self.host.openrazer_factory, device=dict(self.device))

    def update_enabled(self):
        ready = self.snapshot is not None and not self.host.busy
        self.refresh_button.setEnabled(not self.host.busy)
        self.tabs.setEnabled(ready)
        for apply, lighting in self.apply_buttons:
            apply.setEnabled(ready and (not lighting or self.snapshot.get("sync_effects") is False))


class DiscoveryPage(QWidget):
    def __init__(self, host, kind=None):
        super().__init__()
        self.setObjectName("page")
        self.host, self.kind = host, kind
        box = column(self, 16)
        box.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        hero, content = card(True)
        content.addWidget(text("YOUR DEVICES. YOUR CONTROL.", 11, GREEN, 600))
        content.addWidget(text(TYPES[kind] if kind else "Bring your setup together.", 27, weight=700, wrap=True))
        content.addWidget(text("Scan for connected peripherals. Choose a device to see the controls its driver provides.", 13, MUTED, wrap=True))
        self.scan_button = button("Scan for devices", host.scan_devices, "primary")
        content.addWidget(self.scan_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.summary = text("No scan yet. Connect your devices, then scan.", 12, MUTED, wrap=True)
        content.addWidget(self.summary)
        box.addWidget(hero)
        self.results = column(spacing=12)
        box.addLayout(self.results)
        if kind is None:
            panel, settings = card()
            settings.addWidget(text("OpenRazer preferences", 16, weight=600))
            self.sync = QCheckBox("Share lighting effects across devices")
            self.sleep = QCheckBox("Turn lighting off when the screensaver is active")
            settings.addWidget(self.sync)
            settings.addWidget(text("Turn shared lighting off to edit one device independently. This preference applies to all devices managed by OpenRazer.", 12, MUTED, wrap=True))
            settings.addWidget(self.sleep)
            self.save = button("Apply OpenRazer preferences", self.apply_preferences)
            self.save.setEnabled(False)
            settings.addWidget(self.save, 0, Qt.AlignmentFlag.AlignLeft)
            box.addWidget(panel)
            help_panel, help_box = card()
            help_box.addWidget(text("Host setup", 16, weight=600))
            help_box.addWidget(text("OpenRazer's driver and desktop-session daemon must be installed on the host. On SteamOS, your user also needs the package's device permission group and a restart after setup. The Flatpak cannot install host kernel drivers.", 12, MUTED, wrap=True))
            help_box.addWidget(button("View scan diagnostics", lambda: host.navigate("diagnostics"), "ghost"), 0, Qt.AlignmentFlag.AlignLeft)
            box.addWidget(help_panel)

    def receive(self, result):
        self.scan_result = result
        devices = [d for d in result["devices"] if self.kind is None or d["type"] == self.kind]
        self.summary.setText(f"{len(devices)} device{'s' if len(devices) != 1 else ''} found." +
                             (" Some sources need attention; see below." if result.get("errors") else ""))
        clear_layout(self.results)
        for device in devices:
            panel, content = card()
            content.addWidget(text(device["name"], 17, weight=600, wrap=True))
            content.addWidget(text(TYPES[device["type"]] + "  ·  " + device["usb_id"] + "  ·  " + device["serial"], 12, MUTED, wrap=True))
            content.addWidget(button("Open device", lambda _=False, d=device: self.host.open_device(d), "primary"), 0, Qt.AlignmentFlag.AlignLeft)
            self.results.addWidget(panel)
        if not devices:
            self.results.addWidget(text("No connected devices found in this category. Check the USB connection, wake wireless devices, and scan again.", 13, MUTED, wrap=True))
        if self.kind is None:
            for source, message in result.get("errors", {}).items():
                self.results.addWidget(text(f"{source}: {message}", 12, "#f39a90", wrap=True))
            for widget, key in ((self.sync, "sync_effects"), (self.sleep, "off_on_screensaver")):
                value = result.get(key)
                widget.setEnabled(type(value) is bool)
                widget.setChecked(value is True)
            self.save.setEnabled(not self.host.busy and (self.sync.isEnabled() or self.sleep.isEnabled()))

    def apply_preferences(self):
        settings = []
        if self.sync.isEnabled(): settings.append(("syncEffects", self.sync.isChecked()))
        if self.sleep.isEnabled(): settings.append(("enableTurnOffOnScreensaver", self.sleep.isChecked()))
        def apply(controller):
            return {"settings": [controller.global_setting(name, value) for name, value in settings]}
        def done(result):
            # Invalidate cached device pages: sync permissions must be reread.
            for page in self.host.device_pages.values(): page.failed()
            self.host.notify("OpenRazer preferences saved. Refresh a device to read its controls.")
        return self.host.run("Saving OpenRazer preferences", apply, done,
                             controller_factory=self.host.openrazer_factory)

    def update_enabled(self):
        self.scan_button.setEnabled(not self.host.busy)
        if self.kind is None:
            self.save.setEnabled(not self.host.busy and hasattr(self, "scan_result") and
                                 (self.scan_result.get("sync_effects") is not None or self.scan_result.get("off_on_screensaver") is not None))
