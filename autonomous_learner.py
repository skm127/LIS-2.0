"""
LIS Autonomous Learner — Background Knowledge Acquisition

Uses browser-use to autonomously research knowledge gaps and ingest them
into a dedicated vector store, strictly gated by user configuration.
"""

import asyncio
import hashlib
import logging
import os
import time
from urllib.parse import urlparse
from typing import Optional

from env_loader import reload_env
from llm_providers import LLMProviders
from learner_vector_store import LearnerVectorStore
import memory

try:
    from browser_use import Browser, BrowserConfig, Agent
except ImportError:
    Browser = None
    BrowserConfig = None
    Agent = None

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None

log = logging.getLogger("lis.autonomous_learner")
logging.basicConfig(level=logging.INFO)

# --- Configuration ---
DOMAIN_ALLOWLIST = [
    "docs.python.org",
    "developer.mozilla.org",
    "react.dev",
    "wikipedia.org",
    "github.com"
]

# Global state to track the running cycle for interruptibility
_running_learning_task: Optional[asyncio.Task] = None

class AutonomousLearner:
    def __init__(self):
        self.llm = LLMProviders()
        self.store = LearnerVectorStore()

    def _get_langchain_llm(self):
        """Get an LLM instance for the browser-use Agent."""
        if not ChatOpenAI:
            raise ImportError("langchain-openai is not installed.")
            
        nvidia_key = os.getenv("NVIDIA_API_KEY")
        if nvidia_key:
            return ChatOpenAI(
                api_key=nvidia_key,
                base_url="https://integrate.api.nvidia.com/v1",
                model="meta/llama-3.1-70b-instruct"
            )
            
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            return ChatOpenAI(
                api_key=groq_key,
                base_url="https://api.groq.com/openai/v1",
                model="llama-3.3-70b-versatile"
            )
            
        raise ValueError("No NVIDIA_API_KEY or GROQ_API_KEY found to power the browser Agent.")

    async def extract_topics(self) -> list[str]:
        """Extract up to 2 learning topics from recent user activity and memory."""
        recent_tasks = memory.get_open_tasks()
        recent_memories = memory.get_important_memories(limit=5)
        
        context = "Recent Tasks:\\n" + "\\n".join([t.get("title", "") for t in recent_tasks])
        context += "\\n\\nRecent Memories:\\n" + "\\n".join([m.get("text", "") for m in recent_memories])
        
        prompt = (
            "Analyze the following user context and extract up to 2 technical "
            "topics, frameworks, or concepts where the assistant might have knowledge gaps. "
            "Return ONLY a comma-separated list of topics, nothing else.\\n\\n"
            f"CONTEXT:\\n{context}"
        )
        try:
            response = await self.llm.generate(prompt, max_tokens=50)
            topics = [t.strip() for t in response.split(",") if t.strip()]
            
            # Deduplicate against already learned topics
            already_learned = set(self.store.get_all_learned_topics())
            filtered = [t for t in topics if t.lower() not in already_learned]
            
            return filtered[:2]
        except Exception as e:
            log.error(f"Failed to extract topics: {e}")
            return []

    def _chunk_text(self, text: str, token_size: int = 500, overlap_pct: float = 0.15) -> list[str]:
        char_size = token_size * 4
        overlap = int(char_size * overlap_pct)
        
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + char_size, len(text))
            if end < len(text):
                while end > start and text[end] not in (' ', '\\n', '\\t'):
                    end -= 1
                if end == start: 
                    end = min(start + char_size, len(text))
            chunks.append(text[start:end].strip())
            
            new_start = end - overlap
            if new_start <= start:
                start = end
            else:
                start = new_start
        return [c for c in chunks if c]

    async def _handle_route(self, route):
        """Playwright route interceptor to enforce domain allowlist."""
        request = route.request
        url = request.url
        try:
            domain = urlparse(url).netloc
            # Allow basic resources (fonts, tracking pixels) if needed, but strictly block main document navigation
            # Actually, to be perfectly safe, block ANY request not in allowlist if it's a document/fetch
            if request.resource_type in ["document", "fetch", "xhr"]:
                is_allowed = any(allowed in domain for allowed in DOMAIN_ALLOWLIST)
                if not is_allowed:
                    log.warning(f"BLOCKED navigation to non-allowlisted domain: {domain} ({url})")
                    await route.abort()
                    return
        except Exception:
            pass
            
        await route.continue_()

    async def search_and_ingest(self, topic: str):
        """Use browser-use agent to research a topic and ingest findings."""
        if not Browser:
            log.error("browser-use not installed.")
            return

        headless = os.getenv("LIS_BROWSER_HEADLESS", "True").lower() in ("true", "1", "yes")
        browser = Browser(config=BrowserConfig(headless=headless))
        
        context = None
        # We need to inject the route interceptor into the context
        try:
            context = await browser.new_context()
            pw_context = context.context
            # Hard enforce domain allowlist at the network level
            await pw_context.route("**/*", self._handle_route)
            
            llm = self._get_langchain_llm()
            task = (
                f"Research the technical topic: {topic}. "
                f"You MUST strictly only visit domains in this list: {', '.join(DOMAIN_ALLOWLIST)}. "
                "Navigate to relevant articles, read them, and summarize the key technical concepts, APIs, and examples. "
                "Return a detailed, multi-paragraph markdown summary of your findings."
            )
            
            agent = Agent(
                task=task,
                llm=llm,
                browser=browser,
                # Safety rails: prevent infinite looping
                max_actions_per_step=3
            )
            
            log.info(f"Agent starting research on topic: {topic}")
            # Wall-clock timeout of 10 minutes (600 seconds)
            history = await asyncio.wait_for(agent.run(max_steps=10), timeout=600.0)
            
            final_result = history.final_result() if hasattr(history, "final_result") else str(history)
            
            if len(final_result) < 100:
                log.warning("Agent returned too little text. Skipping ingest.")
                return
                
            # We use the agent's summary as the ingested content. 
            # In a more advanced setup we could extract from the DOM directly, but the agent's synthesis is great.
            chunks = self._chunk_text(final_result, token_size=500, overlap_pct=0.15)
            
            texts = []
            metadatas = []
            ids = []
            
            base_url = "browser-use://agent-summary"
            content_hash = hashlib.sha256(final_result.encode("utf-8")).hexdigest()
            
            for i, text_chunk in enumerate(chunks):
                chunk_hash = hashlib.sha256(text_chunk.encode("utf-8")).hexdigest()
                texts.append(text_chunk)
                metadatas.append({
                    "source_url": base_url,
                    "topic": topic,
                    "ingested_at": time.time(),
                    "content_hash": content_hash
                })
                ids.append(f"{topic}::chunk::{i}::{chunk_hash[:8]}")
                
            self.store.add_documents(texts, metadatas, ids)
            log.info(f"Ingested {len(chunks)} chunks for topic: {topic}")
            
        except asyncio.TimeoutError:
            log.error(f"Agent research timed out after 10 minutes for topic: {topic}")
        except asyncio.CancelledError:
            log.warning(f"Agent research was cancelled for topic: {topic}")
            raise # Re-raise to cleanly exit the task
        except Exception as e:
            log.error(f"Agent research failed: {e}")
        finally:
            log.info("Cleaning up browser context...")
            try:
                if context:
                    await context.close()
                await browser.close()
            except Exception as e:
                log.warning(f"Error during browser cleanup: {e}")


