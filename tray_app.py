"""Luma: a small Windows tray companion for Tapo lights."""
import asyncio
import json
import math
import queue
import itertools
import random
import sys
import winreg
from pathlib import Path

from keyring.backends.Windows import WinVaultKeyring
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSettings, QEvent, QLockFile, QStandardPaths
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QCursor, QFontDatabase
from PySide6.QtWidgets import (QApplication, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QLineEdit, QCheckBox, QStackedWidget, QScrollArea,
    QSlider, QSystemTrayIcon, QMenu, QColorDialog, QGridLayout, QSizePolicy)

from backend import Backend

SERVICE = 'Luma.Tapo.Desktop'
PRESET_COLORS = [QColor.fromHsv(hue, 255, 255).name() for hue in range(0, 360, 15)]
PRESET_WHITES = [2500, 2700, 3000, 3500, 4000, 4500, 5000, 6500]


def kelvin_to_hex(kelvin):
    """Approximate blackbody-radiation RGB for a color temperature (Tanner Helland's formula)."""
    temp = kelvin / 100
    if temp <= 66:
        red = 255
    else:
        red = max(0, min(255, 329.698727446 * ((temp - 60) ** -0.1332047592)))
    if temp <= 66:
        green = max(0, min(255, 99.4708025861 * math.log(temp) - 161.1195681661))
    else:
        green = max(0, min(255, 288.1221695283 * ((temp - 60) ** -0.0755148492)))
    if temp >= 66:
        blue = 255
    elif temp <= 19:
        blue = 0
    else:
        blue = max(0, min(255, 138.5177312231 * math.log(temp - 10) - 305.0447927307))
    return QColor(int(red), int(green), int(blue)).name()

STYLE = '''
QWidget { font-family: "Segoe UI"; font-size: 13px; color: #27243A; }
QWidget#shell { background: #F7F6F2; border: 1px solid #DEDDE6; border-radius: 20px; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 25px; font-weight: 700; letter-spacing: -1px; }
QLabel#title { font-size: 25px; font-weight: 650; }
QLabel#muted { color: #827D91; font-size: 12px; }
QLabel#eyebrow { color: #8C829E; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#status { color: #78658F; font-size: 12px; }
QFrame#card { background: white; border: 1px solid #E8E5EF; border-radius: 15px; }
QPushButton { background: #EEEAF4; border: none; border-radius: 10px; padding: 9px 12px; font-weight: 600; }
QPushButton:hover { background: #E4DDEE; }
QPushButton:pressed { background: #D8CBE9; }
QPushButton:disabled { color: #B8B1C3; background: #F1EFF3; }
QPushButton#primary { background: #7961A8; color: white; padding: 13px; }
QPushButton#primary:hover { background: #695195; }
QPushButton#quiet { background: transparent; color: #827D91; padding: 5px 8px; }
QPushButton#quiet:checked { color: #9B5FA8; font-weight: 700; }
QPushButton#power { background: #EEEAF4; color: #8C819A; border-radius: 16px; }
QPushButton#power:checked { background: #E7F1E6; color: #4D7D52; }
QLineEdit { background: white; padding: 12px; border: 1px solid #DFDAE6; border-radius: 10px; }
QLineEdit:focus { border: 1px solid #957AB9; }
QCheckBox { spacing: 8px; color: #777084; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 5px; }
QScrollBar::handle:vertical { background: #D8D2E1; border-radius: 2px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QSlider::groove:horizontal { height: 6px; border-radius: 3px; background: #ECE8F1; }
QSlider::sub-page:horizontal { background: #A28ABA; border-radius: 3px; }
QSlider::handle:horizontal { background: white; border: 2px solid #9474B2; width: 14px; margin: -5px 0; border-radius: 8px; }
QToolButton#viewOption { border: 1px solid #E1DBE9; padding: 7px 10px; border-radius: 9px; }
QPushButton#mover { background: transparent; color: #A79BB8; padding: 0px; font-size: 9px; border-radius: 4px; }
QPushButton#mover:hover { background: #EEEAF4; color: #7961A8; }
QPushButton#mover:disabled { color: #DAD5E2; background: transparent; }
QMenu { background: white; border: 1px solid #DDD7E6; padding: 6px; }
QMenu::item { padding: 8px 25px; border-radius: 5px; }
QMenu::item:selected { background: #EEEAF4; }
QToolTip { background-color: #27243A; color: #FFFFFF; border: 1px solid #46415A; padding: 4px 8px; border-radius: 6px; }
'''

