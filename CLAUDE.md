# LIS — Voice AI Assistant

## Overview
LIS (Linguistically Intelligent System) is a voice-first AI assistant for Windows. It runs locally on your machine, connecting to your Calendar, Mail, Notes, and can spawn Claude Code sessions for development tasks.

## Quick Start
When a user clones this repo and starts Claude Code, help them:
1. Copy .env.example to .env
2. Get an Anthropic API key from console.anthropic.com
3. Get a Fish Audio API key from fish.audio
4. Install Python dependencies: pip install -r requirements.txt
5. Install frontend dependencies: cd frontend && npm install
6. Generate SSL certs: openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'
7. Run the backend: python server.py
8. Run the frontend: cd frontend && npm run dev
9. Open Chrome to http://localhost:5173
10. Click to enable audio, speak to LIS

## Architecture
- **Backend**: FastAPI + Python (server.py, ~3000 lines)
- **Frontend**: Vite + TypeScript + Three.js (audio-reactive orb)
- **Communication**: WebSocket (JSON messages + binary audio)
- **AI**: Claude Haiku for fast responses, Groq/Gemini fallback chain
- **TTS**: Edge-TTS (NeerjaNeural) with gTTS fallback
- **System**: Windows integration for Calendar, Mail, Notes, Terminal

## Key Files
- `server.py` — Main server, WebSocket handler, LLM integration, action system
- `frontend/src/orb.ts` — Three.js particle orb visualization
- `frontend/src/voice.ts` — Web Speech API + audio playback
- `frontend/src/main.ts` — Frontend state machine
- `memory.py` — SQLite memory system with FTS5 search
- `calendar_access.py` — Calendar integration
- `mail_access.py` — Mail integration (READ-ONLY)
- `notes_access.py` — Notes integration
- `actions.py` — System actions (Terminal, Browser, Claude Code)
- `browser.py` — Playwright web automation
- `work_mode.py` — Persistent Claude Code sessions
- `empathy.py` — Sentiment analysis and emotional state engine
- `brain.py` — Internal monologue and cognitive processing

## Environment Variables
- `ANTHROPIC_API_KEY` (optional) — Claude API access (Groq fallback if missing)
- `GROQ_API_KEY` (recommended) — Free Groq API for fast fallback
- `GEMINI_API_KEY` (optional) — Google Gemini fallback
- `FISH_API_KEY` (optional) — Fish Audio TTS
- `FISH_VOICE_ID` (optional) — Voice model ID
- `USER_NAME` (optional) — Your name for LIS to use
- `CALENDAR_ACCOUNTS` (optional) — Comma-separated calendar emails

## Conventions
- LIS personality: Warm Indian-accented partner, Hinglish conversational style
- Max 1-2 sentences per voice response
- Action tags: [ACTION:BUILD], [ACTION:BROWSE], [ACTION:RESEARCH], etc.
- LLM fallback chain: Anthropic → Groq → Gemini → Ollama (local)
- Read-only for Mail (safety by design)
- SQLite for all local data storage
