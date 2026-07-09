"""Screen recording helpers for ClearShot."""

from __future__ import annotations

import datetime
import ctypes
import ctypes.wintypes as wintypes
import os
import re
import subprocess
import tempfile
import threading
import time
import wave
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
    DEFAULT_SAVE_DIR,
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
    """Return available Windows DirectShow microphone/input device names."""
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


def _resolve_system_speaker(device_id: str | None):
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


class _SystemAudioRecorder(threading.Thread):
    """Record Windows output-loopback audio to a temporary WAV file."""

    def __init__(
        self,
        path: str,
        device_id: str | None,
        stop_event: Event,
        pause_event: Event,
        sample_rate: int = 48000,
        channels: int = 2,
    ):
        super().__init__(daemon=True)
        self.path = path
        self.device_id = device_id or SYSTEM_AUDIO_DEFAULT_DEVICE
        self.stop_event = stop_event
        self.pause_event = pause_event
        self.sample_rate = sample_rate
        self.channels = channels
        self.frames = 0
        self.error = ""

    def run(self) -> None:
        try:
            import numpy as np
            import soundcard as sc

            speaker = _resolve_system_speaker(self.device_id)
            loopback = sc.get_microphone(id=speaker.id, include_loopback=True)
            block_size = 1024

            with wave.open(self.path, "wb") as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)

                with loopback.recorder(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    blocksize=block_size,
                ) as recorder:
                    while not self.stop_event.is_set():
                        if self.pause_event.is_set():
                            self.stop_event.wait(0.05)
                            continue

                        data = recorder.record(numframes=block_size)
                        if data is None or len(data) == 0:
                            continue
                        if data.ndim == 1:
                            data = data.reshape(-1, 1)
                        if data.shape[1] < self.channels:
                            data = np.repeat(data[:, :1], self.channels, axis=1)
                        data = data[:, :self.channels]
                        pcm = np.clip(data, -1.0, 1.0)
                        pcm = (pcm * 32767.0).astype("<i2", copy=False)
                        wav_file.writeframes(pcm.tobytes())
                        self.frames += len(pcm)
        except Exception as exc:
            self.error = str(exc) or "System audio recording failed."


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
        audio_mode: str = AUDIO_MODE_NONE,
        microphone_source: str | None = None,
        system_audio_device: str | None = None,
        annotation_store: RecordingAnnotationStore | None = None,
    ):
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
            if self._audio_mode == AUDIO_MODE_MICROPHONE:
                frames = self._run_with_microphone()
            elif self._audio_mode == AUDIO_MODE_SYSTEM:
                frames = self._run_with_system_audio()
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
                frame = self._compose_annotation_frame(screenshot.rgb)
                send_frame(frame)
                frames += 1

                next_frame_at += frame_interval
                delay = next_frame_at - time.perf_counter()
                if delay > 0:
                    self._stop_event.wait(delay)
                else:
                    next_frame_at = time.perf_counter()
        return frames

    def _compose_annotation_frame(self, rgb_data: bytes) -> bytes:
        if self._annotation_store is None or not self._annotation_store.has_items():
            return rgb_data

        width = self._rect.width()
        height = self._rect.height()
        image = QImage(rgb_data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._annotation_store.render(painter)
        painter.end()
        return _qimage_rgb_bytes(image)

    def _run_silent(self, output_path: str | None = None) -> int:
        target_path = output_path or self._output_path
        writer = imageio_ffmpeg.write_frames(
            target_path,
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

    def _run_with_microphone(self) -> int:
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
            f"audio={self._microphone_source}",
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

    def _run_with_system_audio(self) -> int:
        output_dir = os.path.dirname(os.path.abspath(self._output_path)) or os.getcwd()
        os.makedirs(output_dir, exist_ok=True)
        _, extension = os.path.splitext(self._output_path)
        video_file = tempfile.NamedTemporaryFile(
            prefix="clearshot_video_",
            suffix=extension or ".mp4",
            dir=output_dir,
            delete=False,
        )
        audio_file = tempfile.NamedTemporaryFile(
            prefix="clearshot_audio_",
            suffix=".wav",
            dir=output_dir,
            delete=False,
        )
        temp_video_path = video_file.name
        temp_audio_path = audio_file.name
        video_file.close()
        audio_file.close()

        audio_recorder = _SystemAudioRecorder(
            temp_audio_path,
            self._system_audio_device,
            self._stop_event,
            self._pause_event,
        )
        try:
            audio_recorder.start()
            try:
                frames = self._run_silent(temp_video_path)
            finally:
                self._stop_event.set()
                audio_recorder.join(timeout=5)

            if audio_recorder.error:
                raise RuntimeError(audio_recorder.error)
            if audio_recorder.frames <= 0:
                raise RuntimeError("System audio did not produce any samples.")
            self._mux_audio(temp_video_path, temp_audio_path, self._output_path)
            return frames
        finally:
            for path in (temp_video_path, temp_audio_path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def _mux_audio(self, video_path: str, audio_path: str, output_path: str) -> None:
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            video_path,
            "-i",
            audio_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            output_path,
        ]
        proc = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=_subprocess_creationflags(),
        )
        if proc.returncode != 0:
            error = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(error or f"ffmpeg mux exited with code {proc.returncode}.")

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
        self._record_rect = normalize_recording_rect(rect)
        self._started_at = time.perf_counter()
        self._paused = False
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
        self._paused = paused
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
        color = QColor("#ff3b30" if not self._paused else "#ffb020")
        for widget in self._segments:
            widget.setStyleSheet(f"background: {color.name()};")

        elapsed = max(0, int(time.perf_counter() - self._started_at))
        label = "PAUSED" if self._paused else f"REC {elapsed // 60:02d}:{elapsed % 60:02d}"
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
        self._pause_btn: QToolButton | None = None
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
        self._paused = paused
        if self._pause_btn is None:
            return
        icon_name = "play" if paused else "pause"
        tooltip = "Resume recording" if paused else "Pause recording"
        self._pause_btn.setIcon(ui_icon(icon_name))
        self._pause_btn.setToolTip(tooltip)

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
        active = annotation_hold_key_is_pressed(self._hold_key) or self._canvas.is_drawing()
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

        self._pause_btn = QToolButton(toolbar)
        self._pause_btn.setIconSize(QSize(17, 17))
        self._pause_btn.setFixedSize(30, 28)
        self._pause_btn.clicked.connect(self.pause_requested.emit)
        layout.addWidget(self._pause_btn)
        self.set_paused(self._paused)

        stop_btn = QToolButton(toolbar)
        stop_btn.setIcon(ui_icon("stop"))
        stop_btn.setIconSize(QSize(17, 17))
        stop_btn.setFixedSize(30, 28)
        stop_btn.setToolTip("Stop recording")
        stop_btn.clicked.connect(self.stop_requested.emit)
        layout.addWidget(stop_btn)

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
            QToolButton:checked {{
                background: #0078D4;
                border-color: #0078D4;
                color: #ffffff;
            }}
            QLabel {{
                color: {text};
                font-size: 11px;
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
