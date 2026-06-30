"""
main.py
=======
Entry point for Nova Voice Assistant.

Bootstraps the application in this order:
1. Configure logging
2. Initialise the SQLite database
3. Create the VoicePipeline (listener → recogniser → intent → executor → TTS)
4. Start background threads (audio capture, reminder scheduler)
5. Launch the CustomTkinter GUI (blocks until window is closed)

Run with:
    python main.py

Or in text-only mode (no microphone):
    python main.py --no-voice
"""

from __future__ import annotations

import argparse
import queue
import signal
import sys
import threading
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Bootstrap config & logging FIRST — before any other module imports
# ---------------------------------------------------------------------------
from config.settings import settings
from utils.logger import configure_logging, get_logger

configure_logging(
    log_file=settings.log_file,
    console_level=10 if settings.debug else 20,   # DEBUG=10, INFO=20
)
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Now safe to import everything else
# ---------------------------------------------------------------------------
from database.storage import init_database, get_db
from assistant.tts import TTSEngine
from assistant.wakeword import WakeWordDetector
from assistant.recognizer import SpeechRecognizer
from assistant.intent_engine import IntentEngine
from assistant.executor import CommandExecutor
from assistant.response_generator import ResponseGenerator
from commands.timer import set_tts_callback as timer_set_tts
from commands.reminder import (
    ReminderScheduler,
    set_tts_callback as reminder_set_tts,
    set_db_getter as reminder_set_db,
)

try:
    from assistant.listener import AudioListener
    AUDIO_AVAILABLE = True
except RuntimeError:
    AUDIO_AVAILABLE = False
    logger.warning("PyAudio unavailable — running in text-only mode")


# ---------------------------------------------------------------------------
# VoicePipeline — orchestrates all assistant components
# ---------------------------------------------------------------------------