DARK_STYLE = STYLE + '''
QWidget { color: #EEEAF5; }
QWidget#shell { background: #1D1D25; border: 1px solid #363440; }
QLabel#muted { color: #B1AABD; }
QLabel#eyebrow { color: #B5A1C9; }
QLabel#status { color: #C5AFDF; }
QFrame#card { background: #292832; border: 1px solid #3B3945; }
QPushButton { background: #373440; color: #F0EBF5; }
QPushButton:hover { background: #474150; }
QPushButton:pressed { background: #594D65; }
QPushButton:disabled { color: #817B88; background: #292832; }
QPushButton#primary { background: #9175B2; color: white; }
QPushButton#primary:hover { background: #A086C0; }
QPushButton#quiet { background: transparent; color: #C4B8D0; }
QPushButton#quiet:hover { background: #34313D; }
QPushButton#quiet:checked { color: #D89FE0; font-weight: 700; }
QPushButton#power { background: #373440; color: #C2B7CE; }
QPushButton#power:checked { background: #314738; color: #B5DEB9; }
QLineEdit { background: #292832; color: #F0EBF5; border: 1px solid #45414D; }
QLineEdit:focus { border: 1px solid #AA8FC8; }
QCheckBox { color: #C4B8D0; }
QScrollBar::handle:vertical { background: #514A5A; }
QSlider::groove:horizontal { background: #46414D; }
QSlider::sub-page:horizontal { background: #B49ACF; }
QSlider::handle:horizontal { background: #F4EEF9; border-color: #BA9DD3; }
QPushButton#mover { color: #8A7FA0; }
QPushButton#mover:hover { background: #373440; color: #C4B0E0; }
QPushButton#mover:disabled { color: #4A4655; background: transparent; }
QMenu { background: #292832; color: #F0EBF5; border: 1px solid #45414D; }
QMenu::item:selected { background: #40394A; }
'''


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, name=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    widget.clicked.connect(callback)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def bulb_icon(lit=True):
    body_color = '#8D72B1' if lit else '#6B6675'
    glow_color = '#FFF3CF' if lit else '#B9B4C2'
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(body_color))
    painter.drawRoundedRect(2, 2, 60, 60, 18, 18)
    painter.setBrush(QColor(glow_color))
    painter.drawEllipse(20, 12, 24, 27)
    painter.drawRoundedRect(26, 32, 12, 12, 4, 4)
    painter.setPen(QPen(QColor(glow_color), 3))
    painter.drawLine(28, 49, 36, 49)
    painter.end()
    return QIcon(pixmap)


