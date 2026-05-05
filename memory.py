"""
LIS Memory & Planning — persistent context, tasks, notes, and smart routing.

Three systems:
1. Memory — facts, preferences, project context LIS learns from conversations
2. Tasks — to-do items with priority, due dates, project association
3. Notes — freeform context tied to projects, people, or topics

Everything stored in SQLite. Relevant memories injected into every LLM call
so LIS gets smarter over time.
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("lis.memory")

DB_PATH = Path(__file__).parent / "data" / "lis.db"


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,          -- 'fact', 'preference', 'project', 'person', 'decision'
            content TEXT NOT NULL,
            source TEXT DEFAULT '',      -- what conversation/context it came from
            importance INTEGER DEFAULT 5, -- 1-10, higher = more important
            created_at REAL NOT NULL,
            last_accessed REAL,
            access_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            priority TEXT DEFAULT 'medium', -- 'high', 'medium', 'low'
            status TEXT DEFAULT 'open',     -- 'open', 'in_progress', 'done', 'cancelled'
            due_date TEXT,                  -- ISO date string
            due_time TEXT,                  -- HH:MM
            project TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',         -- JSON array
            notes TEXT DEFAULT '',
            created_at REAL NOT NULL,
            completed_at REAL
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT DEFAULT '',
            content TEXT NOT NULL,
            topic TEXT DEFAULT '',       -- project name, person, or topic
            tags TEXT DEFAULT '[]',      -- JSON array
            created_at REAL NOT NULL,
            updated_at REAL
        );

        CREATE TABLE IF NOT EXISTS alarms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,          -- HH:MM
            label TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            repeat_days TEXT DEFAULT '[]', -- JSON array of day names
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS timers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            duration INTEGER NOT NULL,    -- seconds
            end_time REAL NOT NULL,      -- unix timestamp
            label TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_time REAL NOT NULL,   -- unix timestamp
            content TEXT NOT NULL,
            status TEXT DEFAULT 'pending', -- 'pending', 'triggered', 'dismissed'
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS saved_lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,    -- 'shopping', 'todo', etc.
            items TEXT DEFAULT '[]',     -- JSON array of strings
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,          -- 'user', 'assistant'
            content TEXT NOT NULL,
            timestamp REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            user_intent TEXT DEFAULT '',
            sentiment_score REAL DEFAULT 0, -- -1.0 to 1.0
            rapport_delta REAL DEFAULT 0,
            lis_state TEXT DEFAULT 'calm',
            summary TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS narrative (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            emotional_tone TEXT DEFAULT 'neutral',
            created_at REAL NOT NULL
        );

        -- v2.0: Personal Knowledge Graph
        CREATE TABLE IF NOT EXISTS knowledge_graph (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,       -- 'preference', 'person', 'habit', 'routine',
                                          -- 'goal', 'dislike', 'communication_style',
                                          -- 'domain_expertise', 'humor_style'
            key TEXT NOT NULL,            -- e.g., 'favorite_music_genre', 'mom_name'
            value TEXT NOT NULL,          -- e.g., 'lo-fi hip hop', 'Priya'
            confidence REAL DEFAULT 0.8,  -- 0.0-1.0, how sure we are
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            access_count INTEGER DEFAULT 0
        );

        -- v2.0: Adaptive Learning Signals
        CREATE TABLE IF NOT EXISTS learning_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            signal_type TEXT NOT NULL,     -- 'correction', 'positive_engagement',
                                          -- 'ignored', 'repeated_request', 'pattern'
            user_message TEXT DEFAULT '',
            lis_response TEXT DEFAULT '',
            correction_text TEXT DEFAULT '',  -- what the user actually meant
            context TEXT DEFAULT ''
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            content, type, source,
            content='memories', content_rowid='id'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(
            content,
            content='conversation_history', content_rowid='id'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS task_fts USING fts5(
            title, description, project, notes,
            content='tasks', content_rowid='id'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(
            title, content, topic,
            content='notes', content_rowid='id'
        );
    """)
    conn.close()
    log.info("Memory database initialized")


# ---------------------------------------------------------------------------
# Memories — facts LIS learns
# ---------------------------------------------------------------------------

