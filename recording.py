"""Screen recording helpers for ClearShot."""

from __future__ import annotations

import datetime
import ctypes
import ctypes.wintypes as wintypes
import os
import tempfile
import threading
import time
import logging
import shutil
from threading import Event

import imageio_ffmpeg
import mss
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QWidget,
)

from capture import capture_all_monitors, ensure_dpi_awareness, get_virtual_screen_geometry
from constants import (
    COLOR_PALETTE,
    DEFAULT_FONT_SIZE,
    DEFAULT_PEN_COLOR,
    DEFAULT_PEN_WIDTH,
    DEFAULT_RECORDING_ANNOTATION_HOLD_KEY,
    TOOL_ARROW,
    TOOL_COUNTER,
    TOOL_ELLIPSE,
    TOOL_FILLED_RECT,
    TOOL_LINE,
    TOOL_PEN,
    TOOL_RECT,
    TOOL_TEXT,
)
from icon_utils import ui_icon
from config import validate_save_directory
from recording_backend import AudioRecorder, EncoderProcess, RecordingClock, frames_for_duration
from tools import (
    ArrowItem,
    CounterItem,
    EllipseItem,
    FilledRectItem,
    LineItem,
    PenItem,
    RectItem,
    TextItem,
    create_tool_item,
)


AUDIO_MODE_NONE = "none"
AUDIO_MODE_MICROPHONE = "microphone"
AUDIO_MODE_SYSTEM = "system"
SYSTEM_AUDIO_DEFAULT_DEVICE = "__default__"
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
_ANNOTATION_HOLD_KEY_VKS = {
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
}
_ANNOTATION_HOLD_KEY_LABELS = {
    "shift": "Shift",
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
}


def exclude_widget_from_capture(widget: QWidget) -> None:
    """Ask Windows not to include a top-level widget in screen captures."""
    if os.name != "nt":
        return
    try:
        hwnd = wintypes.HWND(int(widget.winId()))
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)
    except Exception:
        pass


class CaptureExcludedInputDialog(QInputDialog):
    """Input dialog that stays visible locally but is hidden from screen capture."""

    def showEvent(self, event) -> None:
        super().showEvent(event)
        exclude_widget_from_capture(self)


def normalize_annotation_hold_key(combo: str | None) -> str:
    raw = str(combo or "").strip().lower()
    if not raw or raw in {"always", "none", "off"}:
        return ""

    requested = {part.strip() for part in raw.split("+") if part.strip()}
    if not requested or any(part not in _ANNOTATION_HOLD_KEY_VKS for part in requested):
        return DEFAULT_RECORDING_ANNOTATION_HOLD_KEY

    ordered = [part for part in ("ctrl", "alt", "shift") if part in requested or ("control" in requested and part == "ctrl")]
    return "+".join(ordered)


def format_annotation_hold_key(combo: str | None) -> str:
    normalized = normalize_annotation_hold_key(combo)
    if not normalized:
        return "Always active"
    return " + ".join(_ANNOTATION_HOLD_KEY_LABELS[part] for part in normalized.split("+"))


def annotation_hold_key_is_pressed(combo: str | None) -> bool:
    normalized = normalize_annotation_hold_key(combo)
    if not normalized:
        return True
    if os.name != "nt":
        return True
    try:
        user32 = ctypes.windll.user32
        return all(
            user32.GetAsyncKeyState(_ANNOTATION_HOLD_KEY_VKS[part]) & 0x8000
            for part in normalized.split("+")
        )
    except Exception:
        return True


def make_recording_path(
    save_dir: str | None,
    pattern: str | None = None,
    extension: str = ".mp4",
) -> str:
    """Create a unique recording path in the configured save directory."""
    folder = validate_save_directory(save_dir, "Recording save location")
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


def list_microphone_devices() -> list[tuple[str, str]]:
    """Return live Windows input names and persistent WASAPI endpoint IDs."""
    try:
        import soundcard as sc
        return [(str(mic.name), str(mic.id)) for mic in sc.all_microphones(include_loopback=False)]
    except Exception:
        logging.exception("Could not enumerate microphones")
        return []


def resolve_microphone(selected: str):
    import soundcard as sc
    microphones = sc.all_microphones(include_loopback=False)
    for mic in microphones:
        if str(mic.id) == selected:
            return mic
    matches = [mic for mic in microphones if str(mic.name) == selected]
    if len(matches) == 1:
        return matches[0]
    raise RuntimeError("The selected microphone is unavailable. Reconnect it or choose another input in Settings.")


