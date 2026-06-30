"""
gui/widgets.py
==============
Custom UI components for Nova Voice Assistant.

Components
----------
- AudioLevelBar       — animated microphone level meter
- StatusIndicator     — pulsing dot showing assistant state
- ConversationBubble  — chat-style message bubble (user / assistant)
- ConversationPanel   — scrollable conversation history
- SettingsPanel       — tabbed settings form
- LogsPanel           — live scrolling log viewer
- SidebarButton       — styled navigation button
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime
from typing import Callable, List, Optional

import customtkinter as ctk
from tkinter import StringVar, IntVar, DoubleVar

from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Colour palette (consistent across light/dark modes)
# ---------------------------------------------------------------------------

COLOURS = {
    "accent":        "#6C63FF",
    "accent_hover":  "#574FD6",
    "accent_light":  "#8B84FF",
    "success":       "#2ECC71",
    "warning":       "#F39C12",
    "error":         "#E74C3C",
    "user_bubble":   "#6C63FF",
    "nova_bubble":   "#2D2D3F",
    "nova_bubble_light": "#E8E8F5",
    "text_light":    "#FFFFFF",
    "text_dark":     "#1A1A2E",
    "text_muted":    "#9999BB",
}


# ---------------------------------------------------------------------------
# AudioLevelBar
# ---------------------------------------------------------------------------

class AudioLevelBar(ctk.CTkFrame):
    """
    Animated horizontal bar that reflects microphone input level in real time.

    The bar uses a gradient from accent to error colour as level rises.
    Uses canvas drawing for smooth animation.
    """

    BAR_COUNT = 20
    UPDATE_MS = 60

    def __init__(self, master, **kwargs):
        super().__init__(master, height=30, **kwargs)
        self._level: float = 0.0
        self._target: float = 0.0
        self._canvas = ctk.CTkCanvas(
            self, height=30, bg=self._get_bg(), highlightthickness=0,
        )
        self._canvas.pack(fill="x", expand=True)
        self._after_id: Optional[str] = None
        self._animate()

    def _get_bg(self) -> str:
        return "#1A1A2E" if ctk.get_appearance_mode() == "Dark" else "#F0F0F8"

    def set_level(self, rms: float, max_rms: float = 3000.0) -> None:
        """Update the target level (0.0–1.0) from a raw RMS value."""
        self._target = min(1.0, rms / max_rms)

    def _animate(self) -> None:
        """Smooth animation loop using exponential decay."""
        # Smooth toward target
        self._level += (self._target - self._level) * 0.3

        w = self._canvas.winfo_width() or 300
        h = self._canvas.winfo_height() or 30
        self._canvas.delete("all")

        bar_width = (w - (self.BAR_COUNT - 1) * 2) / self.BAR_COUNT

        for i in range(self.BAR_COUNT):
            ratio = (i + 1) / self.BAR_COUNT
            active = ratio <= self._level
            if active:
                # Gradient: accent → warning → error
                if ratio < 0.6:
                    colour = COLOURS["accent"]
                elif ratio < 0.85:
                    colour = COLOURS["warning"]
                else:
                    colour = COLOURS["error"]
            else:
                colour = "#2A2A3F" if ctk.get_appearance_mode() == "Dark" else "#DDDDEE"

            x0 = i * (bar_width + 2)
            x1 = x0 + bar_width
            bar_h = h * (0.3 + ratio * 0.7) if active else h * 0.2
            y0 = (h - bar_h) / 2
            y1 = y0 + bar_h
            self._canvas.create_rectangle(x0, y0, x1, y1, fill=colour, outline="")

        self._after_id = self._canvas.after(self.UPDATE_MS, self._animate)

    def destroy(self):
        if self._after_id:
            try:
                self._canvas.after_cancel(self._after_id)
            except Exception:
                pass
        super().destroy()


# ---------------------------------------------------------------------------
# StatusIndicator
# ---------------------------------------------------------------------------

class StatusIndicator(ctk.CTkFrame):
    """
    Pulsing status dot that communicates the assistant's current state.

    States: idle | listening | processing | speaking | error
    """

    _COLOURS = {
        "idle":       "#555577",
        "listening":  "#2ECC71",
        "processing": "#F39C12",
        "speaking":   "#6C63FF",
        "error":      "#E74C3C",
        "wake_ready": "#00BCD4",
    }
    _LABELS = {
        "idle":       "Idle",
        "listening":  "Listening…",
        "processing": "Thinking…",
        "speaking":   "Speaking…",
        "error":      "Error",
        "wake_ready": "Waiting for wake word…",
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._state = "idle"
        self._pulse = 0.0
        self._pulse_dir = 1

        self._canvas = ctk.CTkCanvas(self, width=14, height=14, highlightthickness=0)
        self._canvas.pack(side="left", padx=(0, 6))

        self._label = ctk.CTkLabel(self, text="Idle", font=("Inter", 12))
        self._label.pack(side="left")

        self._animate()

    def set_state(self, state: str) -> None:
        """Update the indicator state."""
        self._state = state
        self._label.configure(text=self._LABELS.get(state, state.title()))

    def _animate(self):
        self._pulse += 0.05 * self._pulse_dir
        if self._pulse >= 1.0 or self._pulse <= 0.0:
            self._pulse_dir *= -1

        colour = self._COLOURS.get(self._state, "#555577")
        alpha = 0.5 + 0.5 * self._pulse if self._state != "idle" else 0.4
        self._canvas.delete("all")
        # Outer glow (simulated)
        if self._state not in ("idle",):
            self._canvas.create_oval(1, 1, 13, 13, fill=colour, outline=colour)
        self._canvas.create_oval(3, 3, 11, 11, fill=colour, outline="")

        self._canvas.after(50, self._animate)


# ---------------------------------------------------------------------------
# ConversationBubble
# ---------------------------------------------------------------------------

class ConversationBubble(ctk.CTkFrame):
    """
    A single message bubble in the conversation history panel.

    User messages appear right-aligned in accent colour.
    Assistant messages appear left-aligned in a muted dark colour.
    """

    def __init__(self, master, role: str, content: str, timestamp: str = "", **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        is_user = role == "user"
        is_dark = ctk.get_appearance_mode() == "Dark"

        bubble_colour = COLOURS["user_bubble"] if is_user else (
            COLOURS["nova_bubble"] if is_dark else COLOURS["nova_bubble_light"]
        )
        text_colour = COLOURS["text_light"] if is_user or is_dark else COLOURS["text_dark"]
        anchor = "e" if is_user else "w"

        # Outer row frame
        row_frame = ctk.CTkFrame(self, fg_color="transparent")
        row_frame.pack(fill="x", padx=8, pady=2)

        # Sender label
        sender = "You" if is_user else "Nova"
        sender_label = ctk.CTkLabel(
            row_frame,
            text=f"{sender}  {timestamp}",
            font=("Inter", 10),
            text_color=COLOURS["text_muted"],
            anchor=anchor,
        )
        sender_label.pack(fill="x", padx=4)

        # Bubble
        bubble_frame = ctk.CTkFrame(row_frame, fg_color=bubble_colour, corner_radius=16)

        if is_user:
            bubble_frame.pack(anchor="e", padx=(80, 4))
        else:
            bubble_frame.pack(anchor="w", padx=(4, 80))

        ctk.CTkLabel(
            bubble_frame,
            text=content,
            font=("Inter", 13),
            text_color=text_colour,
            wraplength=380,
            justify="left",
            padx=14,
            pady=10,
        ).pack()


# ---------------------------------------------------------------------------
# ConversationPanel
# ---------------------------------------------------------------------------

class ConversationPanel(ctk.CTkScrollableFrame):
    """
    Scrollable container for conversation bubbles.
    Auto-scrolls to the bottom on new messages.
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._bubbles: List[ConversationBubble] = []

    def add_message(self, role: str, content: str) -> None:
        """Append a new message bubble and scroll to bottom."""
        timestamp = datetime.now().strftime("%H:%M")
        bubble = ConversationBubble(self, role=role, content=content, timestamp=timestamp)
        bubble.pack(fill="x", pady=2)
        self._bubbles.append(bubble)
        # Scroll to bottom on next event loop tick
        self.after(50, self._scroll_bottom)

    def clear(self) -> None:
        """Remove all conversation bubbles."""
        for b in self._bubbles:
            b.destroy()
        self._bubbles.clear()

    def _scroll_bottom(self) -> None:
        try:
            self._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SettingsPanel
