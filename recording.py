"""Screen recording helpers for ClearShot."""

from __future__ import annotations

import datetime
import os
import re
import subprocess
import time
from threading import Event

import imageio_ffmpeg
import mss
from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from capture import capture_all_monitors, ensure_dpi_awareness, get_virtual_screen_geometry
from constants import DEFAULT_SAVE_DIR


def make_recording_path(
    save_dir: str | None,
    pattern: str | None = None,
    extension: str = ".mp4",
) -> str:
    """Create a unique recording path in the configured save directory."""
    folder = save_dir or DEFAULT_SAVE_DIR
    os.makedirs(folder, exist_ok=True)
    ext = extension if extension.startswith(".") else f".{extension}"

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if pattern:
        base = pattern.replace("{timestamp}", timestamp)
        if "{timestamp}" not in pattern:
            base = f"{base}_{timestamp}"
    else:
        base = f"ClearShot_Recording_{timestamp}"

    root, existing_ext = os.path.splitext(base)
    if existing_ext.lower() in {".mp4", ".mkv", ".mov", ".webm"}:
        base = root
    base = f"{base}{ext.lower()}"
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


def _subprocess_creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def list_audio_sources(timeout: float = 5.0) -> list[str]:
    """Return available Windows DirectShow audio input device names."""
    try:
        proc = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-hide_banner",
                "-list_devices",
                "true",
                "-f",
                "dshow",
                "-i",
                "dummy",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            creationflags=_subprocess_creationflags(),
        )
    except Exception:
        return []

    text = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    in_audio_section = False
    names: list[str] = []
    for line in text.splitlines():
        lower = line.lower()
        if "directshow audio devices" in lower:
            in_audio_section = True
            continue
        if "directshow video devices" in lower:
            in_audio_section = False
            continue
        if not in_audio_section or "alternative name" in lower:
            continue

        match = re.search(r'"([^"]+)"', line)
        if match:
            name = match.group(1).strip()
            if name and name not in names:
                names.append(name)
    return names


class ScreenRecorder(QThread):
    """Capture a screen rectangle to a video file on a worker thread."""

    recording_started = pyqtSignal(str)
    recording_finished = pyqtSignal(str, float, int)
    recording_failed = pyqtSignal(str)
    recording_paused = pyqtSignal()
    recording_resumed = pyqtSignal()

    def __init__(
        self,
        rect: QRect,
        output_path: str,
        fps: int = 15,
        audio_source: str | None = None,
    ):
        super().__init__()
        self._rect = normalize_recording_rect(rect)
        self._output_path = output_path
        self._fps = max(1, min(30, int(fps or 15)))
        self._audio_source = (audio_source or "").strip()
        self._stop_event = Event()
        self._pause_event = Event()
        self._last_error = ""

    @property
    def output_path(self) -> str:
        return self._output_path

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def pause(self) -> None:
        if not self._pause_event.is_set():
            self._pause_event.set()
            self.recording_paused.emit()

    def resume(self) -> None:
        if self._pause_event.is_set():
            self._pause_event.clear()
            self.recording_resumed.emit()

    def toggle_pause(self) -> bool:
        if self.is_paused:
            self.resume()
            return False
        self.pause()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.clear()

    def run(self) -> None:
        ensure_dpi_awareness()
        started_at = time.perf_counter()

        try:
            self.recording_started.emit(self._output_path)
            if self._audio_source:
                frames = self._run_with_audio()
            else:
                frames = self._run_silent()
        except Exception as exc:
            self.recording_failed.emit(str(exc) or self._last_error or "Unknown recording error.")
            return

        duration = max(0.0, time.perf_counter() - started_at)
        self.recording_finished.emit(self._output_path, duration, frames)

    def _capture_loop(self, send_frame) -> int:
        frames = 0
        region = {
            "left": self._rect.x(),
            "top": self._rect.y(),
            "width": self._rect.width(),
            "height": self._rect.height(),
        }
        frame_interval = 1.0 / self._fps
        next_frame_at = time.perf_counter()

        with mss.mss() as sct:
            while not self._stop_event.is_set():
                if self._pause_event.is_set():
                    self._stop_event.wait(0.05)
                    next_frame_at = time.perf_counter()
                    continue

                screenshot = sct.grab(region)
                send_frame(screenshot.rgb)
                frames += 1

                next_frame_at += frame_interval
                delay = next_frame_at - time.perf_counter()
                if delay > 0:
                    self._stop_event.wait(delay)
                else:
                    next_frame_at = time.perf_counter()
        return frames

    def _run_silent(self) -> int:
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
        try:
            writer.send(None)
            return self._capture_loop(writer.send)
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def _run_with_audio(self) -> int:
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{self._rect.width()}x{self._rect.height()}",
            "-r",
            str(self._fps),
            "-i",
            "-",
            "-f",
            "dshow",
            "-i",
            f"audio={self._audio_source}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            self._output_path,
        ]
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=_subprocess_creationflags(),
        )
        try:
            if proc.stdin is None:
                raise RuntimeError("Could not open ffmpeg input pipe.")

            def _send_frame(data: bytes) -> None:
                if proc.stdin is None:
                    raise RuntimeError("ffmpeg input pipe closed.")
                proc.stdin.write(data)

            frames = self._capture_loop(_send_frame)
        except BrokenPipeError as exc:
            self._last_error = self._read_process_error(proc)
            raise RuntimeError(self._last_error or "Audio recording failed.") from exc
        finally:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

        try:
            return_code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            self._last_error = "ffmpeg did not finish cleanly."
            raise RuntimeError(self._last_error)

        if return_code != 0:
            self._last_error = self._read_process_error(proc)
            raise RuntimeError(self._last_error or f"ffmpeg exited with code {return_code}.")
        return frames

    def _read_process_error(self, proc: subprocess.Popen) -> str:
        if proc.stderr is None:
            return ""
        try:
            data = proc.stderr.read()
        except Exception:
            return ""
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = str(data)
        return text.strip()


class RecordingBorderOverlay(QWidget):
    """Thin always-on-top border around the active recording area."""

    def __init__(self, rect: QRect, parent=None):
        super().__init__(parent)
        self._virtual_rect = get_virtual_screen_geometry()
        self._record_rect = normalize_recording_rect(rect)
        self._started_at = time.perf_counter()
        self._paused = False

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        if hasattr(Qt.WindowType, "WindowTransparentForInput"):
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(self._virtual_rect)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(500)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        local = QRectF(self._record_rect).translated(
            -self._virtual_rect.x(),
            -self._virtual_rect.y(),
        )
        color = QColor("#ff3b30" if not self._paused else "#ffb020")
        pen = QPen(color, 3, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(local.adjusted(1.5, 1.5, -1.5, -1.5))

        elapsed = max(0, int(time.perf_counter() - self._started_at))
        label = "PAUSED" if self._paused else f"REC {elapsed // 60:02d}:{elapsed % 60:02d}"
        self._draw_badge(painter, local, label, color)
        painter.end()

    def _draw_badge(self, painter: QPainter, target: QRectF, text: str, color: QColor) -> None:
        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        width = fm.horizontalAdvance(text) + 22
        height = fm.height() + 8
        x = target.left() + 8
        y = target.top() + 8
        if target.height() < height + 18:
            y = max(8, target.top() - height - 6)
        badge = QRectF(x, y, width, height)

        fill = QColor(20, 20, 20, 230)
        painter.setPen(QPen(color, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(badge, 4, 4)
        painter.setPen(QPen(QColor("#f5f7fb")))
        painter.drawText(badge.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignCenter, text)


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
