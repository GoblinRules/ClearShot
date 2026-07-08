"""Screen recording helpers for ClearShot."""

from __future__ import annotations

import datetime
import os
import time
from threading import Event

import imageio_ffmpeg
import mss
from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from capture import capture_all_monitors, ensure_dpi_awareness
from constants import DEFAULT_SAVE_DIR


def make_recording_path(save_dir: str | None, pattern: str | None = None) -> str:
    """Create a unique MP4 path in the configured save directory."""
    folder = save_dir or DEFAULT_SAVE_DIR
    os.makedirs(folder, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if pattern:
        base = pattern.replace("{timestamp}", timestamp)
        if "{timestamp}" not in pattern:
            base = f"{base}_{timestamp}"
    else:
        base = f"ClearShot_Recording_{timestamp}"

    if not base.lower().endswith(".mp4"):
        base = f"{base}.mp4"
    base = _safe_filename(base)

    path = os.path.join(folder, base)
    stem, ext = os.path.splitext(path)
    index = 1
    while os.path.exists(path):
        path = f"{stem}_{index}{ext}"
        index += 1
    return path


def _safe_filename(name: str) -> str:
    invalid = '<>:"/\\|?*'
    return "".join("_" if ch in invalid else ch for ch in name).strip() or "ClearShot_Recording.mp4"


def normalize_recording_rect(rect: QRect) -> QRect:
    """Return a positive, even-sized rectangle suitable for yuv420p video."""
    r = QRect(rect).normalized()
    width = max(2, r.width())
    height = max(2, r.height())
    if width % 2:
        width -= 1
    if height % 2:
        height -= 1
    return QRect(r.x(), r.y(), max(2, width), max(2, height))


class ScreenRecorder(QThread):
    """Capture a screen rectangle to MP4 on a worker thread."""

    recording_started = pyqtSignal(str)
    recording_finished = pyqtSignal(str, float, int)
    recording_failed = pyqtSignal(str)

    def __init__(self, rect: QRect, output_path: str, fps: int = 15):
        super().__init__()
        self._rect = normalize_recording_rect(rect)
        self._output_path = output_path
        self._fps = max(1, min(30, int(fps or 15)))
        self._stop_event = Event()

    @property
    def output_path(self) -> str:
        return self._output_path

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        ensure_dpi_awareness()
        writer = None
        started_at = time.perf_counter()
        frames = 0

        region = {
            "left": self._rect.x(),
            "top": self._rect.y(),
            "width": self._rect.width(),
            "height": self._rect.height(),
        }

        try:
            writer = imageio_ffmpeg.write_frames(
                self._output_path,
                (self._rect.width(), self._rect.height()),
                pix_fmt_in="rgb24",
                pix_fmt_out="yuv420p",
                fps=self._fps,
                quality=8,
                codec="libx264",
                macro_block_size=2,
                ffmpeg_log_level="error",
            )
            writer.send(None)
            self.recording_started.emit(self._output_path)

            frame_interval = 1.0 / self._fps
            next_frame_at = time.perf_counter()
            with mss.mss() as sct:
                while not self._stop_event.is_set():
                    screenshot = sct.grab(region)
                    writer.send(screenshot.rgb)
                    frames += 1

                    next_frame_at += frame_interval
                    delay = next_frame_at - time.perf_counter()
                    if delay > 0:
                        self._stop_event.wait(delay)
                    else:
                        next_frame_at = time.perf_counter()
        except Exception as exc:
            self.recording_failed.emit(str(exc))
            return
        finally:
            if writer is not None:
                try:
                    writer.close()
                except Exception:
                    pass

        duration = max(0.0, time.perf_counter() - started_at)
        self.recording_finished.emit(self._output_path, duration, frames)


class RecordingSelectionOverlay(QWidget):
    """Fullscreen overlay that emits a selected screen region for recording."""

    region_selected = pyqtSignal(QRect)
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._screenshot: QPixmap | None = None
        self._origin = QPoint()
        self._selection = QRect()
        self._start_point = QPoint()
        self._is_selecting = False

    def begin_selection(self) -> None:
        self._screenshot, monitor = capture_all_monitors()
        self._origin = QPoint(monitor["left"], monitor["top"])
        self._selection = QRect()
        self._is_selecting = False
        self.setGeometry(monitor["left"], monitor["top"], monitor["width"], monitor["height"])
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def paintEvent(self, event) -> None:
        if self._screenshot is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self._screenshot)

        full_path = QPainterPath()
        full_path.addRect(QRectF(self.rect()))
        dim = QColor(0, 0, 0, 135)

        if self._selection.isValid() and not self._selection.isEmpty():
            sel = self._selection.normalized()
            sel_path = QPainterPath()
            sel_path.addRect(QRectF(sel))
            painter.fillPath(full_path - sel_path, dim)

            painter.setPen(QPen(QColor("#ff3b30"), 2, Qt.PenStyle.SolidLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(sel)
            self._draw_label(painter, sel, f"{sel.width()} x {sel.height()}")
        else:
            painter.fillPath(full_path, dim)
            self._draw_center_hint(painter)

        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._is_selecting = True
        self._start_point = event.pos()
        self._selection = QRect(self._start_point, self._start_point)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._is_selecting:
            self._selection = QRect(self._start_point, event.pos()).normalized()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._is_selecting:
            return
        self._is_selecting = False
        sel = self._selection.normalized()
        if sel.width() < 8 or sel.height() < 8:
            self._cancel()
            return
        self.hide()
        self.region_selected.emit(QRect(
            sel.x() + self._origin.x(),
            sel.y() + self._origin.y(),
            sel.width(),
            sel.height(),
        ))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(event)

    def _cancel(self) -> None:
        self.hide()
        self.cancelled.emit()

    def _draw_center_hint(self, painter: QPainter) -> None:
        text = "Drag to select a recording region"
        font = QFont("Segoe UI", 13, QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        rect = QRectF(
            self.width() / 2 - (fm.horizontalAdvance(text) + 32) / 2,
            self.height() / 2 - (fm.height() + 20) / 2,
            fm.horizontalAdvance(text) + 32,
            fm.height() + 20,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 220))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QPen(QColor("#f5f7fb")))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_label(self, painter: QPainter, sel: QRect, text: str) -> None:
        font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        rect = QRectF(sel.left(), sel.top() - fm.height() - 12, fm.horizontalAdvance(text) + 16, fm.height() + 8)
        if rect.top() < 0:
            rect.moveTop(sel.bottom() + 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 220))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QPen(QColor("#f5f7fb")))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
