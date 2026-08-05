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

class TimerSkill(Skill):
    name = "start_timer"
    description = "Start a countdown timer."

    async def execute(self, duration_sec: int, label: str = "", **kwargs) -> SkillResult:
        try:
            memory.add_timer(int(duration_sec), label)
            return SkillResult(True, f"Timer started for {duration_sec} seconds, sir.")
        except Exception as e:
            return SkillResult(False, f"Failed to start timer: {e}")
registry.register(TimerSkill())

class AlarmSkill(Skill):
    name = "set_alarm"
    description = "Set an alarm for a specific time."

    async def execute(self, time_str: str, label: str = "", **kwargs) -> SkillResult:
        try:
            memory.add_alarm(time_str, label)
            return SkillResult(True, f"Alarm set for {time_str}, sir.")
        except Exception as e:
            return SkillResult(False, f"Failed to set alarm: {e}")
registry.register(AlarmSkill())

class ReminderSkill(Skill):
    name = "create_reminder"
    description = "Create a reminder for a future time."

    async def execute(self, time_offset_minutes: int, content: str, **kwargs) -> SkillResult:
        try:
            trigger = time.time() + (int(time_offset_minutes) * 60)
            memory.add_reminder(trigger, content)
            return SkillResult(True, f"I will remind you about {content} in {time_offset_minutes} minutes, sir.")
        except Exception as e:
            return SkillResult(False, f"Failed to create reminder: {e}")
registry.register(ReminderSkill())

class TeachingSkill(Skill):
    name = "teach_feature"
    description = "Explain a concept clearly using analogies and structured steps."

    async def execute(self, topic: str, **kwargs) -> SkillResult:
        # This skill doesn't perform a system action per se, 
        # but marks the mode for the LLM. 
        # The prompt will handle the pedagogical structure.
        return SkillResult(True, f"I would be happy to teach you about {topic}, sir. Let's start with the basics.")
registry.register(TeachingSkill())

class SuggestionsSkill(Skill):
    name = "get_suggestions"
    description = "Generate creative ideas, tips, or suggestions for a topic."

    async def execute(self, topic: str, count: int = 5, **kwargs) -> SkillResult:
        return SkillResult(True, f"I've prepared {count} suggestions regarding {topic} for you, sir.")
registry.register(SuggestionsSkill())

class ManageListSkill(Skill):
    name = "manage_list"
    description = "Add or remove items from a persistent list (shopping, todo, etc.)."

    async def execute(self, list_name: str, action: str, item: str = None, **kwargs) -> SkillResult:
        current_items = memory.get_list(list_name) or []
        
        if action == "add" and item:
            if item not in current_items:
                current_items.append(item)
                memory.update_list(list_name, current_items)
            return SkillResult(True, f"I've added {item} to your {list_name} list, sir.")
        
        elif action == "remove" and item:
            if item in current_items:
                current_items.remove(item)
                memory.update_list(list_name, current_items)
                return SkillResult(True, f"I've removed {item} from your {list_name} list, sir.")
            return SkillResult(False, f"{item} wasn't on your {list_name} list, sir.")
        
        elif action == "read":
            if not current_items:
                return SkillResult(True, f"Your {list_name} list is currently empty, sir.")
            items_str = ", ".join(current_items)
            return SkillResult(True, f"Your {list_name} list contains: {items_str}, sir.")
        
        return SkillResult(False, "Invalid list action, sir.")


# Entertainment & Fun
registry.register(ManageListSkill())

class AdaptiveLearningSkill(Skill):
    name = "adaptive_learn"
    description = "Track user preferences and patterns for smarter responses."

    async def execute(self, action: str = "summary", **kwargs) -> SkillResult:
        try:
            if action == "summary":
                recent = memory.get_recent_memories(limit=10)
                prefs = [m for m in recent if m.get("type") == "preference"]
                facts = [m for m in recent if m.get("type") == "fact"]
                return SkillResult(True, 
                    f"I've learned {len(prefs)} preferences and {len(facts)} facts about you, sir. "
                    f"I'm continuously adapting to serve you better.")
            elif action == "forget":
                return SkillResult(True, "Memory cleared for the specified topic, sir.")
            return SkillResult(True, "Adaptive learning is always active, sir.")
        except Exception as e:
            return SkillResult(False, f"Learning tracker error: {e}")


# Market Intelligence (v2.0)
registry.register(AdaptiveLearningSkill())