# ---------------------------------------------------------------------------

class SettingsPanel(ctk.CTkFrame):
    """
    Tabbed settings form for Nova's runtime configuration.

    Tabs: Voice, Wake Word, API Keys, Appearance
    """

    def __init__(self, master, settings_obj, on_save: Optional[Callable] = None, **kwargs):
        super().__init__(master, **kwargs)
        self._settings = settings_obj
        self._on_save = on_save
        self._build()

    def _build(self) -> None:
        # Header
        ctk.CTkLabel(
            self, text="⚙  Settings", font=("Inter", 20, "bold"),
        ).pack(padx=20, pady=(20, 10), anchor="w")

        tabview = ctk.CTkTabview(self, anchor="nw")
        tabview.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self._build_voice_tab(tabview.add("Voice"))
        self._build_wakeword_tab(tabview.add("Wake Word"))
        self._build_api_tab(tabview.add("API Keys"))
        self._build_appearance_tab(tabview.add("Appearance"))

        # Save button
        ctk.CTkButton(
            self, text="Save Settings", command=self._save,
            fg_color=COLOURS["accent"], hover_color=COLOURS["accent_hover"],
            font=("Inter", 14, "bold"), height=42,
        ).pack(padx=16, pady=(0, 20), fill="x")

    def _build_voice_tab(self, tab: ctk.CTkFrame) -> None:
        self._rate_var = IntVar(value=self._settings.tts_rate)
        self._volume_var = DoubleVar(value=self._settings.tts_volume)

        ctk.CTkLabel(tab, text="Speech Rate (WPM)", font=("Inter", 13)).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkSlider(tab, from_=50, to=400, variable=self._rate_var, number_of_steps=70).pack(fill="x", padx=16)
        self._rate_label = ctk.CTkLabel(tab, text=f"{self._rate_var.get()} WPM", font=("Inter", 11))
        self._rate_label.pack(anchor="w", padx=16)
        self._rate_var.trace_add("write", lambda *_: self._rate_label.configure(text=f"{self._rate_var.get()} WPM"))

        ctk.CTkLabel(tab, text="Volume", font=("Inter", 13)).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkSlider(tab, from_=0.0, to=1.0, variable=self._volume_var).pack(fill="x", padx=16)

    def _build_wakeword_tab(self, tab: ctk.CTkFrame) -> None:
        self._wake_word_var = StringVar(value=self._settings.wake_word)
        self._wake_enabled_var = ctk.BooleanVar(value=self._settings.wake_word_enabled)
        self._sensitivity_var = DoubleVar(value=self._settings.wake_word_sensitivity)

        ctk.CTkLabel(tab, text="Wake Word", font=("Inter", 13)).pack(anchor="w", padx=16, pady=(16, 4))
        ctk.CTkEntry(tab, textvariable=self._wake_word_var, placeholder_text="nova").pack(fill="x", padx=16)

        ctk.CTkSwitch(
            tab, text="Enable Wake Word Detection",
            variable=self._wake_enabled_var,
            onvalue=True, offvalue=False,
        ).pack(padx=16, pady=(12, 4), anchor="w")

        ctk.CTkLabel(tab, text="Sensitivity", font=("Inter", 13)).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkSlider(tab, from_=0.0, to=1.0, variable=self._sensitivity_var).pack(fill="x", padx=16)

    def _build_api_tab(self, tab: ctk.CTkFrame) -> None:
        self._openai_key_var = StringVar(value=self._settings.openai_api_key or "")
        self._weather_key_var = StringVar(value=self._settings.openweather_api_key or "")
        self._news_key_var = StringVar(value=self._settings.news_api_key or "")
        self._city_var = StringVar(value=self._settings.default_city)

        for label, var in [
            ("OpenAI API Key", self._openai_key_var),
            ("OpenWeatherMap API Key", self._weather_key_var),
            ("NewsAPI Key", self._news_key_var),
        ]:
            ctk.CTkLabel(tab, text=label, font=("Inter", 13)).pack(anchor="w", padx=16, pady=(12, 4))
            ctk.CTkEntry(tab, textvariable=var, show="•").pack(fill="x", padx=16)

        ctk.CTkLabel(tab, text="Default City (Weather)", font=("Inter", 13)).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkEntry(tab, textvariable=self._city_var).pack(fill="x", padx=16)

    def _build_appearance_tab(self, tab: ctk.CTkFrame) -> None:
        self._theme_var = StringVar(value=ctk.get_appearance_mode())

        ctk.CTkLabel(tab, text="Theme", font=("Inter", 13)).pack(anchor="w", padx=16, pady=(16, 4))
        theme_frame = ctk.CTkFrame(tab, fg_color="transparent")
        theme_frame.pack(fill="x", padx=16)

        for mode in ("Dark", "Light", "System"):
            ctk.CTkRadioButton(
                theme_frame, text=mode, variable=self._theme_var,
                value=mode,
                command=lambda m=mode: ctk.set_appearance_mode(m),
            ).pack(side="left", padx=(0, 16))

    def _save(self) -> None:
        """Collect all form values and invoke the on_save callback."""
        values = {
            "tts_rate": self._rate_var.get(),
            "tts_volume": round(self._volume_var.get(), 2),
            "wake_word": self._wake_word_var.get().strip().lower(),
            "wake_word_enabled": self._wake_enabled_var.get(),
            "wake_word_sensitivity": round(self._sensitivity_var.get(), 2),
            "openai_api_key": self._openai_key_var.get().strip() or None,
            "openweather_api_key": self._weather_key_var.get().strip() or None,
            "news_api_key": self._news_key_var.get().strip() or None,
            "default_city": self._city_var.get().strip(),
        }
        logger.info("Settings saved: %s", {k: "***" if "key" in k else v for k, v in values.items()})
        if self._on_save:
            self._on_save(values)