def remember(content: str, mem_type: str = "fact", source: str = "", importance: int = 5) -> int:
    """Store a memory. Returns the memory ID."""
    conn = _get_db()
    cur = conn.execute(
        "INSERT INTO memories (type, content, source, importance, created_at) VALUES (?, ?, ?, ?, ?)",
        (mem_type, content, source, importance, time.time())
    )
    mem_id = cur.lastrowid
    # Update FTS
    conn.execute(
        "INSERT INTO memory_fts (rowid, content, type, source) VALUES (?, ?, ?, ?)",
        (mem_id, content, mem_type, source)
    )
    conn.commit()
    conn.close()
    log.info(f"Stored memory [{mem_type}]: {content[:60]}")
    return mem_id


def _sanitize_fts_query(query: str) -> str:
    """Clean a query string for FTS5 — remove special characters that break it."""
    # Remove apostrophes, quotes, and FTS operators
    cleaned = query.replace("'", "").replace('"', "").replace("*", "").replace("-", " ")
    # Take meaningful words only
    words = [w for w in cleaned.split() if len(w) > 2]
    if not words:
        return ""
    # Join with OR for broader matching
    return " OR ".join(words[:5])


def recall(query: str, limit: int = 5) -> list[dict]:
    """Search memories by relevance. Returns most relevant matches."""
    fts_query = _sanitize_fts_query(query)
    if not fts_query:
        return []
    conn = _get_db()
    try:
        results = conn.execute("""
            SELECT m.id, m.type, m.content, m.importance, m.created_at, m.access_count
            FROM memory_fts f
            JOIN memories m ON f.rowid = m.id
            WHERE memory_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (fts_query, limit)).fetchall()
    except Exception:
        results = []

    # Update access counts
    for r in results:
        conn.execute(
            "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
            (time.time(), r["id"])
        )
    conn.commit()
    conn.close()
    return [dict(r) for r in results]


def get_recent_memories(limit: int = 10) -> list[dict]:
    """Get most recent memories."""
    conn = _get_db()
    results = conn.execute(
        "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in results]


def get_important_memories(limit: int = 10) -> list[dict]:
    """Get highest importance memories."""
    conn = _get_db()
    results = conn.execute(
        "SELECT * FROM memories ORDER BY importance DESC, access_count DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in results]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def create_task(title: str, description: str = "", priority: str = "medium",
                due_date: str = "", due_time: str = "", project: str = "",
                tags: list[str] = None) -> int:
    """Create a task. Returns task ID."""
    conn = _get_db()
    cur = conn.execute(
        """INSERT INTO tasks (title, description, priority, due_date, due_time,
           project, tags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, description, priority, due_date, due_time,
         project, json.dumps(tags or []), time.time())
    )
    task_id = cur.lastrowid
    conn.execute(
        "INSERT INTO task_fts (rowid, title, description, project, notes) VALUES (?, ?, ?, ?, ?)",
        (task_id, title, description, project, "")
    )
    conn.commit()
    conn.close()
    log.info(f"Created task [{priority}]: {title}")
    return task_id


def get_open_tasks(project: str = None) -> list[dict]:
    """Get all open/in-progress tasks, optionally filtered by project."""
    conn = _get_db()
    if project:
        results = conn.execute(
            "SELECT * FROM tasks WHERE status IN ('open','in_progress') AND project LIKE ? ORDER BY "
            "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, due_date",
            (f"%{project}%",)
        ).fetchall()
    else:
        results = conn.execute(
            "SELECT * FROM tasks WHERE status IN ('open','in_progress') ORDER BY "
            "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, due_date"
        ).fetchall()
    conn.close()
    return [dict(r) for r in results]


