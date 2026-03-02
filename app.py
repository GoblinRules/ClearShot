"""ClearShot — System tray application and hotkey manager."""

import ctypes
import ctypes.wintypes
import os
import sys
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox,
)
from config import Config
from overlay import SelectionOverlay
from annotator import AnnotatorWindow
from capture import capture_all_monitors, capture_region, get_monitor_list, ensure_dpi_awareness
from clipboard_utils import copy_pixmap_to_clipboard
from settings_window import SettingsWindow
from constants import APP_NAME, APP_VERSION

# ── Win32 constants for RegisterHotKey ────────────────────────────────
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_APP_REFRESH = 0x8001  # custom message to trigger re-registration
WM_APP_QUIT = 0x8002     # custom message to exit the message loop

# Hotkey IDs
_HOTKEY_REGION = 1
_HOTKEY_FULLSCREEN = 2

# Virtual-key code map (lowercase name → VK code)
_VK_MAP = {
    "print screen": 0x2C,  # VK_SNAPSHOT
    "snapshot": 0x2C,
    "prtsc": 0x2C,
    "escape": 0x1B, "esc": 0x1B,
    "space": 0x20,
    "enter": 0x0D, "return": 0x0D,
    "tab": 0x09,
    "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23,
    "pageup": 0x21, "page up": 0x21,
    "pagedown": 0x22, "page down": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "numlock": 0x90, "scrolllock": 0x91, "capslock": 0x14,
    "pause": 0x13,
}
# F1–F24
for _i in range(1, 25):
    _VK_MAP[f"f{_i}"] = 0x70 + (_i - 1)
# 0–9
for _i in range(10):
    _VK_MAP[str(_i)] = 0x30 + _i
# A–Z
for _c in range(26):
    _VK_MAP[chr(ord("a") + _c)] = 0x41 + _c

_MODIFIER_MAP = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "meta": MOD_WIN,
}


def _parse_hotkey(combo: str):
    """Parse a hotkey string like 'ctrl+shift+f5' into (modifiers, vk_code).

    Returns (None, None) if the combo cannot be parsed.
    """
    if not combo:
        return None, None
    parts = [p.strip().lower() for p in combo.split("+")]
    modifiers = MOD_NOREPEAT  # always set to avoid auto-repeat spam
    vk = None
    for part in parts:
        if part in _MODIFIER_MAP:
            modifiers |= _MODIFIER_MAP[part]
        elif part in _VK_MAP:
            vk = _VK_MAP[part]
        else:
            # Unknown key name
            print(f"Warning: unknown key '{part}' in hotkey '{combo}'")
            return None, None
    if vk is None:
        return None, None
    return modifiers, vk


class HotkeyThread(QThread):
    """Listens for global hotkeys using the Win32 RegisterHotKey API.

    This is the OS-native approach: registered hotkeys are consumed by Windows
    and never forwarded to the focused application, and modifier key-up events
    are not affected (no stuck keys).
    """

    region_capture_triggered = pyqtSignal()
    fullscreen_capture_triggered = pyqtSignal()

    def __init__(self, config: Config):
        super().__init__()
        self._config = config
        self._thread_id = None  # set once the thread starts

    def run(self):
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._register_all(user32)

        # Pump messages until told to stop
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                hotkey_id = msg.wParam
                if hotkey_id == _HOTKEY_REGION:
                    self.region_capture_triggered.emit()
                elif hotkey_id == _HOTKEY_FULLSCREEN:
                    self.fullscreen_capture_triggered.emit()
            elif msg.message == WM_APP_REFRESH:
                self._unregister_all(user32)
                self._register_all(user32)
            elif msg.message == WM_APP_QUIT:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._unregister_all(user32)

    def _register_all(self, user32):
        """Register both hotkeys from current config."""
        region_key = self._config.get_hotkey("region_capture")
        mods, vk = _parse_hotkey(region_key)
        if vk is not None:
            if not user32.RegisterHotKey(None, _HOTKEY_REGION, mods, vk):
                print(f"Failed to register region hotkey '{region_key}' "
                      f"(error {ctypes.GetLastError()})")
            else:
                print(f"Registered region hotkey: {region_key}")

        fullscreen_key = self._config.get_hotkey("fullscreen_capture")
        mods, vk = _parse_hotkey(fullscreen_key)
        if vk is not None:
            if not user32.RegisterHotKey(None, _HOTKEY_FULLSCREEN, mods, vk):
                print(f"Failed to register fullscreen hotkey '{fullscreen_key}' "
                      f"(error {ctypes.GetLastError()})")
            else:
                print(f"Registered fullscreen hotkey: {fullscreen_key}")

    def _unregister_all(self, user32):
        """Unregister both hotkey IDs (safe to call even if not registered)."""
        user32.UnregisterHotKey(None, _HOTKEY_REGION)
        user32.UnregisterHotKey(None, _HOTKEY_FULLSCREEN)

    def refresh_hotkeys(self):
        """Re-register hotkeys after settings change.

        Posts a message to the thread's message loop so registration
        happens on the correct thread (required by Win32).
        """
        if self._thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(
                self._thread_id, WM_APP_REFRESH, 0, 0,
            )

    def stop(self):
        """Signal the thread to exit."""
        if self._thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(
                self._thread_id, WM_APP_QUIT, 0, 0,
            )
        self.wait(3000)


