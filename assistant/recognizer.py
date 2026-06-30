"""
assistant/recognizer.py
=======================
Speech-to-Text engine for Nova Voice Assistant.

Primary:  Faster-Whisper (high accuracy, local, offline)
Fallback: SpeechRecognition + Google Speech-to-Text (requires internet)

The recogniser accepts raw audio frames (bytes list) from the AudioListener
queue and returns a transcribed string.

Usage
-----
    from assistant.recognizer import SpeechRecognizer
    sr = SpeechRecognizer()
    text = sr.transcribe(frames, sample_rate=16000)
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import List, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Try to import Faster-Whisper
try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("faster-whisper not available — will use SpeechRecognition fallback")

# Try to import SpeechRecognition
try:
    import speech_recognition as sr_lib
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False
    logger.warning("SpeechRecognition not available")


class SpeechRecognizer:
    """
    Dual-engine speech recogniser.

    Attempts Faster-Whisper first; falls back to Google STT via
    SpeechRecognition if Whisper is unavailable or raises an error.

    Parameters
    ----------
    model_size:     Whisper model size ('tiny', 'base', 'small', 'medium', 'large').
    language:       ISO 639-1 language code (e.g. 'en').
    device:         'cpu', 'cuda', or 'auto'.
    use_fallback:   Allow SpeechRecognition as fallback.
    """

    def __init__(
        self,
        model_size: str = settings.whisper_model_size,
        language: str = settings.whisper_language,
        device: str = settings.whisper_device,
        use_fallback: bool = settings.sr_fallback_enabled,
    ) -> None:
        self._language = language
        self._use_fallback = use_fallback
        self._whisper_model: Optional["WhisperModel"] = None
        self._sr_recognizer: Optional["sr_lib.Recognizer"] = None

        # Resolve compute device
        compute_device = self._resolve_device(device)

        if WHISPER_AVAILABLE:
            try:
                logger.info(
                    "Loading Whisper model '%s' on device '%s'…",
                    model_size, compute_device,
                )
                self._whisper_model = WhisperModel(
                    model_size,
                    device=compute_device,
                    compute_type="int8" if compute_device == "cpu" else "float16",
                )
                logger.info("Whisper model loaded successfully")
            except Exception as exc:
                logger.error("Failed to load Whisper model: %s", exc)
                self._whisper_model = None

        if self._whisper_model is None and use_fallback and SR_AVAILABLE:
            self._sr_recognizer = sr_lib.Recognizer()
            self._sr_recognizer.energy_threshold = 300
            self._sr_recognizer.dynamic_energy_threshold = True
            logger.info("SpeechRecognition fallback initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transcribe(
        self,
        frames: List[bytes],
        sample_rate: int = settings.audio_sample_rate,
        channels: int = settings.audio_channels,
    ) -> Optional[str]:
        """
        Convert raw audio frames to text.

        Parameters
        ----------
        frames:         List of raw PCM byte chunks from PyAudio.
        sample_rate:    Audio sample rate in Hz.
        channels:       Number of audio channels (1=mono).

        Returns
        -------
        Transcribed text string, or None if recognition failed.
        """
        if not frames:
            return None

        audio_bytes = b"".join(frames)

        if self._whisper_model:
            return self._transcribe_whisper(audio_bytes, sample_rate, channels)
        elif self._sr_recognizer:
            return self._transcribe_sr(audio_bytes, sample_rate, channels)
        else:
            logger.error("No STT engine available")
            return None

    @property
    def engine_name(self) -> str:
        """Return the name of the active recognition engine."""
        if self._whisper_model:
            return "Faster-Whisper"
        if self._sr_recognizer:
            return "SpeechRecognition (Google)"
        return "None"

    # ------------------------------------------------------------------
    # Whisper transcription
    # ------------------------------------------------------------------

    def _transcribe_whisper(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        channels: int,
    ) -> Optional[str]:
        """Transcribe using Faster-Whisper."""
        wav_bytes = self._to_wav(audio_bytes, sample_rate, channels)
        audio_buffer = io.BytesIO(wav_bytes)
        try:
            segments, info = self._whisper_model.transcribe(
                audio_buffer,
                language=self._language,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            text = " ".join(seg.text for seg in segments).strip()
            logger.debug("Whisper transcription: %r (lang=%s)", text[:80], info.language)
            return text if text else None
        except Exception as exc:
            logger.error("Whisper transcription error: %s", exc)
            if self._sr_recognizer:
                logger.info("Falling back to SpeechRecognition")
                return self._transcribe_sr(audio_bytes, sample_rate, channels)
            return None

    # ------------------------------------------------------------------
    # SpeechRecognition fallback
    # ------------------------------------------------------------------

    def _transcribe_sr(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        channels: int,
    ) -> Optional[str]:
        """Transcribe using SpeechRecognition + Google STT."""
        wav_bytes = self._to_wav(audio_bytes, sample_rate, channels)
        audio_data = sr_lib.AudioData(wav_bytes, sample_rate, 2)
        try:
            text = self._sr_recognizer.recognize_google(audio_data)
            logger.debug("SR transcription: %r", text[:80])
            return text.strip() if text else None
        except sr_lib.UnknownValueError:
            logger.debug("SpeechRecognition: could not understand audio")
            return None
        except sr_lib.RequestError as exc:
            logger.error("SpeechRecognition API error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_wav(pcm_bytes: bytes, sample_rate: int, channels: int) -> bytes:
        """Wrap raw PCM bytes in a WAV container in memory."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)          # 16-bit PCM
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()

    @staticmethod
    def _resolve_device(device: str) -> str:
        """Resolve 'auto' to 'cuda' if torch/CUDA is available, else 'cpu'."""
        if device != "auto":
            return device
        try:
            import torch  # noqa: F401
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