def get_tasks_for_date(date_str: str) -> list[dict]:
    """Get tasks due on a specific date (YYYY-MM-DD)."""
    conn = _get_db()
    results = conn.execute(
        "SELECT * FROM tasks WHERE due_date = ? AND status != 'cancelled' ORDER BY "
        "CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, due_time",
        (date_str,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in results]


def complete_task(task_id: int):
    """Mark a task as done."""
    conn = _get_db()
    conn.execute(
        "UPDATE tasks SET status = 'done', completed_at = ? WHERE id = ?",
        (time.time(), task_id)
    )
    conn.commit()
    conn.close()


def search_tasks(query: str, limit: int = 10) -> list[dict]:
    """Search tasks by text."""
    fts_query = _sanitize_fts_query(query)
    if not fts_query:
        return []
    conn = _get_db()
    try:
        results = conn.execute("""
            SELECT t.* FROM task_fts f
            JOIN tasks t ON f.rowid = t.id
            WHERE task_fts MATCH ?
            ORDER BY rank LIMIT ?
        """, (fts_query, limit)).fetchall()
    except Exception:
        results = []
    conn.close()
    return [dict(r) for r in results]


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def create_note(content: str, title: str = "", topic: str = "", tags: list[str] = None) -> int:
    """Create a note. Returns note ID."""
    conn = _get_db()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO notes (title, content, topic, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (title, content, topic, json.dumps(tags or []), now, now)
    )
    note_id = cur.lastrowid
    conn.execute(
        "INSERT INTO note_fts (rowid, title, content, topic) VALUES (?, ?, ?, ?)",
        (note_id, title, content, topic)
    )
    conn.commit()
    conn.close()
    log.info(f"Created note: {title or content[:40]}")
    return note_id


def search_notes(query: str, limit: int = 10) -> list[dict]:
    """Search notes by text."""
    fts_query = _sanitize_fts_query(query)
    if not fts_query:
        return []
    conn = _get_db()
    try:
        results = conn.execute("""
            SELECT n.* FROM note_fts f
            JOIN notes n ON f.rowid = n.id
            WHERE note_fts MATCH ?
            ORDER BY rank LIMIT ?
        """, (fts_query, limit)).fetchall()
    except Exception:
        results = []
    conn.close()
    return [dict(r) for r in results]


def get_notes_by_topic(topic: str) -> list[dict]:
    """Get all notes for a topic/project."""
    conn = _get_db()
    results = conn.execute(
        "SELECT * FROM notes WHERE topic LIKE ? ORDER BY updated_at DESC",
        (f"%{topic}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in results]


# ---------------------------------------------------------------------------
# Alarms, Timers, Reminders
# ---------------------------------------------------------------------------

def add_alarm(time_str: str, label: str = "", repeat_days: list[str] = None) -> int:
    conn = _get_db()
    cur = conn.execute(
        "INSERT INTO alarms (time, label, repeat_days, created_at) VALUES (?, ?, ?, ?)",
        (time_str, label, json.dumps(repeat_days or []), time.time())
    )
    conn.commit()
    conn.close()
    return cur.lastrowid

def get_active_alarms() -> list[dict]:
    conn = _get_db()
    results = conn.execute("SELECT * FROM alarms WHERE is_active = 1").fetchall()
    conn.close()
    return [dict(r) for r in results]

def add_timer(duration: int, label: str = "") -> int:
    conn = _get_db()
    end_time = time.time() + duration
    cur = conn.execute(
        "INSERT INTO timers (duration, end_time, label, created_at) VALUES (?, ?, ?, ?)",
        (duration, end_time, label, time.time())
    )
    conn.commit()
    conn.close()
    return cur.lastrowid

def get_active_timers() -> list[dict]:
    conn = _get_db()
    results = conn.execute("SELECT * FROM timers WHERE is_active = 1 AND end_time > ?", (time.time(),)).fetchall()
    conn.close()
    return [dict(r) for r in results]

def add_reminder(trigger_time: float, content: str) -> int:
    conn = _get_db()
    cur = conn.execute(
        "INSERT INTO reminders (trigger_time, content, created_at) VALUES (?, ?, ?)",
        (trigger_time, content, time.time())
    )
    conn.commit()
    conn.close()
    return cur.lastrowid

def get_pending_reminders() -> list[dict]:
    conn = _get_db()
    results = conn.execute("SELECT * FROM reminders WHERE status = 'pending'").fetchall()
    conn.close()
    return [dict(r) for r in results]

def update_reminder_status(rem_id: int, status: str):
    conn = _get_db()
    conn.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, rem_id))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Saved Lists (Shopping, etc.)
# ---------------------------------------------------------------------------

def update_list(name: str, items: list[str]):
    conn = _get_db()
    now = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO saved_lists (name, items, updated_at) VALUES (?, ?, ?)",
        (name.lower(), json.dumps(items), now)
    )
    conn.commit()
    conn.close()

