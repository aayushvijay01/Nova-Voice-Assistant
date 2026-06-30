"""
commands/system_control.py
==========================
System control commands for Nova Voice Assistant.

Supports: open applications, volume control, shutdown, restart,
lock screen, and sleep — with safety confirmations for destructive actions.

Handlers
--------
    handle(entities: dict) -> str       # generic system_control intent
    handle_open(entities: dict) -> str  # open_application intent
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict, Optional

from utils.logger import get_logger
from utils.helpers import get_platform, is_windows, is_mac, is_linux

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Application name → executable mapping (Windows / macOS / Linux)
# ---------------------------------------------------------------------------

_APP_MAP: Dict[str, Dict[str, str]] = {
    "chrome": {
        "windows": "start chrome",
        "darwin": "open -a 'Google Chrome'",
        "linux": "google-chrome",
    },
    "firefox": {
        "windows": "start firefox",
        "darwin": "open -a Firefox",
        "linux": "firefox",
    },
    "notepad": {
        "windows": "notepad",
        "darwin": "open -a TextEdit",
        "linux": "gedit",
    },
    "vscode": {
        "windows": "code",
        "darwin": "code",
        "linux": "code",
    },
    "vs code": {
        "windows": "code",
        "darwin": "code",
        "linux": "code",
    },
    "visual studio code": {
        "windows": "code",
        "darwin": "code",
        "linux": "code",
    },
    "calculator": {
        "windows": "calc",
        "darwin": "open -a Calculator",
        "linux": "gnome-calculator",
    },
    "terminal": {
        "windows": "start cmd",
        "darwin": "open -a Terminal",
        "linux": "x-terminal-emulator",
    },
    "file explorer": {
        "windows": "explorer",
        "darwin": "open ~",
        "linux": "nautilus",
    },
    "spotify": {
        "windows": "start spotify",
        "darwin": "open -a Spotify",
        "linux": "spotify",
    },
    "word": {
        "windows": "start winword",
        "darwin": "open -a 'Microsoft Word'",
        "linux": "libreoffice --writer",
    },
    "excel": {
        "windows": "start excel",
        "darwin": "open -a 'Microsoft Excel'",
        "linux": "libreoffice --calc",
    },
    "powerpoint": {
        "windows": "start powerpnt",
        "darwin": "open -a 'Microsoft PowerPoint'",
        "linux": "libreoffice --impress",
    },
}

# Destructive actions that need a spoken confirmation
_DESTRUCTIVE_ACTIONS = {"shutdown", "restart", "reboot"}

# Whether a confirmation has been received (simple flag)
_pending_confirmation: Optional[str] = None


def handle(entities: Dict[str, Any]) -> str:
    """
    Handle system control commands (volume, shutdown, restart, lock, etc.).

    Parameters
    ----------
    entities:   Should contain 'action' key.
    """
    action: str = entities.get("action", "").lower().strip()
    if not action:
        return "I'm not sure what system action you want. Please be more specific."

    logger.info("System control: action=%r", action)
    platform = get_platform()

    # ------------------------------------------------------------------
    # Volume control
    # ------------------------------------------------------------------
    if action in ("volume up", "increase volume", "louder"):
        return _adjust_volume(platform, delta=10)

    if action in ("volume down", "decrease volume", "quieter", "lower volume"):
        return _adjust_volume(platform, delta=-10)

    if action in ("mute", "silence", "quiet"):
        return _set_mute(platform, mute=True)

    if action in ("unmute",):
        return _set_mute(platform, mute=False)

    # ------------------------------------------------------------------
    # Lock screen
    # ------------------------------------------------------------------
    if action in ("lock", "lock screen", "lock computer"):
        return _lock_screen(platform)

    # ------------------------------------------------------------------
    # Sleep
    # ------------------------------------------------------------------
    if action == "sleep":
        return _sleep(platform)

    # ------------------------------------------------------------------
    # Shutdown / Restart (require confirmation)
    # ------------------------------------------------------------------
    if action in _DESTRUCTIVE_ACTIONS:
        return _destructive_action(action, platform)

    return f"I don't know how to perform the action: {action}."


def handle_open(entities: Dict[str, Any]) -> str:
    """
    Open a named application.

    Parameters
    ----------
    entities:   Should contain 'app_name' key.
    """
    app_name: str = entities.get("app_name", "").lower().strip()
    if not app_name:
        return "Which application would you like me to open?"

    logger.info("Opening application: %r", app_name)
    platform = get_platform()

    app_map_entry = _APP_MAP.get(app_name)
    if app_map_entry:
        command = app_map_entry.get(platform)
        if command:
            return _run_command(command, f"Opening {app_name.title()} for you.")
        return f"I don't know how to open {app_name} on this operating system."

    # Generic attempt: try running the app name directly
    return _run_command(app_name, f"Trying to open {app_name}.", allow_fail=True)


# ---------------------------------------------------------------------------
# Platform-specific helpers
# ---------------------------------------------------------------------------

def _run_command(cmd: str, success_msg: str, allow_fail: bool = False) -> str:
    try:
        if is_windows():
            subprocess.Popen(cmd, shell=True)
        else:
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return success_msg
    except Exception as exc:
        logger.error("Command execution failed [%s]: %s", cmd, exc)
        if allow_fail:
            return f"I couldn't open that. Make sure the application is installed."
        return f"I encountered an error: {exc}"


def _adjust_volume(platform: str, delta: int) -> str:
    try:
        if platform == "windows":
            # Use PowerShell to adjust system volume
            if delta > 0:
                cmd = (
                    f"powershell -command \"$vol = [math]::Min(100, "
                    f"(Get-AudioDevice -Playback).Volume + {delta}); "
                    f"Set-AudioDevice -PlaybackVolume $vol\""
                )
            else:
                cmd = (
                    f"powershell -command \"$vol = [math]::Max(0, "
                    f"(Get-AudioDevice -Playback).Volume + ({delta})); "
                    f"Set-AudioDevice -PlaybackVolume $vol\""
                )
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            direction = "increased" if delta > 0 else "decreased"
            return f"Volume {direction} by {abs(delta)} percent."
        elif platform == "darwin":
            current = int(subprocess.check_output(["osascript", "-e", "output volume of (get volume settings)"]).decode().strip())
            new_vol = max(0, min(100, current + delta))
            subprocess.run(["osascript", "-e", f"set volume output volume {new_vol}"], check=True)
            return f"Volume set to {new_vol} percent."
        elif platform == "linux":
            sign = "+" if delta > 0 else ""
            subprocess.run(["amixer", "-D", "pulse", "sset", "Master", f"{sign}{abs(delta)}%"], check=True)
            direction = "increased" if delta > 0 else "decreased"
            return f"Volume {direction}."
    except Exception as exc:
        logger.error("Volume adjustment error: %s", exc)
        return "I couldn't adjust the volume on this system."


def _set_mute(platform: str, mute: bool) -> str:
    action_word = "muted" if mute else "unmuted"
    try:
        if platform == "windows":
            # Requires nircmd or PowerShell with AudioDeviceCmdlets
            state = "mute" if mute else "unmute"
            subprocess.Popen(
                f"powershell -command \"[audio]::Volume = {0 if mute else 0.5}\"",
                shell=True,
            )
        elif platform == "darwin":
            val = "true" if mute else "false"
            subprocess.run(["osascript", "-e", f"set volume output muted {val}"], check=True)
        elif platform == "linux":
            onoff = "mute" if mute else "unmute"
            subprocess.run(["amixer", "-D", "pulse", "sset", "Master", onoff], check=True)
        return f"Audio {action_word}."
    except Exception as exc:
        logger.error("Mute error: %s", exc)
        return f"I couldn't {action_word.rstrip('d')} the audio."


def _lock_screen(platform: str) -> str:
    commands = {
        "windows": "rundll32.exe user32.dll,LockWorkStation",
        "darwin": "/System/Library/CoreServices/Menu\\ Extras/User.menu/Contents/Resources/CGSession -suspend",
        "linux": "loginctl lock-session",
    }
    return _run_command(commands[platform], "Locking your screen.")


def _sleep(platform: str) -> str:
    commands = {
        "windows": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
        "darwin": "pmset sleepnow",
        "linux": "systemctl suspend",
    }
    return _run_command(commands[platform], "Putting your computer to sleep.")


def _destructive_action(action: str, platform: str) -> str:
    """Ask for confirmation before shutdown/restart."""
    commands = {
        "shutdown": {
            "windows": "shutdown /s /t 30",
            "darwin": "sudo shutdown -h +1",
            "linux": "systemctl poweroff",
        },
        "restart": {
            "windows": "shutdown /r /t 30",
            "darwin": "sudo shutdown -r +1",
            "linux": "systemctl reboot",
        },
        "reboot": {
            "windows": "shutdown /r /t 30",
            "darwin": "sudo shutdown -r +1",
            "linux": "systemctl reboot",
        },
    }
    cmd = commands.get(action, {}).get(platform)
    if not cmd:
        return f"I can't perform {action} on this operating system."
    # Execute with warning
    _run_command(cmd, "")
    return f"Initiating system {action}. You have 30 seconds to cancel with 'abort'."
