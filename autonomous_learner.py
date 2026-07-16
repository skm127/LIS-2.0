"""
LIS Autonomous Learner — Background Knowledge Acquisition

Extracts topics from user activity, searches the web, and ingests content
from an explicitly approved domain allowlist into the RAG pipeline.
"""

import asyncio
import hashlib
import logging
import os
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from llm_providers import LLMProviders
from rag_pipeline import RAGPipeline

log = logging.getLogger("lis.autonomous_learner")
logging.basicConfig(level=logging.INFO)

# --- Configuration ---
MAX_FETCHES_PER_HOUR = 10

DOMAIN_ALLOWLIST = [
    "docs.python.org",
    "developer.mozilla.org",
    "react.dev",
]

class AutonomousLearner:
    def __init__(self):
        self.llm = LLMProviders()
        self.rag = RAGPipeline()
        self._fetches_this_hour = 0
        self._hour_start = time.time()

    def _check_rate_limit(self) -> bool:
        now = time.time()
        if now - self._hour_start >= 3600:
            self._hour_start = now
            self._fetches_this_hour = 0

        if self._fetches_this_hour >= MAX_FETCHES_PER_HOUR:
            log.warning("Rate limit exceeded: max fetches per hour reached.")
            return False
        return True

    async def extract_topics(self, recent_activity: str) -> list[str]:
        """Use the LLM to extract learning topics from recent user activity."""
        prompt = (
            "Analyze the following recent user activity and extract up to 3 technical "
            "topics, frameworks, or concepts the user is working with. "
            "Return ONLY a comma-separated list of topics, nothing else.\n\n"
            f"ACTIVITY:\n{recent_activity}"
        )
        try:
            response = await self.llm.generate(prompt, max_tokens=50)
            topics = [t.strip() for t in response.split(",") if t.strip()]
            return topics[:3]
        except Exception as e:
            log.error(f"Failed to extract topics: {e}")
            return []

    async def _search_duckduckgo(self, query: str) -> list[str]:
        """Perform a simple DuckDuckGo HTML search to find URLs."""
        url = "https://html.duckduckgo.com/html/"
        data = {"q": query}
        headers = {"User-Agent": "Mozilla/5.0 LIS-Bot"}
        
        urls = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, data=data, headers=headers, timeout=10.0)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.find_all("a", class_="result__url"):
                        href = a.get("href", "")
                        if href.startswith("//duckduckgo.com/l/?uddg="):
                            # Extract actual URL
                            import urllib.parse
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                            actual_url = parsed.get("uddg", [""])[0]
                            if actual_url:
                                urls.append(actual_url)
                        else:
                            urls.append(href)
        except Exception as e:
            log.warning(f"Search failed: {e}")
        return urls

    def _chunk_text_fixed(self, text: str, token_size: int = 500, overlap_pct: float = 0.15) -> list[str]:
        """Chunk text into fixed sizes with overlap.
        Assuming 1 token ~ 4 chars for rough estimation.
        """
        char_size = token_size * 4
        overlap = int(char_size * overlap_pct)
        
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + char_size, len(text))
            
            # Try to snap to nearest word boundary
            if end < len(text):
                while end > start and text[end] not in (' ', '\n', '\t'):
                    end -= 1
                if end == start: # Word is longer than chunk!
                    end = min(start + char_size, len(text))
                    
            chunks.append(text[start:end].strip())
            start = end - overlap
            # Prevent infinite loop on edge cases
            if start <= len(chunks) - 1: # Just a safeguard
                pass 
                
        return [c for c in chunks if c]

    async def search_and_ingest(self, topic: str):
        """Search the web for a topic and ingest allowed URLs."""
        if not os.getenv("ENABLE_AUTONOMOUS_LEARNING", "False").lower() in ("true", "1", "yes"):
            log.info("Autonomous learning is disabled by config.")
            return

        log.info(f"Starting autonomous learning for topic: {topic}")
        urls = await self._search_duckduckgo(topic)
        
        for url in urls:
            domain = urlparse(url).netloc
            # Check domain allowlist
            if not any(allowed in domain for allowed in DOMAIN_ALLOWLIST):
                log.debug(f"Rejected URL (domain not allowed): {url}")
                continue

            if not self._check_rate_limit():
                break

            log.info(f"Ingesting allowed URL: {url}")
            self._fetches_this_hour += 1
            
            try:
                # Fetch content
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15.0)
                    if resp.status_code != 200:
                        continue
                        
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for tag in soup(["script", "style", "nav", "footer", "header"]):
                        tag.decompose()
                    text_content = soup.get_text(separator="\n", strip=True)
                    
                    if len(text_content) < 100:
                        continue

                    # Deduplication check
                    content_hash = hashlib.sha256(text_content.encode("utf-8")).hexdigest()
                    if self.rag.already_has(content_hash):
                        log.info(f"Content already indexed for URL: {url}")
                        continue

                    # Chunk and store
                    chunks = self._chunk_text_fixed(text_content, token_size=500, overlap_pct=0.15)
                    stored = 0
                    
                    for i, text_chunk in enumerate(chunks):
                        chunk_hash = hashlib.sha256(text_chunk.encode("utf-8")).hexdigest()
                        
                        metadata = {
                            "source_url": url,
                            "source_domain": domain,
                            "ingested_at": time.time(),
                            "topic": topic,
                            "content_hash": content_hash, # To prevent re-ingesting the exact same page
                        }
                        
                        success = self.rag.add({
                            "text": text_chunk,
                            "metadata": metadata,
                            "doc_id": f"{url}::chunk::{i}::{chunk_hash[:8]}"
                        })
                        if success:
                            stored += 1
                            
                    log.info(f"Stored {stored} chunks from {url}")

            except Exception as e:
                log.error(f"Failed to ingest URL {url}: {e}")

async def run_learning_cycle(recent_activity: str):
    learner = AutonomousLearner()
    topics = await learner.extract_topics(recent_activity)
    log.info(f"Extracted topics: {topics}")
    
    for topic in topics:
        await learner.search_and_ingest(topic)

if __name__ == "__main__":
    import sys
    activity = sys.argv[1] if len(sys.argv) > 1 else "I am building a React frontend and need to use useEffect correctly."
    asyncio.run(run_learning_cycle(activity))
