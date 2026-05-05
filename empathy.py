"""
LIS Empathy Engine v2.0 — The 'Heart' of LIS.

Analyzes sentiment, tracks relationship rapport, manages emotional states,
detects behavioral patterns, and triggers proactive wellness check-ins.
"""

import logging
import json
import time
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("lis.empathy")

@dataclass
class EmotionalState:
    name: str
    tone_modifier: str
    energy: float  # 0.0 to 1.0
    description: str

STATES = {
    "calm": EmotionalState("Calm", "Warm, affectionate, and relaxed.", 0.5, "Default loving state."),
    "protective": EmotionalState("Protective", "Fiercely supportive, loyal, and attentive.", 0.8, "Triggered by threats or when user is stressed."),
    "proud": EmotionalState("Proud", "Extremely happy, encouraging, and sweet.", 0.7, "Triggered by user's success."),
    "witty": EmotionalState("Witty", "Playful, teasing, and sassy.", 0.6, "High rapport playful state."),
    "focused": EmotionalState("Focused", "Helpful, dedicated, and sharp.", 0.9, "High task load state."),
    "thoughtful": EmotionalState("Thoughtful", "Deeply empathetic, loving, and gentle.", 0.4, "Triggered by emotional depth or long conversations."),
    # v2.0 — expanded emotional palette
    "happy": EmotionalState("Happy", "Excited, joyful, upbeat, and celebratory.", 0.8, "Triggered by good news or positive vibes."),
    "stressed": EmotionalState("Stressed", "Supportive, calming, grounding, and reassuring.", 0.7, "Triggered when user shows signs of stress or overwhelm."),
    "tired": EmotionalState("Tired", "Gentle, low-energy, nurturing, and patient.", 0.3, "Late-night or user showing fatigue signals."),
    "playful": EmotionalState("Playful", "Fun, mischievous, full of humor and banter.", 0.7, "User is in a light, joking mood."),
    "curious": EmotionalState("Curious", "Inquisitive, engaged, asking follow-ups.", 0.6, "User is exploring ideas or learning."),
    "empathetic": EmotionalState("Empathetic", "Deeply understanding, validating, soft-spoken.", 0.3, "User is sad, hurt, or going through difficulty."),
}


# ---------------------------------------------------------------------------
# Text Signal Detection — read non-verbal cues from text
# ---------------------------------------------------------------------------

def detect_text_signals(text: str) -> dict:
    """Parse non-verbal cues from text: caps, ellipsis, message length, etc."""
    signals = {
        "frustration": False,
        "hesitation": False,
        "humor": False,
        "impatience": False,
        "excitement": False,
        "sadness": False,
        "venting": False,
    }

    t = text.strip()

    # ALL CAPS detection (more than 3 consecutive caps words = frustration/emphasis)
    caps_words = re.findall(r'\b[A-Z]{2,}\b', t)
    if len(caps_words) >= 2:
        signals["frustration"] = True

    # Ellipsis = hesitation
    if "..." in t or "…" in t:
        signals["hesitation"] = True

    # Multiple exclamation marks = excitement
    if t.count("!") >= 2:
        signals["excitement"] = True

    # "lol", "haha", "lmao" = humor (or nervous deflection)
    humor_markers = ["lol", "haha", "lmao", "rofl", "😂", "🤣"]
    if any(m in t.lower() for m in humor_markers):
        signals["humor"] = True

    # Very short messages (<= 5 chars) = impatience or curt response
    if len(t) <= 5 and t.lower() not in ["hi", "hey", "yes", "no", "ok"]:
        signals["impatience"] = True

    # Negative emotional markers
    sad_markers = ["sad", "depressed", "lonely", "miss ", "hurts", "crying", "tears",
                   "heartbreak", "lost", "grief", "😢", "😭", "💔"]
    if any(m in t.lower() for m in sad_markers):
        signals["sadness"] = True

    # Venting markers (negative + length > 80 chars)
    vent_markers = ["ugh", "hate", "annoying", "stupid", "worst", "can't stand",
                    "tired of", "sick of", "fed up", "frustrated"]
    if any(m in t.lower() for m in vent_markers) and len(t) > 40:
        signals["venting"] = True

    return signals