def list_system_audio_sources() -> list[tuple[str, str]]:
    """Return available Windows output devices for loopback system-audio capture."""
    try:
        import soundcard as sc
    except Exception:
        return []

    sources: list[tuple[str, str]] = []
    seen: set[str] = set()
    try:
        for speaker in sc.all_speakers():
            device_id = str(speaker.id)
            name = str(speaker.name)
            if not device_id or device_id in seen:
                continue
            seen.add(device_id)
            sources.append((name, device_id))
    except Exception:
        return []
    return sources


def resolve_system_speaker(device_id: str | None):
    import soundcard as sc

    selected = (device_id or "").strip()
    if not selected or selected == SYSTEM_AUDIO_DEFAULT_DEVICE:
        return sc.default_speaker()

    speakers = list(sc.all_speakers())
    for speaker in speakers:
        if str(speaker.id) == selected:
            return speaker
    for speaker in speakers:
        if str(speaker.name) == selected:
            return speaker
    raise RuntimeError("Selected system audio output device was not found.")


def _clone_annotation_item(item):
    clone = type(item)(color=item.color, width=item.width)
    if isinstance(item, PenItem):
        clone.points = [QPointF(point) for point in item.points]
    elif isinstance(item, (LineItem, ArrowItem, RectItem, FilledRectItem, EllipseItem)):
        clone.start = QPointF(item.start)
        clone.end = QPointF(item.end)
    elif isinstance(item, TextItem):
        clone.position = QPointF(item.position)
        clone.text = item.text
        clone.font_size = item.font_size
        clone.font_family = item.font_family
    elif isinstance(item, CounterItem):
        clone.position = QPointF(item.position)
        clone.number = item.number
        clone.radius = item.radius
    return clone


def _qimage_rgb_bytes(image: QImage) -> bytes:
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    width = image.width()
    height = image.height()
    row_bytes = width * 3
    bytes_per_line = image.bytesPerLine()
    bits = image.bits()
    bits.setsize(image.sizeInBytes())
    raw = memoryview(bits)
    if bytes_per_line == row_bytes:
        return bytes(raw[:row_bytes * height])

    packed = bytearray(row_bytes * height)
    for y in range(height):
        src_start = y * bytes_per_line
        src_end = src_start + row_bytes
        dst_start = y * row_bytes
        packed[dst_start:dst_start + row_bytes] = raw[src_start:src_end]
    return bytes(packed)


class RecordingAnnotationStore:
    """Thread-safe live annotation snapshot for video-frame compositing."""

    def __init__(self):
        self._lock = threading.RLock()
        self._items = []

    def set_items(self, items) -> None:
        with self._lock:
            self._items = [_clone_annotation_item(item) for item in items]

    def clear(self) -> None:
        with self._lock:
            self._items = []

    def snapshot(self):
        with self._lock:
            return [_clone_annotation_item(item) for item in self._items]

    def has_items(self) -> bool:
        with self._lock:
            return bool(self._items)

    def render(self, painter: QPainter) -> None:
        for item in self.snapshot():
            item.render(painter)


