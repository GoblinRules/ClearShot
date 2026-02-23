"""ClearShot — System tray application and hotkey manager."""

import os
import sys
import json
import threading
import urllib.request
import urllib.error
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox, QDialog, QVBoxLayout,
    QLabel, QPushButton, QScrollArea, QWidget, QHBoxLayout,
)
from config import Config
from overlay import SelectionOverlay
from annotator import AnnotatorWindow
from capture import capture_all_monitors, capture_region, get_monitor_list, ensure_dpi_awareness
from clipboard_utils import copy_pixmap_to_clipboard
from settings_window import SettingsWindow
from constants import APP_NAME, APP_VERSION

GITHUB_REPO = "GoblinRules/ClearShot"


class HotkeyThread(QThread):
    """Listens for global hotkeys in a background thread."""
    
    region_capture_triggered = pyqtSignal()
    fullscreen_capture_triggered = pyqtSignal()

    def __init__(self, config: Config):
        super().__init__()
        self._config = config
        self._running = True
        self._hooks = []

    def run(self):
        try:
            import keyboard
            self._register_hotkeys(keyboard)
            # Keep thread alive
            while self._running:
                self.msleep(100)
        except ImportError:
            print("Warning: 'keyboard' module not available. Global hotkeys disabled.")
        except Exception as e:
            print(f"Hotkey thread error: {e}")

    def _register_hotkeys(self, keyboard_module):
        """Register global hotkeys based on current config."""
        self._unregister_all(keyboard_module)

        region_key = self._config.get_hotkey("region_capture")
        if region_key:
            try:
                keyboard_module.add_hotkey(
                    region_key,
                    lambda: self.region_capture_triggered.emit(),
                    suppress=True,
                )
                self._hooks.append(region_key)
            except Exception as e:
                print(f"Failed to register region hotkey '{region_key}': {e}")

        fullscreen_key = self._config.get_hotkey("fullscreen_capture")
        if fullscreen_key:
            try:
                keyboard_module.add_hotkey(
                    fullscreen_key,
                    lambda: self.fullscreen_capture_triggered.emit(),
                    suppress=True,
                )
                self._hooks.append(fullscreen_key)
            except Exception as e:
                print(f"Failed to register fullscreen hotkey '{fullscreen_key}': {e}")

    def _unregister_all(self, keyboard_module):
        """Remove all registered hotkeys."""
        for hook in self._hooks:
            try:
                keyboard_module.remove_hotkey(hook)
            except Exception:
                pass
        self._hooks.clear()

    def refresh_hotkeys(self):
        """Re-register hotkeys after settings change."""
        try:
            import keyboard
            self._register_hotkeys(keyboard)
        except ImportError:
            pass

    def stop(self):
        self._running = False
        try:
            import keyboard
            self._unregister_all(keyboard)
        except ImportError:
            pass
        self.wait(2000)


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
        """Create the application icon from PNG."""
        base = os.path.dirname(__file__)

        # Try loading PNG icon (better quality than .ico at small sizes)
        for candidate in [
            "assets/icon.png", "assets/icon2.png", "resources/icon.png",
        ]:
            icon_path = os.path.join(base, candidate)
            if os.path.exists(icon_path):
                source = QPixmap(icon_path)
                if source.isNull():
                    continue
                icon = QIcon()
                # Skip 16px — Qt picks the smallest available for the tray,
                # so starting at 32px forces it to scale from a crisper source
                for sz in [32, 48, 64, 128, 256]:
                    scaled = source.scaled(
                        sz, sz,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    icon.addPixmap(scaled)
                return icon

        # Fallback: generate a simple crosshair icon
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background circle
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 120, 212))
        painter.drawEllipse(2, 2, size - 4, size - 4)

        # Crosshair
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

        # Help
        help_action = QAction("❓ Help", menu)
        help_action.triggered.connect(self._show_help)
        menu.addAction(help_action)

        # Check for Updates
        update_action = QAction("🔄 Check for Updates", menu)
        update_action.triggered.connect(self._check_for_updates)
        menu.addAction(update_action)

        # About
        about_action = QAction(f"ℹ️ About {APP_NAME}", menu)
        about_action.triggered.connect(self._show_about)
        menu.addAction(about_action)

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

    def _show_help(self):
        """Show Help dialog with usage instructions."""
        dialog = QDialog()
        dialog.setWindowTitle(f"{APP_NAME} — Help")
        dialog.setMinimumSize(520, 520)
        dialog.setStyleSheet("""
            QDialog { background: #1e1e1e; color: #ddd; }
            QLabel { color: #ddd; }
            QScrollArea { border: none; }
            QPushButton {
                background: #0078D4; color: white; font-weight: bold;
                border: none; border-radius: 6px; padding: 8px 24px;
            }
            QPushButton:hover { background: #1a8ae8; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 12)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 20)
        content_layout.setSpacing(0)

        help_html = f"""
        <h2 style="color: #0099FF; margin-bottom: 4px;">📖 How to Use {APP_NAME}</h2>
        <hr style="border: 1px solid #333;">

        <h3 style="color: #0099FF;">🎯 Taking Screenshots</h3>
        <table cellpadding="6" style="margin-left: 8px;">
          <tr><td style="color: #ccc;"><b>Region Capture</b></td>
              <td><code style="background: #333; padding: 2px 8px; border-radius: 3px;">Print Screen</code></td></tr>
          <tr><td style="color: #ccc;"><b>Fullscreen Capture</b></td>
              <td><code style="background: #333; padding: 2px 8px; border-radius: 3px;">Ctrl + Print Screen</code></td></tr>
        </table>
        <p style="color: #aaa; margin-left: 8px;">You can also right-click the tray icon to capture.</p>

        <h3 style="color: #0099FF;">📷 Region Capture</h3>
        <ol style="color: #ccc; margin-left: 8px;">
          <li>Press <b>Print Screen</b> (or your custom hotkey)</li>
          <li>Click and drag to select an area</li>
          <li>Release to see options:<br>
            &nbsp;&nbsp;📋 <b>Copy</b> — Copy to clipboard<br>
            &nbsp;&nbsp;💾 <b>Save</b> — Save with file dialog<br>
            &nbsp;&nbsp;⚡ <b>Quick Save</b> — Save to your default folder<br>
            &nbsp;&nbsp;✏️ <b>Edit</b> — Open annotation editor<br>
            &nbsp;&nbsp;✕ <b>Cancel</b> — Discard</li>
        </ol>

        <h3 style="color: #0099FF;">✏️ Annotation Tools</h3>
        <table cellpadding="4" style="margin-left: 8px;">
          <tr><td style="color: #ccc;">✏️ <b>Pen</b></td><td style="color: #aaa;">Freehand drawing</td></tr>
          <tr><td style="color: #ccc;">─ <b>Line</b></td><td style="color: #aaa;">Straight lines</td></tr>
          <tr><td style="color: #ccc;">→ <b>Arrow</b></td><td style="color: #aaa;">Arrows with heads</td></tr>
          <tr><td style="color: #ccc;">□ <b>Rectangle</b></td><td style="color: #aaa;">Outlined rectangles</td></tr>
          <tr><td style="color: #ccc;">■ <b>Filled Rect</b></td><td style="color: #aaa;">Solid rectangles</td></tr>
          <tr><td style="color: #ccc;">○ <b>Ellipse</b></td><td style="color: #aaa;">Circles and ovals</td></tr>
          <tr><td style="color: #ccc;">T <b>Text</b></td><td style="color: #aaa;">Click to type text</td></tr>
          <tr><td style="color: #ccc;">▪ <b>Blur</b></td><td style="color: #aaa;">Blur sensitive areas</td></tr>
          <tr><td style="color: #ccc;"># <b>Counter</b></td><td style="color: #aaa;">Numbered markers (1, 2, 3…)</td></tr>
        </table>
        <p style="color: #aaa; margin-left: 8px;">Use the color palette and size slider to customize. Undo/Redo are available in the toolbar.</p>

        <h3 style="color: #0099FF;">⚙️ Settings</h3>
        <ul style="color: #ccc; margin-left: 8px;">
          <li><b>General</b> — Save location, image format (PNG/JPEG/BMP), filename pattern</li>
          <li><b>Hotkeys</b> — Customize keyboard shortcuts</li>
          <li><b>Startup</b> — Launch {APP_NAME} when Windows starts</li>
        </ul>

        <h3 style="color: #0099FF;">💡 Tips</h3>
        <ul style="color: #ccc; margin-left: 8px;">
          <li>Double-click the tray icon to start a region capture</li>
          <li>Use <code style="background: #333; padding: 1px 6px; border-radius: 3px;">Esc</code> to cancel a capture</li>
          <li>Quick Save uses the filename pattern from Settings</li>
          <li>Captured images are saved to <b>Pictures/ClearShot</b> by default</li>
        </ul>
        """

        label = QLabel(help_html)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        content_layout.addWidget(label)
        scroll.setWidget(content)
        layout.addWidget(scroll)

        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Got it!")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        dialog.exec()

    def _check_for_updates(self):
        """Check GitHub releases for a newer version."""
        def _do_check():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                req = urllib.request.Request(url, headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": APP_NAME,
                })
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                latest_tag = data.get("tag_name", "").lstrip("vV")
                html_url = data.get("html_url", "")
                QTimer.singleShot(0, lambda: _show_result(latest_tag, html_url))
            except Exception as e:
                QTimer.singleShot(0, lambda: _show_error(str(e)))

        def _show_result(latest: str, url: str):
            current = APP_VERSION.lstrip("vV")
            if not latest:
                _show_error("Could not determine the latest version.")
                return
            if _version_tuple(latest) > _version_tuple(current):
                reply = QMessageBox.information(
                    None,
                    "Update Available",
                    f"<h3>🎉 A new version is available!</h3>"
                    f"<p>Current: <b>v{current}</b><br>"
                    f"Latest: <b>v{latest}</b></p>"
                    f"<p>Visit the releases page to download the update.</p>",
                    QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Close,
                    QMessageBox.StandardButton.Open,
                )
                if reply == QMessageBox.StandardButton.Open:
                    import webbrowser
                    webbrowser.open(url or f"https://github.com/{GITHUB_REPO}/releases")
            else:
                QMessageBox.information(
                    None,
                    "Up to Date",
                    f"<h3>✅ You're up to date!</h3>"
                    f"<p><b>v{current}</b> is the latest version.</p>",
                )

        def _show_error(msg: str):
            QMessageBox.warning(
                None,
                "Update Check Failed",
                f"<p>Could not check for updates.</p>"
                f"<p style='color: gray;'>{msg}</p>",
            )

        def _version_tuple(v: str):
            try:
                return tuple(int(x) for x in v.split("."))
            except ValueError:
                return (0, 0, 0)

        # Run the check in a background thread to avoid blocking the UI
        threading.Thread(target=_do_check, daemon=True).start()

    def _show_about(self):
        """Show About dialog."""
        QMessageBox.about(
            None,
            f"About {APP_NAME}",
            f"<h2>{APP_NAME} v{APP_VERSION}</h2>"
            f"<p>A lightweight, privacy-respecting screenshot tool for Windows.</p>"
            f"<p>• Region & fullscreen capture<br>"
            f"• Annotation tools (pen, arrow, text, blur, and more)<br>"
            f"• Copy to clipboard or save to file<br>"
            f"• Global hotkeys</p>"
            f"<p><a href='https://github.com/{GITHUB_REPO}' style='color: #0099FF;'>GitHub</a></p>"
            f"<p style='color: gray;'>No uploads. No telemetry. Just screenshots.</p>",
        )

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
