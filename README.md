# ✦ Nova Voice Assistant

> **A production-quality desktop AI voice assistant built with Python 3.12+**

Nova is a fully-featured, local-first voice assistant with wake word detection, real-time speech recognition, natural language understanding via OpenAI, and a modern dark-mode GUI — comparable in architecture to Siri, Google Assistant, and Alexa.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🎙 Wake Word | "Nova" — continuous background listening, configurable |
| 🗣 Speech-to-Text | Faster-Whisper (local) + SpeechRecognition (fallback) |
| 🧠 NLP | OpenAI GPT-4o-mini with function calling + regex offline fallback |
| 🔊 Text-to-Speech | pyttsx3 (fully offline), adjustable rate/voice/volume |
| ☁ Weather | OpenWeatherMap API |
| 📰 News | NewsAPI.org top headlines |
| ⏱ Timer | Multiple concurrent countdown timers |
| 🔢 Calculator | Safe spoken math evaluator |
| 🔔 Reminders | SQLite-backed, daily/weekly recurrence |
| 💻 System Control | Open apps, volume, lock, sleep, shutdown |
| 🌐 Web Search | Google & YouTube search, URL opener |
| 🗂 Memory | Multi-turn conversation context with SQLite persistence |
| 🎨 GUI | Dark/light mode CustomTkinter dashboard |

---

## 📁 Project Structure

```
nova_voice_assistant/
│
├── main.py                    # Entry point + VoicePipeline orchestrator
├── config/
│   └── settings.py            # Pydantic settings + dotenv
├── assistant/
│   ├── listener.py            # PyAudio microphone capture + VAD
│   ├── wakeword.py            # Wake word detection
│   ├── recognizer.py          # Faster-Whisper + SR fallback
│   ├── intent_engine.py       # OpenAI function calling + regex
│   ├── executor.py            # Command registry + dispatch
│   ├── response_generator.py  # OpenAI streaming responses
│   └── tts.py                 # pyttsx3 TTS engine
├── commands/
│   ├── base.py                # BaseCommand ABC
│   ├── weather.py             # OpenWeatherMap
│   ├── news.py                # NewsAPI
│   ├── timer.py               # Countdown timers
│   ├── calculator.py          # Safe math evaluator
│   ├── reminder.py            # Scheduler + SQLite
│   ├── system_control.py      # OS-level controls
│   └── web_search.py          # Browser + search
├── database/
│   ├── models.py              # DDL + TypedDicts
│   └── storage.py             # CRUD layer
├── gui/
│   ├── app.py                 # Main CustomTkinter window
│   └── widgets.py             # Custom UI components
├── utils/
│   ├── logger.py              # Rotating file + coloured console logger
│   └── helpers.py             # Time parsing, safe eval, retry decorator
├── tests/                     # pytest unit + integration tests
├── .env.example               # Configuration template
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

---

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.12+
- Windows / macOS / Linux
- Microphone (optional — text-only mode available)

### 2. Clone and set up

```bash
# Clone the repository
git clone https://github.com/yourname/nova-voice-assistant
cd nova_voice_assistant

# Create a virtual environment (recommended)
python -m venv .venv

