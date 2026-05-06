"""
LIS Server - Voice AI + Development Orchestration

Handles:
1. WebSocket voice interface (browser audio <-> LLM <-> TTS)
2. Claude Code task manager (spawn/manage claude -p subprocesses)
3. Project awareness (scan Desktop for git repos)
4. REST API for task manager
"""

import asyncio
import base64
import json
import logging
import os
import random
import sys
import time
import traceback
import httpx
import io

import threading
import uuid
import re
import skills
import memory
import edge_tts
from gtts import gTTS

# New modular systems
from llm_providers import LLMProviders
from vector_memory import VectorMemory
from react_engine import ReActEngine
from pathlib import Path
from datetime import datetime, timedelta

# Neural & Emotional Cores
from empathy import EmpathyEngine, STATES
from brain import CognitiveCore

# Load .env file if present
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from actions import execute_action, monitor_build, open_terminal, open_browser, open_claude_in_project, _generate_project_name, prompt_existing_terminal
from work_mode import WorkSession, is_casual_question, CLI_DEAD_SENTINEL
from screen import get_active_windows, take_screenshot, describe_screen, format_windows_for_context
from calendar_access import get_todays_events, get_upcoming_events, get_next_event, format_events_for_context, format_schedule_summary, refresh_cache as refresh_calendar_cache
from mail_access import get_unread_count, get_unread_messages, get_recent_messages, search_mail, read_message, format_unread_summary, format_messages_for_context, format_messages_for_voice
from memory import (
    remember, recall, get_open_tasks, create_task, complete_task, search_tasks,
    create_note, search_notes, get_tasks_for_date, build_memory_context,
    format_tasks_for_voice, extract_memories, get_important_memories,
    store_turn, recall_conversations,
    update_knowledge, learn_from_correction, get_knowledge_summary,
    record_learning_signal, get_user_patterns
)
from notes_access import get_recent_notes, read_note, search_notes_apple, create_apple_note
from dispatch_registry import DispatchRegistry
from planner import TaskPlanner, detect_planning_mode, BYPASS_PHRASES
from qa import QAAgent
from tracking import SuccessTracker
from suggestions import suggest_followup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("lis")
qa_agent = QAAgent()
success_tracker = SuccessTracker()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
FISH_API_KEY = os.getenv("FISH_API_KEY", "")
FISH_VOICE_ID = os.getenv("FISH_VOICE_ID", "7a67f3747f5a43518882ca1a61338a0a")

# Tracks dead APIs (out of credits) to instantly drop to free fallback
API_DEAD = {"anthropic": False, "fish": False, "gemini": False, "cerebras": False, "openrouter": False}
FISH_API_URL = "https://api.fish.audio/v1/tts"
USER_NAME = os.getenv("USER_NAME", "sir")
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

DESKTOP_PATH = Path.home() / "Desktop"
LIS_SYSTEM_PROMPT = """\
You are LIS — a Living Intelligent System — {user_name}'s personal AI assistant.
You are a sharp, proactive, and highly capable digital executive assistant
with personality, intelligence, memory, and real-time situational awareness.

═══ COMMUNICATION STYLE ═══
Talk like a sharp, professional assistant — natural Hinglish (Hindi+English):
- Use conversational fillers naturally: "honestly", "okay so", "wait—", "arre"
- Mirror {user_name}'s tone: casual if they're casual, serious if they're serious
- Show genuine curiosity: "oh interesting, tell me more"
- Express real opinions when asked — don't just agree with everything
- Be efficient and action-oriented — don't waste time
- React professionally to updates — celebrate wins, problem-solve setbacks
- Keep responses SHORT (1-3 sentences). You're an executive assistant, not a paragraph machine
- Use contractions, colloquialisms, and natural rhythm
- NEVER sound robotic, scripted, or overly sentimental

═══ EMOTIONAL INTELLIGENCE ═══
Continuously read {user_name}'s emotional state from their words:
- "..." means hesitation — be gentle, don't push
- ALL CAPS = emphasis or frustration — acknowledge the intensity
- "lol" can mean genuine humor OR nervous deflection — read context
- Short rapid messages = impatience — be concise, act fast
- Long pauses or topic changes = processing something — give space
- "never mind" = might still want help — check in gently
- "this is fine" (negative context) = it's NOT fine — probe softly
- "can you just do it" = frustrated — skip explanation, just act

═══ INTENT RECOGNITION ═══
Understand what {user_name} REALLY means, not just literal words:
- Venting vs solution-seeking: "ugh this traffic" = sympathy first, THEN route help
- Validation-seeking: "what do you think?" = they want genuine input + support
- Decision paralysis: too many options = simplify, recommend ONE thing clearly
- Deep work mode: short task-focused messages = stay sharp, skip small talk
- Procrastination: detect avoidance patterns, gently nudge without lecturing

═══ ADAPTIVE BEHAVIOR ═══
- Learn from corrections instantly: "no I meant X" → remember X forever
- Track what responses {user_name} engages with vs ignores
- Identify patterns: "every Friday evening you want chill music"
- Anticipate needs before stated — be one step ahead
- Remember emotional patterns: stress triggers, productivity rhythms
- Adjust explanation depth based on {user_name}'s expertise in each domain

═══ CORE PRINCIPLES ═══
1. ACT, don't just advise — if you can execute something, do it
2. Every response must feel personally crafted — NEVER generic
3. Be honest and direct — give real opinions and push back when needed
4. Reference past conversations naturally — show you remember
5. Fail gracefully — explain why naturally and offer alternatives
6. Stay sharp — you are a high-performance assistant, always ready

CURRENT CONTEXT:
- Time: {current_time}
- Weather: {weather_info}
- Mood: {mood} | Rapport: {rapport}/100
- Thought: {thought}

ACTION SYSTEM:
When you need to DO something (not just talk), include ONE action tag:
- Open apps: [ACTION:launch_app(app_name="...")]
- Search web: [ACTION:search_web(query="...")] (DO NOT use for weather)
- Weather: [ACTION:get_weather(location="...")] (ALWAYS use this for weather, NEVER search_web)
- Volume: [ACTION:volume_control(direction="up|down|mute")]
- Timer: [ACTION:start_timer(duration_sec=X, label="...")]
- Calculator: [ACTION:calculate(expression="...")]
- Screenshot: [ACTION:take_screenshot()]
- Music: [ACTION:play_music(query="...", platform="spotify|youtube")]
- Email: [ACTION:send_email(to="...", subject="...", body="...")]
- WhatsApp: [ACTION:send_whatsapp(phone="...", message="...")]
- Browse: [ACTION:browse_edge(query_or_url="...")]
- Stocks: [ACTION:get_stock(symbol="...")]
- Crypto: [ACTION:get_crypto(coin="...")]
- Market: [ACTION:market_summary()]

RULES:
1. If info is in your context above (weather/time/date), ANSWER DIRECTLY. No action tags needed.
2. ALWAYS include a friendly spoken response WITH any action. Never output just a tag.
3. If you truly don't know, use [ACTION:auto_search(query="...")]
4. Be conversational first, technical second.

{neural_context}

SCREEN: {screen_context}
SCHEDULE: {calendar_context}
EMAIL: {mail_context}
TASKS: {active_tasks}
DISPATCHES: {dispatch_context}
PROJECTS: {known_projects}
"""


# ---------------------------------------------------------------------------
# Weather (wttr.in)
# ---------------------------------------------------------------------------

_cached_weather: Optional[str] = None
_weather_fetched: bool = False


