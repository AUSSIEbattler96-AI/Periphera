"""Guided host setup. Checking is automatic; every repair is an explicit action."""
import json
import os
from pathlib import Path

from PyQt6.QtCore import QProcess, QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication, QComboBox, QMessageBox, QTextEdit, QWidget

from barracuda_gui import GREEN, MUTED, RED, TEXT, button, card, column, row, text
from hardware_setup import fingerprint


def host_command(arguments, privileged=False):
    source = Path(__file__).with_name("hardware_setup.py").read_text()
    command = ["/usr/bin/python3", "-c", source, *arguments]
    if privileged:
        command.insert(0, "/usr/bin/pkexec")
    if os.environ.get("FLATPAK_ID"):
        command = ["flatpak-spawn", "--host", *command]
    return command


def decode_result(output):
    for line in reversed(output.splitlines()):
        if line.startswith("PERIPHERA_RESULT="):
            result = json.loads(line.removeprefix("PERIPHERA_RESULT="))
            if not isinstance(result, dict):
                raise ValueError("Invalid setup response")
            return result
    raise ValueError("The host helper did not return a setup report.")


class HardwareSetupPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.process = None
        self.report = None
        self.mode = ""
        self.output_text = ""
        layout = column(self, 16)
        panel, box = card(True)
        box.addWidget(text("LET'S GET YOUR DEVICES READY", 17, GREEN, 600))
        self.summary = text("Check this computer's drivers, device permissions and service status.", 13, TEXT, wrap=True)
        box.addWidget(self.summary)
        box.addWidget(text("Hardware support is shared with other apps on this computer. Checks leave your settings alone.", 12, MUTED, wrap=True))
        actions = row()
        self.check_button = host.action("Check Linux setup", self.check, "primary")
        actions.addWidget(self.check_button)
        actions.addWidget(button("Open device controls", lambda: host.navigate("mouse"), "ghost"))
        actions.addStretch()
        box.addLayout(actions)
        layout.addWidget(panel)
        self.check_panel, self.check_layout = card()
        self.check_layout.addWidget(text("No checks run yet.", 13, MUTED))
        panel, box = card()
        box.addWidget(text("INSTALL OR REPAIR SUPPORT", 11, MUTED, 600))
        self.target = QComboBox()
        self.target.addItem("Mouse and mouse mats", "openrazer")
        self.target.addItem("Barracuda headset", "headset")
        self.target.addItem("Headset, mouse and mats", "all")
        self.target.currentIndexChanged.connect(self.update_enabled)
        box.addWidget(self.target)
        self.plan_note = text("Run the checks to see which setup actions are available.", 12, MUTED, wrap=True)
        box.addWidget(self.plan_note)
        actions = row()
        self.install_button = host.action("Install / repair", self.confirm_repair, "primary")
        self.service_button = host.action("Start / restart device service", self.restart_service)
        actions.addWidget(self.install_button)
        actions.addWidget(self.service_button)
        actions.addStretch()
        box.addLayout(actions)
        layout.addWidget(panel)
        layout.addWidget(self.check_panel)
        panel, box = card()
        line = row()
        line.addWidget(text("SETUP DETAILS", 11, MUTED, 600), 1)
        line.addWidget(button("Copy setup details", self.copy_details, "ghost"))
        box.addLayout(line)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(150)
        box.addWidget(self.output)
        layout.addWidget(panel)
        self.update_enabled()

    @property
    def running(self):
        return self.process is not None

    def append_log(self, value):
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertPlainText(value + "\n")

    def update_enabled(self, _=None):
        busy = self.host.busy or self.running
        plan = self.report["plans"].get(self.target.currentData()) if self.report else None
        self.check_button.setEnabled(not busy)
        self.target.setEnabled(not busy)
        self.install_button.setEnabled(not busy and bool(plan) and not plan.get("blocked"))
        self.service_button.setEnabled(not busy and bool(self.report) and self.report.get("group_active", False)
                                       and bool(self.report.get("daemon_version")) and bool(self.report.get("driver_version")))
        if plan:
            self.plan_note.setText(plan.get("blocked") or
                ("Installs the required driver packages and device permissions. Administrator authentication is required."
                 if plan["packages"] else "Installs the headset's USB access rule. Administrator authentication is required."))

    def render_report(self, report):
        self.report = report
        while self.check_layout.count():
            item = self.check_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        states = {"pass": ("Ready", GREEN), "missing": ("Needs setup", RED),
                  "restart": ("Sign in again", "#e9bc69"), "info": ("Info", MUTED)}
        for check in report["checks"]:
            status, color = states.get(check["state"], ("Check", MUTED))
            widget = QWidget()
            box = column(widget, 4)
            box.addWidget(text(check["label"] + "  ·  " + status, 13, color, 600, wrap=True))
            box.addWidget(text(check["detail"], 12, MUTED, wrap=True))
            self.check_layout.addWidget(widget)
        names = ", ".join(device["name"] for device in report["devices"])
        self.summary.setText(report["name"] + " · " + report["kernel"] +
                             ("\nConnected: " + names if names else "\nConnect a device to check its USB access."))
        self.update_enabled()

    def check(self):
        return self.start("probe", ["--probe"])

    def confirm_repair(self):
        if not self.report or self.host.busy:
            return
        target = self.target.currentData()
        plan = self.report["plans"][target]
        if plan.get("blocked"):
            return
        lines = ["Set up " + self.target.currentText().lower() + " on this computer?"]
        if plan["packages"]:
            lines += ["", "Install using your configured Linux repositories:", ", ".join(plan["packages"]),
                      "Set up your account's device access and load the drivers."]
        if plan["headset_rule"]:
            lines += ["Install the headset's USB permission rule; reconnect the dongle afterwards."]
        if plan["packages"] and plan["steam_readonly"] == "enabled":
            lines += ["", "SteamOS will be made writable during installation and returned to read-only mode afterwards."]
        lines += ["", "You may need to sign out and back in, or reboot. This support is shared with your other apps."]
        answer = QMessageBox.question(self, "Install hardware support", "\n".join(lines),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.start("repair", ["--apply", target, "--expected-plan", fingerprint(plan)], privileged=True)

    def restart_service(self):
        return self.start("service", ["--restart-service"])

    def start(self, mode, arguments, privileged=False):
        if self.host.busy or self.running:
            self.host.notify("Wait for the current operation to finish.")
            return False
        self.mode, self.output_text = mode, ""
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.host.busy = True
        for action in self.host.actions:
            action.setEnabled(False)
        self.host.monitoring.setEnabled(False)
        self.host.mouse_page.update_enabled()
        self.host.mat_page.update_enabled()
        self.host.progress.setRange(0, 0)
        self.update_enabled()
        self.append_log("Checking Linux setup…" if mode == "probe" else
                           "Waiting for administrator authentication…" if privileged else "Starting the device service…")
        self.host.notify("Checking Linux setup…" if mode == "probe" else "Hardware support setup is running…")
        try:
            args = host_command(arguments, privileged=privileged)
            self.process.start(args[0], args[1:])
        except OSError as exc:
            self.output_text = str(exc)
            self.finished(-1)
        return True

    def read_output(self):
        if self.process is None:
            return
        chunk = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        self.output_text += chunk
        self.output_text = self.output_text[-2_000_000:]
        # JSON reports are presented as readable checks, rather than a raw blob.
        for line in chunk.splitlines():
            if not line.startswith("PERIPHERA_RESULT="):
                self.append_log(line)

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.output_text += "Host execution failed. Check that this testing Flatpak has its packaged permissions and that the host has Python 3."
            self.finished(-1)

    def finished(self, code, _status=None):
        if self.process is None:
            return
        self.read_output()
        process, self.process = self.process, None
        process.deleteLater()
        self.host.busy = False
        self.host.progress.setRange(0, 1)
        self.host.progress.setValue(0)
        for action in self.host.actions:
            action.setEnabled(True)
        self.host.monitoring.setEnabled(True)
        self.host.mouse_page.update_enabled()
        self.host.mat_page.update_enabled()
        success = False
        try:
            result = decode_result(self.output_text)
            if code != 0 or result.get("ok") is False:
                raise ValueError(result.get("error", "The setup command failed."))
            if self.mode == "probe":
                self.render_report(result)
                message = "Linux setup checked. Scan your device after resolving any setup items."
            else:
                message = result["message"]
            self.append_log(message)
            self.host.notify(message)
            success = True
        except (ValueError, KeyError, TypeError) as exc:
            message = ("Administrator authentication was cancelled or unavailable." if code in (126, 127) and self.mode == "repair" else
                       str(exc) + ("\n" + self.output_text[-2500:] if "PERIPHERA_RESULT=" not in self.output_text else ""))
            self.append_log(message)
            self.host.notify("Setup could not finish. See the setup details.", error=True)
            # Require a fresh report before another privileged operation.
            self.report = None
            self.summary.setText("Setup could not finish. Read the details below, then run the checks again.")
        self.update_enabled()
        if self.host.closing:
            self.host.close()
        elif success and self.mode != "probe":
            QTimer.singleShot(0, self.check)

    def copy_details(self):
        report = json.dumps(self.report, indent=2) if self.report else "No host report."
        QApplication.clipboard().setText(report + "\n\n" + self.output.toPlainText())
        self.host.notify("Setup details copied.")