class ClearShotApp:
    """Main application class managing the system tray and capture flow."""

    def __init__(self):
        self._config = Config()
        self._overlay: SelectionOverlay | None = None
        self._annotator: AnnotatorWindow | None = None
        self._settings_window: SettingsWindow | None = None

        # Ensure DPI awareness
        ensure_dpi_awareness()

        # Create tray icon
        self._app_icon = self._create_app_icon()
        self._tray = QSystemTrayIcon()
        self._tray.setIcon(self._app_icon)
        self._tray.setToolTip(f"{APP_NAME} v{APP_VERSION}")
        self._tray.activated.connect(self._on_tray_activated)

        # Set app-wide icon so all windows (Settings, About, etc.) get it
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().setWindowIcon(self._app_icon)

        # Build tray menu
        self._build_tray_menu()

        # Show tray
        self._tray.show()

        # Start hotkey listener
        self._hotkey_thread = HotkeyThread(self._config)
        self._hotkey_thread.region_capture_triggered.connect(
            self._start_region_capture
        )
        self._hotkey_thread.fullscreen_capture_triggered.connect(
            self._start_fullscreen_capture
        )
        self._hotkey_thread.start()

        # Show startup notification
        if self._config.get("show_tray_notifications", True):
            self._tray.showMessage(
                APP_NAME,
                f"{APP_NAME} is running. Use Print Screen to capture.",
                QSystemTrayIcon.MessageIcon.Information,
                2000,
            )

    def _create_app_icon(self) -> QIcon:
        """Create the application icon using pre-rendered PNGs from the icon pack."""
        # Use _MEIPASS for PyInstaller bundled exe, otherwise use __file__ dir
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        icon = QIcon()

        # Try loading pre-rendered PNGs at exact sizes (pixel-perfect, no scaling needed)
        icon_pack = os.path.join(base, "assets", "ClearShot_Icon_Pack")
        if os.path.isdir(icon_pack):
            # Skip 16px — Qt picks the smallest available for the tray,
            # so starting at 24px forces it to use a crisper icon
            for sz in [24, 32, 48, 64, 128, 256]:
                png_path = os.path.join(icon_pack, f"ClearShot_icon_{sz}x{sz}.png")
                if os.path.exists(png_path):
                    pm = QPixmap(png_path)
                    if not pm.isNull():
                        icon.addPixmap(pm)
            if not icon.isNull():
                return icon

        # Fallback: scale from a single large PNG
        for candidate in [
            "assets/icon.png", "assets/icon2.png", "resources/icon.png",
        ]:
            icon_path = os.path.join(base, candidate)
            if os.path.exists(icon_path):
                source = QPixmap(icon_path)
                if source.isNull():
                    continue
                for sz in [32, 48, 64, 128, 256]:
                    scaled = source.scaled(
                        sz, sz,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    icon.addPixmap(scaled)
                return icon

        # Last resort: generate a simple crosshair icon
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 120, 212))
        painter.drawEllipse(2, 2, size - 4, size - 4)

        from PyQt6.QtGui import QPen
        pen = QPen(QColor(255, 255, 255), 3)
        painter.setPen(pen)
        cx, cy = size // 2, size // 2
        r = 14
        painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        painter.drawLine(cx, cy - r - 6, cx, cy + r + 6)
        painter.drawLine(cx - r - 6, cy, cx + r + 6, cy)

        painter.end()
        return QIcon(pixmap)

    def _build_tray_menu(self):
        """Build the system tray context menu."""
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: #2b2b2b;
                color: #ddd;
                border: 1px solid #444;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #0078D4;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background: #444;
                margin: 4px 8px;
            }
        """)

        # Capture Region
        region_action = QAction("📷 Capture Region", menu)
        region_action.setToolTip("Select a region to capture")
        region_action.triggered.connect(self._start_region_capture)
        menu.addAction(region_action)

        # Capture Fullscreen — submenu with per-monitor options
        fullscreen_menu = QMenu("🖥️ Capture Fullscreen", menu)
        fullscreen_menu.setStyleSheet(menu.styleSheet())

        all_action = QAction("All Monitors", fullscreen_menu)
        all_action.triggered.connect(lambda: self._start_fullscreen_capture(-1))
        fullscreen_menu.addAction(all_action)

        monitors = get_monitor_list()
        for idx, mon_rect in enumerate(monitors):
            label = f"Monitor {idx + 1}  ({mon_rect.width()}×{mon_rect.height()})"
            mon_action = QAction(label, fullscreen_menu)
            mon_action.triggered.connect(lambda checked, i=idx: self._start_fullscreen_capture(i))
            fullscreen_menu.addAction(mon_action)

        menu.addMenu(fullscreen_menu)

        menu.addSeparator()

        # Open Save Folder
        folder_action = QAction("📁 Open Save Folder", menu)
        folder_action.triggered.connect(self._open_save_folder)
        menu.addAction(folder_action)

        menu.addSeparator()

        # Settings
        settings_action = QAction("⚙️ Settings", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        # Help / About
        help_about_action = QAction("❓ Help / About", menu)
        help_about_action.triggered.connect(self._open_settings)
        menu.addAction(help_about_action)

        menu.addSeparator()

        # Exit
        exit_action = QAction("❌ Exit", menu)
        exit_action.triggered.connect(self._quit)
        menu.addAction(exit_action)

        self._tray.setContextMenu(menu)

    def _on_tray_activated(self, reason):
        """Handle tray icon click."""
        try:
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
                self._start_region_capture()
        except (TypeError, ValueError):
            pass

    def _start_region_capture(self):
        """Start the region selection workflow."""
        # Ensure no other overlay is active
        if self._overlay is not None:
            try:
                self._overlay.close()
            except RuntimeError:
                pass

        self._overlay = SelectionOverlay()
        self._overlay._config = self._config
        self._overlay._tray_icon = self._tray
        self._overlay.region_selected.connect(self._on_region_selected)
        self._overlay.open_annotator.connect(self._open_annotator)
        self._overlay.cancelled.connect(self._on_capture_cancelled)

        # Small delay to allow tray menu to close
        QTimer.singleShot(150, self._overlay.begin_capture)

    def _start_fullscreen_capture(self, monitor_index: int = -1):
        """Capture fullscreen and open annotator.
        
        Args:
            monitor_index: -1 for all monitors, 0+ for a specific monitor.
        """
        if monitor_index < 0:
            pixmap, _ = capture_all_monitors()
        else:
            monitors = get_monitor_list()
            if monitor_index < len(monitors):
                r = monitors[monitor_index]
                pixmap = capture_region(r.x(), r.y(), r.width(), r.height())
            else:
                pixmap, _ = capture_all_monitors()
        self._open_annotator(pixmap)

    def _on_region_selected(self, pixmap: QPixmap):
        """Handle a selected region from the overlay."""
        self._open_annotator(pixmap)

    def _on_capture_cancelled(self):
        """Handle selection cancellation."""
        pass

    def _open_annotator(self, pixmap: QPixmap):
        """Open the annotation editor with the given pixmap."""
        if self._annotator is not None:
            try:
                self._annotator.close()
            except RuntimeError:
                pass

        self._annotator = AnnotatorWindow(pixmap, self._config)
        self._annotator.closed.connect(self._on_annotator_closed)
        self._annotator.show()

    def _on_annotator_closed(self):
        """Clean up when annotator is closed."""
        self._annotator = None

    def _open_save_folder(self):
        """Open the configured save folder in Windows Explorer."""
        save_path = self._config.get("save_path", "")
        if save_path and os.path.isdir(save_path):
            os.startfile(save_path)
        else:
            # Create it if it doesn't exist
            os.makedirs(save_path, exist_ok=True)
            os.startfile(save_path)

    def _open_settings(self):
        """Open the settings dialog."""
        if self._settings_window is not None:
            try:
                self._settings_window.raise_()
                self._settings_window.activateWindow()
                return
            except RuntimeError:
                pass

        self._settings_window = SettingsWindow(self._config)
        self._settings_window.settings_changed.connect(self._on_settings_changed)
        self._settings_window.finished.connect(lambda: setattr(self, '_settings_window', None))
        self._settings_window.show()

    def _on_settings_changed(self):
        """Re-register hotkeys when settings change."""
        self._hotkey_thread.refresh_hotkeys()



    def _quit(self):
        """Clean up and exit."""
        self._hotkey_thread.stop()
        self._tray.hide()

        if self._overlay:
            try:
                self._overlay.close()
            except RuntimeError:
                pass
        if self._annotator:
            try:
                self._annotator.close()
            except RuntimeError:
                pass
        if self._settings_window:
            try:
                self._settings_window.close()
            except RuntimeError:
                pass

        QApplication.quit()