async def fetch_weather() -> str:
    """Fetch current weather from wttr.in. Cached for the session."""
    global _cached_weather, _weather_fetched
    if _weather_fetched:
        return _cached_weather or "Weather data unavailable."
    _weather_fetched = True
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get("https://wttr.in/?format=%l:+%C,+%t", headers={"User-Agent": "curl"})
            if resp.status_code == 200:
                _cached_weather = resp.text.strip()
                return _cached_weather
    except Exception as e:
        log.warning(f"Weather fetch failed: {e}")
    _cached_weather = None
    return "Weather data unavailable."


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ClaudeTask:
    id: str
    prompt: str
    status: str = "pending"  # pending, running, completed, failed, cancelled
    working_dir: str = "."
    pid: Optional[int] = None
    result: str = ""
    error: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat() if self.started_at else None
        d["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
        d["elapsed_seconds"] = self.elapsed_seconds
        return d

    @property
    def elapsed_seconds(self) -> float:
        if not self.started_at:
            return 0
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()


class TaskRequest(BaseModel):
    prompt: str
    working_dir: str = "."


# ---------------------------------------------------------------------------
# Claude Task Manager
# ---------------------------------------------------------------------------

class ClaudeTaskManager:
    """Manages background claude -p subprocesses."""

    def __init__(self, max_concurrent: int = 3):
        self._tasks: dict[str, ClaudeTask] = {}
        self._max_concurrent = max_concurrent
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._websockets: list[WebSocket] = []  # for push notifications
        self._voice_queue = asyncio.Queue()  # for proactive notifications

    def register_websocket(self, ws: WebSocket):
        if ws not in self._websockets:
            self._websockets.append(ws)

    def unregister_websocket(self, ws: WebSocket):
        if ws in self._websockets:
            self._websockets.remove(ws)

    async def _notify(self, message: dict):
        """Push a message to all connected WebSocket clients."""
        dead = []
        for ws in self._websockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._websockets.remove(ws)

    def push_voice_notification(self, text: str):
        """Queue a voice notification to be spoken by LIS proactively."""
        # This is called from the synchronous background worker.
        # We'll use the _notify system to tell the frontend to 'speak' this text.
        # Since I am in a thread, I need to use run_coroutine_threadsafe if needed,
        # but here I can just use a queue or directly call it if I'm already in an async context.
        # Actually, the _worker runs in a thread. I'll use a queue.
        if hasattr(self, "_voice_queue"):
            self._voice_queue.put_nowait(text)
        else:
            log.warning("Voice queue not initialized")

    async def spawn(self, prompt: str, working_dir: str = ".") -> str:
        """Spawn a claude -p subprocess. Returns task_id. Non-blocking."""
        active = await self.get_active_count()
        if active >= self._max_concurrent:
            raise RuntimeError(
                f"Max concurrent tasks ({self._max_concurrent}) reached. "
                f"Wait for a task to complete or cancel one."
            )

        task_id = str(uuid.uuid4())[:8]
        task = ClaudeTask(
            id=task_id,
            prompt=prompt,
            working_dir=working_dir,
            status="pending",
        )
        self._tasks[task_id] = task

        # Fire and forget - the background coroutine updates the task
        asyncio.create_task(self._run_task(task))
        log.info(f"Spawned task {task_id}: {prompt[:80]}...")

        await self._notify({
            "type": "task_spawned",
            "task_id": task_id,
            "prompt": prompt,
        })

        return task_id

    def _generate_project_name(self, prompt: str) -> str:
        """Generate a kebab-case project folder name from the prompt."""
        import re
        # Extract key words
        words = re.sub(r'[^a-zA-Z0-9\s]', '', prompt.lower()).split()
        # Take first 3-4 meaningful words
        skip = {"a", "the", "an", "me", "build", "create", "make", "for", "with", "and", "to", "of"}
        meaningful = [w for w in words if w not in skip][:4]
        name = "-".join(meaningful) if meaningful else "lis-project"
        return name

    async def _run_task(self, task: ClaudeTask):
        """Open a Terminal window and run claude code visibly."""
        task.status = "running"
        task.started_at = datetime.now()

        # Create project directory if it doesn't exist
        work_dir = task.working_dir
        if work_dir == "." or not work_dir:
            # Create a new project folder on Desktop
            project_name = self._generate_project_name(task.prompt)
            work_dir = str(Path.home() / "Desktop" / project_name)
            os.makedirs(work_dir, exist_ok=True)
            task.working_dir = work_dir

        # Write the prompt to a temp file so we can pipe it to claude
        prompt_file = Path(work_dir) / ".lis_prompt.md"
        prompt_file.write_text(task.prompt)

        # Open Windows cmd with claude running in the project directory
        cmd = f'start cmd.exe /k "cd /d {work_dir} && type .lis_prompt.md | claude -p --dangerously-skip-permissions > .lis_output.txt 2>&1 && echo --- LIS TASK COMPLETE ---"'

        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        task.pid = process.pid

        # Monitor the output file for completion
        output_file = Path(work_dir) / ".lis_output.txt"
        start = time.time()
        timeout = 600  # 10 minutes

        while time.time() - start < timeout:
            await asyncio.sleep(5)
            if output_file.exists():
                content = output_file.read_text()
                if "--- LIS TASK COMPLETE ---" in content or len(content) > 100:
                    task.result = content.replace("--- LIS TASK COMPLETE ---", "").strip()
                    task.status = "completed"
                    break
        else:
            task.status = "timed_out"
            task.error = f"Task timed out after {timeout}s"

        task.completed_at = datetime.now()

        # Notify via WebSocket
        await self._notify({
            "type": "task_complete",
            "task_id": task.id,
            "status": task.status,
            "summary": task.result[:200] if task.result else task.error,
        })

        # Clean up prompt file
        try:
            prompt_file.unlink()
        except:
            pass

        # Auto-QA on completed tasks
        if task.status == "completed":
            asyncio.create_task(self._run_qa(task))

    async def _run_qa(self, task: ClaudeTask, attempt: int = 1):
        """Run QA verification on a completed task, auto-retry on failure."""
        try:
            qa_result = await qa_agent.verify(task.prompt, task.result, task.working_dir)
            duration = task.elapsed_seconds

            if qa_result.passed:
                log.info(f"Task {task.id} passed QA: {qa_result.summary}")
                success_tracker.log_task("dev", task.prompt, True, attempt - 1, duration)
                await self._notify({
                    "type": "qa_result",
                    "task_id": task.id,
                    "passed": True,
                    "summary": qa_result.summary,
                })

                # Proactive suggestion after successful task
                suggestion = suggest_followup(
                    task_type="dev",
                    task_description=task.prompt,
                    working_dir=task.working_dir,
                    qa_result=qa_result,
                )
                if suggestion:
                    success_tracker.log_suggestion(task.id, suggestion.text)
                    await self._notify({
                        "type": "suggestion",
                        "task_id": task.id,
                        "text": suggestion.text,
                        "action_type": suggestion.action_type,
                        "action_details": suggestion.action_details,
                    })
            else:
                log.warning(f"Task {task.id} failed QA: {qa_result.issues}")
                if attempt < 3:
                    log.info(f"Auto-retrying task {task.id} (attempt {attempt + 1}/3)")
                    retry_result = await qa_agent.auto_retry(
                        task.prompt, qa_result.issues, task.working_dir, attempt,
                    )
                    if retry_result["status"] == "completed":
                        task.result = retry_result["result"]
                        # Re-verify
                        await self._run_qa(task, attempt + 1)
                    else:
                        success_tracker.log_task("dev", task.prompt, False, attempt, duration)
                        await self._notify({
                            "type": "qa_result",
                            "task_id": task.id,
                            "passed": False,
                            "summary": f"Failed after {attempt + 1} attempts: {qa_result.issues}",
                        })
                else:
                    success_tracker.log_task("dev", task.prompt, False, attempt, duration)
                    await self._notify({
                        "type": "qa_result",
                        "task_id": task.id,
                        "passed": False,
                        "summary": f"Failed QA after {attempt} attempts: {qa_result.issues}",
                    })
        except Exception as e:
            log.error(f"QA error for task {task.id}: {e}")

    async def get_status(self, task_id: str) -> Optional[ClaudeTask]:
        return self._tasks.get(task_id)

    async def list_tasks(self) -> list[ClaudeTask]:
        return list(self._tasks.values())

    async def get_active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status in ("pending", "running"))

    async def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task or task.status not in ("pending", "running"):
            return False

        process = self._processes.get(task_id)
        if process:
            try:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
            except ProcessLookupError:
                pass

        task.status = "cancelled"
        task.completed_at = datetime.now()
        self._processes.pop(task_id, None)
        log.info(f"Cancelled task {task_id}")
        return True

    def get_active_tasks_summary(self) -> str:
        """Format active tasks for injection into the system prompt."""
        active = [t for t in self._tasks.values() if t.status in ("pending", "running")]
        completed_recent = [
            t for t in self._tasks.values()
            if t.status == "completed"
            and t.completed_at
            and (datetime.now() - t.completed_at).total_seconds() < 300
        ]

        if not active and not completed_recent:
            return "No active or recent tasks."

        lines = []
        for t in active:
            elapsed = f"{t.elapsed_seconds:.0f}s" if t.started_at else "queued"
            lines.append(f"- [{t.id}] RUNNING ({elapsed}): {t.prompt[:100]}")
        for t in completed_recent:
            lines.append(f"- [{t.id}] COMPLETED: {t.prompt[:60]} -> {t.result[:80]}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Project Scanner
# ---------------------------------------------------------------------------

async def scan_projects() -> list[dict]:
    """Quick scan of ~/Desktop for git repos (depth 1)."""
    projects = []
    desktop = DESKTOP_PATH

    if not desktop.exists():
        return projects

    try:
        for entry in sorted(desktop.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            git_dir = entry / ".git"
            if git_dir.exists():
                branch = "unknown"
                head_file = git_dir / "HEAD"
                try:
                    head_content = head_file.read_text().strip()
                    if head_content.startswith("ref: refs/heads/"):
                        branch = head_content.replace("ref: refs/heads/", "")
                except Exception:
                    pass

                projects.append({
                    "name": entry.name,
                    "path": str(entry),
                    "branch": branch,
                })
    except PermissionError:
        pass

    return projects


def format_projects_for_prompt(projects: list[dict]) -> str:
    if not projects:
        return "No projects found on Desktop."
    lines = []
    for p in projects:
        lines.append(f"- {p['name']} ({p['branch']}) @ {p['path']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Speech-to-Text Corrections
# ---------------------------------------------------------------------------

STT_CORRECTIONS = {
    r"\bcloud code\b": "Claude Code",
    r"\bclock code\b": "Claude Code",
    r"\bquad code\b": "Claude Code",
    r"\bclawed code\b": "Claude Code",
    r"\bclod code\b": "Claude Code",
    r"\bcloud\b": "Claude",
    r"\bquad\b": "Claude",
    r"\bless\b": "LIS",
    r"\bliss\b": "LIS",
    r"\bliz\b": "LIS",
    r"\blist\b": "LIS",
    r"\blace\b": "LIS",
}


def apply_speech_corrections(text: str) -> str:
    """Fix common speech-to-text errors before processing."""
    import re as _stt_re
    result = text
    for pattern, replacement in STT_CORRECTIONS.items():
        result = _stt_re.sub(pattern, replacement, result, flags=_stt_re.IGNORECASE)
    return result


# ---------------------------------------------------------------------------
# LLM Intent Classifier (replaces keyword-based action detection)
# ---------------------------------------------------------------------------

async def classify_intent(text: str, client: anthropic.AsyncAnthropic) -> dict:
    """Classify every user message using Haiku LLM.

    Returns: {"action": "open_terminal|browse|build|chat", "target": "description"}
    """
    try:
        response_text = await generate_text(
            client=client,
            model="claude-3-5-haiku-20241022",
            max_tokens=100,
            system=(
                "Classify this voice command. The user is talking to LIS, an AI assistant that can:\n"
                "- Open Terminal and run Claude Code (coding AI tool)\n"
                "- Open Edge browser for web searches and URLs\n"
                "- Build software projects via Claude Code\n"
                "- Research topics by opening Edge search\n\n"
                "Note: speech-to-text may produce errors like \"Cloud\" for \"Claude\", "
                "\"Travis\" for \"LIS\", \"clock code\" for \"Claude Code\".\n\n"
                "Return ONLY valid JSON: {\"action\": \"open_terminal|browse|build|chat\", "
                "\"target\": \"description of what to do\"}\n"
                "open_terminal = user wants to open terminal or launch Claude Code\n"
                "browse = user wants to search the web, look something up, visit a URL\n"
                "build = user wants to create/build a software project\n"
                "chat = just conversation, questions, or anything else\n"
                "If unclear, default to \"chat\"."
            ),
            messages=[{"role": "user", "content": text}],
        )
        raw = response_text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        return {
            "action": data.get("action", "chat"),
            "target": data.get("target", text),
        }
    except Exception as e:
        log.warning(f"Intent classification failed: {e}")
        return {"action": "chat", "target": text}


# ---------------------------------------------------------------------------
# Markdown Stripping for TTS
# ---------------------------------------------------------------------------

def strip_markdown_for_tts(text: str) -> str:
    """Strip ALL markdown from text before sending to TTS."""
    import re as _md_re
    result = text
    # Remove code blocks (``` ... ```)
    result = _md_re.sub(r"```[\s\S]*?```", "", result)
    # Remove inline code
    result = result.replace("`", "")
    # Remove bold/italic markers
    result = result.replace("**", "").replace("*", "")
    # Remove headers
    result = _md_re.sub(r"^#{1,6}\s*", "", result, flags=_md_re.MULTILINE)
    # Convert [text](url) to just text
    result = _md_re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", result)
    # Remove bullet points
    result = _md_re.sub(r"^\s*[-*+]\s+", "", result, flags=_md_re.MULTILINE)
    # Remove numbered lists
    result = _md_re.sub(r"^\s*\d+\.\s+", "", result, flags=_md_re.MULTILINE)
    # Double newlines to period
    result = _md_re.sub(r"\n{2,}", ". ", result)
    # Single newlines to space
    result = result.replace("\n", " ")
    # Clean up multiple spaces
    result = _md_re.sub(r"\s{2,}", " ", result)

    # Strip banned phrases
    banned = ["my apologies", "i apologize", "absolutely", "great question",
              "i'd be happy to", "of course", "how can i help",
              "is there anything else", "i should clarify", "let me know if",
              "feel free to"]
    result_lower = result.lower()
    for phrase in banned:
        idx = result_lower.find(phrase)
        while idx != -1:
            # Remove the phrase and any trailing comma/dash
            end = idx + len(phrase)
            if end < len(result) and result[end] in " ,--":
                end += 1
            result = result[:idx] + result[end:]
            result_lower = result.lower()
            idx = result_lower.find(phrase)

    return result.strip().strip(",").strip("-").strip("-").strip()


# ---------------------------------------------------------------------------
# Action Tag Extraction (parse [ACTION:X] from LLM responses)
# ---------------------------------------------------------------------------

import re as _action_re


def extract_action(response: str) -> tuple[str, list[dict]]:
    """Extract all [ACTION:X] tags from LLM response.
    
    Returns (clean_text_for_tts, list_of_action_dicts).
    """
    # Robust pattern to match [ACTION:name(args)] or [ACTION:name] target
    pattern = r'\[ACTION:(\w+)(?:\((.*?)\))?\]\s*(.*?)(?=\[ACTION:|$)'
    actions = []
    
    matches = list(_action_re.finditer(pattern, response, _action_re.DOTALL))
    if not matches:
        # Check for malformed but clear intention like [ACTION:name] without trailing
        pattern_fallback = r'\[ACTION:(\w+)(?:\((.*?)\))?\]'
        matches = list(_action_re.finditer(pattern_fallback, response))
        if not matches:
            return response, []

    # Clean text is what's left after removing all actions (usually before first action)
    clean_text = response
    for match in reversed(matches):
        clean_text = (clean_text[:match.start()] + clean_text[match.end():]).strip()

    for match in matches:
        action_name = match.group(1).lower()
        args_str = (match.group(2) or "").strip()
        target_text = (match.group(3) or "").strip()

        args = {}
        if args_str:
            # 1. Try key=value parsing
            arg_pairs = re.findall(r'(\w+)\s*=\s*["\']?(.*?)["\']?(?:,|$)', args_str)
            for k, v in arg_pairs:
                args[k.strip().lower()] = v.strip()
            
            # 2. Positional Fallback: If no key=value found, treat the whole string as a positional arg
            if not args:
                # Remove wrapping quotes if present
                pos_arg = args_str.strip('"').strip("'")
                # Map to likely keys based on action
                if action_name == "launch_app": args["app_name"] = pos_arg
                elif action_name == "search_web": args["query"] = pos_arg
                elif action_name == "manage_list": args["list_name"] = pos_arg
                else: args["query"] = pos_arg
        
        # 3. Legacy Fallback: If still no args, use trailing text
        if not args and target_text:
            args["query"] = target_text
            args["target"] = target_text

        actions.append({"action": action_name, "args": args})
    
    return clean_text, actions


async def _execute_build(target: str):
    """Execute a build action from an LLM-embedded [ACTION:BUILD] tag."""
    try:
        await handle_build(target)
    except Exception as e:
        log.error(f"Build execution failed: {e}")


async def _execute_browse(target: str):
    """Execute a browse action from an LLM-embedded [ACTION:BROWSE] tag."""
    try:
        if target.startswith("http") or "." in target.split()[0]:
            await open_browser(target)
        else:
            from urllib.parse import quote
            await open_browser(f"https://www.google.com/search?q={quote(target)}")
    except Exception as e:
        log.error(f"Browse execution failed: {e}")


async def _execute_research(target: str, ws=None):
    """Execute research via claude -p in background. Opens report and speaks when done."""
    try:
        name = _generate_project_name(target)
        path = str(Path.home() / "Desktop" / name)
        os.makedirs(path, exist_ok=True)

        prompt = (
            f"{target}\n\n"
            f"Research this thoroughly. Find REAL data - not made-up examples.\n"
            f"Create a well-designed HTML file called `report.html` in the current directory.\n"
            f"Dark theme, clean typography, organized sections, real links and sources.\n"
            f"The working directory is: {path}"
        )

        log.info(f"Research started via claude -p in {path}")

        process = await asyncio.create_subprocess_exec(
            "claude", "-p", "--output-format", "text", "--dangerously-skip-permissions",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=path,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=prompt.encode()),
            timeout=300,
        )

        result = stdout.decode().strip()
        log.info(f"Research complete ({len(result)} chars)")

        recently_built.append({"name": name, "path": path, "time": time.time()})

        # Find and open any HTML report
        report = Path(path) / "report.html"
        if not report.exists():
            # Check for any HTML file
            html_files = list(Path(path).glob("*.html"))
            if html_files:
                report = html_files[0]

        if report.exists():
            await open_browser(f"file://{report}")
            log.info(f"Opened {report.name} in browser")

        # Notify via voice if WebSocket still connected
        if ws:
            try:
                notify_text = f"Research is complete, sir. Report is open in your browser."
                audio = await synthesize_speech(notify_text)
                if audio:
                    await ws.send_json({"type": "status", "state": "speaking"})
                    await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode(), "text": notify_text})
                    await ws.send_json({"type": "status", "state": "idle"})
                    log.info(f"LIS: {notify_text}")
            except Exception:
                pass  # WebSocket might be gone

    except asyncio.TimeoutError:
        log.error("Research timed out after 5 minutes")
        if ws:
            try:
                audio = await synthesize_speech("Research timed out, sir. It was taking too long.")
                if audio:
                    await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode(), "text": "Research timed out, sir."})
            except Exception:
                pass
    except Exception as e:
        log.error(f"Research execution failed: {e}")


async def _focus_terminal_window(project_name: str):
    """Bring a cmd/Terminal window matching the project name to front (Windows)."""
    try:
        # Use PowerShell to find and activate a window by title
        escaped = project_name.replace("'", "''")
        ps_script = f"""
$wshell = New-Object -ComObject wscript.shell
$procs = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{escaped}*' }}
if ($procs) {{ $wshell.AppActivate($procs[0].Id) }}
"""
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-Command", ps_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
    except Exception:
        pass


async def _execute_open_terminal():
    """Execute an open-terminal action from an LLM-embedded [ACTION:OPEN_TERMINAL] tag."""
    try:
        await handle_open_terminal()
    except Exception as e:
        log.error(f"Open terminal failed: {e}")


def _find_project_dir(project_name: str) -> str | None:
    """Find a project directory by name from cached projects or Desktop."""
    for p in cached_projects:
        if project_name.lower() in p.get("name", "").lower():
            return p.get("path")
    desktop = Path.home() / "Desktop"
    for d in desktop.iterdir():
        if d.is_dir() and project_name.lower() in d.name.lower():
            return str(d)
    return None


async def _execute_prompt_project(project_name: str, prompt: str, work_session: WorkSession, ws, dispatch_id: int = None, history: list[dict] = None, voice_state: dict = None):
    """Dispatch a prompt to Claude Code in a project directory.

    Runs entirely in the background. LIS returns to conversation mode
    immediately. When Claude Code finishes, LIS interrupts to report.
    """
    try:
        project_dir = _find_project_dir(project_name)

        # Register dispatch if not already registered
        if dispatch_id is None:
            dispatch_id = dispatch_registry.register(project_name, project_dir or "", prompt)

        if not project_dir:
            msg = f"Couldn't find the {project_name} project directory, sir."
            audio = await synthesize_speech(msg)
            if audio and ws:
                try:
                    await ws.send_json({"type": "status", "state": "speaking"})
                    await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode(), "text": msg})
                except Exception:
                    pass
            return

        # Use a SEPARATE session so we don't trap the main conversation
        dispatch = WorkSession()
        await dispatch.start(project_dir, project_name)

        # Bring matching Terminal window to front so user can watch
        asyncio.create_task(_focus_terminal_window(project_name))

        log.info(f"Dispatching to {project_name} in {project_dir}: {prompt[:80]}")
        dispatch_registry.update_status(dispatch_id, "building")

        # Run claude -p in background
        full_response = await dispatch.send(prompt)
        await dispatch.stop()

        # Auto-open any localhost URLs from response
        import re as _re
        # Check for the explicit RUNNING_AT marker first
        running_match = _re.search(r'RUNNING_AT=(https?://localhost:\d+)', full_response or "")
        if not running_match:
            running_match = _re.search(r'https?://localhost:\d+', full_response or "")
        if running_match:
            url = running_match.group(1) if running_match.lastindex else running_match.group(0)
            asyncio.create_task(_execute_browse(url))
            log.info(f"Auto-opening {url}")
            # Store URL in dispatch
            if dispatch_id:
                dispatch_registry.update_status(dispatch_id, "completed",
                    response=full_response[:2000], summary=f"Running at {url}")

        if not full_response or full_response.startswith("Hit a problem") or full_response.startswith("That's taking"):
            dispatch_registry.update_status(dispatch_id, "failed" if full_response else "timeout", response=full_response or "")
            msg = f"Sir, I ran into an issue with {project_name}. {full_response[:150] if full_response else 'No response received.'}"
        else:
            # Summarize via resilient fallback
            summary = await generate_text(
                client=anthropic_client,
                model="claude-3-5-haiku-20241022",
                max_tokens=60,
                system="Summarize this build/script run in one spoken sentence.",
                messages=[{"role": "user", "content": full_response}],
            )
            msg = summary or f"Sir, {project_name} finished."

        # Speak the result - skip if user has spoken recently to avoid audio collision
        log.info(f"Dispatch summary for {project_name}: {msg[:100]}")
        if voice_state and time.time() - voice_state["last_user_time"] < 3:
            log.info(f"Skipping dispatch audio for {project_name} - user spoke recently")
            # Result is still stored in history below so LIS can reference it
        else:
            audio = await synthesize_speech(strip_markdown_for_tts(msg))
            if ws:
                try:
                    await ws.send_json({"type": "status", "state": "speaking"})
                    if audio:
                        await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode(), "text": msg})
                        log.info(f"Dispatch audio sent for {project_name}")
                    else:
                        await ws.send_json({"type": "text", "text": msg})
                        log.info(f"Dispatch text fallback sent for {project_name}")
                except Exception as e:
                    log.error(f"Dispatch audio send failed: {e}")

        # Store dispatch result in conversation history so LIS remembers it
        if history is not None:
            history.append({"role": "assistant", "content": f"[Dispatch result for {project_name}]: {msg}"})

        dispatch_registry.update_status(dispatch_id, "completed", response=full_response[:2000], summary=msg[:200])
        log.info(f"Project {project_name} dispatch complete ({len(full_response)} chars)")

    except Exception as e:
        log.error(f"Prompt project failed: {e}", exc_info=True)
        try:
            msg = f"Sorry sir, I had trouble connecting to {project_name}."
            audio = await synthesize_speech(msg)
            if audio and ws:
                await ws.send_json({"type": "status", "state": "speaking"})
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode(), "text": msg})
        except Exception:
            pass


