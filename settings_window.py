"""ClearShot — Settings dialog window."""

import os
import sys
import json
import ssl
import threading
import urllib.request
import urllib.error
import webbrowser
import winreg
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QFileDialog, QFormLayout, QGroupBox, QMessageBox,
    QKeySequenceEdit, QSpacerItem, QSizePolicy, QFrame,
    QScrollArea,
)
from constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_HOTKEYS,
    DEFAULT_RECORDING_ANNOTATION_HOLD_KEY,
    IMAGE_FORMATS,
    VIDEO_FORMATS,
)
from icon_utils import ui_icon
from recording import (
    AUDIO_MODE_MICROPHONE,
    AUDIO_MODE_NONE,
    AUDIO_MODE_SYSTEM,
    SYSTEM_AUDIO_DEFAULT_DEVICE,
    list_audio_sources,
    list_system_audio_sources,
)

GITHUB_REPO = "GoblinRules/ClearShot"


class HotkeyEdit(QWidget):
    """A widget to capture a keyboard shortcut."""

    changed = pyqtSignal(str)

    def __init__(self, current_value: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._display = QLineEdit(current_value)
        self._display.setReadOnly(True)
        self._display.setPlaceholderText("Click 'Set' and press a key combination")
        self._display.setStyleSheet("""
            QLineEdit {
                background: #3a3a3a;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px;
                font-family: Consolas;
            }
        """)
        layout.addWidget(self._display)

        self._set_btn = QPushButton("Set")
        self._set_btn.setFixedWidth(60)
        self._set_btn.clicked.connect(self._start_capture)
        layout.addWidget(self._set_btn)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedWidth(60)
        self._clear_btn.clicked.connect(self._clear)
        layout.addWidget(self._clear_btn)

        self._capturing = False
        self._value = current_value

    def _start_capture(self):
        self._capturing = True
        self._display.setText("Press a key combination...")
        self._display.setFocus()
        self._set_btn.setText("...")

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return

        # Build the key string
        parts = []
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")

        key = event.key()
        # Skip modifier-only keys
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta):
            return

        key_name = QKeySequence(key).toString().lower()
        if key_name:
            parts.append(key_name)

        combo = "+".join(parts)
        self._value = combo
        self._display.setText(combo)
        self._capturing = False
        self._set_btn.setText("Set")
        self.changed.emit(combo)

    def _clear(self):
        self._value = ""
        self._display.setText("")
        self._capturing = False
        self._set_btn.setText("Set")
        self.changed.emit("")

    @property
    def value(self):
        return self._value