def system_theme():
    """Windows' own light/dark preference, for the 'Auto' theme option."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
        value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        return 'light' if value else 'dark'
    except OSError:
        return 'light'


class ScrollFriendlySlider(QSlider):
    """Leave mouse-wheel scrolling to the containing light list."""
    def wheelEvent(self, event):
        event.ignore()


class Worker(QThread):
    result = Signal(str, object)
    failure = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.jobs = queue.PriorityQueue()
        self.sequence = itertools.count()

    def submit(self, name, args):
        priority = -1 if name == 'close' else 0 if name == 'control' else 5 if name == 'scan' else 10
        self.jobs.put((priority, next(self.sequence), name, args))

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        backend = Backend()
        try:
            while True:
                _, _, name, args = self.jobs.get()
                if name == 'close':
                    break
                try:
                    value = loop.run_until_complete(getattr(backend, name)(*args))
                    self.result.emit(name, value)
                except Exception as error:
                    # Do not include exception payloads: libraries may include authentication data.
                    self.failure.emit(name, type(error).__name__)
        finally:
            loop.run_until_complete(backend.close())
            loop.close()


class LightCard(QFrame):
    def __init__(self, row, send, parent=None):
        super().__init__(parent)
        self.setObjectName('card')
        self.row = row
        self.send = send
        self.timers = {}
        self.view_mode = 'large'
        self.expanded = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(6)
        names = QVBoxLayout()
        self.name = label(row['name'])
        self.name.setStyleSheet('font-size: 15px; font-weight: 650;')
        self.name.setWordWrap(True)
        self.name.setMinimumWidth(0)
        self.name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        names.addWidget(self.name)
        self.detail = label('', 'muted')
        names.addWidget(self.detail)
        header.addLayout(names, 1)
        self.power = button('ON', self.power_changed, 'power')
        self.power.setCheckable(True)
        self.power.setFixedSize(54, 34)
        header.addWidget(self.power)
        layout.addLayout(header)
        self.details_button = button('Details', self.toggle_details, 'quiet')
        self.details_button.hide()
        self.details_row = QHBoxLayout()
        self.details_row.addStretch()
        self.details_row.addWidget(self.details_button)
        self.controls = QWidget()
        controls = QVBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(9)
        self.brightness_box = QWidget()
        brightness_box = QVBoxLayout(self.brightness_box)
        brightness_box.setContentsMargins(0, 0, 0, 0)
        brightness_box.setSpacing(9)
        self.brightness, self.brightness_text = self.slider(brightness_box, 'Bright', 1, 100, 'brightness')
        controls.addWidget(self.brightness_box)
        self.extra_controls = QWidget()
        extra = QVBoxLayout(self.extra_controls)
        extra.setContentsMargins(0, 0, 0, 0)
        extra.setSpacing(9)
        self.temperature = None
        if row.get('white'):
            self.temperature, self.temperature_text = self.slider(extra, 'Temp', 2500, 6500, 'white')
            whites = QHBoxLayout()
            whites.setSpacing(0)
            for index, kelvin in enumerate(PRESET_WHITES):
                if index > 0:
                    whites.addStretch()
                swatch = button('', lambda checked=False, value=kelvin: self.send(self.row['id'], 'white', value))
                swatch.setFixedSize(20, 20)
                swatch.setToolTip(f'Set {kelvin:,}K')
                swatch.setAccessibleName(f'Set {kelvin:,}K white')
                # A thin outline (unlike the borderless color palette below) since the
                # coolest shades are near-white and otherwise vanish against the card.
                swatch.setStyleSheet(f'background: {kelvin_to_hex(kelvin)}; border-radius: 10px; border: 1px solid #D8D2E1; padding: 0px;')
                whites.addWidget(swatch)
            extra.addLayout(whites)
        if row.get('color'):
            palette = QVBoxLayout()
            palette.setContentsMargins(0, 0, 0, 0)
            palette.setSpacing(6)
            columns = 8
            for start in range(0, len(PRESET_COLORS), columns):
                color_row = QHBoxLayout()
                color_row.setSpacing(0)
                for index, hex_color in enumerate(PRESET_COLORS[start:start + columns]):
                    if index > 0:
                        color_row.addStretch()
                    swatch = button('', lambda checked=False, value=hex_color: self.color(value))
                    swatch.setFixedSize(20, 20)
                    swatch.setToolTip(f'Set color {hex_color}')
                    swatch.setAccessibleName(f'Set color {hex_color}')
                    swatch.setStyleSheet(f'background: {hex_color}; border-radius: 10px; border: none; padding: 0px;')
                    color_row.addWidget(swatch)
                palette.addLayout(color_row)
            custom = QHBoxLayout()
            custom.addStretch()
            custom.addWidget(button('Custom color', self.pick_color, 'quiet'))
            palette.addLayout(custom)
            extra.addLayout(palette)
        controls.addWidget(self.extra_controls)
        layout.addWidget(self.controls)
        layout.addLayout(self.details_row)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.update_row(row)

    def slider(self, layout, title, low, high, action):
        line = QHBoxLayout()
        line.addWidget(label(title, 'muted'))
        value_label = label('', 'muted')
        line.addStretch()
        line.addWidget(value_label)
        layout.addLayout(line)
        slider = ScrollFriendlySlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setAccessibleName(title)
        slider.setSingleStep(1 if action == 'brightness' else 100)
        slider.setFixedHeight(22)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(220)
        self.timers[action] = timer
        timer.timeout.connect(lambda: self.send(self.row['id'], action, slider.value()))
        def changed(value):
            value_label.setText(f'{value}%' if action == 'brightness' else f'{value:,} K')
            timer.start()
        slider.valueChanged.connect(changed)
        layout.addWidget(slider)
        return slider, value_label

    def power_changed(self, checked):
        self.send(self.row['id'], 'power', checked)

    def color(self, value):
        color = QColor(value)
        self.send(self.row['id'], 'color', [max(0, color.hsvHue()), round(color.hsvSaturationF() * 100)])

    def pick_color(self):
        owner = self.window()
        owner.dialog_open = True
        try:
            # A plain QColorDialog.getColor() can open behind the popup, since the
            # popup itself is always-on-top; force the dialog on top too.
            dialog = QColorDialog(QColor.fromHsv(self.row['hsv'][0] % 360, round(self.row['hsv'][1] * 2.55), 255), self)
            dialog.setWindowTitle('Choose light color')
            dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            if dialog.exec() == QColorDialog.DialogCode.Accepted and dialog.selectedColor().isValid():
                self.color(dialog.selectedColor())
        finally:
            owner.dialog_open = False
            owner.activateWindow()

    def update_row(self, row):
        self.row = row
        online = row.get('online', False)
        self.name.setText(row['name'])
        self.detail.setText(f"{row['model']}  ·  {'Connected' if online else 'Offline'}")
        self.detail.setVisible(self.view_mode == 'large')
        self.power.setChecked(row['on'])
        self.power.setText('ON' if row['on'] else 'OFF')
        self.power.setEnabled(online)
        self.controls.setEnabled(online)
        self.details_button.setEnabled(online)
        if not self.brightness.isSliderDown() and not self.timers['brightness'].isActive():
            self.brightness.blockSignals(True)
            self.brightness.setValue(row['brightness'])
            self.brightness.blockSignals(False)
            self.brightness_text.setText(f"{row['brightness']}%")
        if self.temperature and not self.temperature.isSliderDown() and not self.timers['white'].isActive():
            self.temperature.blockSignals(True)
            self.temperature.setValue(row['kelvin'] or 4000)
            self.temperature.blockSignals(False)
            self.temperature_text.setText(f"{row['kelvin']:,} K" if row['kelvin'] else 'Color mode')

    def set_view(self, mode):
        if self.view_mode == mode:
            return
        self.view_mode = mode
        self.expanded = False
        self.detail.setVisible(mode == 'large')
        self.details_button.setVisible(mode == 'compact')
        self.details_row.setEnabled(self.row.get('online', False))
        self._sync_expansion()

    def toggle_details(self):
        self.expanded = not self.expanded
        self._sync_expansion()

    def _sync_expansion(self):
        self.extra_controls.setVisible(self.view_mode == 'large' or self.expanded)
        self.details_button.setText('Less' if self.expanded else 'Details')


class Popup(QWidget):
    def __init__(self, demo=False):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle('Luma · Tapo lights')
        self.setFixedSize(420, 690)
        self.demo = demo
        self.dialog_open = False
        self.rows, self.cards = {}, {}
        self.busy = False
        self.pending_controls = 0
        self.settings = QSettings('Luma', 'TapoTray')
        self.view_mode = {'comfortable': 'large', 'compact': 'compact', 'list': 'compact', 'large': 'large'}.get(
            self.settings.value('cardView', 'large'), 'large')
        self.order = [identity for identity in str(self.settings.value('order', '')).split(',') if identity]
        self.vault = WinVaultKeyring()
        self.credentials = None
        self.worker = Worker()
        self.worker.result.connect(self.received)
        self.worker.failure.connect(self.failed)
        if not demo:
            self.worker.start()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        shell = QWidget()
        shell.setObjectName('shell')
        root.addWidget(shell)
        body = QVBoxLayout(shell)
        body.setContentsMargins(24, 20, 24, 18)
        body.setSpacing(16)
        header = QHBoxLayout()
        mark = label('')
        mark.setPixmap(bulb_icon().pixmap(32, 32))
        header.addWidget(mark)
        header.addWidget(label('luma', 'brand'))
        header.addStretch()
        header.addWidget(button('—', self.hide, 'quiet'))
        body.addLayout(header)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        self.build_login()
        self.build_lights()
        self.build_reorder_page()
        self.status = label('A little light, right where you need it.', 'status')
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        footer = QHBoxLayout()
        footer.addWidget(label('LOCAL CONNECTION', 'eyebrow'))
        footer.addStretch()
        self.account = button('Account', self.show_account, 'quiet')
        footer.addWidget(self.account)
        self.theme_button = button('', self.toggle_theme, 'quiet')
        footer.addWidget(self.theme_button)
        self.theme = self.settings.value('theme', 'dark')
        self.apply_theme()
        body.addLayout(footer)
        self.tray_lit = False
        self.tray = QSystemTrayIcon(bulb_icon(False), self)
        self.tray.setToolTip('Luma · Tapo lights')
        self.tray.activated.connect(self.activated)
        menu = QMenu()
        menu.addAction('Open Luma', self.open_popup)
        menu.addAction('Refresh lights', self.scan)
        menu.addSeparator()
        menu.addAction('Quit', self.quit)
        self.tray.setContextMenu(menu)
        self.menu = menu
        if not demo:
            self.tray.show()
        self.poll = QTimer(self)
        self.poll.setInterval(15000)
        self.poll.timeout.connect(self.on_poll)
        self.poll.start()
        self.discovery_timer = QTimer(self)
        self.discovery_timer.setInterval(60000)
        self.discovery_timer.timeout.connect(self.scan)
        self.discovery_timer.start()
        self.party_active = False
        self.party_interval_ms = 1000
        self.party_timer = QTimer(self)
        self.party_timer.setInterval(self.party_interval_ms)
        self.party_timer.timeout.connect(self.party_tick)
        if demo:
            self.pages.setCurrentIndex(1)
            self.received('scan', {'rows': [dict(id='demo1', host='192.0.2.1', name='Living room', model='L530E', on=True, online=True, brightness=72, color=True, white=True, kelvin=2700, hsv=[30, 40, 72]), dict(id='demo2', host='192.0.2.2', name='Reading nook', model='L530E', on=False, online=True, brightness=35, color=True, white=True, kelvin=4000, hsv=[250, 45, 35])], 'issues': [], 'scan': True})
        else:
            email = self.settings.value('email', '')
            self.email.setText(email)
            try:
                password = self.vault.get_password(SERVICE, email) if email else None
                if password:
                    self.credentials = (email, password)
                    self.pages.setCurrentIndex(1)
                    QTimer.singleShot(100, self.scan)
            except Exception:
                self.status.setText('Saved login unavailable. Please sign in again.')

    def build_login(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 18, 0, 0)
        box.setSpacing(16)
        box.addWidget(label('YOUR SPACE, YOUR LIGHT', 'eyebrow'))
        box.addWidget(label('Make yourself\nat home.', 'title'))
        intro = label('Connect your Tapo account to find and control\nyour lights on this network.', 'muted')
        box.addWidget(intro)
        box.addSpacing(12)
        self.email = QLineEdit()
        self.email.setPlaceholderText('Tapo account email')
        self.email.setAccessibleName('Tapo account email')
        box.addWidget(self.email)
        self.password = QLineEdit()
        self.password.setPlaceholderText('Password')
        self.password.setAccessibleName('Tapo password')
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self.login)
        box.addWidget(self.password)
        self.remember = QCheckBox('Remember me on this computer')
        self.remember.setChecked(True)
        box.addWidget(self.remember)
        self.connect_button = button('Connect my lights  →', self.login, 'primary')
        box.addWidget(self.connect_button)
        hint = label('Enable Third-Party Compatibility in\nTapo → Me → Tapo Lab before connecting.', 'muted')
        hint.setWordWrap(True)
        box.addWidget(hint)
        box.addStretch()
        box.addWidget(button('Forget saved login', self.forget, 'quiet'))
        self.pages.addWidget(page)

    def build_lights(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(14)
        title_row = QHBoxLayout()
        title_row.addWidget(label('Your lights', 'title'))
        title_row.addStretch()
        self.view_button = button('', self.toggle_view, 'quiet')
        title_row.addWidget(self.view_button)
        self.refresh_button = button('Refresh', self.scan, 'quiet')
        title_row.addWidget(self.refresh_button)
        box.addLayout(title_row)
        summary_row = QHBoxLayout()
        self.summary = label('Finding your lights…', 'muted')
        summary_row.addWidget(self.summary, 1)
        self.party_button = button('Party mode', self.toggle_party, 'quiet')
        self.party_button.setCheckable(True)
        self.party_button.setToolTip('Randomize colors on every online, color-capable light on a timer.\nRight-click to change how often.')
        self.party_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.party_button.customContextMenuRequested.connect(self.show_party_menu)
        summary_row.addWidget(self.party_button)
        summary_row.addWidget(button('Reorder', self.show_reorder, 'quiet'))
        box.addLayout(summary_row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName('lightList')
        container.setStyleSheet('QWidget#lightList { background: transparent; }')
        self.card_layout = QGridLayout(container)
        self.card_layout.setContentsMargins(0, 0, 5, 0)
        self.card_layout.setSpacing(12)
        self.card_layout.setColumnStretch(0, 1)
        self.card_layout.setColumnStretch(1, 1)
        self.empty = label('No lights yet.\n\nKeep your bulbs powered on and connected\nto the same network, then choose Refresh.', 'muted')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(200)
        self.card_layout.addWidget(self.empty, 0, 0, 1, 2)
        self.card_layout.setRowStretch(1000, 1)
        scroll.setWidget(container)
        self.scroll = scroll
        scroll.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        box.addWidget(scroll, 1)
        all_row = QHBoxLayout()
        all_row.addWidget(button('All on', lambda: self.all_power(True)))
        all_row.addWidget(button('All off', lambda: self.all_power(False)))
        box.addLayout(all_row)
        self.pages.addWidget(page)
        self.sync_view_button()

    def build_reorder_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 18, 0, 0)
        box.setSpacing(16)
        box.addWidget(label('PRIORITY ORDER', 'eyebrow'))
        box.addWidget(label('Reorder your\nlights.', 'title'))
        intro = label('Move your most-used lights to the top. This is the\norder they appear in everywhere.', 'muted')
        intro.setWordWrap(True)
        box.addWidget(intro)
        box.addSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName('lightList')
        container.setStyleSheet('QWidget#lightList { background: transparent; }')
        self.reorder_layout = QVBoxLayout(container)
        self.reorder_layout.setContentsMargins(0, 0, 5, 0)
        self.reorder_layout.setSpacing(8)
        self.reorder_layout.addStretch()
        scroll.setWidget(container)
        box.addWidget(scroll, 1)
        box.addWidget(button('Done', self.close_reorder, 'primary'))
        self.pages.addWidget(page)

    def show_reorder(self):
        self.refresh_reorder_rows()
        self.pages.setCurrentIndex(2)

    def close_reorder(self):
        self.pages.setCurrentIndex(1)

    def refresh_reorder_rows(self):
        while self.reorder_layout.count() > 1:
            item = self.reorder_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        ids = self.ordered_ids()
        for index, identity in enumerate(ids):
            row_widget = QFrame()
            row_widget.setObjectName('card')
            line = QHBoxLayout(row_widget)
            line.setContentsMargins(14, 6, 10, 6)
            line.addWidget(label(self.rows[identity]['name']), 1)
            up = button('▲', lambda checked=False, i=identity: self.reorder(i, 'up'), 'mover')
            down = button('▼', lambda checked=False, i=identity: self.reorder(i, 'down'), 'mover')
            up.setFixedSize(28, 26)
            down.setFixedSize(28, 26)
            up.setEnabled(index != 0)
            down.setEnabled(index != len(ids) - 1)
            line.addWidget(up)
            line.addWidget(down)
            self.reorder_layout.insertWidget(self.reorder_layout.count() - 1, row_widget)

    VIEW_ORDER = ['large', 'compact']
    VIEW_LABELS = {'large': 'Large cards', 'compact': 'Small cards'}
    THEME_ORDER = ['light', 'dark', 'auto']
    THEME_LABELS = {'light': 'Light mode', 'dark': 'Dark mode', 'auto': 'Auto theme'}

    def sync_view_button(self):
        if hasattr(self, 'view_button'):
            # Shows the CURRENT view name; clicking switches to the other one.
            self.view_button.setText(self.VIEW_LABELS[self.view_mode])
            other = self.VIEW_ORDER[(self.VIEW_ORDER.index(self.view_mode) + 1) % len(self.VIEW_ORDER)]
            self.view_button.setToolTip(f'Switch to {self.VIEW_LABELS[other].lower()}')

    def apply_theme(self):
        if self.theme not in self.THEME_ORDER:
            self.theme = 'dark'
        effective = system_theme() if self.theme == 'auto' else self.theme
        QApplication.instance().setStyleSheet(DARK_STYLE if effective == 'dark' else STYLE)
        next_theme = self.THEME_ORDER[(self.THEME_ORDER.index(self.theme) + 1) % len(self.THEME_ORDER)]
        self.theme_button.setText(self.THEME_LABELS[next_theme])
        self.theme_button.setToolTip(f'Switch to {self.THEME_LABELS[next_theme].lower()}')

    def toggle_theme(self):
        self.theme = self.THEME_ORDER[(self.THEME_ORDER.index(self.theme) + 1) % len(self.THEME_ORDER)]
        if not self.demo:
            self.settings.setValue('theme', self.theme)
        self.apply_theme()

    def toggle_view(self):
        self.view_mode = self.VIEW_ORDER[(self.VIEW_ORDER.index(self.view_mode) + 1) % len(self.VIEW_ORDER)]
        if not self.demo:
            self.settings.setValue('cardView', self.view_mode)
        self.sync_view_button()
        for card in self.cards.values():
            card.set_view(self.view_mode)
        self.layout_cards()

    def reorder(self, identity, direction):
        if identity not in self.order:
            return
        index = self.order.index(identity)
        target = index - 1 if direction == 'up' else index + 1
        if not 0 <= target < len(self.order):
            return
        self.order[index], self.order[target] = self.order[target], self.order[index]
        if not self.demo:
            self.settings.setValue('order', ','.join(self.order))
        self.layout_cards()
        if self.pages.currentIndex() == 2:
            self.refresh_reorder_rows()

    def ordered_ids(self):
        known = [identity for identity in self.order if identity in self.cards]
        known += [identity for identity in self.cards if identity not in self.order]
        return known

    def layout_cards(self):
        ids = self.ordered_ids()
        for index, identity in enumerate(ids):
            card = self.cards[identity]
            self.card_layout.removeWidget(card)
            row, column = (index // 2, index % 2) if self.view_mode == 'compact' else (index, 0)
            self.card_layout.addWidget(card, row, column, 1, 1 if self.view_mode == 'compact' else 2)
        # Widget heights can change a lot between views (e.g. large -> list);
        # force a full relayout so the scroll area doesn't leave stale paint.
        self.card_layout.invalidate()
        self.scroll.widget().adjustSize()

    def login(self):
        email, password = self.email.text().strip(), self.password.text()
        if not email or not password:
            self.status.setText('Enter your Tapo email and password.')
            return
        if self.busy or self.pending_controls:
            return
        # A new account must never retain another account's cards.
        self.clear_cards()
        self.credentials = (email, password)
        self.password.clear()
        self.pages.setCurrentIndex(1)
        self.scan()

    def save_credentials(self):
        if not self.credentials:
            return
        email, password = self.credentials
        previous = self.settings.value('email', '')
        try:
            if previous and (previous != email or not self.remember.isChecked()):
                if self.vault.get_password(SERVICE, previous):
                    self.vault.delete_password(SERVICE, previous)
            if self.remember.isChecked():
                self.vault.set_password(SERVICE, email, password)
                self.settings.setValue('email', email)
            else:
                self.settings.remove('email')
        except Exception:
            self.status.setText('Connected. Windows could not save your login; it is kept for this session only.')

    def clear_cards(self):
        self.stop_party()
        for card in self.cards.values():
            self.card_layout.removeWidget(card)
            card.deleteLater()
        self.cards.clear()
        self.rows.clear()
        self.empty.show()

    def forget(self):
        if self.busy or self.pending_controls:
            self.status.setText('Wait for the current request to finish, then try again.')
            return
        email = self.settings.value('email', '')
        try:
            if email and self.vault.get_password(SERVICE, email):
                self.vault.delete_password(SERVICE, email)
            self.settings.remove('email')
        except Exception:
            self.status.setText('Could not remove the saved login from Windows Credential Manager.')
            return
        self.credentials = None
        self.worker.submit('close', ())
        self.clear_cards()
        self.email.clear()
        self.password.clear()
        self.status.setText('Saved login removed.')

    def show_account(self):
        if self.busy or self.pending_controls:
            self.status.setText('Finishing the current request…')
            return
        if self.pages.currentIndex() == 0 and self.credentials:
            self.pages.setCurrentIndex(1)
        else:
            self.pages.setCurrentIndex(0)
            self.status.setText('Your password is stored in Windows Credential Manager.')

    def scan(self):
        if self.demo or not self.credentials or self.busy or self.pending_controls:
            return
        self.busy = True
        self.refresh_button.setEnabled(False)
        self.connect_button.setEnabled(False)
        self.status.setText('Looking for your lights on this network…')
        self.worker.submit('scan', self.credentials)

    def refresh(self):
        if not self.demo and self.credentials and self.rows and not self.busy and not self.pending_controls and self.isVisible():
            self.busy = True
            self.worker.submit('refresh', ())

    def on_poll(self):
        if self.theme == 'auto':
            self.apply_theme()
        self.refresh()

    def send(self, identity, action, value):
        if self.demo:
            return
        if not self.credentials:
            self.status.setText('Connect to your Tapo account before changing a light.')
            return
        self.pending_controls += 1
        self.status.setText('Sending change…' if not self.busy else 'Refresh in progress · change queued next')
        self.worker.submit('control', (identity, action, value))

    def all_power(self, power):
        for identity, row in self.rows.items():
            if row.get('online'):
                self.send(identity, 'power', power)

    PARTY_INTERVALS = [('Fast · every 0.5s', 500), ('Normal · every 1s', 1000),
                       ('Slow · every 2s', 2000), ('Chill · every 5s', 5000)]

    def toggle_party(self):
        if self.demo or not self.credentials:
            self.party_button.setChecked(False)
            return
        if self.party_active:
            self.stop_party()
        else:
            self.party_active = True
            self.party_button.setChecked(True)
            self.party_button.setText('Stop party')
            self.party_timer.start()
            self.party_tick()

    def stop_party(self):
        self.party_active = False
        self.party_timer.stop()
        self.party_button.setChecked(False)
        self.party_button.setText('Party mode')

    def party_tick(self):
        for identity, row in self.rows.items():
            if row.get('online') and row.get('color'):
                self.send(identity, 'color', [random.randint(0, 359), random.randint(70, 100)])

    def show_party_menu(self, pos):
        menu = QMenu(self.party_button)
        for label_text, ms in self.PARTY_INTERVALS:
            action = menu.addAction(label_text)
            action.setCheckable(True)
            action.setChecked(self.party_interval_ms == ms)
            action.triggered.connect(lambda checked=False, value=ms: self.set_party_interval(value))
        menu.exec(self.party_button.mapToGlobal(pos))

    def set_party_interval(self, ms):
        self.party_interval_ms = ms
        self.party_timer.setInterval(ms)

    def received(self, name, result):
        if name == 'control':
            self.pending_controls = max(0, self.pending_controls - 1)
        if name == 'close':
            return
        if name in ('scan', 'refresh'):
            self.busy = False
            self.refresh_button.setEnabled(True)
            self.connect_button.setEnabled(True)
        if result.get('scan'):
            for row in self.rows.values():
                row['online'] = False
        for row in result['rows']:
            identity = row['id']
            if identity in self.rows:
                self.rows[identity].update(row)
            elif 'name' in row:
                self.rows[identity] = row
        order_changed = False
        for identity, row in self.rows.items():
            if identity not in self.order:
                self.order.append(identity)
                order_changed = True
            if identity not in self.cards:
                card = LightCard(row, self.send)
                self.cards[identity] = card
            self.cards[identity].update_row(row)
            self.cards[identity].set_view(self.view_mode)
        if order_changed and not self.demo:
            self.settings.setValue('order', ','.join(self.order))
        self.layout_cards()
        if self.pages.currentIndex() == 2:
            self.refresh_reorder_rows()
        self.empty.setVisible(not self.rows)
        connected = sum(row.get('online', False) for row in self.rows.values())
        on = sum(row.get('online', False) and row.get('on', False) for row in self.rows.values())
        self.summary.setText(f'{connected} connected  ·  {on} on')
        self.tray.setToolTip(f'Luma · {connected} lights connected')
        # Only touch the tray icon when the on/off state actually flips: recreating
        # it on every poll risks Windows briefly dropping a left-click activation.
        lit = on > 0
        if self.tray_lit != lit:
            self.tray_lit = lit
            self.tray.setIcon(bulb_icon(lit))
        issues = result.get('issues', [])
        self.status.setText(issues[0] if issues else 'All up to date.' if connected else 'No reachable lights. Check Wi-Fi and Tapo Lab settings.')
        if name == 'scan' and connected and not self.demo:
            self.save_credentials()
        if name == 'scan' and not connected and any('login rejected' in issue for issue in issues):
            self.pages.setCurrentIndex(0)

    def failed(self, name, error):
        if name == 'control':
            self.pending_controls = max(0, self.pending_controls - 1)
        if name in ('scan', 'refresh'):
            self.busy = False
        self.refresh_button.setEnabled(True)
        self.connect_button.setEnabled(True)
        self.status.setText('Could not connect. Check your login and Tapo Lab settings.' if name == 'scan' else 'Light did not respond. Refresh and try again.')
        if name == 'control':
            self.refresh()

    def activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible():
                self.hide()
            else:
                self.open_popup()

    def open_popup(self):
        anchor = self.tray.geometry()
        point = anchor.center() if not anchor.isEmpty() else QCursor.pos()
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(point.x() - self.width() + 30, area.left() + 10), area.right() - self.width() - 10)
        y = area.bottom() - self.height() - 10
        if not anchor.isEmpty() and anchor.top() < area.center().y():
            y = area.top() + 10
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def event(self, event):
        if event.type() == QEvent.Type.WindowDeactivate and not self.dialog_open and not self.demo:
            QTimer.singleShot(150, self.hide_if_inactive)
        return super().event(event)

    def hide_if_inactive(self):
        if not self.isActiveWindow() and not self.dialog_open:
            self.hide()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def quit(self):
        self.hide()
        self.tray.hide()
        self.poll.stop()
        self.discovery_timer.stop()
        self.party_timer.stop()
        # Allow active network operations to close cleanly without freezing the UI.
        if self.worker.isRunning():
            self.worker.submit('close', ())
            self.worker.finished.connect(QApplication.instance().quit)
        else:
            QApplication.instance().quit()


def main():
    app = QApplication(sys.argv)
    for font in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    app.setWindowIcon(bulb_icon())
    demo = '--preview' in sys.argv
    lock = QLockFile(str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)) / 'luma-tapo.lock'))
    if not demo and not lock.tryLock(0):
        return 0
    popup = Popup(demo)
    if demo:
        popup.show()
        def capture():
            popup.grab().save(str(Path(__file__).parent / 'preview.png'))
            popup.pages.setCurrentIndex(0)
            app.processEvents()
            popup.grab().save(str(Path(__file__).parent / 'preview-login.png'))
            app.quit()
        QTimer.singleShot(300, capture)
    elif not popup.credentials:
        QTimer.singleShot(150, popup.open_popup)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