def get_list(name: str) -> list[str]:
    conn = _get_db()
    row = conn.execute("SELECT items FROM saved_lists WHERE name = ?", (name.lower(),)).fetchone()
    conn.close()
    return json.loads(row["items"]) if row else []


# ---------------------------------------------------------------------------
# Empathy & Relationship Tracking
# ---------------------------------------------------------------------------

def record_interaction(sentiment: float, state: str, intent: str = "", rapport: float = 0, summary: str = ""):
    """Record the emotional context of an interaction."""
    conn = _get_db()
    conn.execute(
        "INSERT INTO interactions (timestamp, user_intent, sentiment_score, rapport_delta, lis_state, summary) VALUES (?, ?, ?, ?, ?, ?)",
        (time.time(), intent, sentiment, rapport, state, summary)
    )
    conn.commit()
    conn.close()

def get_soul_context(limit: int = 5) -> dict:
    """Get recent emotional trend and rapport context."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT sentiment_score, rapport_delta, lis_state FROM interactions ORDER BY timestamp DESC LIMIT ?",
        (limit,)
    ).fetchall()
    
    # Also get relationship narrative
    story = conn.execute("SELECT content FROM narrative ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()
    
    avg_sentiment = sum(r["sentiment_score"] for r in rows) / len(rows) if rows else 0.0
    total_rapport = sum(r["rapport_delta"] for r in rows) if rows else 0.0
    last_state = rows[0]["lis_state"] if rows else "calm"
    
    return {
        "avg_sentiment": avg_sentiment,
        "rapport_delta": total_rapport,
        "last_state": last_state,
        "narrative_summary": story["content"] if story else "Just beginning our journey, sir."
    }

def add_narrative_event(content: str, tone: str = "neutral"):
    """Add a significant event to the Story of Us."""
    conn = _get_db()
    conn.execute(
        "INSERT INTO narrative (content, emotional_tone, created_at) VALUES (?, ?, ?)",
        (content, tone, time.time())
    )
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# Long-term Conversation History (RAG)
# ---------------------------------------------------------------------------

def store_turn(role: str, content: str):
    """Save a conversation turn permanently."""
    conn = _get_db()
    cur = conn.execute(
        "INSERT INTO conversation_history (role, content, timestamp) VALUES (?, ?, ?)",
        (role, content, time.time())
    )
    turn_id = cur.lastrowid
    conn.execute(
        "INSERT INTO conversation_fts (rowid, content) VALUES (?, ?)",
        (turn_id, content)
    )
    conn.commit()
    conn.close()

def get_chat_history(limit: int = 50) -> list[dict]:
    """Get recent conversation history for the chat panel."""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT role, content, timestamp FROM conversation_history ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in reversed(rows)]
    except Exception as e:
        log.warning(f"get_chat_history failed: {e}")
        return []
    finally:
        conn.close()

def recall_conversations(query: str, limit: int = 3) -> str:
    """Search for semantically relevant past conversations."""
    fts_query = _sanitize_fts_query(query)
    if not fts_query:
        return ""
    conn = _get_db()
    try:
        # Get matching turns and their immediate neighbors if possible
        # (For simplicity we just get the matching turns here)
        results = conn.execute("""
            SELECT h.role, h.content, h.timestamp
            FROM conversation_fts f
            JOIN conversation_history h ON f.rowid = h.id
            WHERE conversation_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (fts_query, limit)).fetchall()
        
        if not results:
            return ""
            
        context = []
        for r in results:
            dt = datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M")
            context.append(f"[{dt}] {r['role'].upper()}: {r['content']}")
        
        return "RELEVANT PAST CONVERSATIONS:\n" + "\n".join(context)
    except Exception:
        return ""
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Context Builder — smart context for LLM calls
# ---------------------------------------------------------------------------

