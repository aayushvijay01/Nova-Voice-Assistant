"""
gui/app.py
==========
Main application window for Nova Voice Assistant.

Architecture
------------
- NovaApp(CTk) — top-level CustomTkinter window
- Left sidebar: navigation, status, mic level
- Right content area: switchable panels (Chat, Settings, Logs)
- Background assistant pipeline runs on daemon threads
- Thread → GUI communication uses tkinter's `after()` method (thread-safe)
- All voice I/O runs via VoicePipeline (orchestrator class)

Usage
-----
    from gui.app import NovaApp
    app = NovaApp(pipeline=pipeline)
    app.mainloop()
"""

from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import customtkinter as ctk
from tkinter import messagebox

from config.settings import settings
from gui.widgets import (
    COLOURS,
    AudioLevelBar,
    ConversationPanel,
    LogsPanel,
    SettingsPanel,
    SidebarButton,
    StatusIndicator,
)
from utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# GUI Log Handler — bridges Python logging → LogsPanel
# ---------------------------------------------------------------------------

class _GUILogHandler(logging.Handler):
    """Forwards log records to a LogsPanel widget via a thread-safe queue."""

    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._queue.put_nowait((record.levelname, msg))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# NovaApp
# ---------------------------------------------------------------------------

class NovaApp(ctk.CTk):
    """
    Main Nova Voice Assistant window.

    Parameters
    ----------
    pipeline:   VoicePipeline instance (optional; if None, text-only mode).
    """

    def __init__(self, pipeline: Optional[Any] = None) -> None:
        # CustomTkinter appearance
        ctk.set_appearance_mode(settings.gui_theme)
        ctk.set_default_color_theme(settings.gui_color_theme)

        super().__init__()
        self._pipeline = pipeline

        # Queues for thread → GUI communication
        self._ui_queue: queue.Queue = queue.Queue()
        self._log_queue: queue.Queue = queue.Queue()

        self._active_nav: str = "chat"

        # Build the window
        self._configure_window()
        self._build_layout()
        self._install_log_handler()

        # Start processing queues
        self._process_ui_queue()
        self._process_log_queue()

        logger.info("Nova GUI launched")

    # ------------------------------------------------------------------
    # Window configuration
    # ------------------------------------------------------------------

    def _configure_window(self) -> None:
        self.title(f"✦ {settings.app_name}")
        self.geometry(f"{settings.gui_width}x{settings.gui_height}")
        self.minsize(settings.gui_min_width, settings.gui_min_height)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self.iconbitmap("")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        """Build sidebar + content area layout."""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content_area()

    def _build_sidebar(self) -> None:
        """Left sidebar: logo, nav, status, level bar, input."""
        sidebar = ctk.CTkFrame(self, width=240, corner_radius=0, fg_color=("#F0F0F8", "#16162A"))
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(8, weight=1)

        # Logo / title
        logo_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        logo_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(24, 8))

        ctk.CTkLabel(
            logo_frame,
            text="✦ Nova",
            font=("Inter", 26, "bold"),
            text_color=COLOURS["accent"],
        ).pack(side="left")

        ctk.CTkLabel(
            logo_frame,
            text=f"v{settings.app_version}",
            font=("Inter", 11),
            text_color=COLOURS["text_muted"],
        ).pack(side="left", padx=(8, 0), pady=(8, 0))

        # Status indicator
        self._status_indicator = StatusIndicator(sidebar)
        self._status_indicator.grid(row=1, column=0, padx=20, pady=(4, 12), sticky="w")

        # Separator
        ctk.CTkFrame(sidebar, height=1, fg_color=("#DDDDEE", "#2D2D45")).grid(
            row=2, column=0, sticky="ew", padx=16, pady=4,
        )

        # Navigation buttons
        nav_items = [
            ("💬", "Chat",      "chat"),
            ("⚙",  "Settings", "settings"),
            ("📋", "Logs",      "logs"),
        ]

        self._nav_buttons: Dict[str, SidebarButton] = {}
        for i, (icon, label, key) in enumerate(nav_items):
            btn = SidebarButton(
                sidebar, text=label, icon=icon,
                command=lambda k=key: self._navigate(k),
            )
            btn.grid(row=3 + i, column=0, padx=12, pady=2, sticky="ew")
            self._nav_buttons[key] = btn

        self._nav_buttons["chat"].set_active(True)

        # Spacer
        ctk.CTkFrame(sidebar, fg_color="transparent").grid(row=8, column=0, sticky="nsew")

        # Microphone level bar
        ctk.CTkLabel(sidebar, text="🎙 Mic Level", font=("Inter", 11), text_color=COLOURS["text_muted"]).grid(
            row=9, column=0, padx=16, pady=(0, 4), sticky="w",
        )
        self._level_bar = AudioLevelBar(sidebar, fg_color="transparent")
        self._level_bar.grid(row=10, column=0, padx=16, pady=(0, 8), sticky="ew")

        # Wake word toggle
        self._ww_var = ctk.BooleanVar(value=settings.wake_word_enabled)
        ctk.CTkSwitch(
            sidebar,
            text="Wake Word",
            variable=self._ww_var,
            command=self._toggle_wake_word,
            font=("Inter", 12),
        ).grid(row=11, column=0, padx=20, pady=(4, 4), sticky="w")

        # PTT button
        ptt_btn = ctk.CTkButton(
            sidebar,
            text="🎤  Push to Talk",
            fg_color=COLOURS["accent"],
            hover_color=COLOURS["accent_hover"],
            font=("Inter", 13, "bold"),
            height=40,
            corner_radius=10,
        )
        ptt_btn.grid(row=12, column=0, padx=16, pady=(4, 4), sticky="ew")
        ptt_btn.bind("<ButtonPress-1>", lambda e: self._ptt_start())
        ptt_btn.bind("<ButtonRelease-1>", lambda e: self._ptt_stop())

        # Footer
        ctk.CTkLabel(
            sidebar,
            text="Powered by OpenAI + Whisper",
            font=("Inter", 10),
            text_color=COLOURS["text_muted"],
        ).grid(row=13, column=0, padx=16, pady=(4, 20))

    def _build_content_area(self) -> None:
        """Right-side content area with panel switching."""
        content = ctk.CTkFrame(self, corner_radius=0, fg_color=("#FAFAFA", "#1A1A2E"))
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._content_container = content

        # Build all panels
        self._chat_panel = self._build_chat_panel(content)
        self._settings_panel = SettingsPanel(
            content, settings_obj=settings, on_save=self._on_settings_save,
            fg_color="transparent",
        )
        self._logs_panel = LogsPanel(content, fg_color="transparent")

        # Show chat by default
        self._show_panel("chat")

    def _build_chat_panel(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        """Build the main conversation + text input panel."""
        panel = ctk.CTkFrame(parent, fg_color="transparent")
        panel.grid_rowconfigure(0, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(panel, fg_color=("white", "#20203A"), height=60, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            header,
            text="✦ Nova — Conversation",
            font=("Inter", 18, "bold"),
        ).pack(side="left", padx=20, pady=16)

        clear_btn = ctk.CTkButton(
            header, text="Clear", width=70, height=30,
            fg_color=COLOURS["error"], hover_color="#C0392B",
            command=self._clear_conversation,
        )
        clear_btn.pack(side="right", padx=16, pady=14)

        # Conversation area
        self._conversation_panel = ConversationPanel(
            panel,
            fg_color=("white", "#1A1A2E"),
            corner_radius=0,
        )
        self._conversation_panel.grid(row=1, column=0, sticky="nsew")
        panel.grid_rowconfigure(1, weight=1)

        # Text input area
        input_area = ctk.CTkFrame(panel, fg_color=("white", "#20203A"), height=80)
        input_area.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        input_area.grid_columnconfigure(0, weight=1)

        self._text_input = ctk.CTkEntry(
            input_area,
            placeholder_text="Type a message or speak to Nova…",
            font=("Inter", 14),
            height=44,
            corner_radius=22,
        )
        self._text_input.grid(row=0, column=0, padx=(16, 8), pady=18, sticky="ew")
        self._text_input.bind("<Return>", self._on_text_submit)

        ctk.CTkButton(
            input_area,
            text="Send →",
            width=90,
            height=44,
            fg_color=COLOURS["accent"],
            hover_color=COLOURS["accent_hover"],
            font=("Inter", 13, "bold"),
            corner_radius=22,
            command=self._on_text_submit,
        ).grid(row=0, column=1, padx=(0, 16), pady=18)

        return panel

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate(self, key: str) -> None:
        for k, btn in self._nav_buttons.items():
            btn.set_active(k == key)
        self._show_panel(key)
        self._active_nav = key

    def _show_panel(self, key: str) -> None:
        panels = {
            "chat": self._chat_panel,
            "settings": self._settings_panel,
            "logs": self._logs_panel,
        }
        for k, panel in panels.items():
            if k == key:
                panel.grid(row=0, column=0, sticky="nsew")
            else:
                panel.grid_remove()

    # ------------------------------------------------------------------
    # Voice pipeline callbacks (called from background threads)
    # ------------------------------------------------------------------

    def notify_audio_level(self, rms: float) -> None:
        """Called from audio thread — safe to call from any thread."""
        self._ui_queue.put(("level", rms))

    def notify_state(self, state: str) -> None:
        self._ui_queue.put(("state", state))

    def notify_user_message(self, text: str) -> None:
        self._ui_queue.put(("user_msg", text))

    def notify_assistant_message(self, text: str) -> None:
        self._ui_queue.put(("nova_msg", text))

    def notify_log(self, level: str, message: str) -> None:
        self._ui_queue.put(("log", (level, message)))

    # ------------------------------------------------------------------
    # Queue processors (run on main thread via after())
    # ------------------------------------------------------------------

    def _process_ui_queue(self) -> None:
        try:
            while not self._ui_queue.empty():
                event, payload = self._ui_queue.get_nowait()
                self._handle_ui_event(event, payload)
        except Exception as exc:
            logger.error("UI queue error: %s", exc)
        self.after(30, self._process_ui_queue)

    def _process_log_queue(self) -> None:
        try:
            while not self._log_queue.empty():
                level, msg = self._log_queue.get_nowait()
                self._logs_panel.append_log(msg, level)
        except Exception:
            pass
        self.after(500, self._process_log_queue)

    def _handle_ui_event(self, event: str, payload: Any) -> None:
        if event == "level":
            self._level_bar.set_level(payload)
        elif event == "state":
            self._status_indicator.set_state(payload)
        elif event == "user_msg":
            self._conversation_panel.add_message("user", payload)
            if self._active_nav != "chat":
                self._navigate("chat")
        elif event == "nova_msg":
            self._conversation_panel.add_message("assistant", payload)
        elif event == "log":
            level, msg = payload
            self._logs_panel.append_log(msg, level)

    # ------------------------------------------------------------------
    # User interactions
    # ------------------------------------------------------------------

    def _on_text_submit(self, event=None) -> None:
        text = self._text_input.get().strip()
        if not text:
            return
        self._text_input.delete(0, "end")
        self._conversation_panel.add_message("user", text)

        # Hand off to pipeline if available, else show offline message
        if self._pipeline:
            threading.Thread(
                target=self._pipeline.process_text,
                args=(text,),
                daemon=True,
            ).start()
        else:
            self._conversation_panel.add_message(
                "assistant",
                "Voice pipeline not connected. Please configure your settings.",
            )

    def _ptt_start(self) -> None:
        if self._pipeline:
            self._pipeline.listener.push_to_talk_start()
        self.notify_state("listening")

    def _ptt_stop(self) -> None:
        if self._pipeline:
            self._pipeline.listener.push_to_talk_stop()
        self.notify_state("processing")

    def _toggle_wake_word(self) -> None:
        enabled = self._ww_var.get()
        if self._pipeline:
            if enabled:
                self._pipeline.wake_detector.enable()
            else:
                self._pipeline.wake_detector.disable()
        logger.info("Wake word %s", "enabled" if enabled else "disabled")

    def _clear_conversation(self) -> None:
        self._conversation_panel.clear()
        if self._pipeline:
            self._pipeline.response_generator.clear_history()

    def _on_settings_save(self, values: dict) -> None:
        """Apply saved settings to the running pipeline."""
        if self._pipeline:
            tts = self._pipeline.tts
            tts.set_rate(values["tts_rate"])
            tts.set_volume(values["tts_volume"])
            ww = self._pipeline.wake_detector
            ww.set_wake_word(values["wake_word"])
            ww.set_sensitivity(values["wake_word_sensitivity"])
            if values["wake_word_enabled"]:
                ww.enable()
            else:
                ww.disable()
        # Persist to DB
        if self._pipeline:
            db = self._pipeline.db
            for k, v in values.items():
                if v is not None:
                    db.set_setting(k, str(v))

        messagebox.showinfo("Nova Settings", "Settings saved successfully!")

    # ------------------------------------------------------------------
    # Log handler installation
    # ------------------------------------------------------------------

    def _install_log_handler(self) -> None:
        """Attach a GUI log handler to the root logger."""
        handler = _GUILogHandler(self._log_queue)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(name)s — %(message)s"))
        logging.getLogger().addHandler(handler)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        """Gracefully shut down before destroying window."""
        logger.info("GUI closing — shutting down pipeline")
        if self._pipeline:
            try:
                self._pipeline.shutdown()
            except Exception as exc:
                logger.error("Pipeline shutdown error: %s", exc)
        self.destroy()