# ---------------------------------------------------------------------------
# LogsPanel
# ---------------------------------------------------------------------------

class LogsPanel(ctk.CTkFrame):
    """
    Live scrolling log panel that captures Python logging output.
    """

    MAX_LINES = 500

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._lines: List[str] = []
        self._build()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))
        ctk.CTkLabel(header, text="📋  Logs", font=("Inter", 18, "bold")).pack(side="left")
        ctk.CTkButton(
            header, text="Clear", width=70, height=28,
            command=self.clear_logs,
            fg_color=COLOURS["error"], hover_color="#C0392B",
        ).pack(side="right")

        self._textbox = ctk.CTkTextbox(
            self,
            font=("Consolas", 11),
            state="disabled",
            wrap="word",
        )
        self._textbox.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def append_log(self, message: str, level: str = "INFO") -> None:
        """Append a log line with colour tagging."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{level:<8}] {message}\n"
        self._lines.append(line)
        if len(self._lines) > self.MAX_LINES:
            self._lines.pop(0)

        self._textbox.configure(state="normal")
        self._textbox.insert("end", line)
        # Keep the last MAX_LINES in the widget
        line_count = int(self._textbox.index("end-1c").split(".")[0])
        if line_count > self.MAX_LINES:
            self._textbox.delete("1.0", f"{line_count - self.MAX_LINES}.0")
        self._textbox.see("end")
        self._textbox.configure(state="disabled")

    def clear_logs(self) -> None:
        self._lines.clear()
        self._textbox.configure(state="normal")
        self._textbox.delete("1.0", "end")
        self._textbox.configure(state="disabled")


# ---------------------------------------------------------------------------
# SidebarButton
# ---------------------------------------------------------------------------

class SidebarButton(ctk.CTkButton):
    """Styled sidebar navigation button with icon support."""

    def __init__(self, master, text: str, icon: str = "", command=None, **kwargs):
        super().__init__(
            master,
            text=f"  {icon}  {text}" if icon else text,
            command=command,
            anchor="w",
            fg_color="transparent",
            hover_color=("#E8E8F0", "#2D2D45"),
            text_color=("#1A1A2E", "#E0E0FF"),
            font=("Inter", 14),
            height=44,
            corner_radius=10,
            **kwargs,
        )

    def set_active(self, active: bool) -> None:
        """Highlight this button as the currently active nav item."""
        if active:
            self.configure(fg_color=(COLOURS["accent"], COLOURS["accent"]), text_color="white")
        else:
            self.configure(fg_color="transparent", text_color=("#1A1A2E", "#E0E0FF"))