class VoicePipeline:
    """
    Central orchestrator that wires all assistant components together.

    Components
    ----------
    - listener          : AudioListener (microphone capture + VAD)
    - wake_detector     : WakeWordDetector
    - recognizer        : SpeechRecognizer (Whisper / SR)
    - intent_engine     : IntentEngine (OpenAI / regex)
    - executor          : CommandExecutor (command dispatch)
    - response_generator: ResponseGenerator (OpenAI / templates)
    - tts               : TTSEngine (pyttsx3)
    - db                : DatabaseManager
    - scheduler         : ReminderScheduler
    """

    def __init__(self, gui_callbacks: Optional[dict] = None) -> None:
        self._gui = gui_callbacks or {}
        self._frames_queue: queue.Queue = queue.Queue(maxsize=50)
        self._listening_for_command = threading.Event()
        self._shutdown_event = threading.Event()

        logger.info("Initialising VoicePipeline…")

        # Database
        self.db = get_db()

        # TTS engine
        self.tts = TTSEngine(
            on_start=self._on_tts_start,
            on_end=self._on_tts_end,
        )

        # STT / recognition
        self.recognizer = SpeechRecognizer()

        # Wake word
        self.wake_detector = WakeWordDetector(
            on_detected=self._on_wake_detected,
        )

        # Intent + execution
        self.intent_engine = IntentEngine()
        self.executor = CommandExecutor()

        # Response generator
        self.response_generator = ResponseGenerator()

        # Seed response generator with recent conversation context
        context = self.db.get_conversation_context(limit=10)
        self.response_generator.set_context_from_db(context)

        # Wire TTS callbacks into timer and reminder commands
        timer_set_tts(lambda text: self.tts.speak(text, priority=False))
        reminder_set_tts(lambda text: self.tts.speak(text, priority=False))
        reminder_set_db(get_db)

        # Audio listener (if PyAudio is available)
        self.listener: Optional[AudioListener] = None
        if AUDIO_AVAILABLE:
            self.listener = AudioListener(
                frames_queue=self._frames_queue,
                on_audio_level=self._on_audio_level,
                on_speech_start=self._on_speech_start,
                on_speech_end=self._on_speech_end,
            )

        # Reminder background scheduler
        self.scheduler = ReminderScheduler(
            db_getter=get_db,
            tts_callback=lambda text: self.tts.speak(text, priority=False),
        )

        logger.info("VoicePipeline initialised (engine=%s)", self.recognizer.engine_name)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start all background components."""
        if self.listener:
            self.listener.start()

        # Audio processing thread
        if AUDIO_AVAILABLE and self.listener:
            self._processing_thread = threading.Thread(
                target=self._processing_loop,
                name="AudioProcessor",
                daemon=True,
            )
            self._processing_thread.start()

        self.scheduler.start()

        # Welcome message
        self.tts.speak(
            f"Hello! I'm Nova, your AI voice assistant. Say 'Nova' to activate me, "
            f"or type your message below.",
        )
        self._notify_state("wake_ready")
        logger.info("VoicePipeline started")

    def shutdown(self) -> None:
        """Gracefully stop all components."""
        self._shutdown_event.set()

        if self.listener:
            self.listener.stop()

        self.scheduler.stop()
        self.tts.shutdown()

        from commands.timer import cancel_all_timers
        cancel_all_timers()

        logger.info("VoicePipeline shut down")

    # ------------------------------------------------------------------
    # Audio processing loop
    # ------------------------------------------------------------------

    def _processing_loop(self) -> None:
        """Background thread: transcribe audio → extract intent → execute → respond."""
        logger.debug("Processing loop started")
        while not self._shutdown_event.is_set():
            try:
                frames = self._frames_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            self._notify_state("processing")

            # Pause listener during processing to avoid feedback
            if self.listener:
                self.listener.pause()

            try:
                self._process_frames(frames)
            except Exception as exc:
                logger.error("Processing loop error: %s", exc, exc_info=True)
            finally:
                if self.listener:
                    self.listener.resume()
                self._frames_queue.task_done()

    def _process_frames(self, frames: list) -> None:
        """Process a batch of audio frames through the full pipeline."""
        # 1. Transcribe
        text = self.recognizer.transcribe(frames)
        if not text:
            self._notify_state("wake_ready")
            return

        logger.info("Transcribed: %r", text[:80])

        # 2. Check wake word (if waiting for it)
        if settings.wake_word_enabled and not self._listening_for_command.is_set():
            if self.wake_detector.is_wake_word(text):
                self._listening_for_command.set()
                self._notify_state("listening")
                self.tts.speak("Yes? How can I help?", priority=True)
                # Reset after 10 seconds of inactivity
                threading.Timer(10.0, self._reset_listening).start()
            return  # Wait for command after wake word

        # If wake word disabled or command mode active, process everything
        if settings.wake_word_enabled:
            # Strip the wake word prefix if present
            command_text = self.wake_detector.strip_wake_word(text)
            if not command_text:
                self._notify_state("wake_ready")
                return
        else:
            command_text = text

        self._process_command(command_text)

    def _reset_listening(self) -> None:
        """Reset to wake word waiting mode after inactivity."""
        if self._listening_for_command.is_set():
            self._listening_for_command.clear()
            self._notify_state("wake_ready")

    # ------------------------------------------------------------------
    # Text processing (used by GUI text input and voice)
    # ------------------------------------------------------------------

    def process_text(self, text: str) -> None:
        """
        Process a text command (from GUI input box).
        Runs on a background thread.
        """
        self._notify_state("processing")
        self._process_command(text)

    def _process_command(self, text: str) -> None:
        """
        Full pipeline: intent extraction → command execution → response generation.
        """
        self._gui.get("user_message", lambda t: None)(text)
        self.db.add_conversation(role="user", content=text)

        # 3. Extract intent
        context = self.db.get_conversation_context(limit=8)
        intent_result = self.intent_engine.extract(text, context=context)
        logger.info("Intent: %s | Entities: %s", intent_result.intent, intent_result.entities)

        # 4. Execute command
        command_result = self.executor.execute(intent_result)

        # 5. Generate natural response (or use command result directly)
        if intent_result.intent in (
            "get_weather", "get_news", "set_timer", "calculate",
            "set_reminder", "system_control", "open_application",
            "web_search", "get_time", "get_date", "stop_listening",
        ):
            # Use the structured command result directly
            response = command_result
        else:
            # Use OpenAI to generate a conversational response
            response_parts = []
            for chunk in self.response_generator.stream(
                text, context=context, intent=intent_result.intent,
            ):
                response_parts.append(chunk)
            response = "".join(response_parts).strip()

        if not response:
            response = "I'm not sure how to help with that."

        # 6. Persist & display
        self.db.add_conversation(role="assistant", content=response, intent=intent_result.intent)
        self.db.log_command(
            command=text,
            result=response,
            intent=intent_result.intent,
        )
        self.response_generator.add_to_history("user", text)
        self.response_generator.add_to_history("assistant", response)

        # 7. Notify GUI
        self._gui.get("assistant_message", lambda t: None)(response)

        # 8. Speak response
        self._notify_state("speaking")
        self.tts.speak(response)

        # Reset listening state
        self._listening_for_command.clear()
        self._notify_state("wake_ready" if settings.wake_word_enabled else "listening")

    # ------------------------------------------------------------------
    # Event callbacks
    # ------------------------------------------------------------------

    def _on_audio_level(self, rms: float) -> None:
        self._gui.get("audio_level", lambda v: None)(rms)

    def _on_speech_start(self) -> None:
        if not self._listening_for_command.is_set() and settings.wake_word_enabled:
            self._notify_state("wake_ready")
        else:
            self._notify_state("listening")

    def _on_speech_end(self) -> None:
        self._notify_state("processing")

    def _on_wake_detected(self, text: str) -> None:
        self._listening_for_command.set()
        self._notify_state("listening")

    def _on_tts_start(self, text: str) -> None:
        self._notify_state("speaking")
        # Pause mic while speaking to avoid feedback
        if self.listener:
            self.listener.pause()

    def _on_tts_end(self) -> None:
        # Resume mic after speaking
        if self.listener:
            self.listener.resume()
        self._notify_state("wake_ready" if settings.wake_word_enabled else "listening")

    def _notify_state(self, state: str) -> None:
        self._gui.get("state", lambda s: None)(state)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nova Voice Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  python main.py\n  python main.py --no-voice",
    )
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Run in text-only mode (no microphone required)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run headless (CLI mode — useful for testing)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose debug logging",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("  %s v%s", settings.app_name, settings.app_version)
    logger.info("  Starting up…")
    logger.info("=" * 60)

    # Initialise database
    db = init_database(settings.database_path)
    logger.info("Database initialised: %s", settings.database_path)

    # Suppress audio if --no-voice
    if args.no_voice:
        global AUDIO_AVAILABLE
        AUDIO_AVAILABLE = False
        logger.info("Voice input disabled (text-only mode)")

    if args.no_gui:
        # Headless / CLI mode for testing
        _run_cli_mode(db)
        return

    # Normal GUI mode
    _run_gui_mode(db)


def _run_gui_mode(db) -> None:
    """Launch the full GUI application."""
    # Import here to avoid circular issues
    from gui.app import NovaApp

    # Pre-create the app so we can wire callbacks before pipeline starts
    app = NovaApp(pipeline=None)

    # Create GUI callbacks
    gui_callbacks = {
        "audio_level":       app.notify_audio_level,
        "state":             app.notify_state,
        "user_message":      app.notify_user_message,
        "assistant_message": app.notify_assistant_message,
    }

    # Build pipeline with GUI wired in
    pipeline = VoicePipeline(gui_callbacks=gui_callbacks)
    app._pipeline = pipeline          # attach pipeline to app

    # Handle CTRL+C gracefully
    def _sigint_handler(sig, frame):
        logger.info("Received SIGINT — shutting down")
        app._on_close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint_handler)

    # Start pipeline background threads
    threading.Thread(target=pipeline.start, daemon=True).start()

    # Run GUI (blocks until window closes)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.shutdown()


def _run_cli_mode(db) -> None:
    """Simple REPL for headless testing."""
    print(f"\n{'=' * 50}")
    print(f"  Nova Voice Assistant — CLI Mode")
    print(f"{'=' * 50}")
    print("Type your command and press Enter. Type 'quit' to exit.\n")

    pipeline = VoicePipeline(gui_callbacks={
        "audio_level":       lambda v: None,
        "state":             lambda s: print(f"[{s.upper()}]"),
        "user_message":      lambda t: None,
        "assistant_message": lambda t: print(f"\n🤖 Nova: {t}\n"),
    })

    # Skip audio listener for CLI
    pipeline.scheduler.start()
    pipeline.tts.speak("Nova CLI mode ready.")

    try:
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "bye"):
                print("Goodbye!")
                break
            pipeline.process_text(user_input)
    finally:
        pipeline.shutdown()


if __name__ == "__main__":
    main()
