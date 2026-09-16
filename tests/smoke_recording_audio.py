"""Opt-in local hardware test; captures brief audio and removes all test media."""

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import threading
import time
from unittest.mock import Mock, patch

import imageio_ffmpeg
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication

from recording import ScreenRecorder, list_microphone_devices


def run():
    if '--hardware' not in sys.argv:
        raise SystemExit('Use --hardware to test connected microphones and default system audio locally.')
    app = QApplication([])
    sources = [('microphone', name, device) for name, device in list_microphone_devices()]
    sources.append(('system', 'Default output', '__default__'))
    with tempfile.TemporaryDirectory(prefix='clearshot_audio_test_') as folder:
        for index, (mode, name, device) in enumerate(sources):
            path = str(Path(folder) / f'audio_{index}.mp4')
            rec = ScreenRecorder(QRect(0, 0, 64, 64), path, fps=10, audio_mode=mode,
                                 microphone_source=device, system_audio_device=device)
            finished, errors = [], []
            rec.recording_finished.connect(lambda *args: finished.append(args))
            rec.recording_failed.connect(errors.append)
            controls = []

            def schedule(_path):
                for delay, action in ((.6, rec.pause), (1.0, rec.resume), (1.7, rec.stop)):
                    timer = threading.Timer(delay, action)
                    controls.append(timer)
                    timer.start()

            rec.recording_started.connect(schedule)
            with patch('recording.mss.mss') as screen:
                screen.return_value.__enter__.return_value.grab.return_value = Mock(rgb=bytes(64 * 64 * 3))
                rec.start()
                deadline = time.monotonic() + 20
                while rec.isRunning() and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.01)
                rec.stop()
                assert rec.wait(15000), 'Recording worker did not finish'
            for timer in controls:
                timer.join()
            app.processEvents()
            assert not errors, (name, errors)
            assert finished, name
            reader = imageio_ffmpeg.read_frames(path)
            metadata = next(reader)
            frames = len(list(reader))
            assert frames == finished[0][2] and frames > 0
            assert metadata.get('audio_codec'), metadata
            assert 1.0 <= frames / 10 <= 1.6, frames
            assert not rec._audio_recorder.is_alive()
            print(f'PASS: {mode}, {name}, pause/resume, {frames} frames, {metadata["audio_codec"]}', flush=True)
        assert not list(Path(folder).glob('ClearShot_recovery_*'))
    print('PASS: all temporary test audio/video removed')


if __name__ == '__main__':
    run()