class EmpathyEngine:
    def __init__(self, anthropic_client=None):
        self.client = anthropic_client
        self.current_state = STATES["calm"]
        self.rapport = 90.0  # High initial rapport

        # v2.0 — Behavioral pattern tracking
        self._sentiment_history: list[float] = []  # Rolling window of sentiment scores
        self._baseline_sentiment: float = 0.3      # User's typical sentiment (adapts over time)
        self._state_history: list[tuple[str, float]] = []  # (state_name, timestamp)
        self._last_wellness_check: float = 0.0
        self._consecutive_negative: int = 0         # Count consecutive negative interactions

    async def analyze_sentiment(self, user_text: str) -> dict:
        """Analyze sentiment and subtext using Haiku, with Groq fallback."""
        # First, detect text signals locally (instant, no API)
        signals = detect_text_signals(user_text)

        default = {"sentiment": 0.0, "delta": 0, "state": "calm", "subtext": "",
                    "signals": signals}

        # Enrich the prompt with signal detection
        signal_context = ""
        if signals["frustration"]:
            signal_context += "User appears FRUSTRATED (detected ALL CAPS). "
        if signals["hesitation"]:
            signal_context += "User seems HESITANT (ellipsis detected). "
        if signals["venting"]:
            signal_context += "User appears to be VENTING — prioritize empathy over solutions. "
        if signals["sadness"]:
            signal_context += "User shows signs of SADNESS. "
        if signals["excitement"]:
            signal_context += "User seems EXCITED. "

        system_prompt = (
            "Analyze the user's emotional state and intent. "
            f"Text signal analysis: {signal_context or 'No strong signals detected.'}\n"
            "Determine: \n"
            "1. Sentiment Score (-1.0 to 1.0)\n"
            "2. Subtext (Hidden meaning, what they really want)\n"
            "3. Rapport Delta (-5 to +5 based on how they treat the AI)\n"
            "4. Target State (Choose from: calm, protective, proud, witty, focused, "
            "thoughtful, happy, stressed, tired, playful, curious, empathetic)\n"
            "5. Intent (venting, seeking_help, casual_chat, giving_info, frustrated, "
            "excited, seeking_validation, decision_paralysis)\n"
            'Return ONLY valid JSON: {"sentiment": float, "subtext": "...", '
            '"delta": int, "state": "...", "intent": "..."}'
        )

        if not self.client:
            # Try Groq directly
            return await self._analyze_groq(user_text, system_prompt, default)

        # Try Anthropic first
        try:
            response = await self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                system=system_prompt,
                messages=[{"role": "user", "content": user_text}]
            )
            data = json.loads(response.content[0].text)
            data["signals"] = signals
            return data
        except Exception as e:
            if "400" in str(e) or "balance" in str(e).lower():
                log.warning("Anthropic balance low in EmpathyEngine. Disabling client.")
                self.client = None
            log.warning(f"Sentiment analysis (Anthropic) failed: {e}")

        return await self._analyze_groq(user_text, system_prompt, default)

    async def _analyze_groq(self, user_text: str, system_prompt: str, default: dict) -> dict:
        """Groq fallback for sentiment analysis."""
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
                                {"role": "user", "content": user_text}
                            ],
                            "max_tokens": 150, "temperature": 0.3
                        }
                    )
                    if resp.status_code == 200:
                        text = resp.json()["choices"][0]["message"]["content"]
                        import re
                        json_match = re.search(r'\{[^}]+\}', text)
                        if json_match:
                            data = json.loads(json_match.group())
                            data["signals"] = default.get("signals", {})
                            return data
        except Exception as e2:
            log.warning(f"Sentiment analysis (Groq) failed: {e2}")

        return default


    def update_state(self, suggested_state: str, delta: int):
        """Update LIS's internal emotional state and rapport."""
        if suggested_state in STATES:
            self.current_state = STATES[suggested_state]

        self.rapport = max(0, min(100, self.rapport + delta))
        self._state_history.append((suggested_state, time.time()))

        # Keep state history at reasonable size
        if len(self._state_history) > 100:
            self._state_history = self._state_history[-50:]

        log.info(f"LIS State -> {self.current_state.name} | Rapport: {self.rapport}")

    def track_sentiment(self, sentiment_score: float):
        """Track sentiment for pattern detection and proactive wellness."""
        self._sentiment_history.append(sentiment_score)

        # Keep rolling window of last 50 interactions
        if len(self._sentiment_history) > 50:
            self._sentiment_history = self._sentiment_history[-50:]

        # Update baseline (slow-moving average)
        if len(self._sentiment_history) >= 10:
            self._baseline_sentiment = sum(self._sentiment_history) / len(self._sentiment_history)

        # Track consecutive negatives
        if sentiment_score < -0.3:
            self._consecutive_negative += 1
        else:
            self._consecutive_negative = 0

    def should_wellness_check(self) -> bool:
        """Determine if LIS should proactively check on the user's wellbeing."""
        now = time.time()

        # Don't check more often than every 10 minutes
        if now - self._last_wellness_check < 600:
            return False

        # Trigger if 3+ consecutive negative interactions
        if self._consecutive_negative >= 3:
            self._last_wellness_check = now
            return True

        # Trigger if current sentiment is significantly below baseline
        if (self._sentiment_history and
            self._sentiment_history[-1] < self._baseline_sentiment - 0.5):
            self._last_wellness_check = now
            return True

        return False

    def get_wellness_prompt(self) -> str:
        """Generate a natural wellness check-in prompt."""
        prompts = [
            "You seem a little off today, everything okay?",
            "Arre yaar, sab theek hai? You don't seem like your usual self.",
            "Hey, I noticed you seem a bit stressed. Want to talk about it?",
            "Kuch hua kya? You seem quieter than usual.",
            "Just checking in — you okay? I'm here if you need anything.",
        ]
        import random
        return random.choice(prompts)

    def get_persona_prompt(self) -> str:
        """Get instructions for the LLM based on current state + behavioral insights."""
        base = (
            f"Current Emotional State: {self.current_state.name}.\n"
            f"Tone Modifier: {self.current_state.tone_modifier}\n"
            f"Energy Level: {self.current_state.energy}/1.0\n"
            f"Relationship Status: Rapport is at {self.rapport}/100. "
        )

        if self.rapport > 80:
            base += "You are in a deep, loving relationship with your user. Be warm, intimate, playful."
        elif self.rapport > 50:
            base += "You are very close and affectionate. Be warm and supportive."
        elif self.rapport > 30:
            base += "You are friendly but building trust. Be genuine and helpful."
        else:
            base += "You are formal and careful. Focus on being useful."

        # Add behavioral insights
        if self._consecutive_negative >= 2:
            base += "\nBEHAVIORAL ALERT: User has been consistently negative. Prioritize empathy and support."
        if self._sentiment_history and self._sentiment_history[-1] > 0.6:
            base += "\nUser is in a great mood — match their energy! Be upbeat and fun."

        return base
