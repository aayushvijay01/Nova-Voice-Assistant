"""
assistant/listener.py
=====================
Microphone audio capture with voice activity detection (VAD) for Nova.

Captures audio from the default (or configured) microphone using PyAudio,
performs simple energy-based voice activity detection, and emits complete
utterances (as raw audio frames) to a thread-safe queue consumed by the
recogniser.

Design
------
- Runs in its own daemon thread for zero main-thread blocking.
- Exposes a ``frames_queue`` for the SpeechRecognizer to read.
- Emits ``audio_level`` callbacks (RMS) for the GUI level meter.
- Supports push-to-talk mode (bypass VAD, hold button to record).
"""

from __future__ import annotations

import array
import math
import queue
import threading
import time
from typing import Callable, List, Optional

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


def _rms(frames: bytes) -> float:
    """Compute root-mean-square amplitude of a raw PCM buffer."""
    shorts = array.array("h", frames)
    if not shorts:
        return 0.0
    sq_sum = sum(s * s for s in shorts)
    return math.sqrt(sq_sum / len(shorts))


class AudioListener:
    """
    Continuous microphone capture with energy-based voice activity detection.

    Parameters
    ----------
    frames_queue:       Queue to push completed utterance audio (list[bytes]).
    on_audio_level:     Callback receiving RMS float on each chunk (for GUI meter).
    on_wake_detected:   Callback invoked when VAD detects speech start.
    """

    def __init__(
        self,
        frames_queue: queue.Queue,
        on_audio_level: Optional[Callable[[float], None]] = None,
        on_speech_start: Optional[Callable[[], None]] = None,
        on_speech_end: Optional[Callable[[], None]] = None,
    ) -> None:
        if not PYAUDIO_AVAILABLE:
            raise RuntimeError(
                "PyAudio is not installed. On Windows run: pip install pyaudio"
            )

        self._frames_queue = frames_queue
        self._on_audio_level = on_audio_level
        self._on_speech_start = on_speech_start
        self._on_speech_end = on_speech_end

        self._running = threading.Event()
        self._paused = threading.Event()
        self._push_to_talk = threading.Event()  # set = actively recording via PTT

        self._thread: Optional[threading.Thread] = None
        self._pyaudio: Optional["pyaudio.PyAudio"] = None

        # Configuration shortcuts
        self._rate = settings.audio_sample_rate
        self._chunk = settings.audio_chunk_size
        self._channels = settings.audio_channels
        self._device_index = settings.audio_device_index
        self._silence_thresh = settings.silence_threshold
        self._silence_dur = settings.silence_duration
        self._max_seconds = settings.max_record_seconds

    # ------------------------------------------------------------------
    # Public controls
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background capture thread."""
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="AudioListener",
            daemon=True,
        )
        self._thread.start()
        logger.info("AudioListener started (rate=%d, chunk=%d)", self._rate, self._chunk)

    def stop(self) -> None:
        """Stop capture and clean up PyAudio resources."""
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=5)
        if self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None
        logger.info("AudioListener stopped")

    def pause(self) -> None:
        """Pause capture (e.g. while TTS is speaking to avoid feedback)."""
        self._paused.set()

    def resume(self) -> None:
        """Resume capture after a pause."""
        self._paused.clear()

    def push_to_talk_start(self) -> None:
        """Begin push-to-talk recording (bypasses VAD)."""
        self._push_to_talk.set()

    def push_to_talk_stop(self) -> None:
        """End push-to-talk recording and flush buffered audio."""
        self._push_to_talk.clear()

    def get_input_devices(self) -> list[dict]:
        """Return a list of available microphone devices."""
        pa = pyaudio.PyAudio()
        devices = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                devices.append({"index": i, "name": info["name"]})
        pa.terminate()
        return devices

    # ------------------------------------------------------------------
    # Internal capture loop
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        """Main audio capture loop — runs in dedicated thread."""
        try:
            self._pyaudio = pyaudio.PyAudio()
            stream = self._pyaudio.open(
                format=pyaudio.paInt16,
                channels=self._channels,
                rate=self._rate,
                input=True,
                input_device_index=self._device_index,
                frames_per_buffer=self._chunk,
            )
        except Exception as exc:
            logger.error("Failed to open audio stream: %s", exc)
            return

        recording = False
        frames: List[bytes] = []
        silent_chunks = 0
        max_chunks = int(self._rate / self._chunk * self._max_seconds)
        silence_chunks_needed = int(self._rate / self._chunk * self._silence_dur)

        logger.debug("Audio capture loop running")

        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                continue

            try:
                data = stream.read(self._chunk, exception_on_overflow=False)
            except Exception as exc:
                logger.warning("Audio read error: %s", exc)
                time.sleep(0.1)
                continue

            rms = _rms(data)

            if self._on_audio_level:
                try:
                    self._on_audio_level(rms)
                except Exception:
                    pass

            # Push-to-talk mode: record while button held
            if self._push_to_talk.is_set():
                frames.append(data)
                continue
            elif frames and not self._push_to_talk.is_set() and not recording:
                # PTT was just released — flush
                if frames:
                    self._frames_queue.put(list(frames))
                    frames.clear()
                continue

            # VAD mode
            is_speech = rms > self._silence_thresh

            if not recording:
                if is_speech:
                    recording = True
                    silent_chunks = 0
                    frames = [data]
                    if self._on_speech_start:
                        try:
                            self._on_speech_start()
                        except Exception:
                            pass
            else:
                frames.append(data)
                if is_speech:
                    silent_chunks = 0
                else:
                    silent_chunks += 1

                # Check for end-of-speech or max length
                if silent_chunks >= silence_chunks_needed or len(frames) >= max_chunks:
                    recording = False
                    if len(frames) > silence_chunks_needed:
                        self._frames_queue.put(list(frames))
                        if self._on_speech_end:
                            try:
                                self._on_speech_end()
                            except Exception:
                                pass
                    frames = []
                    silent_chunks = 0

        stream.stop_stream()
        stream.close()
        logger.debug("Audio capture loop ended")
