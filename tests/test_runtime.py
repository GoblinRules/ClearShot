"""Regression checks for worker shutdown and packaged runtime behavior."""

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import uuid

from PyQt6.QtCore import QThread, QTimer, QRect, QPointF
from PyQt6.QtWidgets import QApplication
import imageio_ffmpeg

from app import ClearShotApp, HotkeyThread
from recording import ScreenRecorder, RecordingAnnotationStore, AUDIO_MODE_MICROPHONE
from tools import ArrowItem
import main

QT_APP = QApplication.instance() or QApplication([])


class WaitingWorker(QThread):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.entered = threading.Event()

    def run(self):
        self.entered.set()
        self.release.wait(10)

    def stop(self):
        pass


class RuntimeTests(unittest.TestCase):
    def test_quit_retains_running_worker_and_keeps_ui_responsive(self):
        worker = WaitingWorker()
        worker.start()
        self.assertTrue(worker.entered.wait(2))
        tray = ClearShotApp.__new__(ClearShotApp)
        tray._quitting = False
        tray._quit_timer = QTimer()
        tray._hotkey_thread = Mock(isRunning=lambda: False)
        tray._recorder = worker
        tray._retired_recorders = []
        tray._tray = Mock()
        tray._set_recording_indicator = Mock()
        for name in ('_overlay', '_annotator', '_settings_window', '_record_region_overlay',
                     '_record_annotation_overlay', '_record_annotation_store', '_record_border_overlay'):
            setattr(tray, name, None)
        try:
            started = time.monotonic()
            tray._quit()
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertIs(tray._recorder, worker)
            self.assertTrue(worker.isRunning())
            tray._quit()
            self.assertIs(tray._recorder, worker)
        finally:
            worker.release.set()
            self.assertTrue(worker.wait(2000))
            with patch.object(QApplication, 'quit') as quit_app:
                tray._finish_quit_when_ready()
                quit_app.assert_called_once()
            self.assertIsNone(tray._recorder)

    def test_hotkey_worker_can_stop_before_start(self):
        worker = HotkeyThread(Mock())
        worker.stop()
        worker.start()
        self.assertTrue(worker.wait(2000))

    def test_low_disk_reports_failure_without_starting_encoder(self):
        recorder = ScreenRecorder(QRect(0, 0, 64, 64), 'test.mp4')
        failures, starts = [], []
        recorder.recording_failed.connect(failures.append)
        recorder.recording_started.connect(starts.append)
        with patch('recording.shutil.disk_usage', return_value=Mock(free=0)), \
                patch.object(recorder, '_run_silent') as encode, \
                self.assertLogs(level='ERROR'):
            recorder.run()
        self.assertFalse(starts)
        self.assertIn('256 MB', failures[0])
        self.assertTrue(recorder.is_stopping)
        encode.assert_not_called()

    def test_repeated_recordings_with_annotations_encode_and_decode(self):
        with tempfile.TemporaryDirectory(prefix='clearshot_test_') as folder:
            annotations = RecordingAnnotationStore()
            arrow = ArrowItem()
            arrow.start, arrow.end = QPointF(5, 5), QPointF(55, 55)
            annotations.set_items([arrow])
            for index in range(3):
                path = str(Path(folder) / f'recording_{index}.mp4')
                recorder = ScreenRecorder(QRect(0, 0, 64, 64), path, annotation_store=annotations)
                done, errors, finalizing = [], [], []
                recorder.recording_finished.connect(lambda *result: done.append(result))
                recorder.recording_failed.connect(errors.append)
                recorder.recording_finalizing.connect(finalizing.append)

                def feed_frames(send):
                    for _ in range(12):
                        send(recorder._compose_annotation_frame(bytes(64 * 64 * 3)))
                    recorder.stop()
                    return 12

                with patch.object(recorder, '_capture_loop', side_effect=feed_frames):
                    recorder.start()
                    self.assertTrue(recorder.wait(15000))
                QT_APP.processEvents()
                self.assertFalse(errors, errors)
                self.assertEqual(done[0][2], 12)
                self.assertIn('Finalizing video file...', finalizing)
                reader = imageio_ffmpeg.read_frames(path)
                self.assertEqual(next(reader)['size'], (64, 64))
                frames = list(reader)
                self.assertEqual(len(frames), 12)
                self.assertGreater(max(frames[0]), 100)

    def test_capture_exception_reaps_encoder(self):
        with tempfile.TemporaryDirectory(prefix='clearshot_test_') as folder:
            recorder = ScreenRecorder(QRect(0, 0, 64, 64), str(Path(folder) / 'failed.mp4'),
                                      audio_mode=AUDIO_MODE_MICROPHONE,
                                      microphone_source='__ClearShot_missing_test_device__')
            real_popen = subprocess.Popen
            children = []

            def spawn(*args, **kwargs):
                child = real_popen(*args, **kwargs)
                children.append(child)
                return child

            with patch('recording_backend.subprocess.Popen', side_effect=spawn), \
                    patch.object(recorder, '_capture_loop', side_effect=RuntimeError('capture failed')):
                with self.assertRaisesRegex(RuntimeError, 'capture failed'):
                    recorder._run_silent(str(Path(folder) / 'video.mkv'))
            self.assertTrue(children)
            self.assertTrue(all(child.poll() is not None for child in children))
            self.assertTrue(all(child.stdin is None or child.stdin.closed for child in children))

    def test_duplicate_process_sees_mutex(self):
        name = 'ClearShot_Test_' + uuid.uuid4().hex
        with patch.object(main, 'MUTEX_NAME', name), patch.object(main, '_mutex_handle', None):
            self.assertFalse(main.is_already_running())
            try:
                result = subprocess.run(
                    [os.sys.executable, '-c',
                     f'import main; main.MUTEX_NAME={name!r}; print(main.is_already_running())'],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'True')
            finally:
                main._kernel32().CloseHandle(main._mutex_handle)


if __name__ == '__main__':
    unittest.main()