class ScreenRecorder(QThread):
    """Capture a screen rectangle with recoverable, bounded finalization."""

    recording_started = pyqtSignal(str)
    recording_finalizing = pyqtSignal(str)
    recording_finished = pyqtSignal(str, float, int)
    recording_failed = pyqtSignal(str)
    recording_paused = pyqtSignal()
    recording_resumed = pyqtSignal()

    def __init__(self, rect: QRect, output_path: str, fps: int = 15,
                 audio_mode: str = AUDIO_MODE_NONE, microphone_source: str | None = None,
                 system_audio_device: str | None = None,
                 annotation_store: RecordingAnnotationStore | None = None):
        super().__init__()
        self._rect = normalize_recording_rect(rect)
        self._output_path = output_path
        self._fps = max(1, min(30, int(fps or 15)))
        self._audio_mode = audio_mode or AUDIO_MODE_NONE
        self._microphone_source = (microphone_source or "").strip()
        self._system_audio_device = (system_audio_device or SYSTEM_AUDIO_DEFAULT_DEVICE).strip()
        self._annotation_store = annotation_store
        self._stop_event = Event()
        self._pause_event = Event()
        self._clock = RecordingClock()
        self._audio_recorder = None
        self._recovery_dir = None

    @property
    def output_path(self) -> str:
        return self._output_path

    @property
    def elapsed(self) -> float:
        return self._clock.snapshot()[0]

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    @property
    def is_stopping(self) -> bool:
        return self._stop_event.is_set()

    def pause(self) -> None:
        if not self.is_stopping and not self.is_paused:
            self._clock.pause()
            self._pause_event.set()
            self.recording_paused.emit()

    def resume(self) -> None:
        if not self.is_stopping and self.is_paused:
            self._clock.resume()
            self._pause_event.clear()
            self.recording_resumed.emit()

    def toggle_pause(self) -> bool:
        if self.is_paused:
            self.resume()
        else:
            self.pause()
        return self.is_paused

    def stop(self) -> None:
        if not self.is_stopping:
            self.recording_finalizing.emit("Stopping and finalizing video...")
            self._clock.stop()
            self._stop_event.set()
            self._pause_event.clear()

    def run(self) -> None:
        ensure_dpi_awareness()
        try:
            self._check_disk_space()
            logging.info('Recording started (%s, %s fps)', self._audio_mode, self._fps)
            frames = self._record_session()
        except Exception as exc:
            self.stop()
            logging.exception('Recording failed')
            message = str(exc) or "Unknown recording error."
            if self._recovery_dir:
                message += ("\n\nRecording files were retained in:\n" + self._recovery_dir
                            + "\nThe video.mkv file may be playable without audio.")
            self.recording_failed.emit(message)
            return
        duration = frames / self._fps
        logging.info('Recording finalized: %s frames, %.1f seconds', frames, duration)
        self.recording_finished.emit(self._output_path, duration, frames)

    def _record_session(self) -> int:
        parent = os.path.dirname(os.path.abspath(self._output_path))
        self._recovery_dir = tempfile.mkdtemp(prefix="ClearShot_recovery_", dir=parent)
        video_path = os.path.join(self._recovery_dir, "video.mkv")
        audio_path = os.path.join(self._recovery_dir, "audio.wav")
        extension = os.path.splitext(self._output_path)[1].lower()
        if extension not in {".mp4", ".mkv"}:
            raise RuntimeError("Choose MP4 or MKV as the recording export format.")
        export_path = os.path.join(self._recovery_dir, "export" + extension)
        if self._audio_mode in {AUDIO_MODE_MICROPHONE, AUDIO_MODE_SYSTEM}:
            self._audio_recorder = AudioRecorder(
                audio_path, self._resolve_audio_device, self._clock, self._stop_event,
            )
            self._audio_recorder.start()
        try:
            if self._audio_recorder:
                if not self._audio_recorder.ready.wait(10):
                    raise RuntimeError("The audio device did not respond within 10 seconds.")
                self._check_audio()
            frames = self._run_silent(video_path)
        finally:
            self.stop()
            if self._audio_recorder:
                self._audio_recorder.join(timeout=5)
        if self._audio_recorder:
            if self._audio_recorder.is_alive():
                raise RuntimeError("The audio device did not stop. Recording files have been retained.")
            self._check_audio()
            if self._audio_recorder.frames <= 0:
                raise RuntimeError("The audio device did not produce any samples. Recording files have been retained.")
        if frames <= 0:
            raise RuntimeError("Recording stopped before any video frames were captured.")
        self._check_disk_space()
        self.recording_finalizing.emit("Exporting recording...")
        self._export(video_path, audio_path if self._audio_recorder else None, export_path, frames)
        if not os.path.isfile(export_path) or os.path.getsize(export_path) == 0:
            raise RuntimeError("The encoder did not produce a video file.")
        os.replace(export_path, self._output_path)
        # Only this session's files, only after a successful export and closed audio.
        try:
            shutil.rmtree(self._recovery_dir)
        except OSError:
            logging.warning("Could not remove completed recording workspace: %s", self._recovery_dir)
        self._recovery_dir = None
        return frames

    def _resolve_audio_device(self):
        if self._audio_mode == AUDIO_MODE_MICROPHONE:
            return resolve_microphone(self._microphone_source)
        import soundcard as sc
        speaker = resolve_system_speaker(self._system_audio_device)
        if speaker is None:
            raise RuntimeError("No system audio output device is available.")
        return sc.get_microphone(id=speaker.id, include_loopback=True)

    def _check_audio(self):
        audio = self._audio_recorder
        if audio and audio.error:
            raise RuntimeError("Audio recording failed: " + audio.error)
        if audio and not self.is_stopping and time.monotonic() - audio.last_activity > 10:
            raise RuntimeError("The audio device stopped responding.")

    def _check_disk_space(self) -> None:
        folder = os.path.dirname(os.path.abspath(self._output_path))
        if shutil.disk_usage(folder).free < 256 * 1024 * 1024:
            raise RuntimeError('Recording stopped because the save drive has less than 256 MB free. Free some disk space before recording again.')

    def _capture_loop(self, send_frame) -> int:
        frames = 0
        region = dict(left=self._rect.x(), top=self._rect.y(),
                      width=self._rect.width(), height=self._rect.height())
        next_space_check = 0.0
        last_frame = None
        self._clock.start()
        with mss.mss() as sct:
            while not self.is_stopping:
                self._check_audio()
                if time.monotonic() >= next_space_check:
                    self._check_disk_space()
                    next_space_check = time.monotonic() + 1.0
                elapsed, active, epoch = self._clock.snapshot()
                if not active:
                    self._stop_event.wait(0.02)
                    continue
                if frames > elapsed * self._fps:
                    self._stop_event.wait(min(0.02, frames / self._fps - elapsed))
                    continue
                screenshot = sct.grab(region)
                frame = self._compose_annotation_frame(screenshot.rgb)
                elapsed, active, after_epoch = self._clock.snapshot()
                if epoch != after_epoch or not active:
                    continue
                target = frames_for_duration(elapsed, self._fps)
                if target - frames > self._fps * 5:
                    raise RuntimeError("The encoder cannot keep up. Try a smaller recording area or lower frame rate.")
                # Keep wall-clock duration when capture is slow, without queuing images.
                while frames < max(1, target):
                    send_frame(last_frame if last_frame is not None and frames < target - 1 else frame)
                    frames += 1
                last_frame = frame
        # Stop/pause may interrupt a capture. Finish only the already elapsed timeline.
        target = frames_for_duration(self.elapsed, self._fps)
        if last_frame is not None:
            if target - frames > self._fps * 5:
                raise RuntimeError("The encoder fell too far behind to finish this recording.")
            while frames < target:
                send_frame(last_frame)
                frames += 1
        return frames

    def _compose_annotation_frame(self, rgb_data: bytes) -> bytes:
        if self._annotation_store is None or not self._annotation_store.has_items():
            return rgb_data
        width = self._rect.width()
        height = self._rect.height()
        image = QImage(rgb_data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._annotation_store.render(painter)
        finally:
            painter.end()
        return _qimage_rgb_bytes(image)

    def _run_silent(self, output_path: str) -> int:
        encoder = EncoderProcess([
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
            f"{self._rect.width()}x{self._rect.height()}", "-r", str(self._fps), "-i", "-",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-cluster_time_limit", "1000", output_path,
        ], input_pipe=True)
        try:
            self._clock.start()
            self.recording_started.emit(self._output_path)
            frames = self._capture_loop(encoder.write)
            self.recording_finalizing.emit("Finalizing video file...")
            encoder.finish()
            return frames
        except Exception:
            self.stop()
            # Close a healthy encoder so even a capture/disk/audio failure leaves
            # a playable video. A stalled encoder is still subject to the timeout.
            try:
                encoder.finish(timeout=10)
            except Exception:
                logging.exception("Could not finalize recovery video")
            raise
        finally:
            encoder.close()

    def _export(self, video_path, audio_path, output_path, frames):
        command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                   "-i", video_path]
        if audio_path:
            command += ["-i", audio_path, "-map", "0:v:0", "-map", "1:a:0",
                        "-c:a", "aac", "-af", "apad"]
        else:
            command += ["-map", "0:v:0", "-an"]
        command += ["-c:v", "copy", "-t", f"{frames / self._fps:.6f}"]
        if output_path.lower().endswith(".mp4"):
            command += ["-movflags", "+faststart"]
        command += ["-progress", "pipe:1", "-nostats", output_path]
        encoder = EncoderProcess(command, progress=True)
        try:
            # Long recordings may take time to encode audio; only advancing output
            # timestamps renew the deadline, not repeated status messages.
            encoder.finish(timeout=60)
        finally:
            encoder.close()