def build_memory_context(user_message: str) -> str:
    """Build relevant context from memories, tasks, and notes for the LLM.

    Searches for relevant memories based on what the user is talking about.
    Fast — runs FTS queries, no heavy computation.
    """
    parts = []

    # Always include: open high-priority tasks
    high_tasks = [t for t in get_open_tasks() if t["priority"] == "high"]
    if high_tasks:
        task_lines = [f"  - [{t['priority']}] {t['title']}" +
                      (f" (due {t['due_date']})" if t["due_date"] else "")
                      for t in high_tasks[:5]]
        parts.append("HIGH PRIORITY TASKS:\n" + "\n".join(task_lines))

    # Search memories relevant to what user is saying
    if len(user_message) > 5:
        relevant = recall(user_message, limit=3)
        if relevant:
            mem_lines = [f"  - [{m['type']}] {m['content']}" for m in relevant]
            parts.append("RELEVANT MEMORIES:\n" + "\n".join(mem_lines))

    # Recent important memories (always available)
    important = get_important_memories(limit=3)
    if important:
        imp_lines = [f"  - {m['content']}" for m in important
                     if not any(m["content"] == r["content"] for r in (relevant if 'relevant' in dir() else []))]
        if imp_lines:
            parts.append("KEY FACTS:\n" + "\n".join(imp_lines[:3]))

    return "\n\n".join(parts) if parts else ""


def format_tasks_for_voice(tasks: list[dict]) -> str:
    """Format tasks for voice response."""
    if not tasks:
        return "No tasks on the list, sir."
    count = len(tasks)
    high = [t for t in tasks if t["priority"] == "high"]
    if count == 1:
        t = tasks[0]
        return f"One task: {t['title']}." + (f" Due {t['due_date']}." if t["due_date"] else "")
    result = f"You have {count} open tasks."
    if high:
        result += f" {len(high)} are high priority."
    top = tasks[:3]
    for t in top:
        result += f" {t['title']}."
    if count > 3:
        result += f" And {count - 3} more."
    return result


def format_plan_for_voice(tasks: list[dict], events: list[dict]) -> str:
    """Format a day plan combining tasks and calendar events."""
    if not tasks and not events:
        return "Your day looks clear, sir. No events or tasks scheduled."

    parts = []
    if events:
        parts.append(f"{len(events)} events on the calendar")
    if tasks:
        high = [t for t in tasks if t["priority"] == "high"]
        parts.append(f"{len(tasks)} tasks" + (f", {len(high)} high priority" if high else ""))

    result = f"For tomorrow: {', '.join(parts)}. "

    # List events first
    if events:
        for e in events[:3]:
            result += f"{e.get('start', '')} {e['title']}. "

    # Then high priority tasks
    if tasks:
        for t in [t for t in tasks if t["priority"] == "high"][:2]:
            result += f"Priority: {t['title']}. "

    result += "Shall I adjust anything?"
    return result


# ---------------------------------------------------------------------------
# Memory extraction — learn from conversations
# ---------------------------------------------------------------------------

