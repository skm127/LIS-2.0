from skills import Skill, SkillResult, registry
import asyncio
import logging
import time
import json
import difflib
import subprocess
import re
import memory
from typing import Optional, List, Dict, Callable, Any

log = logging.getLogger("LIS.plugins")

class WikipediaSkill(Skill):
    name = "wiki_search"
    description = "Search Wikipedia for a brief summary of a topic."

    async def execute(self, query: str, **kwargs) -> SkillResult:
        try:
            # Use gzipped search to keep it fast
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}"
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    summary = data.get("extract", "I couldn't find a summary, sir.")
                    return SkillResult(True, f"According to Wikipedia: {summary}", data=summary)
                return SkillResult(False, f"I couldn't find anything on {query}, sir.")
        except Exception as e:
            return SkillResult(False, "Wikipedia is unreachable at the moment, sir.")
registry.register(WikipediaSkill())

class GoogleMapsSkill(Skill):
    name = "map_action"
    description = "Search for locations or get directions on Google Maps."

    async def execute(self, action: str, query: str = "", origin: str = "", destination: str = "", **kwargs) -> SkillResult:
        from urllib.parse import quote
        try:
            if action == "search":
                url = f"https://www.google.com/maps/search/{quote(query)}"
                msg = f"Pulling up a map for {query}, sir."
            elif action == "directions":
                url = f"https://www.google.com/maps/dir/{quote(origin)}/{quote(destination)}"
                msg = f"Charting a course from {origin} to {destination}, sir."
            else:
                return SkillResult(False, "Invalid map action, sir.")
            
            subprocess.Popen(f'start "" "{url}"', shell=True)
            return SkillResult(True, msg)
        except Exception as e:
            return SkillResult(False, f"Google Maps failed: {e}")
registry.register(GoogleMapsSkill())

class WebSearchSkill(Skill):
    name = "search_web"
    description = "Search the web for information using the default browser."

    async def execute(self, query: str, **kwargs) -> SkillResult:
        try:
            from urllib.parse import quote
            url = f"https://www.google.com/search?q={quote(query)}"
            subprocess.Popen(f'start "" "{url}"', shell=True)
            return SkillResult(True, f"Let me look that up for you, sir.")
        except Exception as e:
            return SkillResult(False, "I had a bit of trouble reaching the web, sorry.")
registry.register(WebSearchSkill())

class NewsSkill(Skill):
    name = "get_news"
    description = "Fetch top news headlines."

    async def execute(self, topic: str = "top", **kwargs) -> SkillResult:
        try:
            import httpx
            from urllib.parse import quote
            # Use free RSS-to-JSON service
            rss_url = f"https://news.google.com/rss/search?q={quote(topic)}&hl=en-IN&gl=IN&ceid=IN:en"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(rss_url)
                if resp.status_code == 200:
                    # Parse RSS XML for titles
                    import re
                    titles = re.findall(r'<title>(.*?)</title>', resp.text)
                    # Skip first two (feed title + Google News)
                    headlines = [t for t in titles[2:7] if t and 'Google' not in t]
                    if headlines:
                        news_text = ". ".join(headlines[:5])
                        return SkillResult(True, f"Here are the top headlines: {news_text}, sir.")
            return SkillResult(False, "I couldn't fetch the news right now, sir.")
        except Exception as e:
            return SkillResult(False, f"News service failed: {e}")
registry.register(NewsSkill())

class AutoSearchSkill(Skill):
    name = "auto_search"
    description = "Automatically search the web and return a summarized answer."

    async def execute(self, query: str, **kwargs) -> SkillResult:
        """Search DuckDuckGo instant answers API for quick facts."""
        try:
            import httpx
            from urllib.parse import quote
            url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    # Try Abstract first
                    abstract = data.get("AbstractText", "")
                    if abstract:
                        return SkillResult(True, f"{abstract[:500]}", data=abstract)
                    # Try Answer
                    answer = data.get("Answer", "")
                    if answer:
                        return SkillResult(True, f"{answer}", data=answer)
                    # Try Related Topics
                    topics = data.get("RelatedTopics", [])
                    if topics and isinstance(topics[0], dict):
                        text = topics[0].get("Text", "")
                        if text:
                            return SkillResult(True, f"{text[:500]}", data=text)
            # Fallback: open browser
            from urllib.parse import quote as q
            subprocess.Popen(f'start "" "https://www.google.com/search?q={q(query)}"', shell=True)
            return SkillResult(True, f"I've opened a search for {query} in your browser, sir.")
        except Exception as e:
            return SkillResult(False, f"Auto-search failed: {e}")
registry.register(AutoSearchSkill())