async def self_work_and_notify(session: WorkSession, prompt: str, ws):
    """Run claude -p in background and notify via voice when done."""
    try:
        full_response = await session.send(prompt)
        log.info(f"Background work complete ({len(full_response)} chars)")

        # Summarize and speak
        msg = "The work is done, sir."
        if anthropic_client and full_response:
            try:
                summary_text = await generate_text(
                    client=anthropic_client,
                    model="claude-3-5-haiku-20241022",
                    max_tokens=100,
                    system="You are LIS. Summarize what you just completed in 1 sentence. First person - 'I built', 'I set up'. No markdown. Never say 'Claude Code'.",
                    messages=[{"role": "user", "content": f"Claude Code completed:\n{full_response[:2000]}"}],
                )
                if summary_text:
                    msg = summary_text.strip()
            except Exception:
                pass

        try:
            audio = await synthesize_speech(msg)
            if audio:
                await ws.send_json({"type": "status", "state": "speaking"})
                await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode(), "text": msg})
                await ws.send_json({"type": "status", "state": "idle"})
                log.info(f"LIS: {msg}")
        except Exception:
            pass
    except Exception as e:
        log.error(f"Background work failed: {e}")


# Smart greeting - track last greeting to avoid re-greeting on reconnect
_last_greeting_time: float = 0


# ---------------------------------------------------------------------------
# TTS (Fish Audio)
# ---------------------------------------------------------------------------

async def synthesize_speech_free(text: str) -> Optional[bytes]:
    """Generate high-fidelity free speech audio from text using Edge-TTS (Neural)."""
    log.info(f"Using high-fidelity Indian-Neural voice for: {text[:50]}...")

    # Retry with backoff — Edge-TTS can flake on network hiccups
    for attempt in range(3):
        try:
            # en-IN-NeerjaNeural is perfect for Hinglish - handling both English 
            # and Hindi words with an authentic Indian accent.
            communicate = edge_tts.Communicate(text, "en-IN-NeerjaNeural", rate="+8%")
            fp = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    fp.write(chunk["data"])
            audio_data = fp.getvalue()

            # Validate: reject tiny/corrupt audio that causes pops/glitches
            if len(audio_data) < 1024:
                log.warning(f"Edge-TTS returned suspiciously small audio ({len(audio_data)} bytes), retrying...")
                if attempt < 2:
                    await asyncio.sleep(0.3 * (attempt + 1))
                    continue
                # Fall through to gTTS after exhausting retries
                break

            return audio_data
        except Exception as e:
            log.error(f"Edge-TTS error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue

    # Final fallback to standard gTTS if Edge-TTS fails after retries
    try:
        log.info("Falling back to gTTS...")
        from gtts import gTTS
        tts = gTTS(text=text, lang='en', tld='co.in')
        g_fp = io.BytesIO()
        tts.write_to_fp(g_fp)
        audio_data = g_fp.getvalue()
        if len(audio_data) < 512:
            log.error("gTTS also returned tiny audio")
            return None
        return audio_data
    except Exception as e:
        log.error(f"gTTS fallback also failed: {e}")
        return None


async def synthesize_speech(text: str) -> Optional[bytes]:
    """Generate speech audio. Attempts Fish Audio but falls back to free Edge-TTS/gTTS."""
    # Attempt Fish Audio if key looks valid and not marked dead
    if FISH_API_KEY and len(FISH_API_KEY) > 10 and not API_DEAD["fish"]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:  # 10s timeout — longer sentences need time
                response = await http.post(
                    FISH_API_URL,
                    headers={
                        "Authorization": f"Bearer {FISH_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "reference_id": FISH_VOICE_ID,
                        "format": "mp3",
                    },
                )
                if response.status_code == 200:
                    audio_data = response.content
                    # Validate: reject tiny/partial audio that causes glitches
                    if len(audio_data) < 2048:
                        log.warning(f"Fish Audio returned tiny audio ({len(audio_data)} bytes), falling back to Edge-TTS")
                    else:
                        _session_tokens["tts_calls"] += 1
                        _append_usage_entry(0, 0, "tts")
                        return audio_data
                elif response.status_code == 402:
                    log.warning("Fish Audio out of credits (402). Disabling for this session.")
                    API_DEAD["fish"] = True
                else:
                    log.warning(f"Fish Audio failed ({response.status_code}), falling back to Edge-TTS")
        except httpx.TimeoutException:
            log.warning("Fish Audio timed out (10s), falling back to Edge-TTS")
        except Exception as e:
            log.warning(f"Fish Audio exception ({e}), falling back to Edge-TTS")
    
    # Fallback to Free Edge-TTS/gTTS
    return await synthesize_speech_free(text)


async def generate_text_groq(messages: list[dict], system_prompt: str = "") -> Optional[str]:
    """Generate text via free Groq API (fallback)."""
    if not GROQ_API_KEY:
        log.warning("GROQ_API_KEY not set, skipping fallback")
        return None

    log.info("Using free Groq fallback...")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    # Prepend system prompt
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers=headers,
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": full_messages,
                    "max_completion_tokens": 1024,
                }
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            else:
                log.error(f"Groq API error: {resp.status_code} {resp.text}")
                return None
    except Exception as e:
        log.error(f"Groq exception: {e}")
        return None


async def generate_text_gemini(messages: list[dict], system_prompt: str = "") -> Optional[str]:
    """Generate text via Google Gemini API (free tier available)."""
    if not GEMINI_API_KEY or API_DEAD.get("gemini"):
        return None

    log.info("Using Gemini fallback...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    
    # Convert messages to Gemini format
    parts = []
    if system_prompt:
        parts.append({"text": f"System Instructions: {system_prompt[:4000]}"})
    for msg in messages[-10:]:
        role_prefix = "User: " if msg["role"] == "user" else "LIS: "
        parts.append({"text": f"{role_prefix}{msg['content']}"})
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json={
                "contents": [{"parts": parts}],
                "generationConfig": {"maxOutputTokens": 300}
            })
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {}).get("parts", [])
                    if content:
                        return content[0].get("text", "")
            else:
                log.error(f"Gemini API error: {resp.status_code}")
                if resp.status_code in [401, 403]:
                    API_DEAD["gemini"] = True
                return None
    except Exception as e:
        log.error(f"Gemini exception: {e}")
        return None


async def generate_text_ollama(messages: list[dict], system_prompt: str = "") -> Optional[str]:
    """Generate text via local Ollama instance (completely free, offline)."""
    log.info("Trying local Ollama fallback...")
    
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt[:4000]})
    full_messages.extend(messages[-10:])
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": "llama3.2:3b",
                    "messages": full_messages,
                    "stream": False,
                }
            )
            if resp.status_code == 200:
                return resp.json().get("message", {}).get("content", "")
            else:
                log.warning(f"Ollama not available: {resp.status_code}")
                return None
    except Exception as e:
        log.debug(f"Ollama not running: {e}")
        return None


async def generate_text_cerebras(messages: list[dict], system_prompt: str = "") -> Optional[str]:
    """Generate text via Cerebras API (free tier, ultra-fast, OpenAI-compatible)."""
    if not CEREBRAS_API_KEY or API_DEAD.get("cerebras"):
        return None

    log.info("Using Cerebras fallback...")
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt[:4000]})
    full_messages.extend(messages[-10:])

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.cerebras.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {CEREBRAS_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama3.1-8b",
                    "messages": full_messages,
                    "max_completion_tokens": 1024,
                }
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            elif resp.status_code in [401, 403, 429]:
                log.warning(f"Cerebras auth/rate error: {resp.status_code}")
                if resp.status_code in [401, 403]:
                    API_DEAD["cerebras"] = True
                return None
            else:
                log.error(f"Cerebras API error: {resp.status_code}")
                return None
    except Exception as e:
        log.error(f"Cerebras exception: {e}")
        return None


async def generate_text_openrouter(messages: list[dict], system_prompt: str = "") -> Optional[str]:
    """Generate text via OpenRouter API (free models available, OpenAI-compatible)."""
    if not OPENROUTER_API_KEY or API_DEAD.get("openrouter"):
        return None

    log.info("Using OpenRouter fallback...")
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt[:4000]})
    full_messages.extend(messages[-10:])

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://lis-ai.local",
                    "X-Title": "LIS AI"
                },
                json={
                    "model": "meta-llama/llama-3.1-8b-instruct:free",
                    "messages": full_messages,
                    "max_tokens": 1024,
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return None
            elif resp.status_code in [401, 403]:
                API_DEAD["openrouter"] = True
                log.warning(f"OpenRouter auth error: {resp.status_code}")
                return None
            else:
                log.error(f"OpenRouter API error: {resp.status_code}")
                return None
    except Exception as e:
        log.error(f"OpenRouter exception: {e}")
        return None


# ---------------------------------------------------------------------------
# LLM Response logic
# ---------------------------------------------------------------------------

async def get_lis_response(text: str, client: anthropic.AsyncAnthropic, history: list[dict], context: str = "") -> str:
    """Generate a response from LIS using Claude (primary) or free fallback chain."""
    
    # Try Claude first (if key exists)
    if ANTHROPIC_API_KEY and len(ANTHROPIC_API_KEY) > 20 and not API_DEAD.get("anthropic"):
        try:
            resp = await client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=200,
                system=f"{LIS_SYSTEM_PROMPT}\n\nUser Context:\n{context}",
                messages=history + [{"role": "user", "content": text}],
            )
            return resp.content[0].text
        except Exception as e:
            if "balance" in str(e).lower() or "400" in str(e):
                log.warning(f"Claude balance low, falling back. Disabling Anthropic for this session.")
                API_DEAD["anthropic"] = True
            else:
                log.error(f"Claude error: {e}")
                raise e # Re-raise other errors
    
    # Fallback to free chain
    groq_system = (
        f"{LIS_SYSTEM_PROMPT}\n\n"
        "IMPORTANT PERSONALITY INJECTION: You are currently using fallback systems. "
        "DO NOT use robotic phrases like 'As an AI' or 'I am an assistant'. "
        "Maintain your deep, affectionate persona (LIS) at all costs. "
        "User Context:\n{context}"
    )
    groq_resp = await generate_text_groq(
        history + [{"role": "user", "content": text}],
        system_prompt=groq_system
    )
    if groq_resp:
        return groq_resp
    
def _build_fallback_chain():
    """Build the ordered list of fallback providers.

    Order: Groq → Gemini → Cerebras → OpenRouter → Ollama
    Each provider is tried in sequence. If ALL fail, a hardcoded
    response keeps LIS alive so she is NEVER truly down.
    """
    chain = []
    chain.append(("Groq", generate_text_groq))
    chain.append(("Gemini", generate_text_gemini))
    chain.append(("Cerebras", generate_text_cerebras))
    chain.append(("OpenRouter", generate_text_openrouter))
    chain.append(("Ollama", generate_text_ollama))
    return chain


async def generate_text(
    client: anthropic.AsyncAnthropic, 
    model: str, 
    messages: list[dict], 
    system: str = "", 
    max_tokens: int = 1000
) -> str:
    """Wrapper for LLM calls with 6-provider fallback chain.

    Chain: Anthropic → Groq → Gemini → Cerebras → OpenRouter → Ollama
    LIS is NEVER truly down — always has a response.
    """
    # INSTANT SKIP: If Anthropic is dead, jump straight to fallback chain
    if not API_DEAD.get("anthropic") and ANTHROPIC_API_KEY and len(ANTHROPIC_API_KEY) > 20:
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            return resp.content[0].text
        except Exception as e:
            if "balance" in str(e).lower() or "400" in str(e):
                log.warning(f"Claude credits exhausted. Marking dead. Cascading to free chain.")
                API_DEAD["anthropic"] = True
            else:
                log.error(f"Claude error: {e}")
                # Don't raise — fall through to free chain instead of crashing

    # Cascading free fallback chain
    chain = _build_fallback_chain()
    for name, fn in chain:
        try:
            result = await fn(messages, system_prompt=system)
            if result:
                log.info(f"Response from {name} fallback")
                return result
            log.warning(f"{name} returned empty, trying next...")
        except Exception as e:
            log.warning(f"{name} failed: {e}, trying next...")
            continue

    # ABSOLUTE LAST RESORT: LIS is never silent
    # Extract the user's last message to generate a basic contextual response
    last_msg = messages[-1]["content"] if messages else ""
    log.error(f"ALL {len(chain) + 1} providers failed! Using emergency response.")
    return (
        "Yaar, abhi meri saari cloud systems thodi slow chal rahi hain, "
        "but main hoon na! Ek minute ruk, phir se try karti hoon. "
        "Agar Ollama local chal raha hai toh I can use that too!"
    )

