"""
config/settings.py
==================
Centralized, type-safe application configuration for Nova Voice Assistant.

All values are read from environment variables (via .env file) and validated
by Pydantic. Sensitive values like API keys must never be hard-coded here.

Usage:
    from config.settings import settings
    print(settings.openai_api_key)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class NovaSettings(BaseSettings):
    """
    Application-wide settings for Nova Voice Assistant.

    All fields can be overridden via environment variables or a .env file
    located at the project root. Pydantic coerces and validates every value.
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application Meta
    # ------------------------------------------------------------------
    app_name: str = Field(default="Nova Voice Assistant", description="Display name")
    app_version: str = Field(default="1.0.0", description="Semantic version")
    debug: bool = Field(default=False, description="Enable verbose debug output")

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    project_root: Path = Field(default=_PROJECT_ROOT)
    data_dir: Path = Field(default=_PROJECT_ROOT / "data")
    log_dir: Path = Field(default=_PROJECT_ROOT / "logs")
    database_path: Path = Field(default=_PROJECT_ROOT / "data" / "nova.db")
    log_file: Path = Field(default=_PROJECT_ROOT / "logs" / "nova.log")

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------
    openai_api_key: Optional[str] = Field(
        default=None,
        description="OpenAI API key (sk-...)",
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI chat completion model",
    )
    openai_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    openai_max_tokens: int = Field(default=512, ge=1, le=4096)
    openai_timeout: int = Field(default=30, description="HTTP timeout in seconds")

    # ------------------------------------------------------------------
    # Wake Word
    # ------------------------------------------------------------------
    wake_word: str = Field(default="nova", description="Trigger keyword (lowercase)")
    wake_word_enabled: bool = Field(default=True)
    wake_word_sensitivity: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Detection threshold (0=strict, 1=loose)",
    )

    # ------------------------------------------------------------------
    # Audio / Microphone
    # ------------------------------------------------------------------
    audio_sample_rate: int = Field(default=16000, description="Samples per second")
    audio_chunk_size: int = Field(default=1024, description="Frames per buffer")
    audio_channels: int = Field(default=1)
    audio_device_index: Optional[int] = Field(
        default=None, description="PyAudio device index; None = system default",
    )
    silence_threshold: int = Field(
        default=500,
        description="RMS amplitude below which audio is considered silence",
    )
    silence_duration: float = Field(
        default=1.5, description="Seconds of silence that signals end of utterance",
    )
    max_record_seconds: int = Field(
        default=15, description="Hard cap on single recording length",
    )

    # ------------------------------------------------------------------
    # Speech Recognition
    # ------------------------------------------------------------------
    whisper_model_size: Literal["tiny", "base", "small", "medium", "large"] = Field(
        default="base",
        description="Faster-Whisper model size (speed vs accuracy tradeoff)",
    )
    whisper_language: str = Field(default="en", description="ISO 639-1 language code")
    whisper_device: Literal["cpu", "cuda", "auto"] = Field(default="auto")
    sr_fallback_enabled: bool = Field(
        default=True, description="Fall back to SpeechRecognition if Whisper fails",
    )

    # ------------------------------------------------------------------
    # Text-to-Speech
    # ------------------------------------------------------------------
    tts_rate: int = Field(
        default=175, ge=50, le=400, description="Words per minute",
    )
    tts_volume: float = Field(default=0.9, ge=0.0, le=1.0)
    tts_voice_index: int = Field(
        default=0, description="pyttsx3 voice index (0=first system voice)",
    )
    tts_queue_maxsize: int = Field(default=20)

    # ------------------------------------------------------------------
    # External APIs
    # ------------------------------------------------------------------
    openweather_api_key: Optional[str] = Field(
        default=None, description="OpenWeatherMap API key",
    )
    openweather_base_url: str = Field(
        default="https://api.openweathermap.org/data/2.5",
    )
    news_api_key: Optional[str] = Field(
        default=None, description="NewsAPI.org key",
    )
    news_api_base_url: str = Field(default="https://newsapi.org/v2")
    default_city: str = Field(default="New York", description="Default city for weather")

    # ------------------------------------------------------------------
    # GUI
    # ------------------------------------------------------------------
    gui_theme: Literal["dark", "light", "system"] = Field(default="dark")
    gui_color_theme: str = Field(default="blue")
    gui_width: int = Field(default=1100)
    gui_height: int = Field(default=720)
    gui_min_width: int = Field(default=900)
    gui_min_height: int = Field(default=600)

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    db_conversation_history_limit: int = Field(
        default=50, description="Max rows returned for conversation history",
    )
    db_command_history_limit: int = Field(default=100)

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------
    default_user_name: str = Field(default="User")
    system_tray_enabled: bool = Field(default=True)
    hotkey_activation: str = Field(
        default="ctrl+shift+n", description="Global hotkey for push-to-talk",
    )
    auto_start: bool = Field(default=False)

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("data_dir", "log_dir", mode="after")
    @classmethod
    def _ensure_dir(cls, v: Path) -> Path:
        """Automatically create required directories on startup."""
        v.mkdir(parents=True, exist_ok=True)
        return v

    @field_validator("wake_word", mode="after")
    @classmethod
    def _lowercase_wake_word(cls, v: str) -> str:
        return v.strip().lower()

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    @property
    def openai_available(self) -> bool:
        """True if an OpenAI API key is configured."""
        return bool(self.openai_api_key)

    @property
    def weather_available(self) -> bool:
        return bool(self.openweather_api_key)

    @property
    def news_available(self) -> bool:
        return bool(self.news_api_key)


# ---------------------------------------------------------------------------
# Singleton — import this everywhere
# ---------------------------------------------------------------------------
settings = NovaSettings()

# Ensure critical directories exist at import time
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.log_dir.mkdir(parents=True, exist_ok=True)