class RecordingBorderOverlay(QWidget):
    """Thin always-on-top border around the active recording area."""

    def __init__(self, rect: QRect, parent=None, elapsed=None):
        super().__init__(parent)
        self._record_rect = normalize_recording_rect(rect)
        self._started_at = time.perf_counter()
        self._elapsed = elapsed or (lambda: time.perf_counter() - self._started_at)
        self._paused = False
        self._finalizing = False
        self._thickness = 3
        self._segments = [self._create_chrome_widget() for _ in range(4)]
        self._badge = QLabel()
        self._prepare_chrome_widget(self._badge)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))

        self._layout_chrome()
        self._update_chrome()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_chrome)
        self._timer.start(500)

    def _prepare_chrome_widget(self, widget: QWidget) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        if hasattr(Qt.WindowType, "WindowTransparentForInput"):
            flags |= Qt.WindowType.WindowTransparentForInput
        widget.setWindowFlags(flags)
        widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _create_chrome_widget(self) -> QWidget:
        widget = QWidget()
        self._prepare_chrome_widget(widget)
        return widget

    def _layout_chrome(self) -> None:
        r = self._record_rect
        t = self._thickness
        geometries = [
            QRect(r.left(), r.top(), r.width(), t),
            QRect(r.left(), r.bottom() - t + 1, r.width(), t),
            QRect(r.left(), r.top(), t, r.height()),
            QRect(r.right() - t + 1, r.top(), t, r.height()),
        ]
        for widget, geometry in zip(self._segments, geometries):
            widget.setGeometry(geometry)

    def set_paused(self, paused: bool) -> None:
        if self._finalizing:
            return
        self._paused = paused
        self._update_chrome()

    def set_finalizing(self, finalizing: bool) -> None:
        self._finalizing = finalizing
        if finalizing:
            self._paused = False
        self._update_chrome()

    def show(self) -> None:
        self._layout_chrome()
        self._update_chrome()
        for widget in [*self._segments, self._badge]:
            widget.show()
            exclude_widget_from_capture(widget)
        self.raise_()

    def raise_(self) -> None:
        for widget in [*self._segments, self._badge]:
            widget.raise_()

    def close(self) -> bool:
        self._timer.stop()
        for widget in [*self._segments, self._badge]:
            widget.close()
        return super().close()

    def _update_chrome(self) -> None:
        if self._finalizing:
            color = QColor("#0099ff")
        else:
            color = QColor("#ffb020" if self._paused else "#ff3b30")
        for widget in self._segments:
            widget.setStyleSheet(f"background: {color.name()};")

        elapsed = max(0, int(self._elapsed()))
        if self._finalizing:
            label = "FINALIZING"
        elif self._paused:
            label = "PAUSED"
        else:
            label = f"REC {elapsed // 60:02d}:{elapsed % 60:02d}"
        self._badge.setText(label)
        self._badge.setStyleSheet(
            "QLabel {"
            "background: #141414;"
            f"border: 1px solid {color.name()};"
            "border-radius: 4px;"
            "color: #f5f7fb;"
            "padding: 5px 9px;"
            "}"
        )
        self._badge.adjustSize()
        self._badge.move(self._record_rect.left() + 8, self._record_rect.top() + 8)
        exclude_widget_from_capture(self._badge)