async def extract_memories(user_text: str, lis_response: str, anthropic_client) -> list[str]:
    """After a conversation turn, extract any facts worth remembering.

    Uses Haiku to decide if anything in the exchange is worth storing.
    v2.0: Also extracts people, habits, routines, preferences for knowledge graph.
    Returns list of memories stored.
    """
    if not anthropic_client or len(user_text) < 15:
        return []

    try:
        response = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=(
                "Extract facts worth remembering from this conversation. "
                "Types to extract:\n"
                "- FACTS: concrete info (names, dates, plans, goals)\n"
                "- PREFERENCES: likes, dislikes, favorites\n"
                "- PEOPLE: names and relationships (mom=Priya, friend=Rahul)\n"
                "- HABITS: routines, patterns (works out mornings, codes at night)\n"
                "- CORRECTIONS: if user corrected the AI, what they actually meant\n"
                "NOT opinions, greetings, or casual chat. "
                'Return JSON array: [{"type": "fact|preference|project|person|decision|habit|correction", '
                '"content": "...", "importance": 1-10, '
                '"kg_category": "preference|person|habit|routine|goal|dislike|domain_expertise", '
                '"kg_key": "short_key", "kg_value": "value"}] '
                "Return [] if nothing worth remembering. Be selective."
            ),
            messages=[{"role": "user", "content": f"User: {user_text}\nLIS: {lis_response}"}],
        )

        text = response.content[0].text.strip()
        # Parse JSON
        if text.startswith("["):
            items = json.loads(text)
            stored = []
            for item in items:
                if isinstance(item, dict) and "content" in item:
                    remember(
                        content=item["content"],
                        mem_type=item.get("type", "fact"),
                        source=user_text[:50],
                        importance=item.get("importance", 5),
                    )
                    stored.append(item["content"])

                    # Also store in knowledge graph if applicable
                    kg_cat = item.get("kg_category")
                    kg_key = item.get("kg_key")
                    kg_val = item.get("kg_value")
                    if kg_cat and kg_key and kg_val:
                        update_knowledge(kg_cat, kg_key, kg_val)

            return stored
    except Exception as e:
        log.debug(f"Memory extraction failed: {e}")

    return []

def analyze_weekly_patterns() -> str:
    """Analyze learning signals and interactions to return a self-improvement summary."""
    try:
        with _get_db() as conn:
            c = conn.cursor()
            
            # Analyze feedback
            c.execute("SELECT signal_type, COUNT(*) FROM learning_signals GROUP BY signal_type")
            feedback = dict(c.fetchall())
            
            # Analyze intents
            c.execute("SELECT intent, COUNT(*) as cnt FROM interactions WHERE intent != '' GROUP BY intent ORDER BY cnt DESC LIMIT 3")
            top_intents = c.fetchall()
            
            # Get last 5 corrections
            c.execute("SELECT user_correction FROM learning_signals WHERE signal_type = 'correction' ORDER BY timestamp DESC LIMIT 5")
            corrections = [r[0] for r in c.fetchall()]
            
            summary = ["Self-Improvement Analysis:"]
            if feedback:
                summary.append(f"- Feedback Profile: {feedback}")
            if top_intents:
                summary.append(f"- Top User Intents: {', '.join([f'{i[0]} ({i[1]})' for i in top_intents])}")
            if corrections:
                summary.append("- Recent Corrections to Learn From:")
                for corr in corrections:
                    summary.append(f"  * {corr}")
                    
            if len(summary) > 1:
                return "\n".join(summary)
            return "Not enough data for self-improvement analysis yet."
    except Exception as e:
        log.error(f"Pattern analysis failed: {e}")
        return "Analysis unavailable."


def get_context_summary() -> str:
    """Build a quick context summary for the LLM from recent memories and tasks."""
    parts = []

    # Recent memories
    recent = get_recent_memories(limit=5)
    if recent:
        mem_lines = [f"  - {m['content']}" for m in recent]
        parts.append("RECENT MEMORIES:\n" + "\n".join(mem_lines))

    # Open tasks
    tasks = get_open_tasks()
    if tasks:
        task_lines = [f"  - [{t['priority']}] {t['title']}" for t in tasks[:5]]
        parts.append("OPEN TASKS:\n" + "\n".join(task_lines))

    # Knowledge graph highlights
    kg = get_knowledge_summary()
    if kg:
        parts.append(f"ABOUT THE USER:\n{kg}")

    # Soul context
    try:
        soul = get_soul_context()
        if soul:
            parts.append(f"EMOTIONAL STATE: {soul['last_state']} | Rapport trend: {soul['rapport_delta']}")
    except Exception:
        pass

    return "\n\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Knowledge Graph — structured user understanding (v2.0)
# ---------------------------------------------------------------------------