class SettingsWindow(QDialog):
    """Application settings dialog with tabs."""

    settings_changed = pyqtSignal()
    update_check_finished = pyqtSignal(str, str)
    update_check_failed = pyqtSignal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle(f"{APP_NAME} — Settings")
        self.setMinimumSize(520, 420)
        self.setStyleSheet("""
            QDialog {
                background: #1e1e1e;
                color: #ddd;
            }
            QTabWidget::pane {
                border: 1px solid #444;
                background: #252525;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #2b2b2b;
                color: #aaa;
                padding: 8px 20px;
                border: 1px solid #444;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                min-width: 80px;
            }
            QTabBar::tab:selected {
                background: #252525;
                color: #fff;
            }
            QTabBar::tab:hover {
                background: #333;
            }
            QGroupBox {
                border: 1px solid #444;
                border-radius: 4px;
                margin-top: 12px;
                padding: 12px;
                color: #ccc;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                padding: 0 8px;
            }
            QLabel {
                color: #ccc;
            }
            QLineEdit, QComboBox {
                background: #3a3a3a;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 6px;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 8px;
            }
            QComboBox QAbstractItemView {
                background: #3a3a3a;
                color: #ddd;
                selection-background-color: #0078D4;
            }
            QCheckBox { color: #ccc; }
            QCheckBox::indicator {
                width: 18px; height: 18px;
                border: 2px solid #555;
                border-radius: 3px;
                background: #3a3a3a;
            }
            QCheckBox::indicator:checked {
                background: #0078D4;
                border-color: #0078D4;
            }
            QPushButton {
                background: #3a3a3a;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #4a4a4a;
            }
            QPushButton#saveBtn {
                background: #0078D4;
                color: white;
                border: none;
            }
            QPushButton#saveBtn:hover {
                background: #1a8adf;
            }
        """)

        self._build_ui()
        self._load_values()
        self.update_check_finished.connect(self._show_update_result)
        self.update_check_failed.connect(self._show_update_error)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._create_general_tab(), "General")
        tabs.addTab(self._create_hotkeys_tab(), "Hotkeys")
        tabs.addTab(self._create_startup_tab(), "Startup")
        tabs.addTab(self._create_about_tab(), "About")
        layout.addWidget(tabs)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setObjectName("saveBtn")
        save_btn.clicked.connect(self._save_and_close)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    def _create_general_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Save location
        save_group = QGroupBox("Save Location")
        save_layout = QHBoxLayout(save_group)
        self._save_path_edit = QLineEdit()
        save_layout.addWidget(self._save_path_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_save_path)
        save_layout.addWidget(browse_btn)
        layout.addWidget(save_group)

        # Format
        format_group = QGroupBox("Image Format")
        format_layout = QFormLayout(format_group)
        self._format_combo = QComboBox()
        self._format_combo.addItems(IMAGE_FORMATS.keys())
        format_layout.addRow("Default format:", self._format_combo)
        layout.addWidget(format_group)

        # Filename pattern
        pattern_group = QGroupBox("Filename")
        pattern_layout = QFormLayout(pattern_group)
        self._pattern_edit = QLineEdit()
        self._pattern_edit.setPlaceholderText("ClearShot_{timestamp}")
        pattern_layout.addRow("Pattern:", self._pattern_edit)
        pattern_layout.addRow("", QLabel("Use {timestamp} for date/time"))
        layout.addWidget(pattern_group)

        # Recording
        recording_group = QGroupBox("Screen Recording")
        recording_layout = QFormLayout(recording_group)

        recording_path_widget = QWidget()
        recording_path_layout = QHBoxLayout(recording_path_widget)
        recording_path_layout.setContentsMargins(0, 0, 0, 0)
        self._recording_path_edit = QLineEdit()
        recording_path_layout.addWidget(self._recording_path_edit)
        recording_browse_btn = QPushButton("Browse...")
        recording_browse_btn.clicked.connect(self._browse_recording_path)
        recording_path_layout.addWidget(recording_browse_btn)
        recording_layout.addRow("Save location:", recording_path_widget)

        self._recording_format_combo = QComboBox()
        self._recording_format_combo.addItems(VIDEO_FORMATS.keys())
        recording_layout.addRow("Export format:", self._recording_format_combo)

        self._recording_fps_combo = QComboBox()
        self._recording_fps_combo.addItems(["10", "15", "20", "30"])
        recording_layout.addRow("Frame rate:", self._recording_fps_combo)

        self._show_recording_border_cb = QCheckBox("Show a border around the recording area")
        recording_layout.addRow("", self._show_recording_border_cb)

        self._recording_annotation_hold_combo = QComboBox()
        self._recording_annotation_hold_combo.addItem("Hold Ctrl + Alt to draw", "ctrl+alt")
        self._recording_annotation_hold_combo.addItem("Hold Ctrl + Shift to draw", "ctrl+shift")
        self._recording_annotation_hold_combo.addItem("Hold Alt + Shift to draw", "alt+shift")
        self._recording_annotation_hold_combo.addItem("Hold Shift to draw", "shift")
        self._recording_annotation_hold_combo.addItem("Hold Ctrl to draw", "ctrl")
        self._recording_annotation_hold_combo.addItem("Hold Alt to draw", "alt")
        self._recording_annotation_hold_combo.addItem("Always draw while tools are visible", "")
        recording_layout.addRow("Annotation input:", self._recording_annotation_hold_combo)

        self._recording_audio_mode_combo = QComboBox()
        self._recording_audio_mode_combo.addItem("No audio", AUDIO_MODE_NONE)
        self._recording_audio_mode_combo.addItem("Microphone input", AUDIO_MODE_MICROPHONE)
        self._recording_audio_mode_combo.addItem("System audio", AUDIO_MODE_SYSTEM)
        self._recording_audio_mode_combo.currentIndexChanged.connect(self._refresh_audio_source_enabled)
        recording_layout.addRow("Audio:", self._recording_audio_mode_combo)

        self._recording_audio_source_combo = QComboBox()
        self._recording_audio_source_combo.setEditable(True)
        self._recording_audio_source_combo.addItem("")
        for source in list_audio_sources():
            self._recording_audio_source_combo.addItem(source)
        recording_layout.addRow("Microphone:", self._recording_audio_source_combo)

        self._recording_system_audio_combo = QComboBox()
        self._recording_system_audio_combo.addItem("Default output device", SYSTEM_AUDIO_DEFAULT_DEVICE)
        for name, device_id in list_system_audio_sources():
            self._recording_system_audio_combo.addItem(name, device_id)
        recording_layout.addRow("System audio:", self._recording_system_audio_combo)

        audio_note = QLabel("Microphone uses Windows DirectShow input devices. System audio records the selected output device through Windows loopback.")
        audio_note.setWordWrap(True)
        audio_note.setStyleSheet("color: #888; font-style: italic;")
        recording_layout.addRow("", audio_note)
        layout.addWidget(recording_group)

        layout.addStretch()
        return tab

    def _create_hotkeys_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        hotkey_group = QGroupBox("Global Keyboard Shortcuts")
        hk_layout = QFormLayout(hotkey_group)

        self._hotkey_region = HotkeyEdit()
        hk_layout.addRow("Region capture:", self._hotkey_region)

        self._hotkey_fullscreen = HotkeyEdit()
        hk_layout.addRow("Fullscreen capture:", self._hotkey_fullscreen)

        self._hotkey_record_pause = HotkeyEdit()
        hk_layout.addRow("Pause/resume recording:", self._hotkey_record_pause)

        self._hotkey_record_stop = HotkeyEdit()
        hk_layout.addRow("Stop recording:", self._hotkey_record_stop)

        layout.addWidget(hotkey_group)

        note = QLabel("Note: Hotkeys work globally while ClearShot is running in the system tray.")
        note.setStyleSheet("color: #888; font-style: italic; padding: 8px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        layout.addStretch()
        return tab

    def _create_startup_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        startup_group = QGroupBox("Startup Options")
        s_layout = QVBoxLayout(startup_group)

        self._auto_start_cb = QCheckBox("Start ClearShot with Windows")
        s_layout.addWidget(self._auto_start_cb)

        self._show_notif_cb = QCheckBox("Show tray notifications")
        s_layout.addWidget(self._show_notif_cb)

        self._copy_on_save_cb = QCheckBox("Also copy to clipboard when saving")
        s_layout.addWidget(self._copy_on_save_cb)

        self._magnifier_cb = QCheckBox("Show magnifier during region selection")
        s_layout.addWidget(self._magnifier_cb)

        layout.addWidget(startup_group)
        layout.addStretch()
        return tab

    def _create_about_tab(self) -> QWidget:
        """Create the About tab with Help, About info, and Check for Updates."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(8)

        # --- About info at the top ---
        about_group = QGroupBox(f"About {APP_NAME}")
        about_layout = QVBoxLayout(about_group)
        about_html = (
            f"<h2 style='margin: 0;'>{APP_NAME} v{APP_VERSION}</h2>"
            f"<p>A lightweight, privacy-respecting screenshot tool for Windows.</p>"
            f"<p>• Region & fullscreen capture<br>"
            f"• Region, monitor, and all-screen recording<br>"
            f"• Live recording annotations and system audio capture<br>"
            f"• Annotation tools (pen, arrow, text, blur, and more)<br>"
            f"• Copy to clipboard or save to file<br>"
            f"• Global hotkeys</p>"
            f"<p><a href='https://github.com/{GITHUB_REPO}' style='color: #0099FF;'>GitHub</a></p>"
            f"<p style='color: gray;'>Interface icons use Material Design Icons by Pictogrammers (Apache-2.0).</p>"
            f"<p style='color: gray;'>No uploads. No telemetry. Just local screenshots and recordings.</p>"
        )
        about_label = QLabel(about_html)
        about_label.setWordWrap(True)
        about_label.setTextFormat(Qt.TextFormat.RichText)
        about_label.setOpenExternalLinks(True)
        about_layout.addWidget(about_label)
        layout.addWidget(about_group)

        # --- Check for Updates button ---
        update_layout = QHBoxLayout()
        self._update_btn = QPushButton("Check for Updates")
        self._update_btn.setIcon(ui_icon("refresh"))
        self._update_btn.setIconSize(QSize(16, 16))
        self._update_btn.setStyleSheet(
            "QPushButton { background: #0078D4; color: white; border: none; "
            "border-radius: 6px; padding: 10px 24px; font-weight: bold; font-size: 13px; }"
            "QPushButton:hover { background: #1a8ae8; }"
            "QPushButton:disabled { background: #555; color: #999; }"
        )
        self._update_btn.clicked.connect(self._check_for_updates)
        update_layout.addStretch()
        update_layout.addWidget(self._update_btn)
        update_layout.addStretch()
        layout.addLayout(update_layout)

        # --- Help section (scrollable) ---
        help_group = QGroupBox("Help")
        help_layout = QVBoxLayout(help_group)
        help_layout.setContentsMargins(0, 8, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 8)

        help_html = f"""
        <h3 style="color: #0099FF;">Taking Screenshots</h3>
        <table cellpadding="6" style="margin-left: 8px;">
          <tr><td style="color: #ccc;"><b>Region Capture</b></td>
              <td><code style="background: #333; padding: 2px 8px; border-radius: 3px;">Print Screen</code></td></tr>
          <tr><td style="color: #ccc;"><b>Fullscreen Capture</b></td>
              <td><code style="background: #333; padding: 2px 8px; border-radius: 3px;">Ctrl + Print Screen</code></td></tr>
        </table>
        <p style="color: #aaa; margin-left: 8px;">You can also right-click the tray icon to capture.</p>

        <h3 style="color: #0099FF;">Screen Recording</h3>
        <ol style="color: #ccc; margin-left: 8px;">
          <li>Right-click the tray icon and open <b>Screen Record</b></li>
          <li>Choose <b>Record Region</b>, <b>Record All Monitors</b>, or a specific monitor</li>
          <li>Use <b>Show Annotation Tools</b> while recording, then hold your configured annotation input key while drawing pen, arrows, shapes, text, and numbered markers into the video</li>
          <li>Use <b>Pause Recording</b>, <b>Resume Recording</b>, or <b>Stop Recording</b> from the tray menu</li>
        </ol>
        <table cellpadding="6" style="margin-left: 8px;">
          <tr><td style="color: #ccc;"><b>Pause/Resume</b></td>
              <td><code style="background: #333; padding: 2px 8px; border-radius: 3px;">Ctrl + Alt + Shift + P</code></td></tr>
          <tr><td style="color: #ccc;"><b>Stop Recording</b></td>
              <td><code style="background: #333; padding: 2px 8px; border-radius: 3px;">Ctrl + Alt + Shift + X</code></td></tr>
        </table>
        <p style="color: #aaa; margin-left: 8px;">Recordings can use a separate save folder, MP4 or MKV export, a visible recording border, hold-to-draw annotation input, microphone input, or system audio from a selected output device.</p>

        <h3 style="color: #0099FF;">Region Capture</h3>
        <ol style="color: #ccc; margin-left: 8px;">
          <li>Press <b>Print Screen</b> (or your custom hotkey)</li>
          <li>Click and drag to select an area</li>
          <li>Release to see options:<br>
            &nbsp;&nbsp;<b>Copy</b> — Copy to clipboard<br>
            &nbsp;&nbsp;<b>Save</b> — Save with file dialog<br>
            &nbsp;&nbsp;<b>Quick Save</b> — Save to your default folder<br>
            &nbsp;&nbsp;<b>Edit</b> — Open annotation editor<br>
            &nbsp;&nbsp;<b>Cancel</b> — Discard</li>
        </ol>

        <h3 style="color: #0099FF;">Annotation Tools</h3>
        <table cellpadding="4" style="margin-left: 8px;">
          <tr><td style="color: #ccc;"><b>Pen</b></td><td style="color: #aaa;">Freehand drawing</td></tr>
          <tr><td style="color: #ccc;"><b>Line</b></td><td style="color: #aaa;">Straight lines</td></tr>
          <tr><td style="color: #ccc;"><b>Arrow</b></td><td style="color: #aaa;">Arrows with heads</td></tr>
          <tr><td style="color: #ccc;"><b>Rectangle</b></td><td style="color: #aaa;">Outlined rectangles</td></tr>
          <tr><td style="color: #ccc;"><b>Filled Rect</b></td><td style="color: #aaa;">Solid rectangles</td></tr>
          <tr><td style="color: #ccc;"><b>Ellipse</b></td><td style="color: #aaa;">Circles and ovals</td></tr>
          <tr><td style="color: #ccc;">T <b>Text</b></td><td style="color: #aaa;">Click to type text</td></tr>
          <tr><td style="color: #ccc;"><b>Blur</b></td><td style="color: #aaa;">Blur sensitive areas</td></tr>
          <tr><td style="color: #ccc;"># <b>Counter</b></td><td style="color: #aaa;">Numbered markers (1, 2, 3…)</td></tr>
        </table>
        <p style="color: #aaa; margin-left: 8px;">Use the color palette and size slider to customize.</p>

        <h3 style="color: #0099FF;">Tips</h3>
        <ul style="color: #ccc; margin-left: 8px;">
          <li>Double-click the tray icon to start a region capture</li>
          <li>Use <code style="background: #333; padding: 1px 6px; border-radius: 3px;">Esc</code> to cancel a capture</li>
          <li>Quick Save uses the filename pattern from Settings</li>
          <li>Captured images are saved to <b>Pictures/ClearShot</b> by default</li>
        </ul>
        """

        help_label = QLabel(help_html)
        help_label.setWordWrap(True)
        help_label.setTextFormat(Qt.TextFormat.RichText)
        content_layout.addWidget(help_label)
        scroll.setWidget(content)
        help_layout.addWidget(scroll)
        layout.addWidget(help_group)

        return tab

    def _check_for_updates(self):
        """Check GitHub releases for a newer version."""
        self._update_btn.setEnabled(False)
        self._update_btn.setText("Checking...")

        def _do_check():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                req = urllib.request.Request(url, headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": APP_NAME,
                })
                # Try with default SSL first, fall back to unverified if certs missing
                try:
                    ctx = ssl.create_default_context()
                    resp = urllib.request.urlopen(req, timeout=10, context=ctx)
                except ssl.SSLError:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    resp = urllib.request.urlopen(req, timeout=10, context=ctx)
                data = json.loads(resp.read().decode("utf-8"))
                resp.close()
                latest_tag = data.get("tag_name", "").lstrip("vV")
                html_url = data.get("html_url", "")
                self.update_check_finished.emit(latest_tag, html_url)
            except Exception as exc:
                self.update_check_failed.emit(str(exc))

        threading.Thread(target=_do_check, daemon=True).start()

    def _version_tuple(self, version: str):
        try:
            return tuple(int(part) for part in version.split("."))
        except ValueError:
            return (0, 0, 0)

    def _reset_update_button(self):
        self._update_btn.setEnabled(True)
        self._update_btn.setText("Check for Updates")

    def _show_update_result(self, latest: str, url: str):
        self._reset_update_button()
        current = APP_VERSION.lstrip("vV")
        if not latest:
            self._show_update_error("Could not determine the latest version.")
            return
        if self._version_tuple(latest) > self._version_tuple(current):
            reply = QMessageBox.information(
                self,
                "Update Available",
                f"<h3>A new version is available</h3>"
                f"<p>Current: <b>v{current}</b><br>"
                f"Latest: <b>v{latest}</b></p>"
                f"<p>Visit the releases page to download the update.</p>",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Close,
                QMessageBox.StandardButton.Open,
            )
            if reply == QMessageBox.StandardButton.Open:
                webbrowser.open(url or f"https://github.com/{GITHUB_REPO}/releases")
        else:
            QMessageBox.information(
                self,
                "Up to Date",
                f"<h3>You're up to date</h3>"
                f"<p><b>v{current}</b> is the latest version.</p>",
            )

    def _show_update_error(self, msg: str):
        self._reset_update_button()
        QMessageBox.warning(
            self,
            "Update Check Failed",
            f"<p>Could not check for updates.</p>"
            f"<p style='color: gray;'>{msg}</p>",
        )

    def _refresh_audio_source_enabled(self):
        mode = self._recording_audio_mode_combo.currentData()
        self._recording_audio_source_combo.setEnabled(mode == AUDIO_MODE_MICROPHONE)
        self._recording_system_audio_combo.setEnabled(mode == AUDIO_MODE_SYSTEM)

    def _load_values(self):
        """Load current config values into the UI."""
        self._save_path_edit.setText(self._config.get("save_path", ""))
        
        fmt = self._config.get("image_format", "PNG")
        idx = self._format_combo.findText(fmt)
        if idx >= 0:
            self._format_combo.setCurrentIndex(idx)
        
        self._pattern_edit.setText(self._config.get("filename_pattern", "ClearShot_{timestamp}"))
        self._recording_path_edit.setText(self._config.get("recording_save_path", ""))
        recording_format = self._config.get("recording_format", "MP4")
        recording_format_idx = self._recording_format_combo.findText(recording_format)
        if recording_format_idx >= 0:
            self._recording_format_combo.setCurrentIndex(recording_format_idx)
        fps = str(self._config.get("recording_fps", 15))
        fps_idx = self._recording_fps_combo.findText(fps)
        if fps_idx >= 0:
            self._recording_fps_combo.setCurrentIndex(fps_idx)
        self._show_recording_border_cb.setChecked(self._config.get("show_recording_border", True))
        hold_key = self._config.get("recording_annotation_hold_key", DEFAULT_RECORDING_ANNOTATION_HOLD_KEY)
        hold_idx = self._recording_annotation_hold_combo.findData(hold_key)
        if hold_idx < 0:
            hold_idx = self._recording_annotation_hold_combo.findData(DEFAULT_RECORDING_ANNOTATION_HOLD_KEY)
        if hold_idx >= 0:
            self._recording_annotation_hold_combo.setCurrentIndex(hold_idx)
        audio_mode = self._config.get("recording_audio_mode", "")
        if not audio_mode:
            audio_mode = AUDIO_MODE_MICROPHONE if self._config.get("recording_audio_enabled", False) else AUDIO_MODE_NONE
        audio_mode_idx = self._recording_audio_mode_combo.findData(audio_mode)
        if audio_mode_idx >= 0:
            self._recording_audio_mode_combo.setCurrentIndex(audio_mode_idx)

        audio_source = self._config.get("recording_microphone_source", "")
        if not audio_source:
            audio_source = self._config.get("recording_audio_source", "")
        audio_source_idx = self._recording_audio_source_combo.findText(audio_source)
        if audio_source_idx >= 0:
            self._recording_audio_source_combo.setCurrentIndex(audio_source_idx)
        else:
            self._recording_audio_source_combo.setCurrentText(audio_source)

        system_audio_device = self._config.get("recording_system_audio_device", SYSTEM_AUDIO_DEFAULT_DEVICE)
        system_audio_idx = self._recording_system_audio_combo.findData(system_audio_device)
        if system_audio_idx >= 0:
            self._recording_system_audio_combo.setCurrentIndex(system_audio_idx)
        self._refresh_audio_source_enabled()
        self._hotkey_region._value = self._config.get_hotkey("region_capture")
        self._hotkey_region._display.setText(self._config.get_hotkey("region_capture"))
        self._hotkey_fullscreen._value = self._config.get_hotkey("fullscreen_capture")
        self._hotkey_fullscreen._display.setText(self._config.get_hotkey("fullscreen_capture"))
        self._hotkey_record_pause._value = self._config.get_hotkey("recording_pause_resume")
        self._hotkey_record_pause._display.setText(self._config.get_hotkey("recording_pause_resume"))
        self._hotkey_record_stop._value = self._config.get_hotkey("recording_stop")
        self._hotkey_record_stop._display.setText(self._config.get_hotkey("recording_stop"))
        self._auto_start_cb.setChecked(self._config.get("start_with_windows", False))
        self._show_notif_cb.setChecked(self._config.get("show_tray_notifications", True))
        self._copy_on_save_cb.setChecked(self._config.get("copy_to_clipboard_on_save", True))
        self._magnifier_cb.setChecked(self._config.get("show_magnifier", True))

    def _browse_save_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Save Directory", self._save_path_edit.text()
        )
        if path:
            self._save_path_edit.setText(path)

    def _browse_recording_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Recording Directory", self._recording_path_edit.text()
        )
        if path:
            self._recording_path_edit.setText(path)

    def _save_and_close(self):
        """Save all settings and close the dialog."""
        self._config.set("save_path", self._save_path_edit.text())
        self._config.set("image_format", self._format_combo.currentText())
        self._config.set("filename_pattern", self._pattern_edit.text())
        self._config.set("recording_save_path", self._recording_path_edit.text())
        self._config.set("recording_format", self._recording_format_combo.currentText())
        self._config.set("recording_fps", int(self._recording_fps_combo.currentText()))
        self._config.set("show_recording_border", self._show_recording_border_cb.isChecked())
        self._config.set("recording_annotation_hold_key", self._recording_annotation_hold_combo.currentData() or "")
        audio_mode = self._recording_audio_mode_combo.currentData() or AUDIO_MODE_NONE
        microphone_source = self._recording_audio_source_combo.currentText().strip()
        system_audio_device = self._recording_system_audio_combo.currentData() or SYSTEM_AUDIO_DEFAULT_DEVICE
        self._config.set("recording_audio_mode", audio_mode)
        self._config.set("recording_audio_enabled", audio_mode != AUDIO_MODE_NONE)
        self._config.set("recording_audio_source", microphone_source if audio_mode == AUDIO_MODE_MICROPHONE else "")
        self._config.set("recording_microphone_source", microphone_source)
        self._config.set("recording_system_audio_device", system_audio_device)
        self._config.set_hotkey("region_capture", self._hotkey_region.value)
        self._config.set_hotkey("fullscreen_capture", self._hotkey_fullscreen.value)
        self._config.set_hotkey("recording_pause_resume", self._hotkey_record_pause.value)
        self._config.set_hotkey("recording_stop", self._hotkey_record_stop.value)
        self._config.set("start_with_windows", self._auto_start_cb.isChecked())
        self._config.set("show_tray_notifications", self._show_notif_cb.isChecked())
        self._config.set("copy_to_clipboard_on_save", self._copy_on_save_cb.isChecked())
        self._config.set("show_magnifier", self._magnifier_cb.isChecked())

        # Handle autostart registry
        self._set_autostart(self._auto_start_cb.isChecked())

        self.settings_changed.emit()
        self.accept()

    def _set_autostart(self, enabled: bool):
        """Add/remove the app from Windows startup via registry."""
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path,
                0, winreg.KEY_SET_VALUE,
            )
            if enabled:
                exe_path = sys.executable
                if getattr(sys, 'frozen', False):
                    exe_path = sys.executable
                else:
                    exe_path = f'"{sys.executable}" "{os.path.abspath("main.py")}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except OSError as e:
            print(f"Failed to set autostart: {e}")
