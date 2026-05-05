"""
LIS Scheduler v1.0 — Proactive Routine Automation.

Cron-like system for scheduled tasks: morning briefings, end-of-day summaries,
periodic check-ins, and custom user-defined routines.
"""

import asyncio
import logging
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Callable, Any

log = logging.getLogger("lis.scheduler")


class ScheduledRoutine:
    """A single scheduled routine."""
    def __init__(self, name: str, hour: int, minute: int = 0,
                 days: list[str] = None, action: str = "", enabled: bool = True):
        self.name = name
        self.hour = hour
        self.minute = minute
        self.days = days or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        self.action = action
        self.enabled = enabled
        self.last_triggered: float = 0

    def should_trigger(self, now: datetime) -> bool:
        """Check if this routine should fire right now."""
        if not self.enabled:
            return False

        day_name = now.strftime("%a").lower()
        if day_name not in self.days:
            return False

        if now.hour != self.hour or now.minute != self.minute:
            return False

        # Prevent double-firing within the same minute
        if time.time() - self.last_triggered < 120:
            return False

        return True

    def to_dict(self) -> dict:
        return {
            "name": self.name, "hour": self.hour, "minute": self.minute,
            "days": self.days, "action": self.action, "enabled": self.enabled,
        }


class LISScheduler:
    """Manages scheduled routines and proactive dispatches."""

    def __init__(self):
        self.routines: list[ScheduledRoutine] = []
        self._voice_queue: Optional[asyncio.Queue] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Default routines
        self._init_defaults()

    def _init_defaults(self):
        """Set up default routines."""
        self.routines.append(ScheduledRoutine(
            name="Morning Briefing",
            hour=8, minute=0,
            days=["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            action="morning_briefing",
        ))
        self.routines.append(ScheduledRoutine(
            name="End of Day Summary",
            hour=22, minute=0,
            days=["mon", "tue", "wed", "thu", "fri"],
            action="eod_summary",
        ))
        log.info(f"Scheduler initialized with {len(self.routines)} default routines")

    def set_voice_queue(self, queue: asyncio.Queue):
        """Connect the scheduler to the voice output queue."""
        self._voice_queue = queue

    def add_routine(self, name: str, hour: int, minute: int = 0,
                    days: list[str] = None, action: str = "") -> ScheduledRoutine:
        """Add a new scheduled routine."""
        routine = ScheduledRoutine(name, hour, minute, days, action)
        self.routines.append(routine)
        log.info(f"Added routine: {name} at {hour:02d}:{minute:02d}")
        return routine

    def remove_routine(self, name: str) -> bool:
        """Remove a routine by name."""
        before = len(self.routines)
        self.routines = [r for r in self.routines if r.name.lower() != name.lower()]
        return len(self.routines) < before

    def list_routines(self) -> list[dict]:
        """List all registered routines."""
        return [r.to_dict() for r in self.routines]

    async def _build_morning_briefing(self) -> str:
        """Build the morning briefing text."""
        import memory

        now = datetime.now()
        parts = [f"Good morning! It's {now.strftime('%A, %B %d')}."]

        # Tasks
        try:
            tasks = memory.get_open_tasks()
            high = [t for t in tasks if t.get("priority") == "high"]
            if tasks:
                parts.append(f"You have {len(tasks)} open tasks")
                if high:
                    parts.append(f"{len(high)} are high priority")
                    for t in high[:2]:
                        parts.append(f"Priority: {t['title']}")
            else:
                parts.append("Your task list is clear today!")
        except Exception:
            pass

        # Knowledge graph pattern
        try:
            patterns = memory.get_user_patterns()
            mood = patterns.get("mood_trends", {})
            if mood.get("trend") == "negative":
                parts.append("I noticed you've been a bit stressed lately. Take care of yourself today, okay?")
        except Exception:
            pass

        parts.append("I'm here whenever you need me!")
        return " ".join(parts)

    async def _build_eod_summary(self) -> str:
        """Build the end-of-day summary."""
        import memory

        now = datetime.now()
        parts = [f"Hey! Quick end-of-day update."]

        try:
            tasks = memory.get_open_tasks()
            if tasks:
                parts.append(f"You still have {len(tasks)} open tasks.")
                high = [t for t in tasks if t.get("priority") == "high"]
                if high:
                    parts.append(f"{len(high)} are high priority — worth looking at tomorrow.")
            else:
                parts.append("All your tasks are done — great day!")
        except Exception:
            pass

        parts.append("Get some rest. Good night!")
        return " ".join(parts)

    async def _execute_routine(self, routine: ScheduledRoutine):
        """Execute a scheduled routine."""
        routine.last_triggered = time.time()
        log.info(f"Executing routine: {routine.name}")

        try:
            if routine.action == "morning_briefing":
                text = await self._build_morning_briefing()
            elif routine.action == "eod_summary":
                text = await self._build_eod_summary()
            elif routine.action.startswith("say:"):
                text = routine.action[4:].strip()
            else:
                text = f"Routine '{routine.name}' triggered."

            # Send to voice queue if connected
            if self._voice_queue:
                await self._voice_queue.put(text)
                log.info(f"Routine dispatched to voice: {text[:80]}")
            else:
                log.warning(f"No voice queue connected, routine text: {text[:80]}")

        except Exception as e:
            log.error(f"Routine execution failed: {e}")

    async def run(self):
        """Main scheduler loop — checks every 30 seconds."""
        self._running = True
        log.info("Scheduler started")

        while self._running:
            try:
                now = datetime.now()
                for routine in self.routines:
                    if routine.should_trigger(now):
                        await self._execute_routine(routine)
            except Exception as e:
                log.error(f"Scheduler tick error: {e}")

            await asyncio.sleep(30)  # Check every 30 seconds

    def start(self):
        """Start the scheduler as a background task."""
        if not self._task:
            self._task = asyncio.create_task(self.run())
            log.info("Scheduler background task started")

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None


# Global scheduler instance
scheduler = LISScheduler()