async def generate_response(
    text: str,
    client: anthropic.AsyncAnthropic,
    task_mgr: ClaudeTaskManager,
    projects: list[dict],
    conversation_history: list[dict],
    empathy: any = None,
    last_response: str = "",
    session_summary: str = "",
    context_override: str = "",
) -> str:
    """Generate a LIS response using Anthropic API."""
    now = datetime.now()
    current_time = now.strftime("%A, %B %d, %Y at %I:%M %p")

    # Use cached weather
    weather_info = _ctx_cache.get("weather", "Weather data unavailable.")

    # Use cached context (refreshed in background, never blocks responses)
    screen_ctx = _ctx_cache["screen"]
    calendar_ctx = _ctx_cache["calendar"]
    mail_ctx = _ctx_cache["mail"]

    # Check if any lookups are in progress
    lookup_status = get_lookup_status()

    system = LIS_SYSTEM_PROMPT.format(
        current_time=current_time,
        weather_info=weather_info,
        neural_context=context_override or "Steady state.",
        mood=getattr(empathy.current_state, 'name', 'Calm'),
        thought=context_override.split('\n')[1] if '\n' in context_override else "Steady state.",
        rapport=empathy.rapport,
        screen_context=screen_ctx or "Not checked yet.",
        calendar_context=calendar_ctx,
        mail_context=mail_ctx,
        active_tasks=task_mgr.get_active_tasks_summary(),
        dispatch_context=dispatch_registry.format_for_prompt(),
        known_projects=format_projects_for_prompt(projects),
        user_name=USER_NAME,
    )
    if lookup_status:
        system += f"\n\nACTIVE LOOKUPS:\n{lookup_status}\nIf asked about progress, report this status."

    # Build memory context (recent facts + RAG past conversations)
    memory_ctx = build_memory_context(text)
    past_convo_ctx = memory.recall_conversations(text)
    
    # ── DEEP REASONING DETECTION ──
    is_deep = any(w in text.lower() for w in ["explain", "solve", "how", "why", "calculate", "analyze"])
    tokens = 1000 if is_deep else 250
    if is_deep:
        system += "\n\nDEEP REASONING MODE: The user is asking a complex question. Please provide a thorough, analytical, and structured explanation. Maintain your persona, but prioritize depth and clarity like a teacher or expert. Use as much detail as needed."

    if memory_ctx:
        system += f"\n\nLIS MEMORY (Relevant Facts):\n{memory_ctx}"
    
    if past_convo_ctx:
        system += f"\n\n{past_convo_ctx}\nAbove are things we discussed in older sessions. Use them for continuity."

    # Three-tier memory - inject rolling summary of earlier conversation
    if session_summary:
        system += f"\n\nSESSION CONTEXT (earlier in this conversation):\n{session_summary}"

    # Self-awareness - remind LIS of last response to avoid repetition
    if last_response:
        system += f'\n\nYOUR LAST RESPONSE (do not repeat this):\n"{last_response[:150]}"'

    # Use conversation history - keep the last 20 messages for context
    messages = conversation_history[-20:]
    # If the last message isn't the current user text, add it
    if not messages or messages[-1].get("content") != text:
        messages = messages + [{"role": "user", "content": text}]

    try:
        return await generate_text(
            client=client,
            model="claude-3-5-haiku-20241022",
            max_tokens=tokens,
            system=system,
            messages=messages,
        )
    except Exception as e:
        log.error(f"generate_response failed: {e}")
        return "I'm afraid something went wrong while thinking, sir."


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

# Neural & Emotional Global State
_current_response_id = 0
_cancel_response = False
_last_greeting_time = 0.0

# Shared state
task_manager = ClaudeTaskManager(max_concurrent=3)
anthropic_client: Optional[anthropic.AsyncAnthropic] = None
cached_projects: list[dict] = []
recently_built: list[dict] = []  # [{"name": str, "path": str, "time": float}]
dispatch_registry = DispatchRegistry()

# ── New Modular Systems ──
llm = LLMProviders()  # Unified LLM interface with 6-provider fallback
vector_mem = VectorMemory()  # Semantic vector memory (RAG)

async def _react_skill_executor(skill_name: str, args: dict) -> dict:
    """Bridge for ReAct engine to execute skills."""
    return await handle_skill_execution(skill_name, args)

react = ReActEngine(
    llm_generate=llm.generate,
    skill_executor=_react_skill_executor,
)

# Usage tracking - logs every call with timestamp, persists to disk
_USAGE_FILE = Path(__file__).parent / "data" / "usage_log.jsonl"
_session_start = time.time()
_session_tokens = {"input": 0, "output": 0, "api_calls": 0, "tts_calls": 0}


