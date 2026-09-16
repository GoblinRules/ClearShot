"""ClearShot — Screenshot tool for Windows.

Entry point with single-instance lock.
"""

import sys
import os
import ctypes
from ctypes import wintypes
import logging

# Ensure the script directory is in the path for local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from constants import MUTEX_NAME, APP_NAME

_mutex_handle = None
_shutdown_handle = None


def _kernel32():
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    return kernel32


def is_already_running() -> bool:
    """Check if another instance of ClearShot is already running using a Windows mutex."""
    global _mutex_handle
    try:
        kernel32 = _kernel32()
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        last_error = ctypes.get_last_error()
        if not mutex:
            raise ctypes.WinError(last_error)
        ERROR_ALREADY_EXISTS = 183
        if last_error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(mutex)
            return True
        # Keep the mutex handle alive for the process lifetime
        # (it gets cleaned up automatically when the process exits)
        _mutex_handle = mutex
        return False
    except AttributeError:
        return False


def main():
    global _shutdown_handle
    # Single-instance check
    if is_already_running():
        # Exit immediately so duplicate launches release their extracted files.
        sys.exit(0)

    from diagnostics import configure_diagnostics
    from constants import APP_VERSION
    try:
        configure_diagnostics()
    except OSError:
        # A full or read-only drive must not prevent screenshots or app startup.
        logging.exception('Could not initialize local diagnostics')
    logging.info('Starting ClearShot %s; runtime=%s', APP_VERSION, getattr(sys, '_MEIPASS', 'source'))

    # Import Qt after mutex check
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt, QTimer
    
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

    kernel32 = _kernel32()
    _shutdown_handle = kernel32.CreateEventW(None, False, False, 'ClearShot_Shutdown_Event')
    shutdown_timer = QTimer(app)
    shutdown_timer.timeout.connect(
        lambda: tray_app._quit() if _shutdown_handle and kernel32.WaitForSingleObject(_shutdown_handle, 0) == 0 else None
    )
    shutdown_timer.start(250)

    result = app.exec()
    logging.info('ClearShot exited cleanly')
    for handle in (_shutdown_handle, _mutex_handle):
        if handle:
            kernel32.CloseHandle(handle)
    sys.exit(result)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
