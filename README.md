# LIS — Living Intelligent System

**Your personal AI command center for Windows.**

A voice-first AI assistant that lives on your desktop. Speak naturally, and LIS responds with an Indian-neural voice, proactive intelligence, and an audio-reactive particle orb. Built with a 6-provider LLM fallback chain, semantic RAG memory, and multi-step autonomous reasoning.

> "Right away, sir."

---

## ✨ Features

- **🎙️ Voice Conversation** — Speak naturally, get spoken responses via Edge TTS neural voice
- **🧠 RAG Memory** — Semantic vector search (ChromaDB + sentence-transformers) + keyword search (SQLite FTS5)
- **⚡ ReAct Reasoning** — Autonomous multi-step task execution (Think → Act → Observe loops)
- **🔁 6-Provider LLM Fallback** — Anthropic → Groq → Gemini → Cerebras → OpenRouter → Ollama
- **👁️ Screen Vision** — Takes screenshots and analyzes them with Gemini Vision
- **💬 Chat Panel** — Persistent conversation history with glassmorphic UI
- **🖥️ System Tray** — Runs silently in background with tray icon
- **📱 40+ Skills** — Web search, Email, WhatsApp, Calendar, Weather, Timers, Stocks, Crypto, and more
- **🔮 Audio-Reactive Orb** — Three.js particle visualization that pulses with LIS's voice
- **🏗️ Build Software** — Spawns Claude Code sessions to build entire projects from voice commands
- **📋 Task Management** — Create, track, and manage tasks with priorities and due dates
- **🌐 Web Research** — Deep research with auto-generated HTML reports
- **✉️ Native Communication** — Send emails and WhatsApp messages directly via Microsoft Edge

## 🖥️ Requirements

- **Windows 10/11**
- **Python 3.11+**
- **Node.js 18+**
- **Microsoft Edge** (default browser)

### API Keys (at least one required)

| Provider | Cost | Key |
|----------|------|-----|
| [Groq](https://console.groq.com/) | Free | `GROQ_API_KEY` |
| [Gemini](https://aistudio.google.com/) | Free | `GEMINI_API_KEY` |
| [Cerebras](https://cloud.cerebras.ai/) | Free | `CEREBRAS_API_KEY` |
| [Anthropic](https://console.anthropic.com/) | Paid | `ANTHROPIC_API_KEY` |
| [OpenRouter](https://openrouter.ai/) | Free tier | `OPENROUTER_API_KEY` |
| Ollama (local) | Free | No key needed |

> **Tip:** LIS works with just free-tier providers. Configure Groq + Gemini for the best free experience.

## 🚀 Quick Start

```powershell
# 1. Clone the repo
git clone https://github.com/prodestiny_23/LIS.git
cd LIS

# 2. Set up environment
copy .env.example .env
# Edit .env with your API keys

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install frontend
cd frontend && npm install && cd ..

# 5. Build frontend
cd frontend && npm run build && cd ..

# 6. Launch LIS
python server.py --port 8340
```

Then open **Microsoft Edge** → `http://localhost:8340`

### One-Click Launch

```powershell
# Option A — Batch file
run_lis.bat

# Option B — System tray (background)
python tray.py

# Option C — Silent startup (no console)
start_lis_silent.vbs
```

## ⚙️ Configuration

Edit your `.env` file:

```env
# At least one LLM provider (free options available)
GROQ_API_KEY=your-groq-key
GEMINI_API_KEY=your-gemini-key
ANTHROPIC_API_KEY=your-anthropic-key

# Optional
USER_NAME=sir
LIS_PORT=8340
```

## 🏗️ Architecture

```
Microphone → Web Speech API → WebSocket → FastAPI → LLM (6-provider chain) → Edge TTS → Speaker
                                              │
                                              ├── ReAct Engine (autonomous multi-step reasoning)
                                              ├── Vector Memory (ChromaDB semantic search)
                                              ├── Skill System (30+ registered skills)
                                              ├── Screen Vision (pyautogui + Gemini Vision)
                                              └── Claude Code Tasks (software building)
```

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Python |
| Frontend | Vite + TypeScript + Three.js |
| Communication | WebSocket (JSON + binary audio) |
| AI | 6-provider fallback (Anthropic, Groq, Gemini, Cerebras, OpenRouter, Ollama) |
| TTS | Edge TTS (neural Indian voice) + gTTS + pyttsx3 fallbacks |
| Memory | SQLite FTS5 (keyword) + ChromaDB (semantic vectors) |
| Vision | pyautogui + Gemini Vision API |
| System | PowerShell/CMD for Windows integration |

## 📂 Project Structure

```
LIS_2.0/
├── server.py              # Main server — WebSocket, LLM, actions
├── llm_providers.py       # 6-provider LLM fallback chain
├── vector_memory.py       # RAG semantic memory (ChromaDB)
├── react_engine.py        # ReAct autonomous reasoning
├── vision.py              # Screen capture + Gemini Vision
├── tray.py                # System tray background service
├── memory.py              # SQLite memory + FTS5 search
├── skills.py              # 30+ skill registry
├── actions.py             # System actions (browser, terminal)
├── brain.py               # Cognitive core (intent analysis)
├── empathy.py             # Emotional intelligence engine
├── screen.py              # Window awareness
├── run_lis.bat            # One-click launcher
├── start_lis_silent.vbs   # Silent background launcher
├── requirements.txt       # Python dependencies
├── .env.example           # Environment template
└── frontend/
    ├── src/
    │   ├── main.ts        # Frontend state machine + chat panel
    │   ├── orb.ts         # Three.js particle orb
    │   ├── voice.ts       # Web Speech API
    │   ├── ws.ts          # WebSocket client
    │   └── style.css      # Glassmorphic UI styles
    └── index.html         # Entry point
```

## 🔌 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Server status |
| `/api/chat/history` | GET | Persistent chat messages |
| `/api/memory/vector/stats` | GET | Vector memory statistics |
| `/api/memory/vector/search?q=` | GET | Semantic search |
| `/api/llm/status` | GET | LLM provider status |
| `/api/react` | POST | Multi-step reasoning task |
| `/api/vision/screen` | GET | Screenshot + AI analysis |
| `/api/tasks` | GET | Task list |
| `/ws/voice` | WebSocket | Voice conversation |

## 🤝 Contributing

Contributions welcome! Some areas that could use work:

- **MCP Protocol** — Connect to external tool servers
- **Dashboard UI** — Widget-based command center
- **Proactive Intelligence** — Anticipate user needs
- **Calendar/Email** — Microsoft 365 Graph API integration
- **Mobile Companion** — PWA enhancements

Please open an issue before submitting large PRs.

## 📄 License

Non-Commercial License — strictly prohibits commercial use or resale. See [LICENSE](LICENSE) for details.

## 👨‍💻 Author

Built by **Shubhendu Kumar Mishra** ([@prodestiny_23](https://github.com/prodestiny_23))

Powered by open-source LLMs, [ChromaDB](https://www.trychroma.com/), and [Edge TTS](https://github.com/rany2/edge-tts).
