"""ClearShot — Multi-monitor screen capture using mss.

With Qt high-DPI scaling disabled (QT_ENABLE_HIGHDPI_SCALING=0),
both mss and Qt work in raw physical pixels — coordinates always match.
"""

import ctypes
import mss
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import QRect


def ensure_dpi_awareness():
    """Set process DPI awareness for accurate screen coordinates."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _mss_to_pixmap(screenshot) -> QPixmap:
    """Convert an mss screenshot to a QPixmap."""
    img = QImage(
        screenshot.rgb,
        screenshot.width,
        screenshot.height,
        screenshot.width * 3,
        QImage.Format.Format_RGB888,
    )
    return QPixmap.fromImage(img)


def capture_all_monitors():
    """Capture the entire virtual desktop spanning all monitors.

    Returns (QPixmap, dict) with left/top/width/height in physical pixels.
    """
    ensure_dpi_awareness()

    with mss.mss() as sct:
        monitor = sct.monitors[0]  # combined virtual screen
        screenshot = sct.grab(monitor)
        return _mss_to_pixmap(screenshot), monitor


def capture_region(x: int, y: int, w: int, h: int) -> QPixmap:
    """Capture a specific region of the screen."""
    ensure_dpi_awareness()

    with mss.mss() as sct:
        region = {"top": y, "left": x, "width": w, "height": h}
        screenshot = sct.grab(region)
        return _mss_to_pixmap(screenshot)


def get_virtual_screen_geometry() -> QRect:
    """Get the bounding rectangle of the entire virtual desktop."""
    ensure_dpi_awareness()
    with mss.mss() as sct:
        mon = sct.monitors[0]
        return QRect(mon["left"], mon["top"], mon["width"], mon["height"])


def get_monitor_list() -> list:
    """Get list of individual monitor geometries.

    Returns a list of QRect objects, one per physical monitor.
    """
    ensure_dpi_awareness()
    with mss.mss() as sct:
        monitors = []
        for i, mon in enumerate(sct.monitors):
            if i == 0:
                continue  # Skip combined virtual screen
            monitors.append(
                QRect(mon["left"], mon["top"], mon["width"], mon["height"])
            )
        return monitors
