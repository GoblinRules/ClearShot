"""ClearShot — Settings dialog window."""

import os
import sys
import winreg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QFileDialog, QFormLayout, QGroupBox, QMessageBox,
    QKeySequenceEdit, QSpacerItem, QSizePolicy, QFrame,
)
from constants import APP_NAME, DEFAULT_HOTKEYS, IMAGE_FORMATS


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

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        tabs = QTabWidget()
        tabs.addTab(self._create_general_tab(), "General")
        tabs.addTab(self._create_hotkeys_tab(), "Hotkeys")
        tabs.addTab(self._create_startup_tab(), "Startup")
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

    def _load_values(self):
        """Load current config values into the UI."""
        self._save_path_edit.setText(self._config.get("save_path", ""))
        
        fmt = self._config.get("image_format", "PNG")
        idx = self._format_combo.findText(fmt)
        if idx >= 0:
            self._format_combo.setCurrentIndex(idx)
        
        self._pattern_edit.setText(self._config.get("filename_pattern", "ClearShot_{timestamp}"))
        self._hotkey_region._value = self._config.get_hotkey("region_capture")
        self._hotkey_region._display.setText(self._config.get_hotkey("region_capture"))
        self._hotkey_fullscreen._value = self._config.get_hotkey("fullscreen_capture")
        self._hotkey_fullscreen._display.setText(self._config.get_hotkey("fullscreen_capture"))
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

    def _save_and_close(self):
        """Save all settings and close the dialog."""
        self._config.set("save_path", self._save_path_edit.text())
        self._config.set("image_format", self._format_combo.currentText())
        self._config.set("filename_pattern", self._pattern_edit.text())
        self._config.set_hotkey("region_capture", self._hotkey_region.value)
        self._config.set_hotkey("fullscreen_capture", self._hotkey_fullscreen.value)
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
