"""Bounded encoder processes and a shared, pause-aware recording timeline."""

from collections import deque
import math
import subprocess
import threading
import time
import wave


class RecordingClock:
    def __init__(self):
        self._lock = threading.RLock()
        self._elapsed = 0.0
        self._since = None
        self._paused = False
        self._stopped = False
        self._epoch = 0

    def start(self):
        with self._lock:
            if self._since is None and not self._paused and not self._stopped:
                self._since = time.perf_counter()

    def snapshot(self):
        with self._lock:
            elapsed = self._elapsed
            if self._since is not None:
                elapsed += time.perf_counter() - self._since
            return elapsed, self._since is not None, self._epoch

    def pause(self):
        with self._lock:
            if self._since is not None:
                self._elapsed += time.perf_counter() - self._since
                self._since = None
            self._paused = True
            self._epoch += 1

    def resume(self):
        with self._lock:
            self._paused = False
            self._epoch += 1
            self.start()

    def stop(self):
        with self._lock:
            self.pause()
            self._stopped = True


class EncoderProcess:
    """Drain diagnostics and interrupt stalled pipe writes by reaping the child."""

    def __init__(self, command, *, input_pipe=False, write_timeout=15.0, progress=False):
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE if input_pipe else subprocess.DEVNULL,
            stdout=subprocess.PIPE if progress else subprocess.DEVNULL,
            stderr=subprocess.PIPE, bufsize=0,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        self._errors = deque(maxlen=16)
        self._lock = threading.Lock()
        self._deadline = None
        self._write_timeout = write_timeout
        self._timed_out = False
        self._closed = threading.Event()
        self._progress_at = time.monotonic()
        self._progress_value = -1
        self._progress_reader = None
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._watchdog = threading.Thread(target=self._watch, daemon=True)
        self._reader.start()
        self._watchdog.start()
        if progress:
            self._progress_reader = threading.Thread(target=self._drain_progress, daemon=True)
            self._progress_reader.start()

    def _drain(self):
        while chunk := self.process.stderr.read(4096):
            self._errors.append(chunk)

    def _drain_progress(self):
        for line in self.process.stdout:
            key, _, value = line.partition(b'=')
            if key != b'out_time_us':
                continue
            try:
                position = int(value.strip())
            except ValueError:
                continue
            with self._lock:
                if position > self._progress_value:
                    self._progress_value = position
                    self._progress_at = time.monotonic()

    def _watch(self):
        while not self._closed.wait(0.05):
            with self._lock:
                if self._deadline is not None and time.monotonic() >= self._deadline:
                    self._timed_out = True
                    self._kill()
                    return

    def _kill(self):
        if self.process.poll() is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass

    def _error(self):
        if self._timed_out:
            return 'The video encoder stopped responding. The unfinished recording has been retained.'
        return b''.join(self._errors).decode('utf-8', errors='replace').strip() or 'The video encoder failed.'

    def write(self, data):
        with self._lock:
            self._deadline = time.monotonic() + self._write_timeout
        try:
            remaining = memoryview(data)
            while remaining:
                count = self.process.stdin.write(remaining)
                if not count:
                    raise BrokenPipeError('Encoder input closed')
                remaining = remaining[count:]
        except (OSError, ValueError) as exc:
            self._reader.join(timeout=0.2)
            raise RuntimeError(self._error()) from exc
        finally:
            with self._lock:
                self._deadline = None

    def finish(self, timeout=60.0):
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        started = time.monotonic()
        while True:
            try:
                code = self.process.wait(timeout=min(0.1, timeout))
                break
            except subprocess.TimeoutExpired as exc:
                with self._lock:
                    last_progress = max(started, self._progress_at) if self._progress_reader else started
                if time.monotonic() - last_progress >= timeout:
                    self._kill()
                    self.process.wait(timeout=5)
                    raise RuntimeError('The video encoder/export stopped making progress and timed out. The unfinished recording has been retained.') from exc
        self._reader.join(timeout=2)
        if code != 0 or self._timed_out:
            raise RuntimeError(self._error())

    def close(self):
        self._kill()
        self.process.wait(timeout=5)
        self._closed.set()
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        self._reader.join(timeout=2)
        self._watchdog.join(timeout=2)
        self.process.stderr.close()
        if self._progress_reader:
            self._progress_reader.join(timeout=2)
            self.process.stdout.close()


class AudioRecorder(threading.Thread):
    """Record microphone or loopback PCM, reopening the device after each pause."""

    def __init__(self, path, source_factory, clock, stop_event, sample_rate=48000):
        super().__init__(daemon=True)
        self.path = path
        self.source_factory = source_factory
        self.clock = clock
        self.stop_event = stop_event
        self.sample_rate = sample_rate
        self.frames = 0
        self.error = ''
        self.ready = threading.Event()
        self.last_activity = time.monotonic()

    def _pad_to(self, wav_file, target):
        while self.frames < target:
            count = min(4096, target - self.frames)
            wav_file.writeframesraw(bytes(count * 4))
            self.frames += count

    def run(self):
        try:
            import numpy as np

            source = self.source_factory()
            with wave.open(self.path, 'wb') as wav_file:
                wav_file.setnchannels(2)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                while not self.stop_event.is_set():
                    # WASAPI's single-channel mode is unreliable; request shared-mode
                    # stereo conversion, including for physical mono microphones.
                    with source.recorder(samplerate=self.sample_rate, channels=2,
                                         blocksize=2048) as recorder:
                        self.ready.set()
                        while not self.stop_event.is_set():
                            _, active, epoch = self.clock.snapshot()
                            if not active:
                                break
                            data = recorder.record(numframes=None)
                            elapsed, active, after_epoch = self.clock.snapshot()
                            self.last_activity = time.monotonic()
                            if not active or epoch != after_epoch:
                                break
                            if data is None or not len(data):
                                self.stop_event.wait(0.005)
                                continue
                            data = np.asarray(data).reshape(len(data), -1)
                            if data.shape[1] == 1:
                                data = np.repeat(data, 2, axis=1)
                            pcm = (np.clip(data[:, :2], -1, 1) * 32767).astype('<i2')
                            # Timestamp each block on the active timeline. Gaps from
                            # opening a device are silence, not accumulated A/V drift.
                            end = int(elapsed * self.sample_rate)
                            start = max(0, end - len(pcm))
                            self._pad_to(wav_file, start)
                            skip = max(0, self.frames - start)
                            pcm = pcm[skip:skip + max(0, end - self.frames)]
                            wav_file.writeframesraw(pcm.tobytes())
                            self.frames += len(pcm)
                    while not self.stop_event.is_set() and not self.clock.snapshot()[1]:
                        self.last_activity = time.monotonic()
                        self.stop_event.wait(0.02)
        except Exception as exc:
            self.error = str(exc) or 'Audio recording failed.'
        finally:
            self.ready.set()


def frames_for_duration(seconds, fps):
    return max(0, math.ceil(seconds * fps - 1e-7))
