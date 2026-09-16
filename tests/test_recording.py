"""Recording failure, synchronization and settings regression tests."""

import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import wave

import imageio_ffmpeg
import numpy as np
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication

import config
from recording import ScreenRecorder, resolve_microphone
from recording_backend import AudioRecorder, EncoderProcess, RecordingClock
from settings_window import SettingsWindow

QT_APP = QApplication.instance() or QApplication([])


class MemoryConfig:
    def __init__(self, folder, **values):
        self.values = copy.deepcopy(config.DEFAULT_SETTINGS)
        self.values.update(save_path=folder, recording_save_path=folder, **values)
        self.writes = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_hotkey(self, key):
        return self.values['hotkeys'][key]

    def set(self, key, value):
        self.writes.append((key, value))
        self.values[key] = value

    def set_hotkey(self, key, value):
        self.writes.append((key, value))
        self.values['hotkeys'][key] = value


class SyntheticDevice:
    def __init__(self):
        self.opens = 0
        self.closed = 0
        self.value = 0.2

    def recorder(self, **kwargs):
        self.opens += 1
        self.kwargs = kwargs
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed += 1

    def record(self, numframes=None):
        value = self.value
        time.sleep(0.01)
        return np.full((480, 2), value, dtype=np.float32)


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not predicate():
        raise AssertionError('Timed out waiting for test condition')


