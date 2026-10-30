"""Qt desktop interface for the unchanged Barracuda HID backend.

No writes occur on launch, refresh, slider editing, or color preview. The
monitoring switch is an explicit apply action. Hardware I/O stays off the UI
thread and only one operation runs at a time.
"""
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

try:
    from PyQt6.QtCore import Qt, QRectF, QPointF, QTimer
    from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPalette, QKeySequence, QShortcut, QRadialGradient
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
        QVBoxLayout, QHBoxLayout, QStackedWidget, QScrollArea,
        QSlider, QLineEdit, QComboBox, QTextEdit, QProgressBar, QColorDialog,
        QAbstractButton, QSizePolicy,
    )
except ImportError as exc:
    raise ImportError("The new GUI needs PyQt6. On Arch/CachyOS run: sudo pacman -S --needed python-pyqt6") from exc

from barracuda import Controller, PRESETS, color_value, diagnose, effect

UI_VERSION = "0.4.1"
APP_ID = "io.github.AUSSIEbattler96_AI.Periphera"
GREEN = "#44d62c"
BG = "#0e1011"
PANEL = "#191c1e"
MUTED = "#99a39d"
TEXT = "#edf1ed"
RED = "#f39a90"


def application_icon():
    """Load the same transparent icon from a source checkout or the Flatpak."""
    root = Path(__file__).resolve().parent
    for path in (root / "packaging" / f"{APP_ID}.png", root / f"{APP_ID}.png"):
        if path.is_file():
            return QIcon(str(path))
    return QIcon.fromTheme(APP_ID)


STYLE = """
QWidget { color: #edf1ed; font-family: "DejaVu Sans"; font-size: 13px; }
QMainWindow, QWidget#shell, QWidget#page, QStackedWidget { background: #0e1011; }
QFrame#sidebar { background: #121416; border-right: 1px solid #292d2f; }
QFrame#header { background: #0e1011; border-bottom: 1px solid #292d2f; }
QFrame#footer { background: #121416; border-top: 1px solid #292d2f; }
QFrame#card { background: #191c1e; border: 1px solid #2b3032; border-radius: 12px; }
QFrame#hero { background: #171c1a; border: 1px solid #2b3730; border-radius: 12px; }
QFrame#line { background: #2b3032; border: none; }
QPushButton { background: #282e2b; border: 1px solid transparent; border-radius: 6px;
              padding: 9px 15px; color: #edf1ed; font-weight: 600; }
QPushButton:hover { background: #344035; border-color: #485b46; }
QPushButton:pressed { background: #243a22; }
QPushButton:focus { border-color: #44d62c; }
QPushButton:disabled { background: #232825; color: #667168; }
QPushButton[kind="primary"] { background: #44d62c; color: #0b1609; }
QPushButton[kind="primary"]:hover { background: #64e64e; }
QPushButton[kind="primary"]:disabled { background: #284f23; color: #859d7e; }
QPushButton[kind="ghost"] { background: transparent; color: #a6b0a8; }
QPushButton[kind="ghost"]:hover { background: #263227; color: #44d62c; }
QPushButton[kind="nav"] { background: transparent; color: #9fa8a2; text-align: left;
                         padding: 13px 18px; border: 1px solid transparent; border-radius: 7px; }
QPushButton[kind="nav"]:checked { background: #20311e; color: #6fe65b; border-left: 3px solid #44d62c; }
QPushButton[kind="nav"]:hover { background: #202822; color: #d1e4d0; }
QPushButton[kind="preset"]:checked { background: #20391e; color: #6ee65b; border-color: #4e9a40; }
QLineEdit { background: #111515; border: 1px solid #343b36; border-radius: 5px;
            padding: 8px; selection-background-color: #32522b; }
QLineEdit:focus { border-color: #44d62c; }
QSpinBox { background: #111515; border: 1px solid #343b36; border-radius: 6px;
           padding: 8px; min-width: 85px; }
QSpinBox:focus { border-color: #44d62c; }
QSpinBox:disabled, QComboBox:disabled, QLineEdit:disabled { color: #667168; }
QCheckBox { spacing: 7px; color: #aab8ad; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #50604f; border-radius: 3px; background: #121713; }
QCheckBox::indicator:checked { background: #44d62c; }
QComboBox { background: #111515; border: 1px solid #343b36; border-radius: 6px;
            padding: 8px 12px; min-width: 75px; }
QComboBox:focus { border-color: #44d62c; }
QComboBox::drop-down { border: none; width: 23px; }
QComboBox QAbstractItemView { background: #1b221d; color: #edf1ed;
                            selection-background-color: #294326; outline: none; }
QTextEdit { background: #111515; border: 1px solid #2f3731; border-radius: 7px;
            padding: 12px; color: #b6d4b9; selection-background-color: #31502d; }
QSlider::groove:horizontal { height: 4px; background: #354038; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #44d62c; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #70e55b;
                            border: 1px solid #44d62c; border-radius: 7px; }
QSlider::groove:vertical { width: 4px; background: #354038; border-radius: 2px; }
QSlider::handle:vertical { height: 9px; margin: 0 -10px; background: #64de50;
                          border: 1px solid #86ef70; border-radius: 3px; }
QSlider:focus { border: 1px solid #3a6332; border-radius: 4px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 0; }
QScrollBar::handle:vertical { background: #3b493d; min-height: 25px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QProgressBar { background: #131814; border: none; max-height: 3px; }
QProgressBar::chunk { background: #44d62c; }
QToolTip { background: #253525; color: #edf1ed; border: 1px solid #477440; padding: 6px; }
"""


