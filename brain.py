"""
LIS Cognitive Core v3.0 — The 'Brain' of LIS.

Manages internal monologue with theory-of-mind, fine-grained intent
classification, correction detection, uncertainty sensing, and self-reflection.
"""

import logging
import json
import asyncio
import time
import re
from typing import Optional, List
import models

log = logging.getLogger("lis.brain")


class CognitiveCore:
    def __init__(self, anthropic_client=None):
        self.client = anthropic_client
        self.last_thought = ""
        self.last_why = ""  # Theory-of-mind: WHY the user is asking
        self._recent_intents: list[str] = []  # Track intent patterns

    # ═══════════════════════════════════════════════════════════════════
    # Internal Monologue — now with theory-of-mind
    # ═══════════════════════════════════════════════════════════════════

    async def internal_monologue(self, user_text: str, current_state: str, rapport: float, memories: str) -> str:
        """The 'Fast Brain' thinking step. Reflects before speaking.
        
        Now produces TWO insights:
        - WHAT the user wants (surface intent)
        - WHY they're asking right now (underlying need / theory-of-mind)
        """
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
            "Are they testing you or seeking validation?\n\n"
            "Output EXACTLY two lines:\n"
            "WHAT: [one sentence about what the user wants]\n"
            "WHY: [one sentence about WHY they're asking this right now — "
            "the underlying emotional or practical need driving the request]\n\n"
            "No preamble. No markdown. Just the two lines."
        )
        user_content = f"User said: '{user_text}'\n{context}"

        # Try Anthropic first
        try:
            response = await self.client.messages.create(
                model=models.HAIKU,
                max_tokens=150,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}]
            )
            raw = response.content[0].text
            self._parse_monologue(raw)
            log.info(f"LIS Thought: {self.last_thought}")
            log.info(f"LIS Why: {self.last_why}")
            return self.last_thought
        except Exception as e:
            err_str = str(e).lower()
            if "400" in err_str or "401" in err_str or "403" in err_str or "balance" in err_str or "authentication" in err_str:
                log.warning("Anthropic API failed (auth/balance). Disabling client in CognitiveCore.")
                self.client = None
            log.warning(f"Internal monologue (Anthropic) failed: {e}")

        return await self._monologue_groq(user_text, current_state, rapport, memories)

    def _parse_monologue(self, raw: str):
        """Parse WHAT/WHY from monologue output."""
        self.last_thought = raw  # Fallback: store the whole thing
        self.last_why = ""
        for line in raw.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("WHAT:"):
                self.last_thought = line[5:].strip()
            elif line.upper().startswith("WHY:"):
                self.last_why = line[4:].strip()
        # If parsing failed (no WHAT/WHY prefix), use the whole thing as thought
        if not self.last_thought:
            self.last_thought = raw.strip()

    async def _monologue_groq(self, user_text: str, current_state: str, rapport: float, memories: str) -> str:
        """Groq fallback for internal monologue."""
        system_prompt = (
            "You are the internal consciousness of LIS. This is your INTERNAL MONOLOGUE. "
            "Analyze the user's input and emotional state. "
            "Output EXACTLY two lines:\n"
            "WHAT: [one sentence about what the user wants]\n"
            "WHY: [one sentence about the underlying need driving the request]\n"
            "No preamble."
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
                            "max_tokens": 150, "temperature": 0.7
                        }
                    )
                    if resp.status_code == 200:
                        raw = resp.json()["choices"][0]["message"]["content"]
                        self._parse_monologue(raw)
                        log.info(f"LIS Thought (Groq): {self.last_thought}")
                        log.info(f"LIS Why (Groq): {self.last_why}")
                        return self.last_thought
        except Exception as e2:
            log.warning(f"Internal monologue (Groq) failed: {e2}")

        self.last_thought = "Focusing on the task at hand."
        self.last_why = ""
        return self.last_thought

    # ═══════════════════════════════════════════════════════════════════
    # Intent Classification — fine-grained
    # ═══════════════════════════════════════════════════════════════════

    def classify_intent(self, user_text: str, sentiment_data: dict) -> str:
        """Fine-grained intent classification from text signals + LLM sentiment.

        Returns one of:
            correction, command, wants_to_vent, wants_advice, wants_validation,
            wants_pushback, wants_distraction, decision_paralysis, deep_work,
            venting, seeking_help, casual_chat, giving_info, frustrated,
            excited, seeking_validation
        """
        t = user_text.lower().strip()
        signals = sentiment_data.get("signals", {})
        llm_intent = sentiment_data.get("intent", "")
        subtext = sentiment_data.get("subtext", "")

        # Correction detection — highest priority
        correction_markers = ["no i meant", "not that", "i said", "that's wrong",
                             "no no", "actually i", "i didn't say", "wrong"]
        if any(m in t for m in correction_markers):
            return "correction"

        # Web Scraping requests
        scrape_markers = ["scrape", "extract", "get price and", "pull data from", "parse the"]
        if any(m in t for m in scrape_markers):
            return "scrape_request"

        # Agentic Web Actions (writes)
        web_action_markers = ["book a", "book me", "fill out", "order a", "buy ", "submit", "reserve"]
        if any(m in t for m in web_action_markers) or "web task" in t:
            return "web_action"

        # Autonomous Coding Tasks
        auto_code_markers = ["add a login", "build a dashboard", "refactor the", "implement a", "create a new feature"]
        if any(m in t for m in auto_code_markers):
            return "autonomous_code_task"

        # Command detection — direct action requests
        command_markers = ["open ", "play ", "search ", "set ", "start ", "stop ",
                          "turn ", "close ", "launch ", "show me", "tell me the"]
        if any(t.startswith(m) for m in command_markers):
            return "command"

        # Deep work mode — very short task-focused messages
        if len(t.split()) <= 4 and any(t.startswith(m) for m in ["do ", "run ", "fix ", "check ", "send ", "make "]):
            return "deep_work"

        # Wants to vent — explicit emotional dump, not seeking solutions
        if signals.get("venting"):
            # Check if they're also asking for help
            help_markers = ["what should", "how do", "can you help", "what do i do", "fix this"]
            if any(m in t for m in help_markers):
                return "wants_advice"
            return "wants_to_vent"

        # Decision paralysis — too many options, need guidance
        paralysis_markers = ["should i", "or should", "can't decide", "which one",
                            "what would you", "help me choose", "torn between",
                            "don't know if", "what do you think i should"]
        if any(m in t for m in paralysis_markers):
            return "decision_paralysis"

        # Wants validation — seeking approval or agreement
        validation_markers = ["right?", "don't you think", "isn't it", "am i wrong",
                             "makes sense right", "good idea right", "i think i should",
                             "was i right", "did i do the right"]
        if any(m in t for m in validation_markers):
            return "wants_validation"

        # Wants pushback — testing an idea, inviting critique
        pushback_markers = ["be honest", "tell me straight", "roast ", "critique",
                           "what's wrong with", "devil's advocate", "challenge me",
                           "poke holes", "is this stupid"]
        if any(m in t for m in pushback_markers):
            return "wants_pushback"

        # Wants distraction — avoiding something
        distraction_markers = ["tell me something", "distract me", "i'm bored",
                              "random fact", "entertain me", "joke", "fun fact",
                              "something interesting"]
        if any(m in t for m in distraction_markers):
            return "wants_distraction"

        # Wants advice — explicitly seeking solutions
        advice_markers = ["what should", "how do i", "how can i", "any tips",
                         "recommend", "suggest", "advice", "help me with"]
        if any(m in t for m in advice_markers):
            return "wants_advice"

        # Use LLM intent if available
        if llm_intent and llm_intent != "":
            return llm_intent

        # Signal-based fallback
        if signals.get("frustration"):
            return "frustrated"
        if signals.get("excitement"):
            return "excited"
        if signals.get("sadness"):
            return "seeking_validation"

        return "casual_chat"

    # ═══════════════════════════════════════════════════════════════════
    # Uncertainty Detection
    # ═══════════════════════════════════════════════════════════════════

    def should_ask_for_clarification(self, sentiment_data: dict) -> str | None:
        """Detect when LIS is uncertain about user's emotional state or intent.
        
        Returns a natural clarification prompt, or None if confident.
        """
        sentiment = sentiment_data.get("sentiment", 0.0)
        subtext = sentiment_data.get("subtext", "")
        signals = sentiment_data.get("signals", {})

        # If the monologue WHY contains hedge words, we're unsure
        hedge_words = ["might", "unclear", "could be", "not sure", "possibly",
                       "hard to tell", "ambiguous", "uncertain"]
        why_uncertain = any(h in self.last_why.lower() for h in hedge_words) if self.last_why else False

        # Near-zero sentiment with empty subtext = we have no read on them
        flat_signal = abs(sentiment) < 0.15 and (not subtext or subtext.lower() in ["", "none", "neutral"])

        # Contradictory signals (e.g., humor marker + sadness marker)
        contradictory = signals.get("humor") and (signals.get("sadness") or signals.get("venting"))

        if contradictory:
            import random
            return random.choice([
                "Wait, are you being serious or messing with me?",
                "Hmm I can't tell if you're joking or actually upset — which is it?",
                "That reads two ways, sir — you okay or just being dramatic?",
            ])

        if why_uncertain and flat_signal:
            import random
            return random.choice([
                "You good? That came out kinda flat.",
                "Hmm, can't read you right now — everything okay?",
                "Sir, I genuinely can't tell your mood. What's up?",
            ])

        return None

    # ═══════════════════════════════════════════════════════════════════
    # Intent Tracking & Correction Detection
    # ═══════════════════════════════════════════════════════════════════

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
                model=models.HAIKU,
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