class RecordingAnnotationCanvas(QWidget):
    """Transparent live-annotation canvas for active screen recordings."""

    def __init__(self, store: RecordingAnnotationStore, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self._store = store

        self._items = []
        self._current_item = None
        self._drawing_enabled = True
        self.current_tool = TOOL_PEN
        self.current_color = DEFAULT_PEN_COLOR
        self.current_width = DEFAULT_PEN_WIDTH
        self.font_size = DEFAULT_FONT_SIZE
        self._counter_value = 1

    def set_drawing_enabled(self, enabled: bool) -> None:
        if self._drawing_enabled == enabled:
            return
        self._drawing_enabled = enabled
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)

    def is_drawing(self) -> bool:
        return self._current_item is not None

    def undo(self) -> None:
        if not self._items:
            return
        item = self._items.pop()
        if isinstance(item, CounterItem):
            self._counter_value = max(1, self._counter_value - 1)
        self._sync_store()
        self.update()

    def clear_all(self) -> None:
        self._items.clear()
        self._current_item = None
        self._counter_value = 1
        self._sync_store()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for item in self._items:
            item.render(painter)
        if self._current_item is not None:
            self._current_item.render(painter)
        painter.end()

    def mousePressEvent(self, event) -> None:
        if not self._drawing_enabled:
            event.ignore()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = QPointF(event.pos())
        if self.current_tool == TOOL_TEXT:
            self._place_text(pos)
            return

        if self.current_tool == TOOL_COUNTER:
            item = CounterItem(color=self.current_color, width=self.current_width)
            item.position = pos
            item.number = self._counter_value
            self._counter_value += 1
            self._items.append(item)
            self._sync_store()
            self.update()
            return

        item = create_tool_item(self.current_tool, self.current_color, self.current_width)
        if isinstance(item, PenItem):
            item.add_point(pos)
        elif hasattr(item, "start"):
            item.start = pos
            item.end = pos
        self._current_item = item

    def mouseMoveEvent(self, event) -> None:
        if not self._drawing_enabled:
            event.ignore()
            return
        if self._current_item is None:
            return

        pos = QPointF(event.pos())
        if isinstance(self._current_item, PenItem):
            self._current_item.add_point(pos)
        elif hasattr(self._current_item, "end"):
            self._current_item.end = pos
        self._sync_store()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if not self._drawing_enabled:
            event.ignore()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._current_item is None:
            return
        self._items.append(self._current_item)
        self._current_item = None
        self._sync_store()
        self.update()

    def _place_text(self, pos: QPointF) -> None:
        dialog = CaptureExcludedInputDialog(self)
        dialog.setWindowTitle("Add Recording Text")
        dialog.setLabelText("Enter text:")
        dialog.setInputMode(QInputDialog.InputMode.TextInput)
        dialog.setTextValue("")
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        text = dialog.textValue()
        if not text:
            return
        item = TextItem(color=self.current_color, width=self.current_width)
        item.position = pos
        item.text = text
        item.font_size = self.font_size
        self._items.append(item)
        self._sync_store()
        self.update()

    def _sync_store(self) -> None:
        items = list(self._items)
        if self._current_item is not None:
            items.append(self._current_item)
        self._store.set_items(items)