def update_knowledge(category: str, key: str, value: str, confidence: float = 0.8):
    """Store or update a knowledge graph entry."""
    conn = _get_db()
    now = time.time()
    # Check if key already exists
    existing = conn.execute(
        "SELECT id FROM knowledge_graph WHERE category = ? AND key = ?",
        (category, key)
    ).fetchone()

    if existing:
        conn.execute(
            "UPDATE knowledge_graph SET value = ?, confidence = ?, updated_at = ?, access_count = access_count + 1 WHERE id = ?",
            (value, confidence, now, existing["id"])
        )
    else:
        conn.execute(
            "INSERT INTO knowledge_graph (category, key, value, confidence, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (category, key, value, confidence, now, now)
        )
    conn.commit()
    conn.close()
    log.info(f"Knowledge graph: [{category}] {key} = {value}")


def get_knowledge(category: str = None) -> list[dict]:
    """Get knowledge graph entries, optionally filtered by category."""
    conn = _get_db()
    if category:
        results = conn.execute(
            "SELECT * FROM knowledge_graph WHERE category = ? ORDER BY access_count DESC",
            (category,)
        ).fetchall()
    else:
        results = conn.execute(
            "SELECT * FROM knowledge_graph ORDER BY access_count DESC, updated_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in results]


def get_knowledge_summary(limit: int = 10) -> str:
    """Build a concise summary of user knowledge for LLM context."""
    conn = _get_db()
    results = conn.execute(
        "SELECT category, key, value FROM knowledge_graph ORDER BY access_count DESC, confidence DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    if not results:
        return ""
    lines = [f"  - [{r['category']}] {r['key']}: {r['value']}" for r in results]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Learning Signals — track response quality (v2.0)
# ---------------------------------------------------------------------------

def record_learning_signal(signal_type: str, user_msg: str = "", lis_resp: str = "",
                           correction: str = "", context: str = ""):
    """Record a learning signal for adaptive improvement."""
    conn = _get_db()
    conn.execute(
        "INSERT INTO learning_signals (timestamp, signal_type, user_message, lis_response, correction_text, context) VALUES (?, ?, ?, ?, ?, ?)",
        (time.time(), signal_type, user_msg[:500], lis_resp[:500], correction, context)
    )
    conn.commit()
    conn.close()
    log.info(f"Learning signal: [{signal_type}] {correction[:60] if correction else user_msg[:60]}")


def learn_from_correction(user_text: str, correction: str, lis_response: str = ""):
    """When the user corrects LIS, store the correction as high-importance memory."""
    # Store as a learning signal
    record_learning_signal("correction", user_text, lis_response, correction)

    # Also store as a high-importance memory
    remember(
        content=f"CORRECTION: When I said/did something wrong, user clarified: {correction}",
        mem_type="decision",
        source=user_text[:50],
        importance=9,  # High importance — corrections are critical
    )
    log.info(f"Learned from correction: {correction[:80]}")


def get_user_patterns() -> dict:
    """Analyze interaction history for behavioral patterns."""
    conn = _get_db()
    patterns = {"time_distribution": {}, "common_intents": {}, "mood_trends": {}}

    try:
        # Time-of-day distribution
        rows = conn.execute(
            "SELECT timestamp FROM interactions ORDER BY timestamp DESC LIMIT 100"
        ).fetchall()
        for r in rows:
            from datetime import datetime
            hour = datetime.fromtimestamp(r["timestamp"]).hour
            bucket = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening" if 17 <= hour < 22 else "night"
            patterns["time_distribution"][bucket] = patterns["time_distribution"].get(bucket, 0) + 1

        # Common intents
        intent_rows = conn.execute(
            "SELECT user_intent, COUNT(*) as cnt FROM interactions WHERE user_intent != '' GROUP BY user_intent ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
        for r in intent_rows:
            patterns["common_intents"][r["user_intent"]] = r["cnt"]

        # Recent mood trend
        mood_rows = conn.execute(
            "SELECT sentiment_score FROM interactions ORDER BY timestamp DESC LIMIT 10"
        ).fetchall()
        if mood_rows:
            scores = [r["sentiment_score"] for r in mood_rows]
            patterns["mood_trends"]["recent_avg"] = sum(scores) / len(scores)
            patterns["mood_trends"]["trend"] = "positive" if scores[0] > 0 else "negative" if scores[0] < 0 else "neutral"

    except Exception as e:
        log.debug(f"Pattern analysis failed: {e}")
    finally:
        conn.close()

    return patterns


# Initialize on import
init_db()
