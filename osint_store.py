import sqlite3
import json
import re
import os
import datetime
from pathlib import Path
from typing import Any

# Secrets redaction patterns
REDACTION_PATTERNS = [
    # AWS Access Keys
    re.compile(r'(?i)(AKIA[0-9A-Z]{16})'),
    # Generic API keys, bearer tokens, passwords in JSON or logs
    re.compile(r'(?i)("?(?:api_key|password|bearer|secret|token|auth_token)"?\s*[:=]\s*["\']?(?:Bearer\s+)?)[a-zA-Z0-9_\-\.]{10,}(["\']?)'),
    # RSA/Ed25519 Private Keys
    re.compile(r'(?i)(-----BEGIN .*PRIVATE KEY-----[\s\S]+?-----END .*PRIVATE KEY-----)'),
]

DB_DIR = Path("data")
DB_PATH = DB_DIR / "osint.db"

def _redact_secrets(text: str) -> str:
    """Scrub obvious secrets/credentials from raw data before storing."""
    if not isinstance(text, str):
        try:
            text = json.dumps(text, default=str)
        except:
            text = str(text)
            
    for pattern in REDACTION_PATTERNS:
        # For the generic pattern with groups (key=)(value)(quote)
        if pattern.groups == 2:
            text = pattern.sub(r'\1[REDACTED]\2', text)
        else:
            text = pattern.sub('[REDACTED]', text)
    return text

def _get_conn():
    if not DB_DIR.exists():
        DB_DIR.mkdir(parents=True, exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn

def _init_db(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            question TEXT,
            status TEXT DEFAULT 'open'
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER,
            tool_name TEXT,
            query TEXT,
            source_url TEXT,
            retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            raw_data_json TEXT,
            notes TEXT,
            FOREIGN KEY (case_id) REFERENCES cases (id)
        )
    ''')
    conn.commit()

def create_case(question: str) -> int:
    """Create a new OSINT case to track lookups."""
    conn = _get_conn()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO cases (question) VALUES (?)", (question,))
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()

def _get_or_create_daily_case() -> int:
    """Get the current day's default case or create one."""
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    question = f"Daily quick lookups for {today}"
    conn = _get_conn()
    try:
        with conn:
            cursor = conn.execute("SELECT id FROM cases WHERE question = ? ORDER BY id DESC LIMIT 1", (question,))
            row = cursor.fetchone()
            if row:
                return row['id']
    finally:
        conn.close()
    return create_case(question)

def log_evidence(tool_name: str, query: str, source_url: str, raw_data: Any, notes: str = "", case_id: int = None) -> int:
    """Log evidence safely to the DB, redacting any obvious secrets first."""
    if not case_id:
        case_id = _get_or_create_daily_case()
        
    redacted_data = _redact_secrets(raw_data)
    
    conn = _get_conn()
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO evidence (case_id, tool_name, query, source_url, raw_data_json, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (case_id, tool_name, query, source_url, redacted_data, notes))
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()

def get_case(case_id: int) -> dict:
    conn = _get_conn()
    try:
        with conn:
            case_row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
            if not case_row:
                return None
            
            evidence_rows = conn.execute("SELECT * FROM evidence WHERE case_id = ? ORDER BY retrieved_at DESC", (case_id,)).fetchall()
            
            return {
                "case": dict(case_row),
                "evidence": [dict(r) for r in evidence_rows]
            }
    finally:
        conn.close()

def list_recent_evidence(limit: int = 20) -> list:
    conn = _get_conn()
    try:
        with conn:
            rows = conn.execute('''
                SELECT e.*, c.question as case_question 
                FROM evidence e
                LEFT JOIN cases c ON e.case_id = c.id
                ORDER BY e.retrieved_at DESC LIMIT ?
            ''', (limit,)).fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()