class RecordingToolbarFrame(QFrame):
    """Solid toolbar chrome with a quieter idle state that remains capture-excludable."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._idle_style = ""
        self._focus_style = ""
        self._focused = False

    def set_visual_styles(self, idle_style: str, focus_style: str) -> None:
        self._idle_style = idle_style
        self._focus_style = focus_style
        self._apply_visual_state()

    def enterEvent(self, event) -> None:
        self._focused = True
        self._apply_visual_state()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._focused = False
        self._apply_visual_state()
        super().leaveEvent(event)

    def _apply_visual_state(self) -> None:
        self.setStyleSheet(self._focus_style if self._focused else self._idle_style)


class RecordingAnnotationOverlay(QWidget):
    """Topmost drawing surface for annotations captured in active recordings."""

    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    def __init__(
        self,
        rect: QRect,
        store: RecordingAnnotationStore,
        hold_key: str | None = DEFAULT_RECORDING_ANNOTATION_HOLD_KEY,
        parent=None,
    ):
        super().__init__(parent)
        self._record_rect = normalize_recording_rect(rect)
        self._store = store
        self._hold_key = normalize_annotation_hold_key(hold_key)
        self._draw_input_active: bool | None = None
        self._paused = False
        self._finalizing = False
        self._pause_btn: QToolButton | None = None
        self._stop_btn: QToolButton | None = None
        self._status_label: QLabel | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setGeometry(self._record_rect)

        self._canvas = RecordingAnnotationCanvas(self._store, self)
        self._canvas.setGeometry(self.rect())
        self._toolbar = self._create_toolbar()
        self._position_toolbar()
        self._refresh_toolbar_hint()

        self._input_timer = QTimer(self)
        self._input_timer.setInterval(30)
        self._input_timer.timeout.connect(self._refresh_input_mode)
        self._input_timer.start()

    def clear_all(self) -> None:
        self._canvas.clear_all()

    def undo(self) -> None:
        self._canvas.undo()

    def set_hold_key(self, hold_key: str | None) -> None:
        self._hold_key = normalize_annotation_hold_key(hold_key)
        self._refresh_toolbar_hint()
        self._refresh_input_mode(force=True)

    def set_paused(self, paused: bool) -> None:
        if self._finalizing:
            return
        self._paused = paused
        if self._pause_btn is None:
            return
        icon_name = "play" if paused else "pause"
        tooltip = "Resume recording" if paused else "Pause recording"
        self._pause_btn.setIcon(ui_icon(icon_name))
        self._pause_btn.setToolTip(tooltip)

    def set_finalizing(self, finalizing: bool, message: str = "") -> None:
        self._finalizing = finalizing
        if self._status_label is not None:
            text = (message or "Finalizing video...").strip()
            self._status_label.setText(text)
            self._status_label.setVisible(finalizing)
        for widget_type in (QToolButton, QPushButton, QSlider):
            for widget in self._toolbar.findChildren(widget_type):
                widget.setEnabled(not finalizing)
        self._canvas.set_drawing_enabled(False if finalizing else self._draw_input_active is not False)
        self._toolbar.adjustSize()
        self._position_toolbar()
        self._refresh_input_mode(force=True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        exclude_widget_from_capture(self)
        self._position_toolbar()
        self._toolbar.show()
        exclude_widget_from_capture(self._toolbar)
        self._toolbar.raise_()
        self._refresh_input_mode(force=True)

    def hideEvent(self, event) -> None:
        self._toolbar.hide()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._toolbar.close()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        self._canvas.setGeometry(self.rect())
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        if self._draw_input_active:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
            painter.end()

    def nativeEvent(self, event_type, message):
        if os.name == "nt" and self._draw_input_active is False:
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_NCHITTEST:
                    return True, HTTRANSPARENT
            except Exception:
                pass
        return False, 0

    def _refresh_input_mode(self, force: bool = False) -> None:
        active = False if self._finalizing else annotation_hold_key_is_pressed(self._hold_key) or self._canvas.is_drawing()
        if not force and active == self._draw_input_active:
            return
        self._draw_input_active = active
        self._canvas.set_drawing_enabled(active)
        self.repaint()
        self._canvas.repaint()
        if active:
            self.raise_()
            self._toolbar.raise_()

    def _refresh_toolbar_hint(self) -> None:
        hold_label = format_annotation_hold_key(self._hold_key)
        if self._hold_key:
            self._toolbar.setToolTip(f"Hold {hold_label} and drag to annotate")
        else:
            self._toolbar.setToolTip("Annotation drawing is always active")

    def _position_toolbar(self) -> None:
        margin = 8
        badge_space = 108
        self._toolbar.adjustSize()
        toolbar_width = self._toolbar.sizeHint().width()
        available_width = self._record_rect.width() - badge_space - (margin * 3)
        if available_width >= toolbar_width:
            x = self._record_rect.left() + badge_space + (margin * 2)
            y = self._record_rect.top() + margin
        else:
            x = self._record_rect.left() + margin
            y = self._record_rect.top() + 44
        self._toolbar.move(x, y)

    def raise_(self) -> None:
        super().raise_()
        self._toolbar.raise_()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Escape:
            self.hide()
        elif key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            self.undo()
        elif key == Qt.Key.Key_P:
            self._set_tool(TOOL_PEN)
            self._check_tool_button(TOOL_PEN)
        elif key == Qt.Key.Key_L:
            self._set_tool(TOOL_LINE)
            self._check_tool_button(TOOL_LINE)
        elif key == Qt.Key.Key_A:
            self._set_tool(TOOL_ARROW)
            self._check_tool_button(TOOL_ARROW)
        elif key == Qt.Key.Key_R:
            self._set_tool(TOOL_RECT)
            self._check_tool_button(TOOL_RECT)
        elif key == Qt.Key.Key_H:
            self._set_tool(TOOL_FILLED_RECT)
            self._check_tool_button(TOOL_FILLED_RECT)
        elif key == Qt.Key.Key_E:
            self._set_tool(TOOL_ELLIPSE)
            self._check_tool_button(TOOL_ELLIPSE)
        elif key == Qt.Key.Key_T:
            self._set_tool(TOOL_TEXT)
            self._check_tool_button(TOOL_TEXT)
        elif key == Qt.Key.Key_N:
            self._set_tool(TOOL_COUNTER)
            self._check_tool_button(TOOL_COUNTER)
        else:
            super().keyPressEvent(event)

    def _create_toolbar(self) -> QFrame:
        toolbar = RecordingToolbarFrame()
        toolbar.setObjectName("recordingAnnotationToolbar")
        toolbar.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        toolbar.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        toolbar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toolbar.set_visual_styles(self._toolbar_stylesheet(focused=False), self._toolbar_stylesheet(focused=True))

        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(2)

        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        tool_defs = [
            (TOOL_PEN, "pen", "Pen (P)"),
            (TOOL_LINE, "line", "Line (L)"),
            (TOOL_ARROW, "arrow", "Arrow (A)"),
            (TOOL_RECT, "rect", "Rectangle (R)"),
            (TOOL_FILLED_RECT, "filled_rect", "Highlight (H)"),
            (TOOL_ELLIPSE, "ellipse", "Ellipse (E)"),
            (TOOL_TEXT, "text", "Text (T)"),
            (TOOL_COUNTER, "counter", "Counter (N)"),
        ]
        for tool_id, icon_name, tooltip in tool_defs:
            btn = QToolButton(toolbar)
            btn.setIcon(ui_icon(icon_name))
            btn.setIconSize(QSize(17, 17))
            btn.setFixedSize(30, 28)
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setProperty("tool_id", tool_id)
            btn.clicked.connect(lambda checked, tid=tool_id: self._set_tool(tid))
            self._tool_group.addButton(btn)
            layout.addWidget(btn)
            if tool_id == TOOL_PEN:
                btn.setChecked(True)

        layout.addWidget(self._separator())

        for color in COLOR_PALETTE[:6]:
            btn = QPushButton(toolbar)
            btn.setFixedSize(22, 22)
            btn.setToolTip(color)
            btn.setStyleSheet(
                f"QPushButton {{ background: {color}; border: 2px solid #555; border-radius: 4px; }}"
                "QPushButton:hover { border-color: #fff; }"
            )
            btn.clicked.connect(lambda checked, c=color: self._set_color(c))
            layout.addWidget(btn)

        custom_color_btn = QPushButton(toolbar)
        custom_color_btn.setIcon(ui_icon("palette"))
        custom_color_btn.setIconSize(QSize(16, 16))
        custom_color_btn.setFixedSize(28, 24)
        custom_color_btn.setToolTip("Custom color")
        custom_color_btn.clicked.connect(self._pick_custom_color)
        layout.addWidget(custom_color_btn)

        layout.addWidget(self._separator())

        layout.addWidget(QLabel("Size:", toolbar))
        self._width_slider = QSlider(Qt.Orientation.Horizontal, toolbar)
        self._width_slider.setRange(1, 20)
        self._width_slider.setValue(DEFAULT_PEN_WIDTH)
        self._width_slider.setFixedWidth(84)
        self._width_slider.valueChanged.connect(self._set_width)
        layout.addWidget(self._width_slider)

        self._width_label = QLabel(str(DEFAULT_PEN_WIDTH), toolbar)
        self._width_label.setFixedWidth(20)
        layout.addWidget(self._width_label)

        layout.addWidget(self._separator())

        self._status_label = QLabel("Finalizing video...", toolbar)
        self._status_label.setObjectName("recordingStatusLabel")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        self._pause_btn = QToolButton(toolbar)
        self._pause_btn.setIconSize(QSize(17, 17))
        self._pause_btn.setFixedSize(30, 28)
        self._pause_btn.clicked.connect(self.pause_requested.emit)
        layout.addWidget(self._pause_btn)
        self.set_paused(self._paused)

        self._stop_btn = QToolButton(toolbar)
        self._stop_btn.setIcon(ui_icon("stop"))
        self._stop_btn.setIconSize(QSize(17, 17))
        self._stop_btn.setFixedSize(30, 28)
        self._stop_btn.setToolTip("Stop recording")
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        layout.addWidget(self._stop_btn)

        layout.addWidget(self._separator())

        undo_btn = QToolButton(toolbar)
        undo_btn.setIcon(ui_icon("undo"))
        undo_btn.setIconSize(QSize(17, 17))
        undo_btn.setFixedSize(30, 28)
        undo_btn.setToolTip("Undo (Ctrl+Z)")
        undo_btn.clicked.connect(self.undo)
        layout.addWidget(undo_btn)

        clear_btn = QToolButton(toolbar)
        clear_btn.setIcon(ui_icon("trash"))
        clear_btn.setIconSize(QSize(17, 17))
        clear_btn.setFixedSize(30, 28)
        clear_btn.setToolTip("Clear annotations")
        clear_btn.clicked.connect(self.clear_all)
        layout.addWidget(clear_btn)

        toolbar.adjustSize()
        return toolbar

    def _toolbar_stylesheet(self, focused: bool) -> str:
        background = "#232323" if focused else "#2b2b2b"
        border = "#666" if focused else "#474747"
        text = "#f0f3f7" if focused else "#b9c0c8"
        hover = "#3d3d3d" if focused else "#353535"
        slider_track = "#5b5b5b" if focused else "#474747"
        return f"""
            #recordingAnnotationToolbar {{
                background: {background};
                border: 1px solid {border};
                border-radius: 5px;
            }}
            QToolButton, QPushButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 5px;
                color: {text};
                font-size: 11px;
                font-weight: bold;
            }}
            QToolButton:hover, QPushButton:hover {{
                background: {hover};
                border-color: #777;
            }}
            QToolButton:disabled, QPushButton:disabled {{
                color: #777;
                border-color: transparent;
            }}
            QToolButton:checked {{
                background: #0078D4;
                border-color: #0078D4;
                color: #ffffff;
            }}
            QLabel {{
                color: {text};
                font-size: 11px;
            }}
            QLabel#recordingStatusLabel {{
                color: #9ed8ff;
                font-weight: bold;
                padding: 0 7px;
            }}
            QSlider::groove:horizontal {{
                height: 4px;
                background: {slider_track};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 13px;
                height: 13px;
                margin: -5px 0;
                background: #0099FF;
                border-radius: 6px;
            }}
        """

    def _separator(self) -> QFrame:
        sep = QFrame(self._toolbar if hasattr(self, "_toolbar") else self)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background: #555;")
        return sep

    def _set_tool(self, tool_id: str) -> None:
        self._canvas.current_tool = tool_id

    def _set_color(self, color: str) -> None:
        self._canvas.current_color = color

    def _pick_custom_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._canvas.current_color), self, "Pick a color")
        if color.isValid():
            self._canvas.current_color = color.name()

    def _set_width(self, value: int) -> None:
        self._canvas.current_width = value
        self._canvas.font_size = max(10, value * 3)
        self._width_label.setText(str(value))

    def _check_tool_button(self, tool_id: str) -> None:
        for btn in self._tool_group.buttons():
            if btn.property("tool_id") == tool_id:
                btn.setChecked(True)
                break


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
