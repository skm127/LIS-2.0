import asyncio
import logging
import time
import json
import difflib
import subprocess
import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Callable, Any

import memory
log = logging.getLogger("LIS.skills")

@dataclass
class SkillResult:
    success: bool
    confirmation: str
    data: Any = None

class Skill:
    name: str
    description: str
    
    async def execute(self, **kwargs) -> SkillResult:
        raise NotImplementedError

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self.agent_spawner: Optional[Callable] = None

    def register(self, skill: Skill):
        self._skills[skill.name] = skill
        log.info(f"Registered skill: {skill.name}")

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_all(self) -> List[Dict]:
        return [{"name": s.name, "description": s.description} for s in self._skills.values()]

registry = SkillRegistry()

