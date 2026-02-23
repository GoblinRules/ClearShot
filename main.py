"""ClearShot — Screenshot tool for Windows.

Entry point with single-instance lock.
"""

import sys
import os
import ctypes

# Ensure the script directory is in the path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from constants import MUTEX_NAME, APP_NAME


def is_already_running() -> bool:
    """Check if another instance of ClearShot is already running using a Windows mutex."""
    try:
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        last_error = ctypes.windll.kernel32.GetLastError()
        ERROR_ALREADY_EXISTS = 183
        if last_error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(mutex)
            return True
        # Keep the mutex handle alive for the process lifetime
        # (it gets cleaned up automatically when the process exits)
        return False
    except Exception:
        return False


def main():
    # Single-instance check
    if is_already_running():
        # Show a message using ctypes (no Qt yet)
        ctypes.windll.user32.MessageBoxW(
            0,
            f"{APP_NAME} is already running.\nCheck your system tray.",
            APP_NAME,
            0x40,  # MB_ICONINFORMATION
        )
        sys.exit(0)

    # Import Qt after mutex check
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    
    # Disable Qt's automatic high-DPI scaling so the app works in raw
    # physical pixels — this matches how screen capture APIs (mss, GDI)
    # report coordinates, eliminating offset on mixed-DPI multi-monitor setups.
    # Qt itself sets DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 internally.
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray
    app.setApplicationName(APP_NAME)

    # Dark fusion style
    app.setStyle("Fusion")
    from PyQt6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base, QColor(37, 37, 37))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(50, 50, 50))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(0, 120, 212))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 120, 212))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    # Start the tray app
    from app import ClearShotApp
    tray_app = ClearShotApp()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