def text(value, size=13, color=TEXT, weight=400, wrap=False):
    w = QLabel(value)
    w.setStyleSheet(f"color: {color}; font-size: {size}px; font-weight: {weight}; background: transparent; border: none;")
    w.setWordWrap(wrap)
    return w


def row(spacing=10):
    layout = QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    return layout


def column(parent=None, spacing=10, margins=0):
    layout = QVBoxLayout(parent)
    layout.setContentsMargins(margins, margins, margins, margins)
    layout.setSpacing(spacing)
    return layout


def card(hero=False):
    w = QFrame()
    w.setObjectName("hero" if hero else "card")
    return w, column(w, 12, 20)


def button(title, callback, kind="", checkable=False):
    w = QPushButton(title)
    w.setProperty("kind", kind)
    w.setCheckable(checkable)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    w.clicked.connect(callback)
    return w


def divider():
    w = QFrame()
    w.setObjectName("line")
    w.setFixedHeight(1)
    return w


class Switch(QAbstractButton):
    """Keyboard-accessible switch. setChecked never emits clicked."""
    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(48, 28)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Microphone monitoring")
        self.setToolTip("Toggle sidetone on the headset")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(GREEN if self.isChecked() else "#465047"))
        p.drawRoundedRect(QRectF(2, 4, 44, 20), 10, 10)
        p.setBrush(QColor("#122210" if self.isChecked() else "#bdc7bd"))
        p.drawEllipse(QPointF(35 if self.isChecked() else 13, 14), 7, 7)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#82e874"), 1))
            p.drawRoundedRect(QRectF(.5, .5, 47, 27), 5, 5)


