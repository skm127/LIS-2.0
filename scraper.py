import os
import json
import sqlite3
import asyncio
from pathlib import Path
from datetime import datetime
from browser import LisBrowser
from llm_providers import LLMProviders

DB_PATH = Path(__file__).parent / "data" / "lis_data.db"
OUTPUT_DIR = Path.home() / "Desktop" / "LIS_Scrapes"

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scrape_jobs (
            name TEXT PRIMARY KEY,
            url TEXT,
            schema_json TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

async def extract_structured(url: str, field_schema: dict) -> dict:
    browser = LisBrowser()
    page_content = await browser.visit(url)
    text_content = page_content.text_content
    
    providers = LLMProviders()
    system_prompt = "You are a data extraction assistant. Extract information from the provided text according to the following JSON schema. Output ONLY valid JSON, no markdown formatting."
    
    messages = [
        {"role": "user", "content": f"Schema: {json.dumps(field_schema)}\n\nText: {text_content}"}
    ]
    
    result_text = await providers.generate(
        messages=messages,
        system=system_prompt,
        max_tokens=2000
    )
    
    if not result_text:
        return {"error": "LLM generation failed"}
        
    # Clean up output in case LLM added markdown code blocks
    result_text = result_text.strip()
    if result_text.startswith("```json"):
        result_text = result_text[7:]
    elif result_text.startswith("```"):
        result_text = result_text[3:]
    if result_text.endswith("```"):
        result_text = result_text[:-3]
        
    try:
        return json.loads(result_text.strip())
    except json.JSONDecodeError:
        return {"error": "Failed to parse LLM output as JSON", "raw": result_text}

def save_job(name: str, url: str, schema: dict):
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT OR REPLACE INTO scrape_jobs (name, url, schema_json, created_at) VALUES (?, ?, ?, ?)",
        (name, url, json.dumps(schema), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_job(name: str) -> dict:
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM scrape_jobs WHERE name = ?", (name,)).fetchone()
    conn.close()
    if row:
        return {
            "name": row["name"],
            "url": row["url"],
            "schema": json.loads(row["schema_json"])
        }
    return None

async def run_scrape_job(job_name: str, url: str = None, schema: dict = None) -> dict:
    if url and schema:
        save_job(job_name, url, schema)
    else:
        job = get_job(job_name)
        if not job:
            return {"error": f"Job {job_name} not found and no URL/schema provided."}
        url = job["url"]
        schema = job["schema"]
        
    result = await extract_structured(url, schema)
    
    job_dir = OUTPUT_DIR / job_name
    job_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = job_dir / f"result_{timestamp}.json"
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        
    return {"status": "success", "file": str(out_file), "data": result}
