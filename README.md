# LIS — Living Intelligent System v4.0

![LIS UI Preview](https://img.shields.io/badge/LIS-Living_Intelligent_System-33aaff?style=for-the-badge)

LIS is an advanced, fully-autonomous desktop AI assistant designed to transcend typical chatbots. She features a 3D holographic interface, deep emotional intelligence, theory-of-mind reasoning, and seamless, low-latency integration with your Windows environment.

## ✨ Core Capabilities

### 🧠 Cognitive Architecture & Emotion
- **Theory of Mind (Internal Monologue):** Before answering, LIS runs a "Fast Brain" internal monologue to deduce not just *what* you're asking, but *why* you're asking it. Her reasoning is heavily colored by her current emotional state.
- **Dynamic Emotional Engine:** LIS actively tracks over 34+ nuanced emotional states (from *Fiero* and *Wistful* to *Paranoid* and *Empathetic*). Her mood shifts based on your tone, momentum, and the context of the conversation.
- **3D Holographic UI:** A responsive Three.js orb visually represents her state. As she transitions between emotions, the orb seamlessly morphs its color palette (e.g., warm golds for Happy, deep purples for Sad, crimson for Frustrated) using HSL interpolation.

### 🗣️ Seamless Voice & Audio
- **Neural Voice Pipeline:** Instant voice-in, voice-out communication using advanced Neural TTS (Edge-TTS) with fallback to gTTS.
- **Glitch-Free Streaming:** Audio chunks are pipelined and synthesized asynchronously, ensuring zero stuttering or gaps between sentences.
- **Voice Activity Detection:** Uses native browser VAD for fluid, natural back-and-forth conversation without needing wake words.

### 🛡️ Unbreakable LLM Fallback Chain
- LIS is highly resilient to API outages. She routes through a multi-provider fallback chain, prioritizing speed and intelligence.
- **The Cascade:** Anthropic (Primary) → NVIDIA NIM → Groq → Cerebras → Gemini → OpenRouter → Local Ollama.
- **Aggressive Timeouts:** Timeouts are tightly tuned (8-12 seconds) to ensure she fails over to a working provider instantly if one hangs, preventing dead air.

### 📚 Deep Memory & RAG
- **Three-Tier Memory System:** 
  1. **Short-term:** Rolling conversational summaries to keep context light.
  2. **Fact Recall (FTS5):** Blazing-fast SQLite full-text search for instantly recalling specific facts, tasks, or notes.
  3. **Deep Semantic RAG:** Vector embeddings via ChromaDB automatically store and retrieve deep context from past conversations and ingested documents.

### 🖥️ Windows Desktop Automation
- **System Control:** Adjust volume/brightness, control media playback, and manage system power states.
- **App Management:** Launch applications and execute arbitrary PowerShell commands safely.
- **Vision & Screen Awareness:** She can capture screenshots, analyze your current visual context, and assist with whatever is currently visible on your monitor.
- **Time Management:** Set alarms, manage active timers, and receive proactive reminders.

### 🌐 Web, OSINT, & Life Integration
- **Autonomous Web Browsing:** Built-in web scraper and search engine integration (DuckDuckGo/Tavily) to research topics, summarize news, and fetch real-time data.
- **Live Market Data:** Instant lookup for stock and cryptocurrency prices.
- **Email & Calendar:** Secure IMAP integration to read your latest emails, and iCal parsing to brief you on your daily schedule.

### 🤖 Autonomous Operations & Self-Healing
- **Proactive Daemon:** LIS operates constantly in the background. She can spontaneously initiate "learning cycles" to research topics while you are away.
- **Sub-Agent Spawning:** For complex tasks, LIS can spawn specialized sub-agents to investigate issues, debug code, or browse the web in the background while she continues chatting with you.
- **Self-Healing:** She possesses the ability to analyze her own codebase, locate errors, and implement fixes autonomously.

---

## 🚀 Quick Setup Guide

### 1. Requirements
- Python 3.10+
- Node.js & npm (for frontend)
- Windows 10/11

### 2. Install Backend Dependencies
Open a terminal in the root directory and run:
```powershell
# Install core Python packages
pip install -r requirements.txt

# Install optional (but recommended) packages for all features
pip install browser-use mediapipe screen-brightness-control
playwright install chromium
```

### 3. Environment Configuration
1. Copy `.env.example` to `.env`:
   ```powershell
   copy .env.example .env
   ```
2. Open `.env` and configure your API keys. **You must provide at least one LLM key (e.g., Groq, Gemini, or Anthropic).**

#### 📧 Free Email Integration (Gmail IMAP)
To allow LIS to read your emails:
1. Enable **2-Step Verification** on your Google Account.
2. Go to [App Passwords](https://myaccount.google.com/apppasswords), generate a password for "Windows Computer".
3. Add to `.env`:
   ```env
   GMAIL_ADDRESS=your-email@gmail.com
   GMAIL_APP_PASSWORD=your-16-char-password
   ```

#### 📅 Free Calendar Integration (Google Calendar)
1. Go to Google Calendar Settings -> click your calendar -> "Integrate calendar".
2. Copy the "Secret address in iCal format".
3. Add to `.env`:
   ```env
   GOOGLE_CALENDAR_ICAL_URL=https://calendar.google.com/calendar/ical/.../basic.ics
   ```

### 4. Install & Build Frontend
Open a **new terminal** and run:
```powershell
cd frontend
npm install
npm run build
```

---

## 🎮 Running LIS

Start the backend server (from the root directory):
```powershell
python server.py
```
> The server will start on `http://127.0.0.1:8340`.

**To interact with LIS:**
1. Open `http://localhost:5173` (if running `npm run dev` in frontend) or open `http://127.0.0.1:8340` (if serving the built frontend from the backend).
2. Click the glowing orb to initialize the microphone.
3. Simply speak to her! LIS will respond with her daily briefing based on your calendar, emails, and weather.

---

## 🧩 Plugin System (Skills)

LIS uses a highly dynamic and modular plugin system. Any `.py` file placed in the `plugins/` directory that inherits from `Skill` and registers itself will be automatically loaded on boot. Currently, LIS ships with **48+ built-in skills**.

## 🛑 Security Note
LIS has immense power over your system (she can execute commands, read files, edit code, and spawn background agents). Do not expose the port to the public internet unless you configure `LIS_AUTH_TOKEN` in the `.env` file.

---
*Built with Python, FastAPI, React, Three.js, and advanced ReAct LLM orchestrations.*
