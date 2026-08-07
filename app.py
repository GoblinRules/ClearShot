"""ClearShot — System tray application and hotkey manager."""

import ctypes
import ctypes.wintypes
import os
import sys
from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox,
)
from config import Config
from overlay import SelectionOverlay
from annotator import AnnotatorWindow
from icon_utils import ui_icon
from capture import capture_all_monitors, capture_region, get_monitor_list, ensure_dpi_awareness
from clipboard_utils import copy_pixmap_to_clipboard
from settings_window import SettingsWindow
from constants import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_RECORDING_ANNOTATION_HOLD_KEY,
    DEFAULT_SAVE_DIR,
    VIDEO_FORMATS,
)
from recording import (
    AUDIO_MODE_MICROPHONE,
    AUDIO_MODE_NONE,
    AUDIO_MODE_SYSTEM,
    RecordingBorderOverlay,
    RecordingAnnotationOverlay,
    RecordingAnnotationStore,
    RecordingSelectionOverlay,
    ScreenRecorder,
    SYSTEM_AUDIO_DEFAULT_DEVICE,
    list_audio_sources,
    make_recording_path,
    normalize_recording_rect,
)

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
_HOTKEY_RECORDING_PAUSE = 3
_HOTKEY_RECORDING_STOP = 4

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
    recording_pause_resume_triggered = pyqtSignal()
    recording_stop_triggered = pyqtSignal()

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
                elif hotkey_id == _HOTKEY_RECORDING_PAUSE:
                    self.recording_pause_resume_triggered.emit()
                elif hotkey_id == _HOTKEY_RECORDING_STOP:
                    self.recording_stop_triggered.emit()
            elif msg.message == WM_APP_REFRESH:
                self._unregister_all(user32)
                self._register_all(user32)
            elif msg.message == WM_APP_QUIT:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        self._unregister_all(user32)

    def _register_all(self, user32):
        """Register all hotkeys from current config."""
        registrations = [
            (_HOTKEY_REGION, "region_capture", "region capture"),
            (_HOTKEY_FULLSCREEN, "fullscreen_capture", "fullscreen capture"),
            (_HOTKEY_RECORDING_PAUSE, "recording_pause_resume", "recording pause/resume"),
            (_HOTKEY_RECORDING_STOP, "recording_stop", "recording stop"),
        ]
        for hotkey_id, action, label in registrations:
            key = self._config.get_hotkey(action)
            mods, vk = _parse_hotkey(key)
            if vk is None:
                continue
            if not user32.RegisterHotKey(None, hotkey_id, mods, vk):
                print(f"Failed to register {label} hotkey '{key}' "
                      f"(error {ctypes.GetLastError()})")
            else:
                print(f"Registered {label} hotkey: {key}")

    def _unregister_all(self, user32):
        """Unregister all hotkey IDs (safe to call even if not registered)."""
        user32.UnregisterHotKey(None, _HOTKEY_REGION)
        user32.UnregisterHotKey(None, _HOTKEY_FULLSCREEN)
        user32.UnregisterHotKey(None, _HOTKEY_RECORDING_PAUSE)
        user32.UnregisterHotKey(None, _HOTKEY_RECORDING_STOP)

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
        self._record_region_overlay: RecordingSelectionOverlay | None = None
        self._record_border_overlay: RecordingBorderOverlay | None = None
        self._record_annotation_overlay: RecordingAnnotationOverlay | None = None
        self._record_annotation_store: RecordingAnnotationStore | None = None
        self._recorder: ScreenRecorder | None = None
        self._recording_rect: QRect | None = None
        self._recording_finalizing = False
        self._recording_finalizing_message = ""
        self._recording_session_id = 0
        self._retired_recorders: list[ScreenRecorder] = []

        # Ensure DPI awareness
        ensure_dpi_awareness()

        # Create tray icon
        self._app_icon = self._create_app_icon()
        self._recording_icon = self._create_recording_tray_icon(paused=False)
        self._paused_recording_icon = self._create_recording_tray_icon(paused=True)
        self._finalizing_recording_icon = self._create_recording_tray_icon(finalizing=True)
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
        self._hotkey_thread.recording_pause_resume_triggered.connect(
            self._toggle_recording_pause
        )
        self._hotkey_thread.recording_stop_triggered.connect(self._stop_recording)
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
        """Create the application icon from bundled icon assets."""
        # Use _MEIPASS for PyInstaller bundled exe, otherwise use __file__ dir
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

        for candidate in [
            "assets/icon.ico",
            "assets/favicon.ico",
            "resources/icon.ico",
        ]:
            icon_path = os.path.join(base, candidate)
            if os.path.exists(icon_path):
                icon = QIcon(icon_path)
                if not icon.isNull():
                    return icon

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

    def _create_recording_tray_icon(self, paused: bool = False, finalizing: bool = False) -> QIcon:
        """Create a tray icon variant with a small recording state badge."""
        size = 64
        pixmap = self._app_icon.pixmap(size, size)
        if pixmap.isNull():
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if finalizing:
            badge_color = QColor("#0099ff")
        elif paused:
            badge_color = QColor("#ffb020")
        else:
            badge_color = QColor("#ff3b30")
        shadow = QColor(0, 0, 0, 180)
        badge = QRectF(size * 0.58, size * 0.58, size * 0.34, size * 0.34)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(badge.adjusted(2, 2, 2, 2))
        painter.setBrush(badge_color)
        painter.drawEllipse(badge)
        painter.setBrush(QColor("#ffffff"))
        if finalizing:
            dot_size = size * 0.045
            y = badge.center().y() - dot_size / 2
            for offset in (-0.08, 0, 0.08):
                dot = QRectF(0, 0, dot_size, dot_size)
                dot.moveCenter(QPointF(badge.center().x() + size * offset, y + dot_size / 2))
                painter.drawEllipse(dot)
        elif paused:
            bar_w = size * 0.045
            bar_h = size * 0.15
            y = badge.center().y() - bar_h / 2
            painter.drawRoundedRect(QRectF(badge.center().x() - bar_w * 1.8, y, bar_w, bar_h), 1, 1)
            painter.drawRoundedRect(QRectF(badge.center().x() + bar_w * 0.8, y, bar_w, bar_h), 1, 1)
        else:
            dot = QRectF(0, 0, size * 0.11, size * 0.11)
            dot.moveCenter(badge.center())
            painter.drawEllipse(dot)
        painter.end()
        return QIcon(pixmap)

    def _set_recording_indicator(self, recording: bool, paused: bool = False, finalizing: bool = False) -> None:
        if recording:
            if finalizing:
                self._tray.setIcon(self._finalizing_recording_icon)
                state = "Finalizing video"
            else:
                self._tray.setIcon(self._paused_recording_icon if paused else self._recording_icon)
                state = "Paused" if paused else "Recording"
            self._tray.setToolTip(f"{APP_NAME} v{APP_VERSION} - {state}")
        else:
            self._tray.setIcon(self._app_icon)
            self._tray.setToolTip(f"{APP_NAME} v{APP_VERSION}")

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
        region_action = QAction(ui_icon("capture_region"), "Capture Region", menu)
        region_action.setToolTip("Select a region to capture")
        region_action.triggered.connect(self._start_region_capture)
        menu.addAction(region_action)

        # Capture Fullscreen — submenu with per-monitor options
        fullscreen_menu = menu.addMenu(ui_icon("fullscreen"), "Capture Fullscreen")
        fullscreen_menu.setStyleSheet(menu.styleSheet())

        all_action = QAction(ui_icon("fullscreen"), "All Monitors", fullscreen_menu)
        all_action.triggered.connect(lambda: self._start_fullscreen_capture(-1))
        fullscreen_menu.addAction(all_action)

        monitors = get_monitor_list()
        for idx, mon_rect in enumerate(monitors):
            label = f"Monitor {idx + 1}  ({mon_rect.width()}×{mon_rect.height()})"
            mon_action = QAction(ui_icon("monitor"), label, fullscreen_menu)
            mon_action.triggered.connect(lambda checked, i=idx: self._start_fullscreen_capture(i))
            fullscreen_menu.addAction(mon_action)

        menu.addSeparator()

        record_menu = menu.addMenu(ui_icon("record"), "Screen Record")
        record_menu.setStyleSheet(menu.styleSheet())

        if self._is_recording():
            if self._recording_finalizing:
                finalizing_action = QAction(ui_icon("save"), "Finalizing Recording...", record_menu)
                finalizing_action.setEnabled(False)
                record_menu.addAction(finalizing_action)
            else:
                annotations_visible = bool(
                    self._record_annotation_overlay is not None
                    and self._record_annotation_overlay.isVisible()
                )
                annotation_label = "Hide Annotation Tools" if annotations_visible else "Show Annotation Tools"
                annotation_action = QAction(ui_icon("edit"), annotation_label, record_menu)
                annotation_action.triggered.connect(self._toggle_recording_annotations)
                record_menu.addAction(annotation_action)

                if self._record_annotation_overlay is not None:
                    clear_annotation_action = QAction(ui_icon("trash"), "Clear Recording Annotations", record_menu)
                    clear_annotation_action.triggered.connect(self._clear_recording_annotations)
                    record_menu.addAction(clear_annotation_action)

                record_menu.addSeparator()

                paused = bool(self._recorder and self._recorder.is_paused)
                pause_label = "Resume Recording" if paused else "Pause Recording"
                pause_icon = "play" if paused else "pause"
                pause_action = QAction(ui_icon(pause_icon), pause_label, record_menu)
                pause_action.triggered.connect(self._toggle_recording_pause)
                record_menu.addAction(pause_action)

                stop_action = QAction(ui_icon("stop"), "Stop Recording", record_menu)
                stop_action.triggered.connect(self._stop_recording)
                record_menu.addAction(stop_action)
        else:
            record_region_action = QAction(ui_icon("capture_region"), "Record Region", record_menu)
            record_region_action.triggered.connect(self._start_region_recording)
            record_menu.addAction(record_region_action)

            record_all_action = QAction(ui_icon("video"), "Record All Monitors", record_menu)
            record_all_action.triggered.connect(lambda: self._start_fullscreen_recording(-1))
            record_menu.addAction(record_all_action)

            record_monitor_menu = record_menu.addMenu(ui_icon("monitor"), "Record Monitor")
            record_monitor_menu.setStyleSheet(menu.styleSheet())
            for idx, mon_rect in enumerate(monitors):
                label = f"Monitor {idx + 1}  ({mon_rect.width()}Ã—{mon_rect.height()})"
                rec_mon_action = QAction(ui_icon("monitor"), label, record_monitor_menu)
                rec_mon_action.triggered.connect(lambda checked, i=idx: self._start_fullscreen_recording(i))
                record_monitor_menu.addAction(rec_mon_action)

        menu.addSeparator()

        # Open Save Folder
        folder_action = QAction(ui_icon("folder"), "Open Save Folder", menu)
        folder_action.triggered.connect(self._open_save_folder)
        menu.addAction(folder_action)

        menu.addSeparator()

        # Settings
        settings_action = QAction(ui_icon("settings"), "Settings", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        # Help / About
        help_about_action = QAction(ui_icon("help"), "Help / About", menu)
        help_about_action.triggered.connect(self._open_settings)
        menu.addAction(help_about_action)

        menu.addSeparator()

        # Exit
        exit_action = QAction(ui_icon("close"), "Exit", menu)
        exit_action.triggered.connect(self._quit)
        menu.addAction(exit_action)

        self._tray.setContextMenu(menu)

    def _is_recording(self) -> bool:
        return self._recorder is not None and (
            self._recorder.isRunning() or self._recording_finalizing
        )

    def _is_current_recorder(self, recorder: ScreenRecorder, session_id: int) -> bool:
        return recorder is self._recorder and session_id == self._recording_session_id

    def _retain_recorder_until_finished(self, recorder: ScreenRecorder) -> None:
        if recorder.isRunning() and recorder not in self._retired_recorders:
            self._retired_recorders.append(recorder)

    def _on_recorder_thread_finished(self, recorder: ScreenRecorder, session_id: int) -> None:
        try:
            self._retired_recorders.remove(recorder)
        except ValueError:
            pass
        if self._is_current_recorder(recorder, session_id):
            self._build_tray_menu()

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

    def _start_region_recording(self):
        """Ask the user for a recording region, then start recording it."""
        if self._is_recording():
            self._show_recording_busy_message()
            return

        if self._record_region_overlay is not None:
            try:
                self._record_region_overlay.close()
            except RuntimeError:
                pass

        self._record_region_overlay = RecordingSelectionOverlay()
        self._record_region_overlay.region_selected.connect(self._on_record_region_selected)
        self._record_region_overlay.cancelled.connect(self._on_record_region_cancelled)
        QTimer.singleShot(150, self._record_region_overlay.begin_selection)

    def _on_record_region_selected(self, rect: QRect):
        self._record_region_overlay = None
        QTimer.singleShot(250, lambda r=QRect(rect): self._start_recording_rect(r, "region"))

    def _on_record_region_cancelled(self):
        self._record_region_overlay = None

    def _start_fullscreen_recording(self, monitor_index: int = -1):
        """Start recording all monitors or one physical monitor."""
        if self._is_recording():
            self._show_recording_busy_message()
            return

        monitors = get_monitor_list()
        if monitor_index < 0:
            pixmap, monitor = capture_all_monitors()
            rect = QRect(monitor["left"], monitor["top"], pixmap.width(), pixmap.height())
            label = "all monitors"
        elif monitor_index < len(monitors):
            rect = QRect(monitors[monitor_index])
            label = f"monitor {monitor_index + 1}"
        else:
            pixmap, monitor = capture_all_monitors()
            rect = QRect(monitor["left"], monitor["top"], pixmap.width(), pixmap.height())
            label = "all monitors"

        QTimer.singleShot(250, lambda r=QRect(rect), name=label: self._start_recording_rect(r, name))

    def _start_recording_rect(self, rect: QRect, label: str):
        """Start a background recording for the given screen rectangle."""
        if self._is_recording():
            self._show_recording_busy_message()
            return

        save_path = self._config.get(
            "recording_save_path",
            os.path.join(DEFAULT_SAVE_DIR, "Recordings"),
        )
        pattern = self._config.get("filename_pattern", "ClearShot_{timestamp}")
        recording_format = self._config.get("recording_format", "MP4")
        extension = VIDEO_FORMATS.get(recording_format, VIDEO_FORMATS["MP4"])
        output_path = make_recording_path(save_path, f"{pattern}_Recording", extension)
        fps = int(self._config.get("recording_fps", 15))
        audio_mode = self._get_recording_audio_mode()
        microphone_source = ""
        system_audio_device = SYSTEM_AUDIO_DEFAULT_DEVICE
        if audio_mode == AUDIO_MODE_MICROPHONE:
            microphone_source = str(self._config.get("recording_microphone_source", "")).strip()
            if not microphone_source:
                microphone_source = str(self._config.get("recording_audio_source", "")).strip()
            if not microphone_source:
                available_microphones = list_audio_sources()
                if available_microphones:
                    microphone_source = available_microphones[0]
                    self._config.set("recording_microphone_source", microphone_source)
                    self._config.set("recording_audio_source", microphone_source)
            if not microphone_source:
                QMessageBox.warning(
                    None,
                    "Recording Microphone Required",
                    "Choose a microphone input in Settings before recording with microphone audio.",
                )
                return
        elif audio_mode == AUDIO_MODE_SYSTEM:
            system_audio_device = str(
                self._config.get("recording_system_audio_device", SYSTEM_AUDIO_DEFAULT_DEVICE)
            ).strip() or SYSTEM_AUDIO_DEFAULT_DEVICE

        self._recording_rect = normalize_recording_rect(rect)
        self._recording_finalizing = False
        self._recording_finalizing_message = ""
        self._record_annotation_store = RecordingAnnotationStore()
        self._recording_session_id += 1
        session_id = self._recording_session_id
        recorder = ScreenRecorder(
            self._recording_rect,
            output_path,
            fps,
            audio_mode=audio_mode,
            microphone_source=microphone_source,
            system_audio_device=system_audio_device,
            annotation_store=self._record_annotation_store,
        )
        self._recorder = recorder
        recorder.recording_started.connect(
            lambda path, target=label, rec=recorder, sid=session_id: self._on_recording_started(rec, sid, path, target)
        )
        recorder.recording_finalizing.connect(
            lambda message, rec=recorder, sid=session_id: self._on_recording_finalizing(rec, sid, message)
        )
        recorder.recording_finished.connect(
            lambda path, duration, frames, rec=recorder, sid=session_id: self._on_recording_finished(rec, sid, path, duration, frames)
        )
        recorder.recording_failed.connect(
            lambda message, rec=recorder, sid=session_id: self._on_recording_failed(rec, sid, message)
        )
        recorder.recording_paused.connect(
            lambda rec=recorder, sid=session_id: self._on_recording_paused(rec, sid)
        )
        recorder.recording_resumed.connect(
            lambda rec=recorder, sid=session_id: self._on_recording_resumed(rec, sid)
        )
        recorder.finished.connect(
            lambda rec=recorder, sid=session_id: self._on_recorder_thread_finished(rec, sid)
        )
        recorder.start()
        self._build_tray_menu()

    def _get_recording_audio_mode(self) -> str:
        mode = str(self._config.get("recording_audio_mode", "")).strip()
        if mode in {AUDIO_MODE_NONE, AUDIO_MODE_MICROPHONE, AUDIO_MODE_SYSTEM}:
            return mode
        if self._config.get("recording_audio_enabled", False):
            return AUDIO_MODE_MICROPHONE
        return AUDIO_MODE_NONE

    def _stop_recording(self):
        if self._recorder is not None and self._recorder.isRunning():
            if self._recording_finalizing:
                self._tray.showMessage(
                    APP_NAME,
                    self._recording_finalizing_message or "Recording is still finalizing. Longer recordings can take a moment to save.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000,
                )
                return
            self._recorder.stop()
            if not self._recording_finalizing:
                self._on_recording_finalizing(
                    self._recorder,
                    self._recording_session_id,
                    "Stopping and finalizing video...",
                )

    def _toggle_recording_pause(self):
        if self._recorder is None or not self._recorder.isRunning():
            return
        if self._recording_finalizing:
            return
        self._recorder.toggle_pause()

    def _on_recording_started(self, recorder: ScreenRecorder, session_id: int, path: str, target: str):
        if not self._is_current_recorder(recorder, session_id):
            return
        if recorder.is_stopping:
            self._on_recording_finalizing(
                recorder,
                session_id,
                self._recording_finalizing_message or "Stopping and finalizing video...",
            )
            return
        self._recording_finalizing = False
        self._recording_finalizing_message = ""
        self._set_recording_indicator(True, False)
        if self._recording_rect is not None:
            if self._config.get("show_recording_border", True):
                self._show_recording_border(self._recording_rect)
            self._show_recording_annotations(self._recording_rect, activate=False)
        self._build_tray_menu()
        self._tray.showMessage(
            APP_NAME,
            f"Recording {target}. Use the floating controls, tray menu, or hotkeys to pause or stop.",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def _on_recording_finalizing(self, recorder: ScreenRecorder, session_id: int, message: str):
        if not self._is_current_recorder(recorder, session_id):
            return
        first_update = not self._recording_finalizing
        self._recording_finalizing = True
        self._recording_finalizing_message = message or "Stopping and finalizing video..."
        self._set_recording_indicator(True, finalizing=True)
        if self._record_border_overlay is not None:
            self._record_border_overlay.set_finalizing(True)
        if self._record_annotation_overlay is not None:
            self._record_annotation_overlay.set_finalizing(True, self._recording_finalizing_message)
        self._build_tray_menu()
        if first_update:
            self._tray.showMessage(
                APP_NAME,
                "Stopping and finalizing video. Longer recordings can take a moment to save.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def _on_recording_finished(
        self,
        recorder: ScreenRecorder,
        session_id: int,
        path: str,
        duration: float,
        frames: int,
    ):
        self._retain_recorder_until_finished(recorder)
        if not self._is_current_recorder(recorder, session_id):
            return
        self._recorder = None
        self._recording_rect = None
        self._recording_finalizing = False
        self._recording_finalizing_message = ""
        self._hide_recording_annotations()
        self._record_annotation_store = None
        self._hide_recording_border()
        self._set_recording_indicator(False)
        self._build_tray_menu()
        self._tray.showMessage(
            APP_NAME,
            f"Recording saved: {os.path.basename(path)}",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def _on_recording_failed(self, recorder: ScreenRecorder, session_id: int, message: str):
        self._retain_recorder_until_finished(recorder)
        if not self._is_current_recorder(recorder, session_id):
            return
        self._recorder = None
        self._recording_rect = None
        self._recording_finalizing = False
        self._recording_finalizing_message = ""
        self._hide_recording_annotations()
        self._record_annotation_store = None
        self._hide_recording_border()
        self._set_recording_indicator(False)
        self._build_tray_menu()
        QMessageBox.warning(
            None,
            "Recording Failed",
            f"ClearShot could not record the screen.\n\n{message}",
        )

    def _on_recording_paused(self, recorder: ScreenRecorder, session_id: int):
        if not self._is_current_recorder(recorder, session_id):
            return
        if self._recording_finalizing:
            return
        self._set_recording_indicator(True, True)
        if self._record_border_overlay is not None:
            self._record_border_overlay.set_paused(True)
        if self._record_annotation_overlay is not None:
            self._record_annotation_overlay.set_paused(True)
        self._build_tray_menu()

    def _on_recording_resumed(self, recorder: ScreenRecorder, session_id: int):
        if not self._is_current_recorder(recorder, session_id):
            return
        if self._recording_finalizing:
            return
        self._set_recording_indicator(True, False)
        if self._record_border_overlay is not None:
            self._record_border_overlay.set_paused(False)
        if self._record_annotation_overlay is not None:
            self._record_annotation_overlay.set_paused(False)
        self._build_tray_menu()

    def _show_recording_border(self, rect: QRect) -> None:
        self._hide_recording_border()
        self._record_border_overlay = RecordingBorderOverlay(rect)
        self._record_border_overlay.show()
        self._record_border_overlay.raise_()

    def _hide_recording_border(self) -> None:
        if self._record_border_overlay is not None:
            try:
                self._record_border_overlay.close()
            except RuntimeError:
                pass
            self._record_border_overlay = None

    def _toggle_recording_annotations(self) -> None:
        if not self._is_recording() or self._recording_rect is None:
            return
        if self._record_annotation_overlay is not None and self._record_annotation_overlay.isVisible():
            self._record_annotation_overlay.hide()
        else:
            self._show_recording_annotations(self._recording_rect)
        self._build_tray_menu()

    def _show_recording_annotations(self, rect: QRect, activate: bool = True) -> None:
        if self._record_annotation_store is None:
            self._record_annotation_store = RecordingAnnotationStore()
        hold_key = self._recording_annotation_hold_key()
        if self._record_annotation_overlay is None:
            self._record_annotation_overlay = RecordingAnnotationOverlay(
                rect,
                self._record_annotation_store,
                hold_key=hold_key,
            )
            self._record_annotation_overlay.pause_requested.connect(self._toggle_recording_pause)
            self._record_annotation_overlay.stop_requested.connect(self._stop_recording)
        else:
            self._record_annotation_overlay.set_hold_key(hold_key)
        self._record_annotation_overlay.set_paused(bool(self._recorder and self._recorder.is_paused))
        self._record_annotation_overlay.set_finalizing(
            self._recording_finalizing,
            self._recording_finalizing_message,
        )
        self._record_annotation_overlay.show()
        self._record_annotation_overlay.raise_()
        if activate:
            self._record_annotation_overlay.activateWindow()

    def _recording_annotation_hold_key(self) -> str:
        return str(
            self._config.get(
                "recording_annotation_hold_key",
                DEFAULT_RECORDING_ANNOTATION_HOLD_KEY,
            )
            or ""
        ).strip()

    def _hide_recording_annotations(self) -> None:
        if self._record_annotation_overlay is not None:
            try:
                self._record_annotation_overlay.close()
            except RuntimeError:
                pass
            self._record_annotation_overlay = None

    def _clear_recording_annotations(self) -> None:
        if self._record_annotation_store is not None:
            self._record_annotation_store.clear()
        if self._record_annotation_overlay is not None:
            self._record_annotation_overlay.clear_all()

    def _show_recording_busy_message(self):
        if self._recording_finalizing:
            message = "Recording is finalizing. Longer recordings can take a moment to save."
        else:
            message = "A screen recording is already running."
        self._tray.showMessage(
            APP_NAME,
            message,
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

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
        if self._record_annotation_overlay is not None:
            self._record_annotation_overlay.set_hold_key(self._recording_annotation_hold_key())



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
        if self._record_region_overlay:
            try:
                self._record_region_overlay.close()
            except RuntimeError:
                pass
        if self._record_annotation_overlay:
            self._hide_recording_annotations()
        self._record_annotation_store = None
        if self._record_border_overlay:
            self._hide_recording_border()
        active_recorders = [rec for rec in [self._recorder, *self._retired_recorders] if rec is not None]
        for recorder in active_recorders:
            try:
                recorder.stop()
                recorder.wait(5000)
            except RuntimeError:
                pass
        self._retired_recorders.clear()
        self._recorder = None
        self._set_recording_indicator(False)

        QApplication.quit()
