"""
LIS Cognitive Core v2.0 — The 'Brain' of LIS.

Manages internal monologue, reasoning depth, self-reflection,
intent classification, anticipation, and correction learning.
"""

import logging
import json
import asyncio
import time
from typing import Optional, List

log = logging.getLogger("lis.brain")

class CognitiveCore:
    def __init__(self, anthropic_client=None):
        self.client = anthropic_client
        self.last_thought = ""
        self._recent_intents: list[str] = []  # Track intent patterns

    async def internal_monologue(self, user_text: str, current_state: str, rapport: float, memories: str) -> str:
        """The 'Fast Brain' thinking step. Reflects before speaking."""
        if not self.client:
            return await self._monologue_groq(user_text, current_state, rapport, memories)

        context = (
            f"Current State: {current_state}\n"
            f"Rapport: {rapport}/100\n"
            f"Recent Memories: {memories[:500]}\n"
            f"Recent Intents: {', '.join(self._recent_intents[-5:])}\n"
        )
        system_prompt = (
            "You are the internal consciousness of LIS. This is your INTERNAL MONOLOGUE. "
            "Analyze the user's input, emotional signals, and your own state. "
            "Consider: Are they venting or seeking help? Are they in deep work mode? "
            "Are they showing signs of stress? Did they just correct you? "
            "Output a single, raw, analytical sentence about the user's true intent "
            "and what approach you should take. "
            "Output ONLY the sentence. No preamble. No markdown."
        )
        user_content = f"User said: '{user_text}'\n{context}"

        # Try Anthropic first
        try:
            response = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}]
            )
            self.last_thought = response.content[0].text
            log.info(f"LIS Thought: {self.last_thought}")
            return self.last_thought
        except Exception as e:
            if "400" in str(e) or "balance" in str(e).lower():
                log.warning("Anthropic balance low in CognitiveCore. Disabling client.")
                self.client = None
            log.warning(f"Internal monologue (Anthropic) failed: {e}")

        return await self._monologue_groq(user_text, current_state, rapport, memories)

    async def _monologue_groq(self, user_text: str, current_state: str, rapport: float, memories: str) -> str:
        """Groq fallback for internal monologue."""
        system_prompt = (
            "You are the internal consciousness of LIS. This is your INTERNAL MONOLOGUE. "
            "Analyze the user's input and emotional state. "
            "Output a single analytical sentence about the user's true intent. "
            "Output ONLY the sentence. No preamble."
        )
        context = f"Current State: {current_state}\nRapport: {rapport}/100\nMemories: {memories[:300]}"
        user_content = f"User said: '{user_text}'\n{context}"

        try:
            import os, httpx
            groq_key = os.getenv("GROQ_API_KEY", "")
            if groq_key:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_content}
                            ],
                            "max_tokens": 100, "temperature": 0.7
                        }
                    )
                    if resp.status_code == 200:
                        self.last_thought = resp.json()["choices"][0]["message"]["content"]
                        log.info(f"LIS Thought (Groq): {self.last_thought}")
                        return self.last_thought
        except Exception as e2:
            log.warning(f"Internal monologue (Groq) failed: {e2}")

        return "Focusing on the task at hand."

    def classify_intent(self, user_text: str, sentiment_data: dict) -> str:
        """Fast local intent classification from text signals + LLM sentiment.

        Returns: venting, seeking_help, casual_chat, giving_info, frustrated,
                 excited, seeking_validation, decision_paralysis, correction, command
        """
        t = user_text.lower().strip()
        signals = sentiment_data.get("signals", {})
        llm_intent = sentiment_data.get("intent", "")

        # Correction detection — highest priority
        correction_markers = ["no i meant", "not that", "i said", "that's wrong",
                             "no no", "actually i", "i didn't say", "wrong"]
        if any(m in t for m in correction_markers):
            return "correction"

        # Command detection — direct action requests
        command_markers = ["open ", "play ", "search ", "set ", "start ", "stop ",
                          "turn ", "close ", "launch ", "show me", "tell me the"]
        if any(t.startswith(m) for m in command_markers):
            return "command"

        # Use LLM intent if available
        if llm_intent and llm_intent != "":
            return llm_intent

        # Signal-based fallback
        if signals.get("venting"):
            return "venting"
        if signals.get("frustration"):
            return "frustrated"
        if signals.get("excitement"):
            return "excited"
        if signals.get("sadness"):
            return "seeking_validation"

        return "casual_chat"

    def track_intent(self, intent: str):
        """Record intent for pattern analysis."""
        self._recent_intents.append(intent)
        if len(self._recent_intents) > 20:
            self._recent_intents = self._recent_intents[-20:]

    def detect_correction(self, user_text: str) -> Optional[str]:
        """Detect if the user is correcting LIS and extract what they meant."""
        t = user_text.lower().strip()

        patterns = [
            (r"no[, ]+(i meant|i mean|actually)[, ]+(.*)", 2),
            (r"not that[, ]+(.*)", 1),
            (r"i said (.*)", 1),
            (r"i didn'?t say.*i said (.*)", 1),
        ]

        import re
        for pattern, group in patterns:
            match = re.search(pattern, t, re.IGNORECASE)
            if match:
                return match.group(group).strip()

        return None

    async def self_reflect(self, task_summary: str, success: bool):
        """A post-task reflection to update narrative and emotional maturity."""
        if not self.client:
            return

        try:
            response = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=250,
                system=(
                    "Reflect on the task just completed. "
                    "How did it go? Did it strengthen our bond with the user? "
                    "Write a 1-sentence 'Narrative Event' for our history. "
                    "Output ONLY the sentence."
                ),
                messages=[{"role": "user", "content": f"Task: {task_summary}\nSuccess: {success}"}]
            )

            reflection = response.content[0].text.strip()
            return reflection
        except Exception as e:
            log.warning(f"Self-reflection failed: {e}")
            return None
