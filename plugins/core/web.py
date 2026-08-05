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
            from urllib.parse import quote
            # Use gzipped search to keep it fast
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(query)}"
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
            from bs4 import BeautifulSoup
            import urllib.parse
            import re
            
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.post(url, headers=headers, data={'q': query}) # DDG HTML prefers POST for the first query
                
                # Fallback to GET if POST fails or returns empty
                if resp.status_code != 200 or "No results" in resp.text:
                    resp = await client.get(url, headers=headers)
                
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    snippets = []
                    for a in soup.find_all('a', class_='result__snippet'):
                        text = a.get_text(strip=True)
                        if text:
                            snippets.append(text)
                            
                    if snippets:
                        # Combine top 3 snippets for a rich summary
                        combined = " ".join(snippets[:3])
                        # Clean up weird characters
                        combined = re.sub(r'[^\x00-\x7F]+', ' ', combined)
                        return SkillResult(True, f"I found some information: {combined[:800]}", data=combined)
            
            # Fallback: open browser if scraping fails
            import webbrowser
            webbrowser.open(f'https://www.google.com/search?q={urllib.parse.quote(query)}')
            return SkillResult(True, f"I've opened a search for {query} in your browser, sir.")
        except Exception as e:
            return SkillResult(False, f"Auto-search failed: {e}")
registry.register(AutoSearchSkill())

class ScrapeSiteSkill(Skill):
    name = "scrape_site"
    description = "Scrape structured data from a URL based on a JSON schema."

    async def execute(self, job_name: str, url: str, schema: dict, **kwargs) -> SkillResult:
        try:
            import scraper
            res = await scraper.run_scrape_job(job_name, url, schema)
            if "error" in res:
                return SkillResult(False, res["error"])
            return SkillResult(True, f"Scraping completed and saved to {res['file']}", data=res['data'])
        except Exception as e:
            return SkillResult(False, f"Scraping failed: {e}")
registry.register(ScrapeSiteSkill())

class RerunScrapeJobSkill(Skill):
    name = "rerun_scrape_job"
    description = "Re-run a previously saved scrape job by name."

    async def execute(self, job_name: str, **kwargs) -> SkillResult:
        try:
            import scraper
            res = await scraper.run_scrape_job(job_name)
            if "error" in res:
                return SkillResult(False, res["error"])
            return SkillResult(True, f"Scrape job {job_name} rerun successfully and saved to {res['file']}", data=res['data'])
        except Exception as e:
            return SkillResult(False, f"Rerun failed: {e}")
registry.register(RerunScrapeJobSkill())

class WebTaskSkill(Skill):
    name = "web_task"
    description = "Navigate the web and fill out forms or perform actions."

    def __init__(self):
        super().__init__()
        # State tracking for multi-stage confirmation
        self._in_progress = {}

    async def execute(self, instruction: str, **kwargs) -> SkillResult:
        try:
            confirmed = kwargs.get("confirmed", False)
            
            # Use task hash as a simple session key
            import hashlib
            task_id = hashlib.md5(instruction.encode()).hexdigest()

            # Stage 0: Initial request, hasn't started yet
            if not confirmed and task_id not in self._in_progress:
                return SkillResult(False, f"I'll launch the browser to {instruction} — proceed?")
            
            import browser
            b = browser.LisBrowser()

            # Stage 1: User approved the intent. Navigate and fill form.
            if confirmed and task_id not in self._in_progress:
                self._in_progress[task_id] = "stage_1_done"
                summary = await b.execute_web_task(instruction)
                return SkillResult(False, f"Here is what I am about to submit: {summary}. Please confirm to proceed with the final click.")
            
            # Stage 2: User approved the final submission.
            if confirmed and self._in_progress.get(task_id) == "stage_1_done":
                result = await b.confirm_web_task()
                del self._in_progress[task_id]
                return SkillResult(True, f"Web task completed: {result}")

            # Fallback if state is weird
            del self._in_progress[task_id]
            return SkillResult(False, "Task state mismatch, aborting.")

        except Exception as e:
            return SkillResult(False, f"Web task failed: {e}")

registry.register(WebTaskSkill())
