"""
LIS Browser — browser-use based web capabilities.

Provides search, page visits, screenshots, and multi-step research.
Runs headless Chromium with realistic user agent to avoid blocking.
"""

import asyncio
import logging
import tempfile
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

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

log = logging.getLogger("lis.browser")

TIMEOUT_MS = 30_000


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PageContent:
    title: str
    url: str
    text_content: str
    word_count: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResearchResult:
    topic: str
    sources: list[str]
    summary: str
    key_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Browser Manager
# ---------------------------------------------------------------------------

class LisBrowser:
    """Browser-use backed web browsing for LIS."""

    def __init__(self):
        self._browser = None
        self._context = None
        self._pw_browser = None

    async def _ensure_browser(self):
        """Launch browser if not running."""
        if self._browser and self._context:
            return

        if not Browser:
            raise ImportError("browser-use is not installed.")

        # Initialize browser-use Browser with visible UI
        self._browser = Browser(config=BrowserConfig(headless=False))
        self._context = await self._browser.new_context()
        log.info("Browser-use launched (visible)")

    async def _get_pw_page(self):
        """Get a raw Playwright page for deterministic tasks."""
        await self._ensure_browser()
        # BrowserContext in browser-use wraps Playwright context.
        # We can create a new page on its underlying Playwright context.
        pw_context = self._context.context
        return await pw_context.new_page()

    def _get_llm(self):
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

    # -- Search ----------------------------------------------------------------

    async def search(self, query: str) -> list[SearchResult]:
        """Search DuckDuckGo and return top results."""
        page = await self._get_pw_page()
        results = []

        try:
            await page.goto(
                f"https://html.duckduckgo.com/html/?q={query}",
                timeout=TIMEOUT_MS,
                wait_until="domcontentloaded",
            )

            # Extract search results from DDG HTML version
            raw = await page.evaluate("""
                () => {
                    const items = document.querySelectorAll('.result');
                    return Array.from(items).slice(0, 5).map(item => ({
                        title: (item.querySelector('.result__title a') || item.querySelector('.result__a'))?.textContent?.trim() || '',
                        url: (item.querySelector('.result__title a') || item.querySelector('.result__a'))?.href || '',
                        snippet: item.querySelector('.result__snippet')?.textContent?.trim() || ''
                    }));
                }
            """)

            for r in raw:
                if r.get("title") and r.get("url"):
                    results.append(SearchResult(
                        title=r["title"],
                        url=r["url"],
                        snippet=r.get("snippet", ""),
                    ))

            log.info(f"Search '{query}' returned {len(results)} results")
            await asyncio.sleep(2)
        except Exception as e:
            log.warning(f"Search failed for '{query}': {e}")
        finally:
            await page.close()

        return results

    # -- Visit URL -------------------------------------------------------------

    async def visit(self, url: str) -> PageContent:
        """Visit a URL and extract main text content."""
        page = await self._get_pw_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

            data = await page.evaluate("""
                () => {
                    const title = document.title || '';

                    const main = document.querySelector('main')
                        || document.querySelector('article')
                        || document.querySelector('[role="main"]')
                        || document.body;

                    const clone = main.cloneNode(true);
                    for (const el of clone.querySelectorAll(
                        'script, style, nav, header, footer, aside, .sidebar, .menu, .ad, .advertisement, iframe'
                    )) {
                        el.remove();
                    }

                    const text = clone.innerText || clone.textContent || '';
                    const trimmed = text.substring(0, 5000).trim();
                    return {
                        title: title,
                        text: trimmed,
                    };
                }
            """)

            await asyncio.sleep(3)

            text = data.get("text", "")
            return PageContent(
                title=data.get("title", ""),
                url=url,
                text_content=text,
                word_count=len(text.split()),
            )
        except Exception as e:
            log.warning(f"Visit failed for '{url}': {e}")
            return PageContent(
                title="Error",
                url=url,
                text_content=f"Failed to load page: {e}",
                word_count=0,
            )
        finally:
            await page.close()

    # -- Screenshot ------------------------------------------------------------

    async def screenshot(self, url: str, path: str = None) -> str:
        """Take screenshot of a page. Returns file path to PNG."""
        page = await self._get_pw_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            await page.wait_for_timeout(1000)

            if not path:
                tmp = tempfile.mktemp(suffix=".png", prefix="lis_screenshot_")
                path = tmp

            await page.screenshot(path=path, full_page=True)
            log.info(f"Screenshot saved: {path}")
            return path

        except Exception as e:
            log.warning(f"Screenshot failed for '{url}': {e}")
            return ""
        finally:
            await page.close()

    # -- Research (multi-step) -------------------------------------------------

    async def research(self, topic: str) -> ResearchResult:
        """Multi-step research powered entirely by browser-use Agent."""
        await self._ensure_browser()
        llm = self._get_llm()
        
        task = f"Research the following topic: {topic}. Search the web, read at least 2 relevant articles, and write a summary of your key findings."
        
        log.info(f"Starting browser-use Agent for topic: {topic}")
        agent = Agent(
            task=task,
            llm=llm,
            browser=self._browser
        )
        
        try:
            history = await agent.run()
            # The agent run returns an AgentHistoryList. We can get the final result text.
            final_result = history.final_result() if hasattr(history, "final_result") else str(history)
            
            return ResearchResult(
                topic=topic,
                sources=["Agent-driven exploration"],
                summary=final_result or "The agent completed the task but returned no summary.",
                key_findings=["(See summary for findings)"]
            )
        except Exception as e:
            log.error(f"Browser Agent failed on research: {e}")
            return ResearchResult(
                topic=topic,
                sources=[],
                summary=f"Research failed: {e}",
                key_findings=[]
            )

    # -- Lifecycle -------------------------------------------------------------

    async def close(self):
        """Shut down the browser."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            log.info("Browser closed")
        except Exception as e:
            log.warning(f"Browser close error: {e}")
        finally:
            self._browser = None
            self._context = None