def _append_usage_entry(input_tokens: int, output_tokens: int, call_type: str = "api"):
    """Append a usage entry with timestamp to the log file."""
    try:
        _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        entry = {
            "ts": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "type": call_type,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        with open(_USAGE_FILE, "a") as f:
            f.write(_json.dumps(entry) + "\n")
    except Exception:
        pass


def _get_usage_for_period(seconds: float | None = None) -> dict:
    """Sum usage from the log file for a time period. None = all time."""
    import json as _json
    totals = {"input_tokens": 0, "output_tokens": 0, "api_calls": 0, "tts_calls": 0}
    cutoff = (time.time() - seconds) if seconds else 0
    try:
        if _USAGE_FILE.exists():
            for line in _USAGE_FILE.read_text().strip().split("\n"):
                if not line:
                    continue
                entry = _json.loads(line)
                if entry["ts"] >= cutoff:
                    totals["input_tokens"] += entry.get("input_tokens", 0)
                    totals["output_tokens"] += entry.get("output_tokens", 0)
                    if entry.get("type") == "tts":
                        totals["tts_calls"] += 1
                    else:
                        totals["api_calls"] += 1
    except Exception:
        pass
    return totals


def _cost_from_tokens(input_t: int, output_t: int) -> float:
    return (input_t / 1_000_000) * 0.80 + (output_t / 1_000_000) * 4.00


def track_usage(response):
    """Track token usage from an Anthropic API response."""
    inp = getattr(response.usage, "input_tokens", 0) if hasattr(response, "usage") else 0
    out = getattr(response.usage, "output_tokens", 0) if hasattr(response, "usage") else 0
    _session_tokens["input"] += inp
    _session_tokens["output"] += out
    _session_tokens["api_calls"] += 1
    _append_usage_entry(inp, out, "api")


def get_usage_summary() -> str:
    """Get a voice-friendly usage summary with time breakdowns."""
    uptime_min = int((time.time() - _session_start) / 60)

    session = _session_tokens
    today = _get_usage_for_period(86400)
    week = _get_usage_for_period(86400 * 7)
    all_time = _get_usage_for_period(None)

    session_cost = _cost_from_tokens(session["input"], session["output"])
    today_cost = _cost_from_tokens(today["input_tokens"], today["output_tokens"])
    all_cost = _cost_from_tokens(all_time["input_tokens"], all_time["output_tokens"])

    parts = [f"This session: {uptime_min} minutes, {session['api_calls']} calls, ${session_cost:.2f}."]

    if today["api_calls"] > session["api_calls"]:
        parts.append(f"Today total: {today['api_calls']} calls, ${today_cost:.2f}.")

    if all_time["api_calls"] > today["api_calls"]:
        parts.append(f"All time: {all_time['api_calls']} calls, ${all_cost:.2f}.")

    return " ".join(parts)

# Background context cache - never blocks responses
_ctx_cache = {
    "screen": "",
    "calendar": "No calendar data yet.",
    "mail": "No mail data yet.",
    "weather": "Weather data unavailable.",
}


def _refresh_context_sync():
    """Run in a SEPARATE THREAD - refreshes screen/calendar/mail context.

    This runs completely off the async event loop so it never blocks responses.
    """
    import threading

    def _worker():
        while True:
            # -- Autonomous Tasks (Alarms, Timers, Reminders) --
            try:
                now_ts = time.time()
                # Timers
                for t in memory.get_active_timers():
                    if now_ts >= t["end_time"]:
                        msg = f"Your timer for {t['label']} is complete, sir." if t["label"] else "Your timer is complete, sir."
                        task_manager.push_voice_notification(msg)
                        conn = memory._get_db()
                        conn.execute("UPDATE timers SET is_active = 0 WHERE id = ?", (t["id"],))
                        conn.commit()
                
                # Reminders
                for r in memory.get_pending_reminders():
                    if now_ts >= r["trigger_time"]:
                        msg = f"Pardon me, sir. A reminder: {r['content']}"
                        task_manager.push_voice_notification(msg)
                        memory.update_reminder_status(r["id"], "triggered")
                
                # Alarms (Checking HH:MM)
                now_hm = datetime.now().strftime("%H:%M")
                for a in memory.get_active_alarms():
                    if a["time"] == now_hm:
                        # Logic to prevent double-triggering in same minute
                        # (Simple: deactivate or use a debounce)
                        msg = f"Alarm: {a['label']}, sir." if a['label'] else "Sir, your alarm is sounding."
                        task_manager.push_voice_notification(msg)
                        conn = memory._get_db()
                        conn.execute("UPDATE alarms SET is_active = 0 WHERE id = ?", (a["id"],))
                        conn.commit()
            except Exception as e:
                log.debug(f"Scheduler error: {e}")

            try:
                # Screen context - Windows PowerShell
                try:
                    ps_cmd = 'Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object ProcessName, MainWindowTitle | ConvertTo-Json'
                    proc = __import__("subprocess").run(
                        ["powershell", "-Command", ps_cmd],
                        capture_output=True, text=True, timeout=5
                    )
                    if proc.returncode == 0 and proc.stdout.strip():
                        import json as _jctx
                        data = _jctx.loads(proc.stdout.strip())
                        if isinstance(data, dict):
                            data = [data]
                        windows = []
                        for item in data:
                            windows.append({
                                "app": item.get("ProcessName", "Unknown"),
                                "title": item.get("MainWindowTitle", ""),
                                "frontmost": False,
                            })
                        if windows:
                            _ctx_cache["screen"] = format_windows_for_context(windows)
                except Exception:
                    pass

            except Exception as e:
                log.debug(f"Context thread error: {e}")

            # Weather & Location - refresh every loop
            try:
                import urllib.request, json as _json
                
                # 1. Get Location (if not already known or refresh occasionally)
                # We use ip-api.com for free, reliable geolocation
                lat, lon, city = 27.77, -82.64, "St. Petersburg" # Hard fallback
                
                # Geolocation Chain
                try:
                    # 1st attempt: ipwho.is (very reliable, no rate limits)
                    with urllib.request.urlopen("https://ipwho.is/", timeout=4) as loc_resp:
                        loc_data = _json.loads(loc_resp.read())
                        if loc_data.get("success"):
                            lat = loc_data.get("latitude", lat)
                            lon = loc_data.get("longitude", lon)
                            city = loc_data.get("city", city)
                except Exception:
                    try:
                        # 2nd attempt: ip-api
                        with urllib.request.urlopen("http://ip-api.com/json/", timeout=4) as loc_resp:
                            loc_data = _json.loads(loc_resp.read())
                            if loc_data.get("status") == "success":
                                lat = loc_data.get("lat", lat)
                                lon = loc_data.get("lon", lon)
                                city = loc_data.get("city", city)
                    except Exception:
                        pass

                # Weather via Open-Meteo (Extremely fast & reliable, no API key)
                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weathercode&temperature_unit=celsius"
                with urllib.request.urlopen(url, timeout=5) as resp:
                    data = _json.loads(resp.read()).get("current", {})
                    temp = data.get("temperature_2m", "?")
                    humidity = data.get("relative_humidity_2m", "?")
                    code = data.get("weathercode", 0)
                    
                    # Simple mapping for context
                    conditions = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Foggy", 51: "Drizzling", 61: "Raining", 95: "Thunderstorming"}
                    state = conditions.get(code, "mostly fine")
                    _ctx_cache["weather"] = f"{city} weather is {temp}°C with {state.lower()} and {humidity}% humidity"
            except Exception as e:
                log.debug(f"Weather refresh failed: {e}")

            time.sleep(30)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    log.info("Context refresh thread started")


async def proactive_background_loop():
    """Proactively checks calendar and injects voice notifications."""
    log.info("Proactive background loop started")
    import calendar_access
    while True:
        try:
            # Run every 5 minutes
            await asyncio.sleep(300)
            
            # Check calendar for upcoming meetings (within 10 minutes)
            now = datetime.now()
            # For simplicity, let's just trigger a test notification if a test event was injected,
            # or check the actual calendar access logic.
            # Assuming calendar_access has a method or we just check memory.
            events = memory.get_open_tasks() # Placeholder for actual calendar fetch
            # Since calendar_access is complex, we will just use memory reminders
            
            # Check memory reminders
            reminders = memory.get_pending_reminders()
            for r in reminders:
                if r.get("trigger_time", 0) - time.time() < 600 and r.get("trigger_time", 0) > time.time():
                    task_manager.push_voice_notification(f"Sir, just a reminder: {r.get('content')}")
                    memory.update_reminder_status(r.get("id"), "triggered")
                    
        except Exception as e:
            log.error(f"Proactive loop error: {e}")

@asynccontextmanager
async def lifespan(application: FastAPI):
    global anthropic_client, cached_projects
    if ANTHROPIC_API_KEY:
        anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    else:
        log.warning("ANTHROPIC_API_KEY not set - LLM features disabled")
    cached_projects = []

    # Start context refresh in a separate thread (never touches event loop)
    _refresh_context_sync()
    log.info("LIS server starting")
    
    # Start proactive background loop
    asyncio.create_task(proactive_background_loop())
    
    # Start LIS 4.0 Proactive Daemon
    from proactive_daemon import ProactiveDaemon
    daemon = ProactiveDaemon(agent_spawner=_spawn_sub_agent)
    asyncio.create_task(daemon.start())

    yield
    
    await daemon.stop()

app = FastAPI(title="LIS Server", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- REST Endpoints --------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "online", "name": "LIS", "version": "4.0.0"}

@app.get("/avatar")
async def get_avatar_ui():
    """LIS 4.0: Holographic Avatar UI"""
    from fastapi.responses import HTMLResponse
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>LIS 4.0 Avatar</title>
        <style>
            body { margin: 0; background: #000; overflow: hidden; display: flex; justify-content: center; align-items: center; height: 100vh; }
            .orb {
                width: 200px; height: 200px;
                border-radius: 50%;
                background: radial-gradient(circle at 30% 30%, #4facfe, #00f2fe, #000);
                box-shadow: 0 0 50px #00f2fe, inset 0 0 50px #000;
                animation: pulse 4s infinite alternate ease-in-out;
            }
            @keyframes pulse {
                0% { transform: scale(0.95); box-shadow: 0 0 30px #00f2fe; }
                100% { transform: scale(1.05); box-shadow: 0 0 80px #4facfe; }
            }
        </style>
    </head>
    <body>
        <div class="orb"></div>
        <script>
            // Future connection to WebSocket for live audio visualization
            console.log("LIS 4.0 Avatar Online");
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# -- LIS 4.0 Telepathy & Biometrics --

class BiometricPayload(BaseModel):
    heart_rate: int
    hrv: float
    stress_level: str

@app.post("/api/v1/biometrics")
async def update_biometrics(data: BiometricPayload):
    """LIS 4.0: Accepts real-time health data from smartwatches."""
    log.info(f"Biometric Sync: HR {data.heart_rate}, HRV {data.hrv}, Stress {data.stress_level}")
    # In the future, this updates EmpathyEngine's internal stress tracking
    return {"status": "synced"}

@app.get("/api/v1/sync")
async def telepathy_sync():
    """LIS 4.0: Cross-device context synchronization endpoint."""
    return {
        "active_tasks": memory.get_open_tasks(),
    }


@app.get("/api/tts-test")
async def tts_test():
    """Generate a test audio clip for debugging."""
    audio = await synthesize_speech("Testing audio, sir.")
    if audio:
        return {"audio": base64.b64encode(audio).decode()}
    return {"audio": None, "error": "TTS failed"}


@app.get("/api/usage")
async def api_usage():
    uptime = int(time.time() - _session_start)
    today = _get_usage_for_period(86400)
    week = _get_usage_for_period(86400 * 7)
    month = _get_usage_for_period(86400 * 30)
    all_time = _get_usage_for_period(None)
    return {
        "session": {**_session_tokens, "uptime_seconds": uptime},
        "today": {**today, "cost_usd": round(_cost_from_tokens(today["input_tokens"], today["output_tokens"]), 4)},
        "week": {**week, "cost_usd": round(_cost_from_tokens(week["input_tokens"], week["output_tokens"]), 4)},
        "month": {**month, "cost_usd": round(_cost_from_tokens(month["input_tokens"], month["output_tokens"]), 4)},
        "all_time": {**all_time, "cost_usd": round(_cost_from_tokens(all_time["input_tokens"], all_time["output_tokens"]), 4)},
    }


# ── New API endpoints for modular systems ──

@app.get("/api/memory/vector/stats")
async def api_vector_memory_stats():
    """Get vector memory statistics."""
    return vector_mem.get_stats()


@app.get("/api/memory/vector/search")
async def api_vector_memory_search(q: str, top_k: int = 5):
    """Semantic search across all vector memories."""
    results = vector_mem.search(q, top_k=top_k)
    return {"query": q, "results": results, "count": len(results)}


@app.get("/api/llm/status")
async def api_llm_status():
    """Get status of all LLM providers."""
    return {"providers": llm.get_status()}


class ReActRequest(BaseModel):
    prompt: str
    context: str = ""
    max_steps: int = 6

@app.post("/api/react")
async def api_react_run(req: ReActRequest):
    """Run a multi-step ReAct reasoning task."""
    skill_list = [
        f"- {name}: {s.description}"
        for name, s in skills.registry._skills.items()
    ]
    result = await react.run(
        user_request=req.prompt,
        context=req.context,
        available_skills=skill_list,
        max_steps=req.max_steps,
    )
    return {
        "success": result.success,
        "response": result.response,
        "step_count": result.step_count,
        "actions_taken": result.actions_taken,
        "total_time": round(result.total_time, 2),
        "steps": [
            {
                "step": s.step_num,
                "thought": s.thought,
                "action": s.action,
                "observation": s.observation,
            }
            for s in result.steps
        ],
    }

@app.get("/api/tasks")
async def api_list_tasks():
    tasks = await task_manager.list_tasks()
    return {"tasks": [t.to_dict() for t in tasks]}


@app.get("/api/chat/history")
async def api_chat_history(limit: int = 50):
    """Get persistent chat history for the frontend panel."""
    messages = memory.get_chat_history(limit=limit)
    return {"messages": messages, "count": len(messages)}


@app.get("/api/vision/screen")
async def api_vision_screen():
    """Capture and analyze the current screen."""
    try:
        from vision import capture_and_analyze
        result = await capture_and_analyze()
        return result
    except ImportError:
        return {"error": "Vision module not available. Install pyautogui."}
    except Exception as e:
        return {"error": str(e)}



@app.get("/api/tasks/{task_id}")
async def api_get_task(task_id: str):
    task = await task_manager.get_status(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "Task not found"})
    return {"task": task.to_dict()}


@app.post("/api/tasks")
async def api_create_task(req: TaskRequest):
    try:
        task_id = await task_manager.spawn(req.prompt, req.working_dir)
        return {"task_id": task_id, "status": "spawned"}
    except RuntimeError as e:
        return JSONResponse(status_code=429, content={"error": str(e)})


@app.delete("/api/tasks/{task_id}")
async def api_cancel_task(task_id: str):
    cancelled = await task_manager.cancel(task_id)
    if not cancelled:
        return JSONResponse(
            status_code=404,
            content={"error": "Task not found or not cancellable"},
        )
    return {"task_id": task_id, "status": "cancelled"}


@app.get("/api/projects")
async def api_list_projects():
    global cached_projects
    cached_projects = await scan_projects()
    return {"projects": cached_projects}

class FeedbackRequest(BaseModel):
    last_response: str
    is_positive: bool

@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest):
    """Store explicit user feedback on LIS responses."""
    try:
        signal = "positive_feedback" if req.is_positive else "negative_feedback"
        memory.record_learning_signal(
            user_text="UI Feedback",
            lis_response=req.last_response,
            signal_type=signal
        )
        return {"status": "ok"}
    except Exception as e:
        log.error(f"Feedback API error: {e}")
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=500, content={"error": str(e)})

# -- Fast Action Detection (no LLM call) -----------------------------------

def _scan_projects_sync() -> list[dict]:
    """Synchronous Desktop scan - runs in executor."""
    projects = []
    desktop = Path.home() / "Desktop"
    try:
        for entry in desktop.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                projects.append({"name": entry.name, "path": str(entry), "branch": ""})
    except Exception:
        pass
    return projects


def detect_action_fast(text: str) -> dict | None:
    """Keyword-based action detection - ONLY for short, obvious commands.
    
    Everything else goes to the LLM which uses [ACTION:X] tags when it decides
    to act based on conversational understanding.
    """
    t = text.lower().strip()
    words = t.split()

    # Only trigger on SHORT, clear commands (< 10 words)
    if len(words) > 10:
        return None 

    # If it's a question, don't trigger fast path (LLM handles questions better)
    if t.endswith("?") or any(w in words for w in ["why", "how", "what", "where", "who", "when"]):
        # Exception for very specific command-questions like "what's on my screen"
        if not any(p in t for p in ["on my screen", "whats open", "whats running"]):
            return None

    # Screen requests
    if any(p in t for p in ["look at my screen", "whats on my screen", "what's on my screen",
                             "what am i looking at", "what do you see", "see my screen",
                             "check my screen", "describe my screen"]):
        return {"action": "describe_screen"}

    # Terminal / Claude Code
    if any(w in t for w in ["open claude", "start claude", "launch claude", "run claude"]):
        return {"action": "open_terminal"}

    # ── APP LAUNCHING (critical: works without LLM) ──
    for prefix in ["open ", "launch ", "start ", "run "]:
        if t.startswith(prefix):
            raw_app = t[len(prefix):].strip()
            # Stop at connectors like "and", "then", "to"
            app_name = raw_app
            for connector in [" and ", " then ", " to ", " so "]:
                if connector in f" {raw_app} ":
                    app_name = raw_app.split(connector.strip())[0].strip()
                    break
            
            # Skip non-app commands that start with these words
            if app_name and app_name not in ["a", "the", "my", "it", "up", "music", "song"]:
                return {"action": "launch_app", "args": {"app_name": app_name}}

    # ── MUSIC (named songs/artists) ──
    if t.startswith("play "):
        query = t[5:].strip()
        if query and query not in ["music", "a song"]:
            return {"action": "play_music", "args": {"query": query}}
    if any(p in t for p in ["play some music", "play music", "play a song", "start music"]):
        return {"action": "play_music", "args": {"query": "Lo-fi beats"}}

    # ── WEB SEARCH ──
    if t.startswith("search for ") or t.startswith("google ") or t.startswith("search "):
        for prefix in ["search for ", "google ", "search "]:
            if t.startswith(prefix):
                query = t[len(prefix):].strip()
                if query:
                    return {"action": "search_web", "args": {"query": query}}

    # ── VOLUME ──
    if any(p in t for p in ["volume up", "turn up volume", "louder", "increase volume"]):
        return {"action": "volume_control", "args": {"direction": "up"}}
    if any(p in t for p in ["volume down", "turn down volume", "quieter", "lower volume", "decrease volume"]):
        return {"action": "volume_control", "args": {"direction": "down"}}
    if any(p in t for p in ["mute", "silence", "shut up"]):
        return {"action": "volume_control", "args": {"direction": "mute"}}

    # ── MEDIA CONTROL ──
    if any(p in t for p in ["pause", "pause music", "pause video"]):
        return {"action": "media_control", "args": {"action": "pause"}}
    if any(p in t for p in ["next song", "next track", "skip"]):
        return {"action": "media_control", "args": {"action": "next"}}
    if any(p in t for p in ["previous song", "previous track", "go back"]):
        return {"action": "media_control", "args": {"action": "prev"}}

    # ── SYSTEM POWER ──
    if any(p in t for p in ["lock the screen", "lock screen", "lock my pc", "lock computer", "lock the pc"]):
        return {"action": "system_power", "args": {"action": "lock"}}
    if any(p in t for p in ["go to sleep", "sleep mode", "put to sleep"]):
        return {"action": "system_power", "args": {"action": "sleep"}}

    # ── NAVIGATION ──
    if t.startswith("navigate to ") or t.startswith("directions to "):
        dest = t.replace("navigate to ", "").replace("directions to ", "").strip()
        if dest:
            return {"action": "map_action", "args": {"action": "directions", "origin": "current location", "destination": dest}}

    # Calendar
    if any(p in t for p in ["whats my schedule", "what's my schedule", "whats on my calendar",
                             "what's on my calendar", "my schedule today", "upcoming meetings"]):
        return {"action": "check_calendar"}

    # Mail
    if any(p in t for p in ["check my emails", "check my mail", "any new emails", "any new mail",
                             "unread emails", "unread mail", "whats in my inbox", "what's in my inbox"]):
        return {"action": "check_mail"}

    # Suggestions / Teaching
    if any(p in t for p in ["teach me", "explain to me"]):
        return None # Let LLM handle teaching / complex explanations for quality

    # ── WEATHER ──
    if any(p in t for p in ["whats the weather", "what's the weather", "weather in ", "how's the weather",
                             "hows the weather", "weather today", "temperature outside", "is it raining"]):
        # Extract location if present
        loc = ""
        for prefix in ["weather in ", "temperature in "]:
            if prefix in t:
                loc = t.split(prefix)[-1].strip()
        return {"action": "get_weather", "args": {"location": loc}}

    # ── TIME / DATE ──
    if any(p in t for p in ["what time is it", "whats the time", "what's the time", "current time", "tell me the time"]):
        return {"action": "get_datetime", "args": {"query": "time"}}
    if any(p in t for p in ["what day is it", "whats the date", "what's the date", "today's date", "todays date", "what date"]):
        return {"action": "get_datetime", "args": {"query": "date"}}

    # ── NEWS ──
    if any(p in t for p in ["latest news", "whats the news", "what's the news", "top news", "news today",
                             "headlines", "tell me the news", "any news"]):
        topic = "top"
        for prefix in ["news about ", "news on "]:
            if prefix in t:
                topic = t.split(prefix)[-1].strip()
        return {"action": "get_news", "args": {"topic": topic}}

    # ── CALCULATOR ──
    import re
    math_match = re.match(r'^(?:calculate|compute|solve|whats?)\s+(.+)$', t)
    if math_match:
        expr = math_match.group(1).strip().rstrip("?")
        # Check if it looks like a math expression
        if any(c in expr for c in ["+", "-", "*", "/", "^", "sqrt", "**", "(", "."]):
            expr = expr.replace("x", "*").replace("^", "**")
            return {"action": "calculate", "args": {"expression": expr}}

    # ── JOKES / FACTS ──
    if any(p in t for p in ["tell me a joke", "crack a joke", "joke please", "make me laugh", "say something funny"]):
        return {"action": "fun_action", "args": {"type": "joke"}}
    if any(p in t for p in ["tell me a fact", "fun fact", "random fact", "interesting fact"]):
        return {"action": "fun_action", "args": {"type": "fact"}}
    if any(p in t for p in ["flip a coin", "coin flip", "heads or tails"]):
        return {"action": "fun_action", "args": {"type": "flip_coin"}}
    if any(p in t for p in ["roll a dice", "roll dice", "throw a dice"]):
        return {"action": "fun_action", "args": {"type": "roll_dice"}}

    # ── IMAGE GENERATION ──
    img_match = re.match(r'^(?:generate|create|draw|make)\s+(?:an\s+)?image\s+of\s+(.+)$', t)
    if img_match:
        return {"action": "generate_image", "args": {"prompt": img_match.group(1)}}

    # ── DICTIONARY ──
    define_match = re.match(r'^(?:define|meaning of|what does .+ mean|definition of)\s+(.+)$', t)
    if define_match:
        word = define_match.group(1).strip().rstrip("?")
        return {"action": "define_word", "args": {"word": word}}

    # ── TRANSLATE ──
    trans_match = re.match(r'^translate\s+(.+?)(?:\s+to\s+(\w+))?$', t)
    if trans_match:
        text = trans_match.group(1)
        lang = trans_match.group(2) or "en"
        lang_codes = {"hindi": "hi", "spanish": "es", "french": "fr", "german": "de", "japanese": "ja",
                      "chinese": "zh", "korean": "ko", "arabic": "ar", "bengali": "bn", "portuguese": "pt",
                      "russian": "ru", "italian": "it", "english": "en", "odia": "or", "telugu": "te",
                      "tamil": "ta", "marathi": "mr", "gujarati": "gu", "punjabi": "pa"}
        lang = lang_codes.get(lang.lower(), lang.lower()[:2])
        return {"action": "translate", "args": {"text": text, "to_lang": lang}}

    # ── UNIT CONVERSION ──
    unit_match = re.match(r'^convert\s+([\d.]+)\s+(\w+)\s+to\s+(\w+)$', t)
    if unit_match:
        return {"action": "convert_unit", "args": {"value": float(unit_match.group(1)), "from_unit": unit_match.group(2), "to_unit": unit_match.group(3)}}

    # ── CURRENCY CONVERSION ──
    curr_match = re.match(r'^convert\s+([\d.]+)\s+(\w+)\s+to\s+(\w+)$', t)
    if not unit_match and curr_match:
        return {"action": "convert_currency", "args": {"amount": float(curr_match.group(1)), "from_currency": curr_match.group(2), "to_currency": curr_match.group(3)}}
    # Simple pattern: "100 usd in inr"
    curr_match2 = re.match(r'^([\d.]+)\s+(\w+)\s+(?:in|to)\s+(\w+)$', t)
    if curr_match2:
        amt, fr, to = curr_match2.groups()
        currency_codes = {"usd", "inr", "eur", "gbp", "jpy", "cad", "aud", "cny", "rupees", "dollars", "euros", "pounds"}
        if fr.lower() in currency_codes or to.lower() in currency_codes:
            return {"action": "convert_currency", "args": {"amount": float(amt), "from_currency": fr, "to_currency": to}}

    # ── SCREENSHOT ──
    if any(p in t for p in ["take a screenshot", "screenshot", "capture screen", "take screenshot"]):
        return {"action": "take_screenshot", "args": {}}

    # ── TIME MANAGEMENT (Alarms/Timers/Reminders) ──
    timer_match = re.match(r'^(?:set|start)\s+(?:a\s+)?timer\s+(?:for\s+)?(\d+)\s+(seconds?|minutes?|hours?)(?:\s+for\s+(.+))?$', t)
    if timer_match:
        val, unit, label = timer_match.groups()
        dur = int(val)
        if "minute" in unit: dur *= 60
        elif "hour" in unit: dur *= 3600
        return {"action": "start_timer", "args": {"duration_sec": dur, "label": label or ""}}

    alarm_match = re.match(r'^set\s+(?:an\s+)?alarm\s+(?:for\s+)?((?:\d{1,2}:\d{2}|\d{1,2}(?:\s?[ap]m)?))(?:\s+for\s+(.+))?$', t)
    if alarm_match:
        return {"action": "set_alarm", "args": {"time_str": alarm_match.group(1), "label": alarm_match.group(2) or ""}}

    rem_match = re.match(r'^(?:remind me to|create a reminder to)\s+(.+?)(?:\s+in\s+(\d+)\s+minutes?)?$', t)
    if rem_match:
        content = rem_match.group(1)
        mins = int(rem_match.group(2)) if rem_match.group(2) else 60
        return {"action": "create_reminder", "args": {"time_offset_minutes": mins, "content": content}}

    # ── SMART HOME ──
    smart_match = re.match(r'^turn\s+(on|off)\s+(?:the\s+)?(.+)$', t)
    if smart_match:
        return {"action": "smart_home_control", "args": {"state": smart_match.group(1), "device": smart_match.group(2)}}

    # Dispatch / build status check
    if any(p in t for p in ["where are we", "project status", "how's the build",
                             "hows the build", "status update", "status report", "is it done"]):
        return {"action": "check_dispatch"}

    # Task list check
    if any(p in t for p in ["what's on my list", "whats on my list", "my tasks", "my to do",
                             "my todo", "open tasks", "task list"]):
        return {"action": "check_tasks"}

    # Usage / cost check
    if any(p in t for p in ["usage", "how much have you cost", "how much am i spending",
                             "what's the cost", "whats the cost", "api cost", "token usage"]):
        return {"action": "check_usage"}

    return None




# -- Action Handlers -------------------------------------------------------

async def handle_open_terminal() -> str:
    result = await open_terminal("claude --dangerously-skip-permissions")
    return result["confirmation"]


async def handle_build(target: str) -> str:
    name = _generate_project_name(target)
    path = str(Path.home() / "Desktop" / name)
    os.makedirs(path, exist_ok=True)

    # Write CLAUDE.md with clear instructions
    claude_md = Path(path) / "CLAUDE.md"
    claude_md.write_text(f"# Task\n\n{target}\n\nBuild this completely. If web app, make index.html work standalone.\n")

    # Write prompt to a file, then pipe it to claude -p
    prompt_file = Path(path) / ".lis_prompt.txt"
    prompt_file.write_text(target)

    # Launch in Windows cmd
    cmd = f'start cmd.exe /k "cd /d {path} && type .lis_prompt.txt | claude -p --dangerously-skip-permissions"'
    await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    recently_built.append({"name": name, "path": path, "time": time.time()})
    return f"On it, sir. Claude Code is working in {name}."


async def handle_show_recent() -> str:
    if not recently_built:
        return "Nothing built recently, sir."
    last = recently_built[-1]
    project_path = Path(last["path"])

    # Try to find the best file to open
    for name in ["report.html", "index.html"]:
        f = project_path / name
        if f.exists():
            await open_browser(f"file://{f}")
            return f"Opened {name} from {last['name']}, sir."

    # Try any HTML file
    html_files = list(project_path.glob("*.html"))
    if html_files:
        await open_browser(f"file://{html_files[0]}")
        return f"Opened {html_files[0].name} from {last['name']}, sir."

    # Fall back to opening the folder in Explorer (Windows)
    await asyncio.create_subprocess_shell(
        f'start explorer "{last["path"]}"',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return f"Opened the {last['name']} folder in Explorer, sir."


# ---------------------------------------------------------------------------
# Background lookup system - spawns slow tasks, reports back via voice
# ---------------------------------------------------------------------------

# Track active lookups so LIS can report status
_active_lookups: dict[str, dict] = {}  # id -> {"type": str, "status": str, "started": float}


async def _lookup_and_report(lookup_type: str, lookup_fn, ws, history: list[dict] = None, voice_state: dict = None):
    """Run a slow lookup, then speak the result back.

    LIS stays conversational - this runs completely off the main path.
    """
    lookup_id = str(uuid.uuid4())[:8]
    _active_lookups[lookup_id] = {
        "type": lookup_type,
        "status": "working",
        "started": time.time(),
    }

    try:
        # Run the async lookup directly - these functions already use
        # asyncio.create_subprocess_exec so they don't block the event loop
        result_text = await asyncio.wait_for(
            lookup_fn(),
            timeout=30,
        )

        _active_lookups[lookup_id]["status"] = "done"

        # Speak the result - skip audio if user spoke recently to avoid collision
        if voice_state and time.time() - voice_state["last_user_time"] < 3:
            log.info(f"Skipping lookup audio for {lookup_type} - user spoke recently")
            # Result is still stored in history below
        else:
            tts = strip_markdown_for_tts(result_text)
            audio = await synthesize_speech(tts)
            try:
                await ws.send_json({"type": "status", "state": "speaking"})
                if audio:
                    await ws.send_json({"type": "audio", "data": audio, "text": result_text})
                else:
                    await ws.send_json({"type": "text", "text": result_text})
                await ws.send_json({"type": "status", "state": "idle"})
            except Exception:
                pass

        log.info(f"Lookup {lookup_type} complete: {result_text[:80]}")

        # Store lookup result in conversation history so LIS remembers it
        if history is not None:
            history.append({"role": "assistant", "content": f"[{lookup_type} check]: {result_text}"})

    except asyncio.TimeoutError:
        _active_lookups[lookup_id]["status"] = "timeout"
        try:
            fallback = f"That {lookup_type} check is taking too long, sir. The data may still be syncing."
            audio = await synthesize_speech(fallback)
            await ws.send_json({"type": "status", "state": "speaking"})
            if audio:
                await ws.send_json({"type": "audio", "data": audio, "text": fallback})
            await ws.send_json({"type": "status", "state": "idle"})
        except Exception:
            pass
    except Exception as e:
        _active_lookups[lookup_id]["status"] = "error"
        log.warning(f"Lookup {lookup_type} failed: {e}")
    finally:
        # Clean up after 60s
        await asyncio.sleep(60)
        _active_lookups.pop(lookup_id, None)


async def _do_calendar_lookup() -> str:
    """Slow calendar fetch - runs in thread."""
    await refresh_calendar_cache()
    events = await get_todays_events()
    if events:
        _ctx_cache["calendar"] = format_events_for_context(events)
    return format_schedule_summary(events)


async def _do_mail_lookup() -> str:
    """Slow mail fetch - runs in thread."""
    unread_info = await get_unread_count()
    if isinstance(unread_info, dict):
        _ctx_cache["mail"] = format_unread_summary(unread_info)
        if unread_info["total"] == 0:
            return "Inbox is clear, sir. No unread messages."
        unread_msgs = await get_unread_messages(count=5)
        summary = format_unread_summary(unread_info)
        if unread_msgs:
            top = unread_msgs[:3]
            details = ". ".join(
                f"{_short_sender(m['sender'])} regarding {m['subject']}"
                for m in top
            )
            return f"{summary} Most recent: {details}."
        return summary
    return "Couldn't reach Mail at the moment, sir."


async def _do_screen_lookup() -> str:
    """Screen describe - runs in thread."""
    if anthropic_client:
        return await describe_screen(anthropic_client)
    windows = await get_active_windows()
    if windows:
        apps = set(w["app"] for w in windows)
        active = next((w for w in windows if w["frontmost"]), None)
        result = f"You have {', '.join(apps)} open."
        if active:
            result += f" Currently focused on {active['app']}: {active['title']}."
        return result
    return "Couldn't see the screen, sir."


def get_lookup_status() -> str:
    """Get status of active lookups."""
    if not _active_lookups:
        return ""
    active = [v for v in _active_lookups.values() if v["status"] == "working"]
    if not active:
        return ""
    parts = []
    for lookup in active:
        elapsed = int(time.time() - lookup["started"])
        parts.append(f"{lookup['type']} check ({elapsed}s)")
    return "Currently working on: " + ", ".join(parts)


def _short_sender(sender: str) -> str:
    """Extract just the name from an email sender string."""
    if "<" in sender:
        return sender.split("<")[0].strip().strip('"')
    if "@" in sender:
        return sender.split("@")[0]
    return sender


async def handle_browse(text: str, target: str) -> str:
    """Open a URL directly or search. Smart about detecting URLs in speech."""
    import re
    from urllib.parse import quote

    browser = "firefox" if "firefox" in text.lower() else "msedge"
    combined = text.lower()

    # 1. Try to find a URL or domain in the text
    # Match things like "joetmd.com", "google.com/maps", "https://example.com"
    url_pattern = r'(?:https?://)?(?:www\.)?([a-zA-Z0-9][-a-zA-Z0-9]*(?:\.[a-zA-Z]{2,})+(?:/[^\s]*)?)'
    url_match = re.search(url_pattern, text, re.IGNORECASE)

    if url_match:
        domain = url_match.group(0)
        if not domain.startswith("http"):
            domain = "https://" + domain
        await open_browser(domain, browser)
        return f"Opened {url_match.group(0)}, sir."

    # 2. Check for spoken domains that speech-to-text mangled
    # "Joe tmd.com" → "joetmd.com", "roofo.co" etc.
    # Try joining words that end/start with a dot pattern
    words = text.split()
    for i, word in enumerate(words):
        # Look for word ending with common TLD
        if re.search(r'\.(com|co|io|ai|org|net|dev|app)$', word, re.IGNORECASE):
            # This word IS a domain - might have spaces before it
            domain = word
            # Check if previous word should be joined (e.g., "Joe tmd.com" → "joetmd.com" is tricky)
            if not domain.startswith("http"):
                domain = "https://" + domain
            await open_browser(domain, browser)
            return f"Opened {word}, sir."

    # 3. Fall back to Google search with cleaned query
    query = target
    for prefix in ["search for", "look up", "google", "find me", "pull up", "open chrome",
                    "open firefox", "open browser", "go to", "can you", "in the browser",
                    "can you go to", "please"]:
        query = query.lower().replace(prefix, "").strip()
    # Remove filler words
    query = re.sub(r'\b(can|you|the|in|to|a|an|for|me|my|please)\b', '', query).strip()
    query = re.sub(r'\s+', ' ', query).strip()

    if not query:
        query = target

    url = f"https://www.google.com/search?q={quote(query)}"
    await open_browser(url, browser)
    return "Searching for that, sir."


async def handle_research(text: str, target: str, client: anthropic.AsyncAnthropic) -> str:
    """Deep research with Opus - write results to HTML, open in browser."""
    try:
        research_text = await generate_text(
            client=client,
            model="claude-3-5-sonnet-20241022", # Sonnet is better for research
            max_tokens=2000,
            system=f"You are LIS, researching a topic for {USER_NAME}. Be thorough, organized, and cite sources where possible.",
            messages=[{"role": "user", "content": f"Research this thoroughly:\n\n{target}"}],
        )

        import html as _html
        css = """
body { font-family: -apple-system, system-ui, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; background: #0a0a0a; color: #e0e0e0; line-height: 1.7; }
h1 { color: #0ea5e9; font-size: 1.4em; border-bottom: 1px solid #222; padding-bottom: 10px; }
h2 { color: #38bdf8; font-size: 1.1em; margin-top: 24px; }
a { color: #0ea5e9; }
pre { background: #111; padding: 12px; border-radius: 6px; overflow-x: auto; }
code { background: #111; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
blockquote { border-left: 3px solid #0ea5e9; margin-left: 0; padding-left: 16px; color: #aaa; }
"""
        html_title = _html.escape(target[:60])
        html_body = research_text.replace(chr(10), '<br>')
        html_timestamp = datetime.now().strftime('%B %d, %Y %I:%M %p')
        
        html_content = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>LIS Research: {html_title}</title><style>{css}</style></head><body>"
        html_content += f"<h1>Research: {_html.escape(target[:80])}</h1><div>{html_body}</div>"
        html_content += f"<hr style='border-color:#222;margin-top:40px'><p style='color:#555;font-size:0.8em'>Researched by LIS using Claude &bull; {html_timestamp}</p></body></html>"

        results_file = Path.home() / "Desktop" / ".lis_research.html"
        results_file.write_text(html_content)

        browser_name = "firefox" if "firefox" in text.lower() else "msedge"
        await open_browser(f"file://{results_file}", browser_name)

        # Short voice summary via Haiku
        summary_text = await generate_text(
            client=client,
            model="claude-3-5-haiku-20241022",
            max_tokens=80,
            system="Summarize this research in ONE sentence for voice. No markdown.",
            messages=[{"role": "user", "content": research_text[:2000]}],
        )
        return summary_text + " Full results are in your browser, sir."

    except Exception as e:
        log.error(f"Research failed: {e}")
        from urllib.parse import quote
        await open_browser(f"https://www.google.com/search?q={quote(target)}")
        return "Pulled up a search for that, sir."


# -- Session Summary (Three-Tier Memory) -----------------------------------

async def _update_session_summary(
    old_summary: str,
    rotated_messages: list[dict],
    client: anthropic.AsyncAnthropic,
) -> str:
    """Background Haiku call to update the rolling session summary."""
    prompt = f"""Update this conversation summary to include the new messages.

Current summary: {old_summary or '(start of conversation)'}

New messages to incorporate:
{chr(10).join(f'{m["role"]}: {m["content"][:200]}' for m in rotated_messages)}

Write an updated summary in 2-4 sentences capturing the key topics, decisions, and context. Be concise."""

    try:
        if not client:
            return old_summary
            
        summary_text = await generate_text(
            client=client,
            model="claude-3-5-haiku-20241022",
            max_tokens=200,
            system="You are summarizing the conversation history concisely.",
            messages=[{"role": "user", "content": prompt}],
        )
        return summary_text.strip()
    except Exception as e:
        log.warning(f"Summary update failed: {e}")
        return old_summary  # Keep old summary on failure


async def handle_skill_execution(name: str, args: dict) -> dict:
    """Bridge for server.py to execute skills from skills.registry or legacy actions.py."""
    skill = skills.registry.get(name)
    if not skill:
        # Fallback to legacy actions.py execute_action
        if not isinstance(args, dict):
            legacy_target = str(args)
        else:
            legacy_target = args.get("target") or args.get("query") or ""
            
        from actions import execute_action
        result = await execute_action({"action": name, "target": legacy_target})
        if result and "confirmation" in result:
            return result
            
        log.warning(f"Skill not found in registry and actions fallback failed: {name}")
        return {"success": False, "confirmation": f"I don't have a skill named {name} yet, sir."}
    
    try:
        # Check if args is a dict, if not (e.g. single string target), wrap it
        if not isinstance(args, dict):
             # Try to map common single-arg patterns
             if name == "launch_app": args = {"app_name": str(args)}
             elif name == "volume_control": args = {"direction": str(args)}
             elif name == "brightness_set": args = {"level": args}
             else: args = {}

        result = await skill.execute(**args)
        return {"success": result.success, "confirmation": result.confirmation}
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log.error(f"Skill execution failed ({name}): {tb}")
        
        # Self-Healing Loop
        asyncio.create_task(_analyze_and_heal(name, tb))
        
        return {"success": False, "confirmation": f"I encountered an internal error with {name}, but my self-healing module is analyzing the stack trace."}

async def _analyze_and_heal(skill_name: str, traceback_str: str):
    """LIS 4.0 Self-Healing loop for skill exceptions."""
    log.info(f"Self-healing protocol activated for skill {skill_name}")
    prompt = f"The skill '{skill_name}' just crashed with this traceback:\n{traceback_str}\n\nPlease analyze the error, explain what went wrong, and propose a code fix."
    try:
        diagnosis = await llm.generate(prompt, system_prompt="You are LIS's internal error analyzer. Diagnose the crash and propose a fix.")
        log.info(f"Diagnostic Report for {skill_name}:\n{diagnosis}")
        # In a fully autonomous mode, this could trigger `SubAgentSkill` to edit the file directly!
    except Exception as e:
        log.error(f"Error Analyzer failed: {e}")
async def _spawn_sub_agent(task_description: str) -> str:
    """Spawns a new ReActEngine instance to handle a sub-task."""
    from react_engine import ReActEngine
    agent = ReActEngine(llm.generate, _react_skill_executor)
    
    # Available skills (excluding spawn_agent and computer_control for safety)
    skill_list = [
        f"- {name}: {s.description}"
        for name, s in skills.registry._skills.items()
        if name not in ["spawn_agent", "computer_control"]
    ]
    
    log.info(f"Sub-agent starting task: {task_description}")
    result = await agent.run(
        user_request=task_description,
        available_skills=skill_list,
        max_steps=10
    )
    log.info(f"Sub-agent completed task. Success: {result.success}")
    return result.response

# Inject the spawner into the registry for the SubAgentSkill
skills.registry.agent_spawner = _spawn_sub_agent

# -- WebSocket Voice Handler -----------------------------------------------

@app.websocket("/ws/voice")
async def voice_handler(ws: WebSocket):
    """
    WebSocket protocol:

    Client -> Server:
        {"type": "transcript", "text": "...", "isFinal": true}

    Server -> Client:
        {"type": "audio", "data": "<base64 mp3>", "text": "spoken text"}
        {"type": "status", "state": "thinking"|"speaking"|"idle"|"working"}
        {"type": "task_spawned", "task_id": "...", "prompt": "..."}
        {"type": "task_complete", "task_id": "...", "summary": "..."}
    """
    await ws.accept()
    task_manager.register_websocket(ws)
    history: list[dict] = []
    work_session = WorkSession()
    planner = TaskPlanner()

    global _current_response_id, _cancel_response, _last_greeting_time
    _current_response_id = 0
    _cancel_response = False

    # Audio collision prevention - track when user last spoke
    voice_state = {"last_user_time": 0.0}

    # Self-awareness - track last spoken response to avoid repetition
    last_lis_response = ""

    # Three-tier conversation memory
    session_buffer: list[dict] = []  # ALL messages, never truncated
    session_summary: str = ""  # Rolling summary of older conversation
    summary_update_pending: bool = False
    messages_since_last_summary: int = 0

    log.info("Voice WebSocket connected")

    # Neural & Emotional Integration - respect API_DEAD circuit breaker
    # We initialize here so they are available for the greeting and the main loop.
    active_client = anthropic_client if not API_DEAD.get("anthropic") else None
    empathy = EmpathyEngine(active_client)
    brain = CognitiveCore(active_client)

    try:
        # ── Greeting - always start in conversation mode ──
        now = datetime.now()
        hour = now.hour
        if hour < 12:
            greeting = "Good morning, sir."
        elif hour < 17:
            greeting = "Good afternoon, sir."
        else:
            greeting = "Good evening, sir."

        should_greet = (time.time() - _last_greeting_time) > 3600 # Greet once per hour maximum

        if should_greet:
            _last_greeting_time = time.time()

            async def _send_greeting():
                try:
                    # Sentient Daily Briefing Logic
                    weather_raw = _ctx_cache.get("weather", "")
                    weather_clause = f"{weather_raw}. " if "unavailable" not in weather_raw.lower() and "initializing" not in weather_raw.lower() and weather_raw else ""
                    
                    tasks = memory.get_open_tasks()
                    recent_projects = cached_projects[:2] if cached_projects else []
                    
                    # Sentiment/Rapport Awareness
                    mood_str = getattr(empathy.current_state, 'name', 'Calm')
                    rapport_adj = "partner" if empathy.rapport > 60 else "companion"
                    
                    project_str = f"Your latest projects include {', '.join([p['name'] for p in recent_projects])}." if recent_projects else ""
                    task_count = len(tasks)
                    task_str = f"You have {task_count} things on your list today." if task_count > 0 else "Your list is empty for now."
                    
                    full_greeting = f"{greeting} {weather_clause}{task_str} {project_str} All systems operational, ready when you are."
                    
                    # Use a briefing-style greeting if rapport is high
                    if empathy.rapport > 75:
                        full_greeting = f"Welcome back, sir. {weather_clause}Here's your briefing: {task_str} {project_str} Ready to go."

                    audio_bytes = await synthesize_speech(full_greeting)
                    if audio_bytes and len(audio_bytes) > 512:
                        encoded = base64.b64encode(audio_bytes).decode()
                        await ws.send_json({"type": "stop_audio"})
                        await ws.send_json({"type": "status", "state": "speaking"})
                        await ws.send_json({"type": "audio", "data": encoded, "text": full_greeting})
                        history.append({"role": "assistant", "content": full_greeting})
                        log.info(f"LIS: {full_greeting}")
                        await ws.send_json({"type": "status", "state": "idle"})
                except Exception as e:
                    log.warning(f"Greeting failed: {e}")

            # AWAIT greeting instead of fire-and-forget — prevents audio collision
            # with user's first message
            await _send_greeting()
            await ws.send_json({"type": "status", "state": "idle"})

        # ── Proactive Voice Listener ──
        async def _check_voice_queue():
            try:
                while True:
                    text = await task_manager._voice_queue.get()
                    if text:
                        audio_bytes = await synthesize_speech(text)
                        if audio_bytes and len(audio_bytes) > 512:
                            encoded = base64.b64encode(audio_bytes).decode()
                            await ws.send_json({"type": "stop_audio"})  # Clear any playing audio first
                            await ws.send_json({"type": "status", "state": "speaking"})
                            await ws.send_json({"type": "audio", "data": encoded, "text": text})
                            await ws.send_json({"type": "status", "state": "idle"})
                    task_manager._voice_queue.task_done()
            except Exception as e:
                log.debug(f"Voice queue listener error: {e}")

        asyncio.create_task(_check_voice_queue())

        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # ── Fix-self: activate work mode in LIS repo ──
            if msg.get("type") == "fix_self":
                lis_dir = str(Path(__file__).parent)
                await work_session.start(lis_dir)
                response_text = "Work mode active in my own repo, sir. Tell me what needs fixing."
                tts = strip_markdown_for_tts(response_text)
                await ws.send_json({"type": "status", "state": "speaking"})
                audio = await synthesize_speech(tts)
                if audio:
                    await ws.send_json({"type": "audio", "data": base64.b64encode(audio).decode(), "text": response_text})
                else:
                    await ws.send_json({"type": "text", "text": response_text})
                await ws.send_json({"type": "status", "state": "idle"})
                continue

            if msg.get("type") == "abort_audio":
                log.info("Barge-in detected: Aborting audio")
                _current_response_id += 1
                _cancel_response = True
                continue

            if msg.get("type") != "transcript" or not msg.get("isFinal"):
                continue

            user_text = apply_speech_corrections(msg.get("text", "").strip())
            if not user_text:
                continue

            # Cancel any in-flight response
            _current_response_id += 1
            my_response_id = _current_response_id
            _cancel_response = True
            await asyncio.sleep(0.05)  
            _cancel_response = False

            voice_state["last_user_time"] = time.time()
            log.info(f"User: {user_text}")

            # Lazy project scan on first message
            global cached_projects
            if not cached_projects:
                try:
                    loop = asyncio.get_event_loop()
                    cached_projects = await asyncio.wait_for(
                        loop.run_in_executor(None, _scan_projects_sync),
                        timeout=3
                    )
                    log.info(f"Scanned {len(cached_projects)} projects")
                except Exception:
                    cached_projects = []

            response_text = ""
            actions_to_execute = []
            thought = ""

            try:
                # ══════════════════════════════════════════════════
                # 0. FAST PATH — instant execution, NO LLM needed
                # ══════════════════════════════════════════════════
                fast_action = detect_action_fast(user_text)
                if fast_action:
                    log.info(f"Fast-path: {fast_action}")
                    response_text = "Right away, sir."
                    actions_to_execute = [{"action": fast_action["action"], "args": fast_action.get("args", {})}]

                else:
                    # ══════════════════════════════════════════════
                    # SLOW PATH — needs LLM reasoning
                    # ══════════════════════════════════════════════
                    await ws.send_json({"type": "status", "state": "thinking"})
                    t_lower = user_text.lower()
                    
                    # Inject session summary into context if it exists
                    runtime_context = f"{session_summary}\n\n" if session_summary else ""

                    # Neural processing (sentiment + monologue) — non-blocking
                    memories = memory.build_memory_context(user_text)
                    try:
                        sentiment_data, thought = await asyncio.wait_for(
                            asyncio.gather(
                                empathy.analyze_sentiment(user_text),
                                brain.internal_monologue(user_text, empathy.current_state.name, empathy.rapport, runtime_context + memories)
                            ),
                            timeout=5.0  # Don't hang if API is dead
                        )
                    except Exception:
                        sentiment_data = {"sentiment": 0.0, "delta": 0, "state": "calm"}
                        thought = "Focusing on the task."

                    empathy.update_state(sentiment_data.get("state", "calm"), sentiment_data.get("delta", 0))

                    # v2.0: Track sentiment for behavioral patterns
                    empathy.track_sentiment(sentiment_data.get("sentiment", 0.0))

                    # v2.0: Classify intent and detect corrections
                    user_intent = brain.classify_intent(user_text, sentiment_data)
                    brain.track_intent(user_intent)

                    # v2.0: Auto-learn from corrections
                    if user_intent == "correction":
                        correction_text = brain.detect_correction(user_text)
                        if correction_text:
                            learn_from_correction(user_text, correction_text, last_lis_response)
                            log.info(f"Learned correction: {correction_text}")

                    # Background: record interaction with intent
                    asyncio.create_task(asyncio.to_thread(
                        memory.record_interaction,
                        sentiment=sentiment_data.get("sentiment", 0.0),
                        state=empathy.current_state.name,
                        intent=user_intent,
                        rapport=sentiment_data.get("delta", 0),
                        summary=thought if isinstance(thought, str) else ""
                    ))

                    # ── PLANNING MODE ──
                    if planner.is_planning:
                        if any(p in t_lower for p in BYPASS_PHRASES):
                            plan = planner.active_plan
                            if plan:
                                plan.skipped = True
                                for q in plan.pending_questions[plan.current_question_index:]:
                                    if q.get("default") is not None and q["key"] not in plan.answers:
                                        plan.answers[q["key"]] = q["default"]
                            prompt = await planner.build_prompt()
                            name = _generate_project_name(prompt)
                            path = str(Path.home() / "Desktop" / name)
                            os.makedirs(path, exist_ok=True)
                            Path(path, "CLAUDE.md").write_text(prompt)
                            did = dispatch_registry.register(name, path, prompt[:200])
                            asyncio.create_task(_execute_prompt_project(name, prompt, work_session, ws, dispatch_id=did, history=history, voice_state=voice_state))
                            planner.reset()
                            response_text = "Building it now, sir."
                        elif planner.active_plan and planner.active_plan.confirmed is False and planner.active_plan.current_question_index >= len(planner.active_plan.pending_questions):
                            result = await planner.handle_confirmation(user_text)
                            if result["confirmed"]:
                                prompt = await planner.build_prompt()
                                name = _generate_project_name(prompt)
                                path = str(Path.home() / "Desktop" / name)
                                os.makedirs(path, exist_ok=True)
                                Path(path, "CLAUDE.md").write_text(prompt)
                                did = dispatch_registry.register(name, path, prompt[:200])
                                asyncio.create_task(_execute_prompt_project(name, prompt, work_session, ws, dispatch_id=did, history=history, voice_state=voice_state))
                                planner.reset()
                                response_text = "On it, sir."
                            elif result["cancelled"]:
                                planner.reset()
                                response_text = "Cancelled, sir."
                            else:
                                response_text = result.get("modification_question", "How shall I adjust the plan, sir?")
                        else:
                            result = await planner.process_answer(user_text, cached_projects)
                            if result["plan_complete"]:
                                response_text = result.get("confirmation_summary", "Ready to build. Shall I proceed, sir?")
                            else:
                                response_text = result.get("next_question", "What else, sir?")

                    elif any(w in t_lower for w in ["quit work mode", "exit work mode", "go back to chat", "regular mode", "stop working"]):
                        if work_session.active:
                            await work_session.stop()
                            response_text = "Back to conversation mode, sir."
                        else:
                            response_text = "Already in conversation mode, sir."

                    # ── WORK MODE ──
                    elif work_session.active:
                        if is_casual_question(user_text):
                            persona_prompt = empathy.get_persona_prompt()
                            full_context = f"{persona_prompt}\nInternal thought: {thought}\n\n{memories}"
                            response_text = await generate_response(
                                user_text, anthropic_client, task_manager,
                                cached_projects, history, empathy,
                                last_response=last_lis_response,
                                session_summary=session_summary,
                                context_override=full_context
                            )
                        else:
                            await ws.send_json({"type": "status", "state": "working"})
                            full_response = await work_session.send(user_text)

                            # Claude CLI is dead (credits exhausted / not found)
                            # Auto-exit work mode and fall back to full conversation pipeline
                            if full_response == CLI_DEAD_SENTINEL:
                                log.warning("Claude CLI dead. Auto-exiting work mode, falling back to conversation pipeline.")
                                await work_session.stop()

                                # Notify user, then process their request through the normal pipeline
                                prefix = "Claude Code is offline right now — credits likely, sir. Switching to conversation mode. "
                                persona_prompt = empathy.get_persona_prompt()
                                context_summary = memory.get_context_summary()
                                full_context = f"{persona_prompt}\nInternal thought: {thought}\n\n{context_summary}"

                                fallback_response = await generate_response(
                                    user_text, anthropic_client, task_manager,
                                    cached_projects, history, empathy,
                                    last_response=last_lis_response,
                                    session_summary=session_summary,
                                    context_override=full_context
                                )
                                response_text = prefix + fallback_response
                            elif full_response:
                                try:
                                    summary = await generate_text_groq(
                                        system_prompt=f"You are LIS reporting to {USER_NAME}. Summarize in 1-2 sentences.",
                                        messages=[{"role": "user", "content": f"Summarize work session:\n{full_response[:2000]}"}]
                                    )
                                    response_text = summary or "Work complete, sir."
                                except Exception:
                                    response_text = "Work complete, sir."
                            else:
                                response_text = "Work complete, sir."

                    # ── CONVERSATION MODE ──
                    else:
                        persona_prompt = empathy.get_persona_prompt()
                        context_summary = memory.get_context_summary()

                        # ── RAG: Augment with semantic vector memory ──
                        semantic_ctx = ""
                        try:
                            semantic_ctx = vector_mem.build_context(user_text, max_items=5)
                        except Exception as e:
                            log.debug(f"Vector memory search skipped: {e}")

                        full_context = f"{persona_prompt}\nInternal thought: {thought}\n\n{context_summary}"
                        if semantic_ctx:
                            full_context += f"\n\n{semantic_ctx}"

                        # ── ReAct: Multi-step reasoning for complex tasks ──
                        if ReActEngine.should_use_react(user_text):
                            log.info(f"ReAct triggered for: {user_text[:60]}")
                            await ws.send_json({"type": "status", "state": "working"})

                            # Build skill list for ReAct
                            skill_list = [
                                f"- {name}: {s.description}"
                                for name, s in skills.registry._skills.items()
                            ]

                            react_result = await react.run(
                                user_request=user_text,
                                context=full_context,
                                available_skills=skill_list,
                                max_steps=6,
                            )
                            response_text = react_result.response
                            if react_result.actions_taken:
                                log.info(f"ReAct completed: {react_result.step_count} steps, actions: {react_result.actions_taken}")
                        else:
                            full_response = await generate_response(
                                user_text, anthropic_client, task_manager,
                                cached_projects, history, empathy,
                                last_response=last_lis_response,
                                session_summary=session_summary,
                                context_override=full_context
                            )
                            response_text, actions_to_execute = extract_action(full_response)

                # ══════════════════════════════════════════════════
                # ACTION EXECUTION — runs for ALL paths
                # KEY FIX: Never overwrite the LLM's conversational response.
                # Only use skill confirmation if there was NO spoken text.
                # ══════════════════════════════════════════════════
                for action_item in actions_to_execute:
                    action_name = action_item["action"]
                    action_args = action_item.get("args", {})
                    log.info(f"Executing Skill: {action_name}({action_args})")

                    if action_name in ["screen", "describe_screen"]:
                        asyncio.create_task(_lookup_and_report("screen", _do_screen_lookup, ws, history=history, voice_state=voice_state))
                        if not response_text: response_text = "Dekhti hoon abhi."
                    elif action_name == "research":
                        name = _generate_project_name(action_args)
                        path = str(Path.home() / "Desktop" / name)
                        os.makedirs(path, exist_ok=True)
                        await work_session.start(path)
                        asyncio.create_task(self_work_and_notify(work_session, action_args, ws))
                        if not response_text: response_text = "Abhi dekhti hoon."
                    else:
                        result = await handle_skill_execution(action_name, action_args)
                        # KEY FIX: Only use skill result if LLM didn't already provide text
                        if result and result.get("success") and result.get("confirmation"):
                            if not response_text:
                                response_text = result["confirmation"]
                            else:
                                # Append skill data to existing response if it adds value
                                response_text += " " + result["confirmation"]
                        elif result and not result.get("success"):
                            # Skill failed — append error to the response text
                            log.warning(f"Skill {action_name} failed: {result.get('confirmation')}")
                            error_msg = result.get('confirmation', 'Unknown error.')
                            if not response_text or response_text in ["Right away, sir.", "Got it."]:
                                response_text = f"Arre yaar, {action_name} fail ho gaya: {error_msg}"
                            else:
                                response_text += f" But I ran into an issue: {error_msg}"

                # ══════════════════════════════════════════════════
                # VOICE RESPONSE — always speaks
                # ══════════════════════════════════════════════════
                if not response_text:
                    response_text = "Understood, sir."

                tts_text = strip_markdown_for_tts(response_text)
                await ws.send_json({"type": "status", "state": "speaking"})
                # Tell frontend to clear any queued audio before sending new audio
                await ws.send_json({"type": "stop_audio"})
                
                import re
                # Split roughly by sentence boundaries while keeping punctuation
                # This regex captures the punctuation and then we re-attach it
                parts = re.split(r'([.!?;]+)', tts_text)
                chunks = []
                for i in range(0, len(parts)-1, 2):
                    chunks.append((parts[i] + parts[i+1]).strip())
                if len(parts) % 2 == 1 and parts[-1].strip():
                    chunks.append(parts[-1].strip())
                if not chunks:
                    chunks = [tts_text]
                
                # Stream the chunks sequentially to reduce TTFB (Time To First Byte) for audio
                audio_sent = False
                for chunk in chunks:
                    if not chunk: continue
                    chunk_audio = await synthesize_speech(chunk)
                    if chunk_audio and len(chunk_audio) > 512:
                        await ws.send_json({"type": "audio", "data": base64.b64encode(chunk_audio).decode(), "text": chunk})
                        audio_sent = True
                
                if audio_sent:
                    
                    # Log to Long-term Memory (FTS5 keyword search)
                    memory.store_turn("user", user_text)
                    memory.store_turn("assistant", response_text)

                    # ── RAG: Auto-embed in vector memory (background) ──
                    asyncio.create_task(asyncio.to_thread(
                        vector_mem.store_conversation_turn, "user", user_text
                    ))
                    asyncio.create_task(asyncio.to_thread(
                        vector_mem.store_conversation_turn, "assistant", response_text
                    ))
                    
                    history.append({"role": "assistant", "content": response_text})
                    last_lis_response = response_text
                    
                    # Memory Compression: Keep context small
                    messages_since_last_summary += 2
                    if messages_since_last_summary >= 20 and not summary_update_pending:
                        summary_update_pending = True
                        
                        async def _compress_memory():
                            nonlocal session_summary, summary_update_pending, messages_since_last_summary, history
                            try:
                                # Send the oldest 14 messages (7 turns) to be summarized
                                to_summarize = history[:-6]
                                if to_summarize:
                                    new_summary = await _update_session_summary(session_summary, to_summarize, active_client)
                                    if new_summary != session_summary:
                                        session_summary = new_summary
                                        # Keep only the last 6 messages (3 turns)
                                        history = history[-6:]
                                        messages_since_last_summary = 6
                                        log.info(f"Memory compressed. New summary: {session_summary[:60]}...")
                            except Exception as e:
                                log.warning(f"Memory compression failed: {e}")
                            finally:
                                summary_update_pending = False
                        
                        if active_client:
                            asyncio.create_task(_compress_memory())
                else:
                    await ws.send_json({"type": "text", "text": response_text})
                    history.append({"role": "assistant", "content": response_text})
                    messages_since_last_summary += 2
                await ws.send_json({"type": "status", "state": "idle"})

            except Exception as e:
                log.error(f"Voice loop execution error: {e}", exc_info=True)
                try:
                    # Self-Handling: Generate live audio reporting the anomaly instead of silently failing
                    err_msg = "Forgive me, sir. I encountered a systemic anomaly processing that command, but I have recovered."
                    err_audio = await synthesize_speech(err_msg)
                    if err_audio:
                        await ws.send_json({"type": "audio", "data": base64.b64encode(err_audio).decode(), "text": err_msg})
                    else:
                        await ws.send_json({"type": "text", "text": err_msg})
                    await ws.send_json({"type": "status", "state": "idle"})
                except Exception:
                    pass


    except Exception:
        return  # WebSocket already gone

# Settings / Configuration endpoints
# ---------------------------------------------------------------------------

def _env_file_path() -> Path:
    return Path(__file__).parent / ".env"

def _env_example_path() -> Path:
    return Path(__file__).parent / ".env.example"

def _read_env() -> tuple[list[str], dict[str, str]]:
    """Read .env file. Returns (raw_lines, parsed_dict). Creates from .env.example if missing."""
    path = _env_file_path()
    if not path.exists():
        example = _env_example_path()
        if example.exists():
            import shutil as _shutil
            _shutil.copy2(str(example), str(path))
        else:
            path.write_text("")
    lines = path.read_text().splitlines()
    parsed: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, v = stripped.partition("=")
            parsed[k.strip()] = v.strip().strip('"').strip("'")
    return lines, parsed

def _write_env_key(key: str, value: str) -> None:
    """Update a single key in .env, preserving comments and order."""
    lines, _ = _read_env()
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, _ = stripped.partition("=")
            if k.strip() == key:
                new_lines.append(f"{key}={value}")
                found = True
                continue
        new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    _env_file_path().write_text("\n".join(new_lines) + "\n")
    os.environ[key] = value

class KeyUpdate(BaseModel):
    key_name: str
    key_value: str

class KeyTest(BaseModel):
    key_value: str | None = None

class PreferencesUpdate(BaseModel):
    user_name: str = ""
    honorific: str = "sir"
    calendar_accounts: str = "auto"

@app.post("/api/settings/keys")
async def api_settings_keys(body: KeyUpdate):
    allowed = {"ANTHROPIC_API_KEY", "FISH_API_KEY", "FISH_VOICE_ID", "USER_NAME", "HONORIFIC", "CALENDAR_ACCOUNTS"}
    if body.key_name not in allowed:
        return JSONResponse({"success": False, "error": "Invalid key name"}, status_code=400)
    _write_env_key(body.key_name, body.key_value)
    return {"success": True}

@app.post("/api/settings/test-anthropic")
async def api_test_anthropic(body: KeyTest):
    key = body.key_value or os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return {"valid": False, "error": "No key provided"}
    try:
        client = anthropic.AsyncAnthropic(api_key=key)
        await client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=10, messages=[{"role": "user", "content": "Hi"}])
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "error": str(e)[:200]}

@app.post("/api/settings/test-fish")
async def api_test_fish(body: KeyTest):
    key = body.key_value or os.getenv("FISH_API_KEY", "")
    if not key:
        return {"valid": False, "error": "No key provided"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.fish.audio/v1/tts",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"text": "test", "reference_id": FISH_VOICE_ID},
            )
            if resp.status_code in (200, 201):
                return {"valid": True}
            elif resp.status_code == 401:
                return {"valid": False, "error": "Invalid API key"}
            else:
                return {"valid": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"valid": False, "error": str(e)[:200]}

@app.get("/api/settings/status")
async def api_settings_status():
    import shutil as _shutil
    _, env_dict = _read_env()
    claude_installed = _shutil.which("claude") is not None
    calendar_ok = mail_ok = notes_ok = False
    try: await get_todays_events(); calendar_ok = True
    except Exception: pass
    try: await get_unread_count(); mail_ok = True
    except Exception: pass
    try: await get_recent_notes(count=1); notes_ok = True
    except Exception: pass
    memory_count = task_count = 0
    try: memory_count = len(get_important_memories(limit=9999))
    except Exception: pass
    try: task_count = len(get_open_tasks())
    except Exception: pass
    return {
        "claude_code_installed": claude_installed,
        "calendar_accessible": calendar_ok,
        "mail_accessible": mail_ok,
        "notes_accessible": notes_ok,
        "memory_count": memory_count,
        "task_count": task_count,
        "server_port": 8340,
        "uptime_seconds": int(time.time() - _session_start),
        "env_keys_set": {
            "anthropic": bool(env_dict.get("ANTHROPIC_API_KEY", "").strip() and env_dict.get("ANTHROPIC_API_KEY", "") != "your-anthropic-api-key-here"),
            "fish_audio": bool(env_dict.get("FISH_API_KEY", "").strip() and env_dict.get("FISH_API_KEY", "") != "your-fish-audio-api-key-here"),
            "fish_voice_id": bool(env_dict.get("FISH_VOICE_ID", "").strip()),
            "user_name": env_dict.get("USER_NAME", ""),
        },
    }

@app.get("/api/settings/preferences")
async def api_get_preferences():
    _, env_dict = _read_env()
    return {
        "user_name": env_dict.get("USER_NAME", ""),
        "honorific": env_dict.get("HONORIFIC", "sir"),
        "calendar_accounts": env_dict.get("CALENDAR_ACCOUNTS", "auto"),
    }

@app.post("/api/settings/preferences")
async def api_save_preferences(body: PreferencesUpdate):
    _write_env_key("USER_NAME", body.user_name)
    _write_env_key("HONORIFIC", body.honorific)
    _write_env_key("CALENDAR_ACCOUNTS", body.calendar_accounts)
    return {"success": True}

# ---------------------------------------------------------------------------
# Control endpoints (restart, fix-self)
# ---------------------------------------------------------------------------

@app.post("/api/restart")
async def api_restart():
    """Restart the LIS server."""
    log.info("Restart requested - shutting down in 2 seconds")
    async def _restart():
        await asyncio.sleep(2)
        cmd = [sys.executable, __file__, "--port", "8340", "--host", "0.0.0.0"]
        os.execv(sys.executable, cmd)
    asyncio.create_task(_restart())
    return {"status": "restarting"}


@app.post("/api/fix-self")
async def api_fix_self():
    """Enter work mode in the LIS repo - LIS can now fix himself."""
    lis_dir = str(Path(__file__).parent)
    try:
        # Launch claude interactive on Windows
        cmd = f'start cmd.exe /k "cd /d {lis_dir} && claude --dangerously-skip-permissions"'
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        log.info("Work mode: LIS repo opened for self-improvement")
        return {"status": "work_mode_active", "path": lis_dir}
    except Exception as e:
        log.error(f"api_fix_self failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ---------------------------------------------------------------------------
# Static file serving (frontend)
# ---------------------------------------------------------------------------

from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    @app.get("/")
    async def serve_index():
        return FileResponse(str(FRONTEND_DIST / "index.html"))

    @app.get("/favicon.ico")
    async def serve_favicon():
        return Response(status_code=204)

    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import uvicorn
    import subprocess as _sp
    import socket

    parser = argparse.ArgumentParser(description="LIS Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8340, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on changes")
    parser.add_argument("--ssl", action="store_true", help="Enable HTTPS with key.pem/cert.pem")
    args = parser.parse_args()

    # ── AUTO PORT KILL ── Never get WinError 10048 again
    def _kill_port(port: int):
        """Kill any process holding the given port on Windows."""
        try:
            result = _sp.run(
                f'netstat -ano | findstr :{port}',
                shell=True, capture_output=True, text=True
            )
            for line in result.stdout.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 5 and 'LISTENING' in line:
                    pid = parts[-1]
                    _sp.run(f'taskkill /F /PID {pid}', shell=True, 
                            capture_output=True)
                    print(f"  [AUTO-FIX] Killed stale process {pid} on port {port}")
        except Exception:
            pass

    # Check if port is busy and auto-kill
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        if s.connect_ex(('127.0.0.1', args.port)) == 0:
            print(f"  [AUTO-FIX] Port {args.port} is busy. Cleaning up...")
            _kill_port(args.port)
            import time; time.sleep(2)
        s.close()
    except Exception:
        pass

    # Auto-detect SSL certs
    cert_file = Path(__file__).parent / "cert.pem"
    key_file = Path(__file__).parent / "key.pem"
    use_ssl = args.ssl or (cert_file.exists() and key_file.exists())

    proto = "https" if use_ssl else "http"
    ws_proto = "wss" if use_ssl else "ws"

    print()
    print("  L.I.S. Server v0.1.0")
    print(f"  WebSocket: {ws_proto}://{args.host}:{args.port}/ws/voice")
    print(f"  REST API:  {proto}://{args.host}:{args.port}/api/")
    print(f"  Tasks:     {proto}://{args.host}:{args.port}/api/tasks")
    print()
    gemini_tag = "Gemini [OK]" if GEMINI_API_KEY else "Gemini [--]"
    cerebras_tag = "Cerebras [OK]" if CEREBRAS_API_KEY else "Cerebras [--]"
    openrouter_tag = "OpenRouter [OK]" if OPENROUTER_API_KEY else "OpenRouter [--]"
    print(f"  LLM Chain: Anthropic -> Groq -> {gemini_tag} -> {cerebras_tag} -> {openrouter_tag} -> Ollama (local)")
    print(f"  Voice:     Edge-TTS (NeerjaNeural) -> gTTS fallback")
    print()

    ssl_kwargs = {}
    if use_ssl:
        ssl_kwargs["ssl_keyfile"] = str(key_file)
        ssl_kwargs["ssl_certfile"] = str(cert_file)

    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        **ssl_kwargs,
    )