class HeadsetArt(QWidget):
    """Anti-aliased headset illustration with six preview colors."""
    def __init__(self, colors=None, brightness=None):
        super().__init__()
        self.colors = colors
        self.brightness = brightness
        self.setMinimumSize(230, 210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = min(self.width()/560, self.height()/360)
        p.translate((self.width()-560*s)/2, (self.height()-360*s)/2)
        p.scale(s, s)
        glow = QRadialGradient(QPointF(280, 190), 240)
        glow.setColorAt(0, QColor(68, 214, 44, 17))
        glow.setColorAt(1, QColor(68, 214, 44, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(20, -45, 520, 440))
        p.setBrush(QColor("#0c140f"))
        p.drawEllipse(QRectF(120, 315, 330, 21))
        for rect, width, color in [
            (QRectF(130, 32, 300, 300), 32, "#090c0b"),
            (QRectF(130, 32, 300, 300), 23, "#343d38"),
            (QRectF(132, 29, 296, 300), 2, "#687269"),
            (QRectF(149, 51, 262, 282), 11, "#252d28"),
        ]:
            p.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(rect, 0, 180*16)
        for x in (140, 420):
            p.setPen(QPen(QColor("#657063"), 8))
            p.drawLine(QPointF(x, 154), QPointF(x, 203))
            for rect, color, outline in [
                (QRectF(x-53, 170, 106, 133), "#090d0b", "#171e18"),
                (QRectF(x-46, 165, 92, 130), "#303931", "#53614f"),
                (QRectF(x-38, 172, 76, 115), "#19211b", "#29352b"),
            ]:
                p.setPen(QPen(QColor(outline), 1.4))
                p.setBrush(QColor(color))
                p.drawRoundedRect(rect, 18, 18)
            ring = QRectF(x-27, 186, 54, 86)
            for i in range(6):
                color = QColor(GREEN)
                if self.colors is not None:
                    try:
                        color = QColor("#" + bytes(color_value(self.colors[i].text())).hex())
                        strength = self.brightness.value()/100
                        color = QColor(round(color.red()*strength),
                                       round(color.green()*strength),
                                       round(color.blue()*strength))
                    except ValueError:
                        color = QColor("#58645a")
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 25), 13))
                p.drawArc(ring, (90-i*60+3)*16, -54*16)
                p.setPen(QPen(color, 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawArc(ring, (90-i*60+3)*16, -54*16)
            p.setPen(QPen(QColor("#61755f"), 2))
            p.drawLine(QPointF(x-7, 219), QPointF(x+7, 219))
            p.drawLine(QPointF(x+7, 219), QPointF(x+7, 239))
            p.drawLine(QPointF(x+7, 239), QPointF(x-7, 239))
        path = QPainterPath(QPointF(99, 267))
        path.cubicTo(68, 292, 72, 316, 112, 316)
        path.lineTo(151, 316)
        p.setPen(QPen(QColor("#4e5f4b"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(path)
        p.setBrush(QColor("#6b7f62"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(138, 309, 25, 14), 5, 5)


class Window(QMainWindow):
    def __init__(self, device=None, controller_factory=Controller, autorefresh=True, mouse_factory=None,
                 mat_factory=None):
        super().__init__()
        self.device, self.factory = device, controller_factory
        self.bus = queue.Queue()
        self.busy = self.closing = False
        self.stop = threading.Event()
        self.data, self.dirty = {}, set()
        self.loading = False
        self.actions, self.nav, self.pages = [], {}, {}
        self.last_json = "{}"
        self.draft_preset = "music"
        self.setWindowTitle("Periphera")
        self.setWindowIcon(application_icon())
        self.resize(1180, 860)
        self.setMinimumSize(980, 700)
        self.setStyleSheet(STYLE)
        self._shell()
        self._overview()
        self._sound()
        self._lighting()
        self._diagnostics()
        from naga_gui import MousePage
        from naga import NagaController
        self.mouse_page = MousePage(self, mouse_factory or NagaController)
        self.pages["mouse"][1].addWidget(self.mouse_page)
        from mousemat_gui import MouseMatPage
        from mousemat import MouseMatController
        self.mat_page = MouseMatPage(self, mat_factory or MouseMatController)
        self.pages["mousemat"][1].addWidget(self.mat_page)
        self.navigate("overview")
        self.paint_status()
        self.paint_presets()
        self.paint_colors()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(50)
        self.refresh_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        self.refresh_shortcut.activated.connect(self.refresh_current)
        if autorefresh:
            QTimer.singleShot(200, self.refresh)

    def action(self, title, callback, kind=""):
        w = button(title, callback, kind)
        self.actions.append(w)
        return w

    def _shell(self):
        shell = QWidget()
        shell.setObjectName("shell")
        self.setCentralWidget(shell)
        outer = QHBoxLayout(shell)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        rail = QFrame()
        rail.setObjectName("sidebar")
        rail.setFixedWidth(190)
        outer.addWidget(rail)
        nav = column(rail, 7, 16)
        nav.addSpacing(17)
        mark = QLabel()
        mark.setObjectName("brandLogo")
        mark.setAccessibleName("Periphera kraken logo")
        mark.setPixmap(application_icon().pixmap(40, 40))
        mark.setFixedSize(40, 40)
        nav.addWidget(mark, 0, Qt.AlignmentFlag.AlignLeft)
        nav.addSpacing(9)
        nav.addWidget(text("PERIPHERA", 17, weight=700))
        nav.addWidget(text("Y O U R  D E V I C E S", 9, GREEN, 600))
        nav.addSpacing(28)
        nav.addWidget(text("DEVICE", 10, "#6d7c71", 600))
        nav.addSpacing(5)
        for name, title in (("overview", "Overview"), ("sound", "Sound"),
                            ("lighting", "Lighting"), ("diagnostics", "Diagnostics"),
                            ("mouse", "Naga V2 Pro"), ("mousemat", "Mouse mats")):
            if name == "mouse":
                nav.addSpacing(18)
                nav.addWidget(text("MOUSE", 10, "#6d7c71", 600))
            elif name == "mousemat":
                nav.addSpacing(12)
                nav.addWidget(text("DESK", 10, "#6d7c71", 600))
            w = button(title, lambda _=False, n=name: self.navigate(n), "nav", True)
            nav.addWidget(w)
            self.nav[name] = w
        nav.addStretch()
        nav.addWidget(text("UNOFFICIAL CONTROLLER", 9, "#718076", 600))
        nav.addSpacing(3)
        nav.addWidget(text("Linux  /  UI " + UI_VERSION, 11, MUTED))
        nav.addWidget(text("Headset · mouse · mats", 10, "#718076"))
        nav.addSpacing(6)

        main = QWidget()
        outer.addWidget(main, 1)
        right = column(main, 0)
        header = QFrame()
        header.setObjectName("header")
        line = QHBoxLayout(header)
        line.setContentsMargins(28, 20, 28, 19)
        names = column(spacing=6)
        self.device_category = text("DEVICES  /  AUDIO", 10, "#7e8a82", 600)
        self.device_heading = text("BARRACUDA X CHROMA", 17, weight=700)
        names.addWidget(self.device_category)
        names.addWidget(self.device_heading)
        line.addLayout(names)
        line.addStretch()
        self.connection = text("●  Not checked", 12, MUTED)
        line.addWidget(self.connection)
        line.addSpacing(14)
        line.addWidget(self.action("Refresh status", self.refresh_current))
        right.addWidget(header)

        heading = QWidget()
        headings = column(heading, 6)
        headings.setContentsMargins(28, 22, 28, 18)
        self.page_title = text("", 27, weight=700)
        self.page_caption = text("", 13, MUTED)
        headings.addWidget(self.page_title)
        headings.addWidget(self.page_caption)
        right.addWidget(heading)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        titles = {
            "overview": ("Device overview", "Your headset, at a glance."),
            "sound": ("Sound & microphone", "Tune your listening experience."),
            "lighting": ("Chroma lighting", "Six zones. Make them yours."),
            "diagnostics": ("Diagnostics", "Connection details and the latest device response."),
            "mouse": ("Mouse control", "Performance, lighting and power. One place."),
            "mousemat": ("Mouse-mat lighting", "Your desk. Your colours."),
        }
        for name, title in titles.items():
            page = QWidget()
            page.setObjectName("page")
            layout = column(page, 16)
            layout.setContentsMargins(28, 0, 28, 22)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
            self.pages[name] = (scroll, layout, title)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        right.addWidget(self.progress)
        footer = QFrame()
        footer.setObjectName("footer")
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(24, 13, 24, 13)
        self.notice = text("●  Ready. Refresh to read your headset.", 12, MUTED)
        self.notice.setWordWrap(True)
        self.notice.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.updated = text("Not yet refreshed", 10, "#78877b")
        bottom.addWidget(self.notice, 1)
        bottom.addWidget(self.updated)
        right.addWidget(footer)

    def _overview(self):
        page = self.pages["overview"][1]
        hero, content = card(True)
        content.setContentsMargins(20, 12, 24, 12)
        line = row(18)
        art = HeadsetArt()
        art.setMinimumHeight(244)
        line.addWidget(art, 4)
        details = column(spacing=7)
        details.addStretch()
        details.addWidget(text("WIRELESS GAMING HEADSET", 10, GREEN, 600))
        details.addSpacing(4)
        details.addWidget(text("BARRACUDA", 35, weight=700))
        details.addWidget(text("X CHROMA", 30, "#a4b2a7", 400))
        details.addSpacing(6)
        details.addWidget(text("Your hardware. Your settings.", 13, MUTED))
        details.addSpacing(12)
        actions = row()
        actions.addWidget(button("Tune your sound", lambda: self.navigate("sound"), "primary"))
        actions.addWidget(button("Customize lighting", lambda: self.navigate("lighting"), "ghost"))
        actions.addStretch()
        details.addLayout(actions)
        details.addStretch()
        line.addLayout(details, 5)
        content.addLayout(line)
        page.addWidget(hero)

        stats = row(16)
        self.stat = {}
        for name, heading, sub in [
            ("battery", "BATTERY", "Refresh to read battery"),
            ("preset", "EQUALIZER", "Hardware preset"),
            ("monitor", "MIC MONITORING", "Sidetone"),
        ]:
            panel, box = card()
            box.addWidget(text(heading, 10, MUTED, 600))
            value = text("—", 34, GREEN if name == "battery" else TEXT, 600)
            detail = text(sub, 12, MUTED)
            box.addWidget(value)
            box.addWidget(detail)
            stats.addWidget(panel, 1)
            self.stat[name] = (value, detail)
        page.addLayout(stats)
        panel, box = card()
        line = row()
        left = column(spacing=7)
        left.addWidget(text("WIRELESS POWER SAVING", 10, MUTED, 600))
        self.overview_sleep = text("Idle power-off: —", 14)
        left.addWidget(self.overview_sleep)
        line.addLayout(left, 1)
        line.addWidget(button("Manage power", lambda: self.navigate("sound"), "ghost"))
        box.addLayout(line)
        page.addWidget(panel)

    def _sound(self):
        page = self.pages["sound"][1]
        eq, box = card()
        top = row()
        top.addWidget(text("EQUALIZER", 11, MUTED, 600))
        top.addStretch()
        self.eq_current = text("Current preset: —", 12, MUTED)
        top.addWidget(self.eq_current)
        box.addLayout(top)
        modes = row(8)
        self.preset_buttons = {}
        for name in ("game", "music", "movie", "custom"):
            b = button(name.title(), lambda _=False, n=name: self.select_preset(n), "preset", True)
            modes.addWidget(b)
            self.preset_buttons[name] = b
        modes.addStretch()
        modes.addWidget(self.action("Apply preset", self.apply_preset, "primary"))
        box.addLayout(modes)
        box.addWidget(divider())
        top = row()
        top.addWidget(text("CUSTOM CURVE", 10, MUTED, 600))
        top.addStretch()
        top.addWidget(text("10 bands  ·  Low → high  ·  ±6 gain limit", 11, "#7e8d81"))
        box.addLayout(top)
        sliders = row(7)
        self.gains, self.gain_labels = [], []
        for i in range(10):
            channel = column(spacing=7)
            value = text("0", 14, GREEN, 600)
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fader = QSlider(Qt.Orientation.Vertical)
            fader.setRange(-6, 6)
            fader.setValue(0)
            fader.setMinimumHeight(150)
            fader.setFixedWidth(32)
            fader.setAccessibleName(f"EQ band {i+1}, low to high")
            fader.setToolTip(f"Band {i+1} • range −6 to +6")
            fader.valueChanged.connect(lambda v, n=i: self.gain_changed(n, v))
            channel.addWidget(value)
            channel.addWidget(fader, 1, Qt.AlignmentFlag.AlignHCenter)
            caption = text(f"{i+1:02}", 10, "#859589")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            channel.addWidget(caption)
            sliders.addLayout(channel, 1)
            self.gains.append(fader)
            self.gain_labels.append(value)
        box.addLayout(sliders)
        bottom = row(8)
        bottom.addWidget(text("Edit here, then apply to the headset.", 11, "#7e8d81"), 1)
        bottom.addWidget(button("Flatten", self.flatten, "ghost"))
        bottom.addWidget(self.action("Apply curve", self.apply_curve))
        box.addLayout(bottom)
        page.addWidget(eq)

        cards = row(16)
        sidetone, side = card()
        top = row()
        top.addWidget(text("MIC MONITORING", 11, MUTED, 600), 1)
        self.monitoring = Switch()
        self.monitoring.clicked.connect(self.apply_monitoring)
        top.addWidget(self.monitoring)
        side.addLayout(top)
        side.addWidget(text("Hear your microphone through the headset.", 12, MUTED, wrap=True))
        line = row()
        line.addWidget(text("Level", 12, MUTED), 1)
        self.sidetone_value = text("20%", 14, GREEN, 600)
        line.addWidget(self.sidetone_value)
        side.addLayout(line)
        self.sidetone = QSlider(Qt.Orientation.Horizontal)
        self.sidetone.setRange(0, 100)
        self.sidetone.setValue(20)
        self.sidetone.setAccessibleName("Microphone monitoring level")
        self.sidetone.valueChanged.connect(self.sidetone_changed)
        side.addWidget(self.sidetone)
        line = row()
        line.addStretch()
        line.addWidget(self.action("Apply level", self.apply_sidetone))
        side.addLayout(line)
        cards.addWidget(sidetone, 3)

        power, contents = card()
        contents.addWidget(text("POWER SAVING", 11, MUTED, 600))
        self.power_current = text("Current timeout: —", 12, MUTED)
        contents.addWidget(self.power_current)
        self.sleep = QComboBox()
        for caption, value in (("Never", 0), ("15 minutes", 15), ("30 minutes", 30)):
            self.sleep.addItem(caption, value)
        self.sleep.setCurrentIndex(1)
        self.sleep.currentIndexChanged.connect(lambda _: self.mark_dirty("sleep"))
        self.sleep.setAccessibleName("Idle power-off timeout")
        contents.addWidget(self.sleep)
        contents.addStretch()
        contents.addWidget(self.action("Apply timeout", self.apply_sleep), 0, Qt.AlignmentFlag.AlignRight)
        cards.addWidget(power, 2)
        page.addLayout(cards)

    def _lighting(self):
        page = self.pages["lighting"][1]
        self.colors = [QLineEdit("44D62C") for _ in range(6)]
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setRange(0, 100)
        self.brightness.setValue(50)
        self.brightness.setAccessibleName("Lighting brightness")
        self.brightness.valueChanged.connect(self.brightness_changed)
        self.light_art = HeadsetArt(self.colors, self.brightness)
        top = row(16)
        panel, preview = card(True)
        preview.addWidget(text("COLOR PREVIEW", 11, MUTED, 600))
        preview.addWidget(self.light_art, 1)
        preview.addWidget(text("Preview only. Apply to update the headset.", 11, MUTED, wrap=True))
        top.addWidget(panel, 4)
        settings, controls = card()
        controls.addWidget(text("QUICK COLOR", 11, MUTED, 600))
        controls.addWidget(text("Choose a color for all six zones.", 12, MUTED))
        palette = row(9)
        for color in ("44D62C", "17CBB4", "389EFF", "9C70FF", "FF537F", "FFFFFF"):
            b = button("", lambda _=False, c=color: self.all_colors(c))
            b.setFixedSize(34, 30)
            b.setStyleSheet(f"background:#{color}; border:1px solid #{color}; border-radius:5px; padding:0;")
            b.setAccessibleName("All zones " + color)
            palette.addWidget(b)
        palette.addStretch()
        controls.addLayout(palette)
        controls.addWidget(button("Choose custom color", self.choose_all, "ghost"), 0, Qt.AlignmentFlag.AlignLeft)
        top_line = row()
        top_line.addWidget(text("BRIGHTNESS", 10, MUTED, 600), 1)
        self.brightness_value = text("50%", 15, GREEN, 600)
        top_line.addWidget(self.brightness_value)
        controls.addLayout(top_line)
        controls.addWidget(self.brightness)
        controls.addSpacing(3)
        actions = row()
        actions.addWidget(self.action("Apply colors", self.apply_rgb, "primary"))
        actions.addWidget(self.action("Lights off", self.turn_off, "ghost"))
        actions.addStretch()
        controls.addLayout(actions)
        top.addWidget(settings, 5)
        page.addLayout(top)

        zones, content = card()
        top_line = row()
        top_line.addWidget(text("INDIVIDUAL ZONES", 11, MUTED, 600), 1)
        top_line.addWidget(text("Click a swatch to pick a color", 11, MUTED))
        content.addLayout(top_line)
        line = row(14)
        self.swatches = []
        for i, entry in enumerate(self.colors):
            zone = column(spacing=6)
            zone.addWidget(text(f"ZONE {i}", 10, MUTED, 600))
            b = button("", lambda _=False, n=i: self.pick_color(n))
            b.setFixedHeight(26)
            b.setAccessibleName(f"Pick color for zone {i}")
            self.swatches.append(b)
            zone.addWidget(b)
            entry.setMaximumWidth(140)
            entry.setMaxLength(7)
            entry.setAccessibleName(f"Zone {i} RGB hex color")
            entry.textChanged.connect(lambda _: self.paint_colors())
            zone.addWidget(entry)
            line.addLayout(zone, 1)
        content.addLayout(line)
        page.addWidget(zones)

        panel, contents = card()
        contents.addWidget(text("QUICK EFFECTS", 11, MUTED, 600))
        line = row()
        self.effect_name = QComboBox()
        for name in ("Spectrum", "Wheel", "Breathe"):
            self.effect_name.addItem(name, name.lower())
        line.addWidget(self.effect_name)
        line.addWidget(self.action("Preview for 30 seconds", self.preview_effect))
        self.stop_button = button("Stop", self.stop.set, "ghost")
        self.stop_button.setEnabled(False)
        line.addWidget(self.stop_button)
        line.addStretch()
        line.addWidget(self.action("Use headset lighting", self.release_lighting, "ghost"))
        contents.addLayout(line)
        contents.addWidget(text(
            "Breathing uses Zone 0's color. Effects run in this app; static colors stay until changed.",
            11, MUTED, wrap=True))
        page.addWidget(panel)

    def _diagnostics(self):
        page = self.pages["diagnostics"][1]
        panel, box = card()
        box.addWidget(text("CONNECTION & SUPPORT", 11, MUTED, 600))
        box.addWidget(text("Barracuda X Chroma  /  1532:0574  /  2.4 GHz USB", 14))
        box.addWidget(text("Independent Linux controls. Not an official Razer application.", 12, MUTED))
        actions = row()
        actions.addWidget(button("Check device access", self.show_diagnose))
        actions.addWidget(self.action("Refresh headset", self.refresh, "ghost"))
        actions.addStretch()
        box.addLayout(actions)
        page.addWidget(panel)
        panel, box = card()
        line = row()
        line.addWidget(text("LATEST RESPONSE", 11, MUTED, 600), 1)
        line.addWidget(button("Copy", self.copy_details, "ghost"))
        box.addLayout(line)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(310)
        self.log.setStyleSheet('font-family: "DejaVu Sans Mono"; font-size: 12px;')
        box.addWidget(self.log, 1)
        page.addWidget(panel, 1)
        page.addWidget(text("RGB previews show your chosen colors, not a live readback of the LEDs.", 11, MUTED, wrap=True))

    def navigate(self, name):
        self.current_page = name
        page, _, title = self.pages[name]
        self.stack.setCurrentWidget(page)
        self.page_title.setText(title[0])
        self.page_caption.setText(title[1])
        for key, b in self.nav.items():
            b.setChecked(key == name)
        self.device_category.setText("DEVICES  /  MOUSE MATS" if name == "mousemat" else
                                     "DEVICES  /  MOUSE" if name == "mouse" else "DEVICES  /  AUDIO")
        self.device_heading.setText("RAZER CHROMA RGB" if name == "mousemat" else
                                    "NAGA V2 PRO" if name == "mouse" else "BARRACUDA X CHROMA")
        self.connection.setVisible(name not in ("mouse", "mousemat"))

    def refresh_current(self):
        if self.current_page == "mouse":
            return self.mouse_page.refresh()
        if self.current_page == "mousemat":
            return self.mat_page.refresh()
        return self.refresh()

    def mark_dirty(self, field):
        if not self.loading:
            self.dirty.add(field)

    def select_preset(self, name):
        self.draft_preset = name
        self.mark_dirty("preset")
        self.paint_presets()

    def paint_presets(self):
        for name, b in self.preset_buttons.items():
            b.setChecked(name == self.draft_preset)

    def gain_changed(self, index, value):
        self.gain_labels[index].setText(f"+{value}" if value > 0 else str(value))
        self.mark_dirty("curve")

    def sidetone_changed(self, value):
        self.sidetone_value.setText(f"{value}%")
        self.mark_dirty("sidetone")

    def brightness_changed(self, value):
        self.brightness_value.setText(f"{value}%")
        self.light_art.update()

    def paint_colors(self):
        for i, b in enumerate(self.swatches):
            try:
                color = "#" + bytes(color_value(self.colors[i].text())).hex()
            except ValueError:
                color = "#333b35"
            b.setStyleSheet(f"background:{color}; border:1px solid {color}; border-radius:5px; padding:0;")
        self.light_art.update()

    def paint_status(self):
        battery, charge = self.data.get("battery_percent"), self.data.get("charging")
        self.stat["battery"][0].setText(f"{battery}%" if battery is not None else "—")
        self.stat["battery"][1].setText("Charging" if charge is True else
                                       "Not charging" if charge is False else "Refresh to read battery")
        preset = self.data.get("eq_preset")
        self.stat["preset"][0].setText(preset.title() if preset else "—")
        self.eq_current.setText("Current preset: " + (preset.title() if preset else "—"))
        monitor = self.data.get("sidetone_enabled")
        self.stat["monitor"][0].setText("On" if monitor is True else "Off" if monitor is False else "—")
        raw = self.data.get("sidetone_level")
        self.stat["monitor"][1].setText(f"Level {round(raw*100/15)}%" if raw is not None else "Sidetone")
        timeout = self.data.get("sleep_minutes")
        caption = "Disabled" if timeout == 0 else f"{timeout} minutes" if timeout is not None else "—"
        self.power_current.setText("Current timeout: " + caption)
        self.overview_sleep.setText("Idle power-off: " + caption)

    def notify(self, message, error=False):
        self.notice.setText("●  " + message)
        self.notice.setStyleSheet(f"color:{RED if error else MUTED}; font-size:12px; border:none;")
        self.notice.setToolTip(message)

    def show_response(self, result):
        self.last_json = json.dumps(result, indent=2)
        self.log.setPlainText(self.last_json)

    def copy_details(self):
        QApplication.clipboard().setText(self.last_json)
        self.notify("Response copied to clipboard.")

    def show_diagnose(self):
        self.show_response(diagnose())
        self.navigate("diagnostics")
        self.notify("Device access checked. No headset settings were changed.")

    def run(self, title, operation, done=None, failed=None, is_effect=False,
            controller_factory=None, device=None):
        if self.busy:
            self.notify("An operation is running. Wait, or stop the lighting preview.")
            return False
        self.busy = True
        self.stop.clear()
        for b in self.actions:
            b.setEnabled(False)
        self.monitoring.setEnabled(False)
        self.mouse_page.update_enabled()
        self.mat_page.update_enabled()
        self.stop_button.setEnabled(is_effect)
        self.progress.setRange(0, 0)
        self.notify(title + "…")

        factory = controller_factory or self.factory
        target = device if controller_factory is not None else self.device
        def worker():
            try:
                with factory(target) as c:
                    result = operation(c)
                self.bus.put((True, result, done, failed))
            except Exception as exc:
                self.bus.put((False, str(exc), done, failed))
        threading.Thread(target=worker, daemon=True).start()
        return True

    def poll(self):
        try:
            ok, result, done, failed = self.bus.get_nowait()
        except queue.Empty:
            return
        self.busy = False
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        for b in self.actions:
            b.setEnabled(True)
        self.monitoring.setEnabled(True)
        self.stop_button.setEnabled(False)
        if ok:
            self.show_response(result)
            if done:
                done(result)
            else:
                self.notify("Operation completed.")
        else:
            self.show_response({"error": result})
            self.notify("Operation failed. Open Diagnostics for the full response.", error=True)
            if failed:
                failed()
        self.mouse_page.update_enabled()
        self.mat_page.update_enabled()
        if self.closing:
            self.close()

    def refresh(self):
        def failed():
            self.data.clear()
            self.connection.setText("●  Unavailable")
            self.connection.setStyleSheet(f"color:{RED}; font-size:12px;")
            self.updated.setText("Refresh failed")
            self.paint_status()
        return self.run("Reading headset", lambda c: c.status(), self.receive_status, failed)

    def receive_status(self, result):
        self.data = dict(result.get("values", {}))
        errors = result.get("errors", {})
        if result.get("link_event") is False:
            self.data.clear()
        self.loading = True
        curve_outside_range = False
        try:
            if "eq_preset" in self.data and "preset" not in self.dirty:
                self.draft_preset = self.data["eq_preset"]
                self.paint_presets()
            gains = self.data.get("eq_gains")
            if gains is not None and len(gains) == 10 and "curve" not in self.dirty:
                if all(-6 <= v <= 6 for v in gains):
                    for slider, value in zip(self.gains, gains):
                        slider.setValue(value)
                else:
                    # Keep the original values in Diagnostics; do not present a
                    # clipped curve as the one actually read from the headset.
                    curve_outside_range = True
            if "sidetone_level" in self.data and "sidetone" not in self.dirty:
                self.sidetone.setValue(round(self.data["sidetone_level"]*100/15))
            if "sidetone_enabled" in self.data:
                self.monitoring.setChecked(self.data["sidetone_enabled"])
            if self.data.get("sleep_minutes") in (0, 15, 30) and "sleep" not in self.dirty:
                self.sleep.setCurrentIndex(self.sleep.findData(self.data["sleep_minutes"]))
        finally:
            self.loading = False
        good = bool(self.data) and not errors
        self.connection.setText("●  Headset responding" if good else
                                "●  Partial response" if self.data else "●  Unavailable")
        self.connection.setStyleSheet(f"color:{GREEN if good else '#e9bc69' if self.data else RED}; font-size:12px;")
        self.updated.setText("Updated " + time.strftime("%H:%M:%S"))
        self.paint_status()
        if curve_outside_range:
            self.notify("Hardware EQ exceeds this editor's range. Sliders were not loaded; see Diagnostics.", error=True)
        else:
            self.notify("Headset status updated." if good else "Some queries failed. See Diagnostics.", error=not good)

    def applied(self, field, value, name, draft=None, expected=None):
        self.data[field] = value
        if draft is not None:
            current = {
                "preset": lambda: self.draft_preset,
                "curve": lambda: [s.value() for s in self.gains],
                "sidetone": self.sidetone.value,
                "sleep": self.sleep.currentData,
            }[draft]()
            if current == expected:
                self.dirty.discard(draft)
        self.paint_status()
        self.notify(name + " applied. Device readback confirmed.")

    def apply_preset(self):
        name = self.draft_preset
        return self.run("Applying " + name.title() + " preset",
                        lambda c: c.set(0x13, bytes((PRESETS[name],))),
                        lambda r: self.applied("eq_preset", r["value"], "EQ preset", "preset", name))

    def flatten(self):
        for slider in self.gains:
            slider.setValue(0)
        self.mark_dirty("curve")
        self.notify("Curve flattened in the editor. Press Apply curve to send it.")

    def apply_curve(self):
        values = [s.value() for s in self.gains]
        def done(r):
            self.data["eq_preset"] = "custom"
            if "preset" not in self.dirty:
                self.draft_preset = "custom"
                self.paint_presets()
            self.applied("eq_gains", r["value"], "Custom EQ curve", "curve", values)
        return self.run("Applying custom EQ curve", lambda c: c.set_curve(values), done)

    def apply_sidetone(self):
        value = self.sidetone.value()
        raw = round(value*15/100)
        return self.run("Applying monitoring level", lambda c: c.set(0x19, bytes((raw,))),
                        lambda r: self.applied("sidetone_level", r["value"], "Monitoring level", "sidetone", value))

    def apply_monitoring(self):
        wanted = self.monitoring.isChecked()
        def failed():
            self.monitoring.setChecked(self.data.get("sidetone_enabled", False))
        started = self.run("Enabling monitoring" if wanted else "Disabling monitoring",
                           lambda c: c.set(0x18, bytes((wanted,))),
                           lambda r: self.applied("sidetone_enabled", r["value"], "Mic monitoring"), failed)
        if not started:
            failed()

    def apply_sleep(self):
        value = self.sleep.currentData()
        return self.run("Applying power-saving timeout", lambda c: c.set(0x2C, bytes((value,))),
                        lambda r: self.applied("sleep_minutes", r["value"], "Power-saving timeout", "sleep", value))

    def pick_color(self, index):
        try:
            initial = QColor("#" + bytes(color_value(self.colors[index].text())).hex())
        except ValueError:
            initial = QColor(GREEN)
        color = QColorDialog.getColor(initial, self, f"Zone {index} color",
                                      QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            self.colors[index].setText(color.name()[1:].upper())

    def all_colors(self, color):
        for entry in self.colors:
            entry.setText(color)
        self.notify("Color preview updated. Press Apply colors to send it.")

    def choose_all(self):
        color = QColorDialog.getColor(QColor(GREEN), self, "Color for all six zones",
                                      QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            self.all_colors(color.name()[1:].upper())

    def apply_rgb(self):
        try:
            colors = [color_value(entry.text()) for entry in self.colors]
        except ValueError:
            self.notify("Enter six-digit hex colors, for example 44D62C.", error=True)
            return False
        brightness = self.brightness.value()
        def apply(c):
            c.rgb(colors, brightness)
            return {"result": "RGB reports sent; visually confirm the headset",
                    "brightness": brightness, "colors": colors}
        return self.run("Applying lighting", apply,
                        lambda _: self.notify("Colors sent to the headset. Visually confirm the lighting."))

    def turn_off(self):
        def apply(c):
            c.rgb([(0, 0, 0)]*6, 0)
            return {"result": "RGB off reports sent; visually confirm"}
        return self.run("Switching lighting off", apply,
                        lambda _: self.notify("Lighting-off command sent. Check the headset."))

    def release_lighting(self):
        def apply(c):
            c.release_rgb()
            return {"result": "Firmware lighting control requested; visually confirm"}
        return self.run("Returning lighting control", apply,
                        lambda _: self.notify("Headset lighting control requested."))

    def preview_effect(self):
        try:
            color = color_value(self.colors[0].text())
        except ValueError:
            self.notify("Zone 0 needs a valid six-digit color for the effect.", error=True)
            return False
        name, brightness = self.effect_name.currentData(), self.brightness.value()
        def preview(c):
            effect(c, name, color, brightness, 30, self.stop)
            return {"result": "Preview ended; firmware lighting requested"}
        return self.run("Previewing " + name, preview,
                        lambda _: self.notify("Preview ended. Headset lighting control requested."),
                        is_effect=True)

    def closeEvent(self, event):
        if self.busy:
            self.closing = True
            self.stop.set()
            self.notify("Finishing the current device operation before closing…")
            event.ignore()
            return
        self.timer.stop()
        event.accept()


def launch(device=None):
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or
            os.environ.get("QT_QPA_PLATFORM") in ("offscreen", "minimal")):
        raise RuntimeError("Open the GUI from your graphical desktop session.")
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("periphera")
    app.setApplicationVersion(UI_VERSION)
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(application_icon())
    app.setStyle("Fusion")
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.Base, QColor("#151a16"))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor("#28322a"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#365f2c"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    app.setPalette(palette)
    app.setFont(QFont("DejaVu Sans", 10))
    window = Window(device)
    window.show()
    app.exec()

