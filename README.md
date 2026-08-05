# LIS — Living Intelligent System v4.0

![LIS UI Preview](https://img.shields.io/badge/LIS-Living_Intelligent_System-33aaff?style=for-the-badge)

LIS is an advanced, fully-autonomous desktop AI assistant with a 3D holographic interface, emotional intelligence, theory-of-mind, and seamless integration with your Windows environment.

## ✨ Features

- **🗣️ Neural Voice Interaction**: Instant voice-in, voice-out communication with sub-500ms latency.
- **🧠 Cognitive Core (v4.0)**: Tracks conversation context, emotional state (280 distinct states), and builds long-term memory via ChromaDB vector RAG.
- **👁️ Vision & Context**: Can see your screen, analyze screenshots, and answer questions about what you're looking at.
- **🖥️ System Integration**: Launch apps, control media, adjust volume/brightness, set alarms/timers.
- **🌐 Web & Research**: Browse the web, read emails, check your calendar, get stock/crypto prices, and summarize news.
- **🛠️ Self-Healing & Autonomous**: Can spawn sub-agents to fix its own code, learn from its mistakes, and build software using Claude Code.

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
To allow LIS to read your emails for free:
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
3. Simply speak to her! LIS will respond with her daily briefing.

---

## 🧩 Plugin System (Skills)

LIS uses a dynamic plugin system. Any `.py` file placed in `plugins/core/` that inherits from `Skill` and registers itself will be automatically loaded on boot. Currently, LIS ships with **48 built-in skills**.

## 🛑 Security Note
LIS has immense power over your system (can execute commands, read files, edit code). Do not expose the port to the public internet unless you configure `LIS_AUTH_TOKEN` in the `.env` file.

---
*Built with Python, FastAPI, React, Three.js, and advanced LLM orchestrations.*
