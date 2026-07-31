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

class BrowseEdgeSkill(Skill):
    name = "browse_edge"
    description = "Open Microsoft Edge and navigate to a specific URL or perform a web search."
    
    async def execute(self, query_or_url: str, **kwargs) -> SkillResult:
        try:
            import urllib.parse
            import asyncio
            if query_or_url.startswith("http"):
                url = query_or_url
            else:
                url = f"https://www.google.com/search?q={urllib.parse.quote(query_or_url)}"
            
            cmd = f'start msedge "{url}"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return SkillResult(True, f"Opened Edge for: {query_or_url}")
        except Exception as e:
            return SkillResult(False, f"Failed to open Edge: {e}")
registry.register(BrowseEdgeSkill())

class SendEmailSkill(Skill):
    name = "send_email"
    description = "Open Microsoft Edge to compose an email via Gmail."
    
    async def execute(self, to: str = "", subject: str = "", body: str = "", **kwargs) -> SkillResult:
        try:
            import urllib.parse
            import asyncio
            
            url = f"https://mail.google.com/mail/?view=cm&fs=1"
            if to: url += f"&to={urllib.parse.quote(to)}"
            if subject: url += f"&su={urllib.parse.quote(subject)}"
            if body: url += f"&body={urllib.parse.quote(body)}"
            
            cmd = f'start msedge "{url}"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return SkillResult(True, "Opened Gmail compose window in Edge.")
        except Exception as e:
            return SkillResult(False, f"Failed to open Email: {e}")
registry.register(SendEmailSkill())

class WhatsAppSkill(Skill):
    name = "send_whatsapp"
    description = "Open Microsoft Edge to send a WhatsApp message."
    
    async def execute(self, phone: str = "", message: str = "", **kwargs) -> SkillResult:
        try:
            import urllib.parse
            import asyncio
            
            url = "https://web.whatsapp.com/send?"
            if phone:
                clean_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
                url += f"phone={clean_phone}&"
            if message:
                url += f"text={urllib.parse.quote(message)}"
            
            cmd = f'start msedge "{url}"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return SkillResult(True, "Opened WhatsApp Web in Edge.")
        except Exception as e:
            return SkillResult(False, f"Failed to open WhatsApp: {e}")
registry.register(WhatsAppSkill())

