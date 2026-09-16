"""Exercise real capture, consecutive sessions, and Quit through the Qt loop."""

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
from unittest.mock import patch

from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtWidgets import QApplication
import imageio_ffmpeg

from app import ClearShotApp
from config import DEFAULT_SETTINGS


class MemoryConfig:
    def __init__(self, folder):
        self.values = dict(DEFAULT_SETTINGS, recording_save_path=folder, recording_fps=10,
                           show_tray_notifications=False)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_hotkey(self, action):
        return ''


def run():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix='clearshot_smoke_') as folder:
        with patch('app.Config', return_value=MemoryConfig(folder)):
            tray = ClearShotApp()
        completions, errors = [], []
        attempts = 0

        def start():
            nonlocal attempts
            attempts += 1
            tray._start_recording_rect(QRect(0, 0, 320, 240), 'test region')
            recorder = tray._recorder
            recorder.recording_finished.connect(finished)
            recorder.recording_failed.connect(errors.append)
            if attempts == 3:
                QTimer.singleShot(700, tray._quit)
            else:
                QTimer.singleShot(200, tray._toggle_recording_pause)
                QTimer.singleShot(400, tray._toggle_recording_pause)
                QTimer.singleShot(900, tray._stop_recording)

        def finished(path, duration, frames):
            completions.append((path, frames))
            if attempts < 3:
                QTimer.singleShot(50, start)

        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda: (errors.append('Smoke test timed out'), tray._quit()))
        watchdog.start(15000)
        QTimer.singleShot(0, start)
        app.exec()
        watchdog.stop()
        app.processEvents()
        assert not errors, errors
        assert len(completions) == 3, completions
        for path, expected_frames in completions:
            reader = imageio_ffmpeg.read_frames(path)
            assert next(reader)['size'] == (320, 240)
            assert len(list(reader)) == expected_frames > 0
        assert not tray._hotkey_thread.isRunning()
        assert tray._recorder is None
        assert {path.name for path in Path(folder).iterdir()} == {
            Path(path).name for path, _ in completions
        }
        print('PASS: three real screen captures, pause/resume, consecutive sessions, quit during recording, decoded videos, worker cleanup')


if __name__ == '__main__':
    run()