async def _learning_cycle_task():
    """The actual coroutine that does the work."""
    log.info("Starting learning cycle...")
    try:
        learner = AutonomousLearner()
        topics = await learner.extract_topics()
        log.info(f"Extracted knowledge gap topics: {topics}")
        
        for topic in topics:
            # Re-check enablement before each topic
            reload_env()
            if os.getenv("ENABLE_AUTONOMOUS_LEARNING", "False").lower() not in ("true", "1", "yes"):
                log.info("Autonomous learning disabled mid-cycle.")
                break
                
            await learner.search_and_ingest(topic)
            
    except asyncio.CancelledError:
        log.info("Learning cycle task was cancelled.")
    except Exception as e:
        log.error(f"Learning cycle encountered an error: {e}")
    finally:
        global _running_learning_task
        _running_learning_task = None
        log.info("Learning cycle finished.")

def trigger_learning_cycle():
    """Trigger the learning cycle safely. Ensures only one runs at a time."""
    reload_env()
    if os.getenv("ENABLE_AUTONOMOUS_LEARNING", "False").lower() not in ("true", "1", "yes"):
        log.info("Autonomous learning is disabled by config.")
        return
        
    global _running_learning_task
    if _running_learning_task and not _running_learning_task.done():
        log.warning("A learning cycle is already running. Skipping.")
        return
        
    _running_learning_task = asyncio.create_task(_learning_cycle_task())

def stop_learning_cycle():
    """Cancel the currently running learning cycle."""
    global _running_learning_task
    if _running_learning_task and not _running_learning_task.done():
        _running_learning_task.cancel()
        return True
    return False

def get_learning_status():
    global _running_learning_task
    is_running = _running_learning_task is not None and not _running_learning_task.done()
    return is_running

async def run_learning_cycle(activity_hint: str = "") -> None:
    learner = AutonomousLearner()
    topics = await learner.extract_topics()
    if activity_hint and not topics:
        topics = [activity_hint]
    for topic in topics:
        await learner.search_and_ingest(topic)

if __name__ == "__main__":
    # For testing
    async def test():
        trigger_learning_cycle()
        global _running_learning_task
        if _running_learning_task:
            await _running_learning_task
    asyncio.run(test())