# Activate it
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> ⚠️ **Windows PyAudio Note**: If `pip install pyaudio` fails, run:
> ```bash
> pip install pipwin
> pipwin install pyaudio
> ```
> Or download the pre-built wheel from [Gohlke's page](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio).

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

**Required for full features:**
- `OPENAI_API_KEY` — for NLP (app works offline without it via regex fallback)
- `OPENWEATHER_API_KEY` — for weather commands (free tier at openweathermap.org)
- `NEWS_API_KEY` — for news commands (free tier at newsapi.org)

### 5. Run Nova

```bash
python main.py
```

**Additional modes:**
```bash
# Text-only (no microphone required)
python main.py --no-voice

# CLI / headless mode (for testing)
python main.py --no-gui

# Enable verbose debug logging
python main.py --debug
```

---

## 🗣 Voice Commands

| Intent | Example Phrases |
|---|---|
| **Weather** | "Nova, what's the weather?" / "Weather in London" |
| **News** | "Tell me today's headlines" / "What's in the news?" |
| **Timer** | "Set a timer for 10 minutes" |
| **Calculator** | "What is 245 times 87?" / "Square root of 144" |
| **Reminder** | "Remind me to call John in 30 minutes" |
| **Time** | "What time is it?" |
| **Date** | "What's today's date?" |
| **Open App** | "Open Chrome" / "Launch VS Code" |
| **Volume** | "Volume up" / "Mute" |
| **Search** | "Search Google for Python tutorials" |
| **Web** | "Open github.com" |
| **Lock** | "Lock my screen" |

---

## 🧪 Running Tests

```bash
# Run all tests
pytest tests/ -v

# With coverage report
pytest tests/ --cov=. --cov-report=term-missing

# Run a specific test module
pytest tests/test_database.py -v
pytest tests/test_commands.py -v
```

---

## ⚙️ Configuration

All settings can be configured via:
1. **`.env` file** — recommended for API keys
2. **Environment variables** — override any setting
3. **GUI Settings panel** — runtime changes (persisted to SQLite)

| Key | Default | Description |
|---|---|---|
| `WAKE_WORD` | `nova` | Trigger keyword |
| `WHISPER_MODEL_SIZE` | `base` | STT model (tiny→large) |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model |
| `TTS_RATE` | `175` | Speech rate (WPM) |
| `GUI_THEME` | `dark` | `dark` / `light` / `system` |
| `DEFAULT_CITY` | `New York` | Default city for weather |
| `SILENCE_THRESHOLD` | `500` | Mic sensitivity (RMS) |

---

## 🔌 Adding Custom Commands

Create a new file in `commands/`:

```python
# commands/my_command.py

def handle(entities: dict) -> str:
    """My custom command handler."""
    return "Hello from my custom command!"
```

Register it in `assistant/executor.py`:
```python
self._safe_register_module("commands.my_command", "my_intent", "handle")
```

Add the intent to `IntentEngine`'s OpenAI function schema and regex rules.

---

## 🗄️ Database Schema

| Table | Description |
|---|---|
| `users` | User profiles with preferences JSON |
| `conversations` | Full chat history (user + assistant turns) |
| `reminders` | Scheduled reminders with recurrence support |
| `settings` | Persistent key-value application settings |
| `command_history` | Log of all executed commands |

Default location: `data/nova.db`

---

## 🔒 Security Notes

- API keys are stored in `.env` (never committed to version control)
- Math evaluator uses a whitelist — no `eval()` of arbitrary code
- System commands (shutdown, restart) display a confirmation warning
- Input is sanitised before processing

---

## 🏗️ Architecture

```
User Voice Input
     │
     ▼
AudioListener (PyAudio VAD)
     │
     ▼
WakeWordDetector ──No──► Wait
     │ Yes
     ▼
SpeechRecognizer (Faster-Whisper / SR)
     │
     ▼
IntentEngine (OpenAI / Regex)
     │
     ▼
CommandExecutor ──► Command Handler
     │
     ▼
ResponseGenerator (OpenAI Streaming)
     │
     ▼
TTSEngine (pyttsx3) ──► Speech Output
     │
     ▼
GUI Update (Tkinter after())
     │
     ▼
Database (SQLite)
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

- [OpenAI](https://openai.com) — GPT-4o language models
- [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) — Local speech recognition
- [CustomTkinter](https://customtkinter.tomschimansky.com) — Modern GUI framework
- [pyttsx3](https://pyttsx3.readthedocs.io) — Offline text-to-speech
- [OpenWeatherMap](https://openweathermap.org) — Weather data
- [NewsAPI](https://newsapi.org) — News headlines
