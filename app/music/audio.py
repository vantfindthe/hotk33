"""System-audio capture (WASAPI loopback) and spectrum analysis."""

import threading
import time

import numpy as np
import pyaudiowpatch as pyaudio

FFT_SIZE = 2048
NUM_BANDS = 16
FMIN, FMAX = 40.0, 16000.0
# Music loses roughly 5 dB of energy per octave going up; add it back so the
# treble bands react as readily as the bass ones.
TILT_DB_PER_OCTAVE = 5.0


def band_edges():
    return np.geomspace(FMIN, FMAX, NUM_BANDS + 1)


def band_centers():
    edges = band_edges()
    return np.sqrt(edges[:-1] * edges[1:])


def list_devices():
    """Returns [(label, device_index)], default output's loopback first."""
    p = pyaudio.PyAudio()
    try:
        devices = []
        try:
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
        except OSError:
            wasapi, default_out = None, None
        loopbacks = list(p.get_loopback_device_info_generator())
        for d in loopbacks:
            label = d["name"].replace(" [Loopback]", "")
            if default_out and default_out["name"] in d["name"]:
                devices.insert(0, (f"Speakers: {label} (default)", d["index"]))
            else:
                devices.append((f"Speakers: {label}", d["index"]))
        if wasapi:
            for i in range(p.get_device_count()):
                d = p.get_device_info_by_index(i)
                if (d["hostApi"] == wasapi["index"] and d["maxInputChannels"] > 0
                        and not d.get("isLoopbackDevice")):
                    devices.append((f"Mic: {d['name']}", i))
        return devices
    finally:
        p.terminate()


class AudioCapture:
    """Keeps the most recent FFT_SIZE samples (per channel) in a ring buffer."""

    def __init__(self):
        self._pa = None
        self._stream = None
        self._lock = threading.Lock()
        self._buf = np.zeros((FFT_SIZE, 2), dtype=np.float32)
        self._last_data = 0.0
        self.rate = 48000

    def start(self, device_index):
        self.stop()
        self._pa = pyaudio.PyAudio()
        info = self._pa.get_device_info_by_index(device_index)
        self.rate = int(info["defaultSampleRate"])
        self._channels = max(1, min(2, int(info["maxInputChannels"])))
        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=self._channels,
            rate=self.rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=512,
            stream_callback=self._callback,
        )

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except OSError:
                pass
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

    def _callback(self, in_data, frame_count, time_info, status):
        data = np.frombuffer(in_data, dtype=np.float32).reshape(-1, self._channels)
        if self._channels == 1:
            data = np.repeat(data, 2, axis=1)
        data = data[-FFT_SIZE:]
        with self._lock:
            self._buf = np.roll(self._buf, -len(data), axis=0)
            self._buf[-len(data):] = data
        self._last_data = time.monotonic()
        return (None, pyaudio.paContinue)

    def snapshot(self):
        """Latest samples, shape (FFT_SIZE, 2). Zeros if nothing is playing
        (WASAPI loopback simply stops delivering data during silence)."""
        if time.monotonic() - self._last_data > 0.25:
            return np.zeros((FFT_SIZE, 2), dtype=np.float32)
        with self._lock:
            return self._buf.copy()


class Analyzer:
    """Turns raw samples into smoothed, auto-gained band levels (0..1),
    per-channel volume and beat events."""

    def __init__(self):
        self.num_bands = NUM_BANDS
        self._window = np.hanning(FFT_SIZE).astype(np.float32)
        self._edges_rate = None
        self.bands = np.zeros(NUM_BANDS)
        self.vu = np.zeros(2)
        self.bass = 0.0
        self.beat = False
        self.silent = True
        self._peak_db = -30.0
        self._bass_avg = 0.0
        self._last_beat = 0.0

        # Tunables (set from the UI)
        self.sensitivity = 0.5  # 0..1
        self.smoothing = 0.5    # 0..1
        self.eq_db = np.zeros(NUM_BANDS)  # per-band sensitivity offsets

        centers = band_centers()
        self._tilt_db = TILT_DB_PER_OCTAVE * np.log2(centers / centers[0])

    def _band_bins(self, rate):
        if self._edges_rate != rate:
            freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / rate)
            edges = band_edges()
            bins = []
            for lo, hi in zip(edges[:-1], edges[1:]):
                idx = np.where((freqs >= lo) & (freqs < hi))[0]
                if len(idx) == 0:  # low bands narrower than one bin
                    idx = np.array([np.argmin(np.abs(freqs - (lo + hi) / 2))])
                bins.append(idx)
            self._bins = bins
            self._bass_bins = np.where((freqs >= 30) & (freqs < 150))[0]
            self._edges_rate = rate
        return self._bins

    def process(self, samples, rate):
        mono = samples.mean(axis=1)
        rms = np.sqrt(np.mean(samples ** 2, axis=0))
        self.silent = float(rms.max()) < 1e-4

        spectrum = np.abs(np.fft.rfft(mono * self._window)) / (FFT_SIZE / 4)
        bins = self._band_bins(rate)
        raw = np.array([np.sqrt(np.mean(spectrum[b] ** 2)) for b in bins])
        db = 20 * np.log10(raw + 1e-9) + self._tilt_db

        # Auto-gain: follow the loudest band, fall back slowly.
        loudest = float(db.max())
        if loudest > self._peak_db:
            self._peak_db = loudest
        else:
            self._peak_db = max(self._peak_db - 0.15, -45.0)

        # The EQ is applied after auto-gain, so boosting one band makes that
        # band more sensitive without dimming the others.
        dyn_range = 20 + 40 * self.sensitivity  # dB shown between dark and full
        level = np.clip((db + self.eq_db - (self._peak_db - dyn_range)) / dyn_range, 0, 1)
        level = level ** 1.6  # expand, so quiet bands stay dark
        if self.silent:
            level[:] = 0

        decay = 0.55 + 0.4 * self.smoothing  # per-frame multiplier while falling
        self.bands = np.where(level > self.bands,
                              self.bands + (level - self.bands) * 0.7,
                              np.maximum(level, self.bands * decay))

        vu = np.clip((20 * np.log10(rms + 1e-9) + 40 + 25 * self.sensitivity) / 40, 0, 1)
        self.vu = np.where(vu > self.vu, vu, np.maximum(vu, self.vu * decay))

        # Beat: bass energy jumps well above its recent average.
        bass = float(np.mean(spectrum[self._bass_bins] ** 2)) if len(self._bass_bins) else 0.0
        now = time.monotonic()
        self.beat = (bass > self._bass_avg * 1.6 and bass > 1e-6
                     and now - self._last_beat > 0.18 and not self.silent)
        if self.beat:
            self._last_beat = now
        self._bass_avg = self._bass_avg * 0.95 + bass * 0.05
        self.bass = float(np.mean(self.bands[:3]))