class RecordingTests(unittest.TestCase):
    def test_audio_watchdog_ignores_time_spent_finalizing(self):
        rec = ScreenRecorder(QRect(0, 0, 16, 16), 'finalizing.mp4')
        rec._audio_recorder = Mock(error='', last_activity=time.monotonic() - 90)
        with self.assertRaisesRegex(RuntimeError, 'stopped responding'):
            rec._check_audio()
        rec.stop()
        rec._check_audio()
        rec._audio_recorder.error = 'Device disconnected'
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            rec._check_audio()

    def test_clock_excludes_pause_and_freezes_at_stop(self):
        with patch('recording_backend.time.perf_counter') as now:
            clock = RecordingClock()
            now.return_value = 10
            clock.start()
            now.return_value = 12
            clock.pause()
            now.return_value = 20
            self.assertEqual(clock.snapshot()[0], 2)
            clock.resume()
            now.return_value = 23
            clock.stop()
            now.return_value = 30
            clock.resume()
            self.assertEqual(clock.snapshot()[0], 5)
            self.assertFalse(clock.snapshot()[1])

    def test_slow_screen_capture_keeps_wall_clock_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            rec = ScreenRecorder(QRect(0, 0, 16, 16), str(Path(folder) / 'slow.mp4'), fps=30)
            calls = 0

            def grab(region):
                nonlocal calls
                time.sleep(0.08)
                calls += 1
                if calls == 10:
                    rec.stop()
                return Mock(rgb=bytes(16 * 16 * 3))

            with patch('recording.mss.mss') as screen:
                screen.return_value.__enter__.return_value.grab.side_effect = grab
                count = rec._capture_loop(lambda frame: None)
            self.assertGreater(count, 20)
            self.assertLess(abs(count / 30 - rec.elapsed), 1 / 30 + .005)

    def test_stalled_encoder_write_is_bounded_and_reaped(self):
        encoder = EncoderProcess([sys.executable, '-c', 'import time; time.sleep(30)'],
                                 input_pipe=True, write_timeout=0.2)
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(RuntimeError, 'stopped responding'):
                encoder.write(bytes(1024 * 1024))
        finally:
            encoder.close()
        self.assertLess(time.monotonic() - started, 3)
        self.assertIsNotNone(encoder.process.poll())
        self.assertTrue(encoder.process.stdin.closed)

    def test_stalled_export_is_bounded_and_reaped(self):
        encoder = EncoderProcess([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                encoder.finish(timeout=0.1)
        finally:
            encoder.close()
        self.assertIsNotNone(encoder.process.poll())

    def test_export_progress_extends_timeout_for_long_recordings(self):
        script = 'import time\nfor i in range(8):\n print("out_time_us=" + str(i), flush=True)\n time.sleep(.08)'
        encoder = EncoderProcess([sys.executable, '-c', script], progress=True)
        try:
            encoder.finish(timeout=.3)
        finally:
            encoder.close()
        self.assertEqual(encoder.process.returncode, 0)

    def test_repeated_export_status_is_not_progress(self):
        script = 'import time\nfor i in range(80):\n print("out_time_us=0", flush=True)\n time.sleep(.02)'
        encoder = EncoderProcess([sys.executable, '-c', script], progress=True)
        try:
            with self.assertRaisesRegex(RuntimeError, 'stopped making progress'):
                encoder.finish(timeout=.3)
        finally:
            encoder.close()

    @staticmethod
    def _feed(recorder, send):
        for _ in range(10):
            send(bytes(16 * 16 * 3))
        recorder.stop()
        return 10

    def test_encoder_error_never_reports_success(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'bad.mp4')
            rec = ScreenRecorder(QRect(0, 0, 16, 16), path)
            done, failed = [], []
            rec.recording_finished.connect(lambda *args: done.append(args))
            rec.recording_failed.connect(failed.append)

            def broken_encoder(command, **kwargs):
                command[command.index('libx264')] = '__missing_encoder__'
                return EncoderProcess(command, **kwargs)

            with patch('recording.EncoderProcess', side_effect=broken_encoder), \
                    patch.object(rec, '_capture_loop', side_effect=lambda send: self._feed(rec, send)), \
                    self.assertLogs(level='ERROR'):
                rec.run()
            self.assertFalse(done)
            self.assertIn('encoder', failed[0].lower())
            self.assertFalse(Path(path).exists())

    def test_failed_export_retains_playable_video_and_reports_location(self):
        with tempfile.TemporaryDirectory() as folder:
            rec = ScreenRecorder(QRect(0, 0, 16, 16), str(Path(folder) / 'failed.mp4'))
            failed = []
            rec.recording_failed.connect(failed.append)
            with patch.object(rec, '_capture_loop', side_effect=lambda send: self._feed(rec, send)), \
                    patch.object(rec, '_export', side_effect=RuntimeError('export failed')), \
                    self.assertLogs(level='ERROR'):
                rec.run()
            recovery = Path(rec._recovery_dir)
            self.assertIn(str(recovery), failed[0])
            reader = imageio_ffmpeg.read_frames(str(recovery / 'video.mkv'))
            next(reader)
            self.assertEqual(len(list(reader)), 10)
            self.assertFalse(Path(rec.output_path).exists())

    def test_pause_discards_audio_and_reopens_device(self):
        with tempfile.TemporaryDirectory() as folder:
            clock = RecordingClock()
            stop = threading.Event()
            device = SyntheticDevice()
            path = str(Path(folder) / 'audio.wav')
            audio = AudioRecorder(path, lambda: device, clock, stop)
            audio.start()
            try:
                self.assertTrue(audio.ready.wait(2))
                clock.start()
                wait_for(lambda: audio.frames > 3000)
                clock.pause()
                time.sleep(.05)
                before = audio.frames
                opens = device.opens
                device.value = .9
                time.sleep(.12)
                self.assertEqual(audio.frames, before)
                device.value = .3
                clock.resume()
                wait_for(lambda: audio.frames > before + 3000)
                self.assertGreater(device.opens, opens)
            finally:
                clock.stop()
                stop.set()
                audio.join(3)
            self.assertFalse(audio.is_alive())
            self.assertFalse(audio.error, audio.error)
            self.assertEqual(device.opens, device.closed)
            self.assertEqual(device.kwargs['channels'], 2)
            with wave.open(path, 'rb') as wav:
                pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
            self.assertLess(np.max(pcm), .5 * 32767)
            self.assertLess(abs(audio.frames / 48000 - clock.snapshot()[0]), .06)

    def test_audio_modes_formats_and_consecutive_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            for mode in ('microphone', 'system'):
                for extension in ('mp4', 'mkv'):
                    with self.subTest(mode=mode, extension=extension):
                        path = str(Path(folder) / f'{mode}.{extension}')
                        rec = ScreenRecorder(QRect(0, 0, 16, 16), path, fps=10, audio_mode=mode)
                        done, errors = [], []
                        rec.recording_finished.connect(lambda *result: done.append(result))
                        rec.recording_failed.connect(errors.append)
                        device = SyntheticDevice()
                        timer = threading.Timer(.65, rec.stop)
                        timer.start()
                        try:
                            with patch.object(rec, '_resolve_audio_device', return_value=device), \
                                    patch('recording.mss.mss') as screen:
                                screen.return_value.__enter__.return_value.grab.return_value = Mock(rgb=bytes(768))
                                rec.run()
                        finally:
                            rec.stop()
                            timer.join()
                        self.assertFalse(errors, errors)
                        self.assertTrue(done)
                        reader = imageio_ffmpeg.read_frames(path)
                        meta = next(reader)
                        self.assertEqual(len(list(reader)), done[0][2])
                        self.assertTrue(meta.get('audio_codec'), meta)
                        self.assertFalse(rec._audio_recorder.is_alive())
                        self.assertFalse(list(Path(folder).glob('ClearShot_recovery_*')))

    def test_audio_disconnect_retains_video_and_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'disconnect.mp4')
            rec = ScreenRecorder(QRect(0, 0, 16, 16), path, audio_mode='system')
            device = SyntheticDevice()
            real_record = device.record
            calls = 0

            def disconnect(**kwargs):
                nonlocal calls
                calls += 1
                if calls > 15:
                    raise RuntimeError('Device disconnected')
                return real_record(**kwargs)

            device.record = disconnect
            errors = []
            rec.recording_failed.connect(errors.append)
            with patch.object(rec, '_resolve_audio_device', return_value=device), \
                    patch('recording.mss.mss') as screen, self.assertLogs(level='ERROR'):
                screen.return_value.__enter__.return_value.grab.return_value = Mock(rgb=bytes(768))
                rec.run()
            self.assertIn('Device disconnected', errors[0])
            recovery = Path(rec._recovery_dir)
            self.assertGreater((recovery / 'audio.wav').stat().st_size, 44)
            reader = imageio_ffmpeg.read_frames(str(recovery / 'video.mkv'))
            next(reader)
            self.assertGreater(len(list(reader)), 0)


class SettingsTests(unittest.TestCase):
    def test_blank_and_unavailable_folders_do_not_break_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            for saved in ({'recording_save_path': '  ', 'save_path': ''},
                          {'recording_save_path': r'Z:\Disconnected\Recordings'}, []):
                path.write_text(json.dumps(saved), encoding='utf-8')
                with patch.object(config, 'APPDATA_DIR', folder), patch.object(config, 'CONFIG_FILE', str(path)):
                    loaded = config.Config()
                self.assertTrue(loaded.get('recording_save_path').strip())
                if isinstance(saved, dict) and saved.get('recording_save_path', '').startswith('Z:'):
                    self.assertEqual(loaded.get('recording_save_path'), saved['recording_save_path'])

    def test_invalid_folder_rejected(self):
        with self.assertRaisesRegex(ValueError, 'empty'):
            config.validate_save_directory('  ')
        with patch('config.tempfile.TemporaryFile', side_effect=PermissionError('denied')):
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(ValueError, 'not writable'):
                    config.validate_save_directory(folder)

    def test_microphone_legacy_name_and_stable_id_resolution(self):
        mic = Mock(id='mic-id')
        mic.name = 'USB microphone'
        with patch('soundcard.all_microphones', return_value=[mic]):
            self.assertIs(resolve_microphone('mic-id'), mic)
            self.assertIs(resolve_microphone('USB microphone'), mic)
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                resolve_microphone('Disconnected mic')

    def test_disconnected_microphone_disabled_and_refreshable(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = MemoryConfig(folder, recording_audio_mode='microphone',
                               recording_microphone_source='USB microphone')
            with patch('settings_window.list_microphone_devices', return_value=[]), \
                    patch('settings_window.list_system_audio_sources', return_value=[]):
                window = SettingsWindow(cfg)
            try:
                combo = window._recording_audio_source_combo
                self.assertIn('unavailable', combo.currentText())
                self.assertFalse(combo.model().item(combo.currentIndex()).isEnabled())
                with patch('settings_window.list_microphone_devices', return_value=[('USB microphone', 'mic-id')]), \
                        patch('settings_window.list_system_audio_sources', return_value=[]):
                    window._reload_audio_devices()
                self.assertEqual(combo.currentData(), 'mic-id')
                self.assertTrue(combo.model().item(combo.currentIndex()).isEnabled())
            finally:
                window.close()

    def test_settings_validation_happens_before_any_write(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = MemoryConfig(folder)
            with patch('settings_window.list_microphone_devices', return_value=[]), \
                    patch('settings_window.list_system_audio_sources', return_value=[]):
                window = SettingsWindow(cfg)
            try:
                window._recording_path_edit.setText('  ')
                with patch('settings_window.QMessageBox.warning') as warning:
                    window._save_and_close()
                warning.assert_called_once()
                self.assertFalse(cfg.writes)
                window._recording_path_edit.setText(folder)
                window._recording_audio_mode_combo.setCurrentIndex(1)
                with patch('settings_window.resolve_microphone', side_effect=RuntimeError('unavailable')), \
                        patch('settings_window.QMessageBox.warning') as warning:
                    window._save_and_close()
                warning.assert_called_once()
                self.assertFalse(cfg.writes)
            finally:
                window.close()


if __name__ == '__main__':
    unittest.main()
