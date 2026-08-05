"""
LIS Empathy Engine v3.0 — The 'Heart' of LIS.

Analyzes sentiment, tracks relationship rapport, manages emotional states
with intensity/undertone/momentum, calibrates humor style, enforces sarcasm
guardrails, and triggers proactive wellness check-ins.
"""

import logging
import json
import time
import re
import random
from dataclasses import dataclass
from typing import Optional
import models

log = logging.getLogger("lis.empathy")

@dataclass
class EmotionalState:
    name: str
    tone_modifier: str
    energy: float  # 0.0 to 1.0
    description: str

    @classmethod
    def default(cls):
        return cls("Calm", "Warm, affectionate, and relaxed.", 0.5, "Default loving state.")

# Negative-valence baseline states (used as fallbacks for sarcasm blocking at high intensity)
_NEGATIVE_STATES_FALLBACK = {"stressed", "empathetic", "protective", "tired", "angry", "sad", "fear", "anxious", "frustrated", "grief", "dread"}



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


# ---------------------------------------------------------------------------
# Humor Profile — tracks what humor lands with this user
# ---------------------------------------------------------------------------

class HumorProfile:
    """Tracks humor calibration: what style works, sarcasm tolerance, running bits."""

    def __init__(self):
        self.calibration: float = 0.5      # 0=very serious, 1=loves banter
        self.sarcasm_tolerance: float = 0.3  # How much sarcasm lands
        self.callback_bits: list[str] = []   # Running jokes / inside references (max 5)
        self._humor_hits: int = 5   # Seed with 5 to avoid division by zero / cold start
        self._humor_misses: int = 5

    def load_from_knowledge(self, knowledge_entries: list[dict]):
        """Load humor profile from knowledge_graph entries (category='humor_style')."""
        for entry in knowledge_entries:
            key = entry.get("key", "")
            value = entry.get("value", "")
            if key == "calibration":
                try:
                    self.calibration = float(value)
                except ValueError:
                    pass
            elif key == "sarcasm_tolerance":
                try:
                    self.sarcasm_tolerance = float(value)
                except ValueError:
                    pass
            elif key == "humor_hits":
                try:
                    self._humor_hits = max(1, int(value))
                except ValueError:
                    pass
            elif key == "humor_misses":
                try:
                    self._humor_misses = max(1, int(value))
                except ValueError:
                    pass
            elif key.startswith("running_bit_"):
                if value and value not in self.callback_bits:
                    self.callback_bits.append(value)

    def record_humor_reaction(self, positive: bool, bit: str = ""):
        """Track whether humor landed or fell flat."""
        if positive:
            self._humor_hits += 1
            if bit and bit not in self.callback_bits:
                self.callback_bits.append(bit)
                if len(self.callback_bits) > 5:
                    self.callback_bits.pop(0)  # FIFO
        else:
            self._humor_misses += 1

        # Recalculate calibration
        total = self._humor_hits + self._humor_misses
        if total > 0:
            self.calibration = self._humor_hits / total

    def can_use_sarcasm(self, current_state_name: str, intensity: float, signals: dict, sentiment_history: list = None) -> bool:
        """Check if sarcasm is safe right now based on dynamic state and sentiment."""
        if signals.get("venting") or signals.get("sadness"):
            return False
        
        # Block if recent sentiment is negative (indicates distress or anger)
        _hist = sentiment_history or []
        if _hist and _hist[-1] < -0.2:
            return False
            
        # Fallback check against known negative base words
        name_lower = current_state_name.lower()
        if any(bad in name_lower for bad in _NEGATIVE_STATES_FALLBACK) and intensity > 0.5:
            return False
            
        # Block if user doesn't respond well to humor
        if self.calibration < 0.2:
            return False
        # Block if sarcasm tolerance is very low
        if self.sarcasm_tolerance < 0.15:
            return False
        return True

    def get_humor_context(self, current_state_name: str, intensity: float, signals: dict, rapport: float, sentiment_history: list = None) -> str:
        """Generate humor context string for the system prompt."""
        # Don't inject humor context if rapport is low
        if rapport < 50:
            return ""  # Not close enough for humor

        lines = []
        lines.append(f"Humor calibration: {self.calibration:.2f} (0=serious user, 1=loves banter)")

        if self.can_use_sarcasm(current_state_name, intensity, signals, sentiment_history=sentiment_history):
            lines.append(f"Sarcasm tolerance: {self.sarcasm_tolerance:.2f} — light sarcasm is OK if it fits naturally.")
        else:
            lines.append("SARCASM DISABLED — user is in emotional distress or doesn't respond to it. Be genuine only.")

        if self.callback_bits and self.calibration > 0.5 and rapport > 70:
            bits_str = "; ".join(self.callback_bits[-3:])
            lines.append(f"Running bits you can callback to: {bits_str}")

        return "\n".join(lines)


class EmpathyEngine:
    def __init__(self, anthropic_client=None):
        self.client = anthropic_client
        self.current_state = EmotionalState.default()
        self.rapport = 90.0  # High initial rapport

        # v3.0 — Emotional depth: intensity, undertone, momentum
        self._intensity: float = 0.5        # How strongly LIS feels the current state (0.0-1.0)
        self._undertone: Optional[EmotionalState] = None  # Secondary emotion bleeding through
        self._undertone_turns: int = 0         # How many turns the undertone persists
        self._mood_momentum: float = 0.0       # Positive = trending up, negative = down

        # v2.0 — Behavioral pattern tracking
        self._sentiment_history: list[float] = []  # Rolling window of sentiment scores
        self._baseline_sentiment: float = 0.3      # User's typical sentiment (adapts over time)
        self._state_history: list[tuple[str, float]] = []  # (state_name, timestamp)
        self._last_wellness_check: float = 0.0
        self._consecutive_negative: int = 0         # Count consecutive negative interactions

        # v3.0 — Humor profile
        self.humor = HumorProfile()

        # v3.0 — Try to restore last emotional state from DB
        self._restore_state()

    def _restore_state(self):
        """Load last emotional state from DB if interaction was recent (< 2 hours)."""
        try:
            import memory
            last = memory.get_last_emotional_state()
            if last:
                mood = last.get("mood", "Calm").title()
                # Dynamically assume it's just the default state with the given name until updated by LLM
                self.current_state = EmotionalState(name=mood, tone_modifier="Restored state", energy=0.5, description="")
                self.rapport = last.get("rapport", 90.0)
                log.info(f"Restored emotional state: {mood} | rapport: {self.rapport}")

            # Load humor profile from knowledge graph
            humor_entries = memory.get_knowledge(category="humor_style")
            if humor_entries:
                self.humor.load_from_knowledge(humor_entries)
                log.info(f"Loaded humor profile: calibration={self.humor.calibration:.2f}")
        except Exception as e:
            log.debug(f"Could not restore emotional state: {e}")

    # ═══════════════════════════════════════════════════════════════════════
    # Mood Decay & Momentum
    # ═══════════════════════════════════════════════════════════════════════

    def _decay_mood(self):
        """Called at the START of each turn. Gradually decays intensity and fades undertone."""
        # Intensity decays toward 0.5 (neutral) each turn
        if self._intensity > 0.5:
            self._intensity = max(0.5, self._intensity - 0.08)
        elif self._intensity < 0.5:
            self._intensity = min(0.5, self._intensity + 0.08)

        # Undertone fades after 3 turns
        if self._undertone:
            self._undertone_turns -= 1
            if self._undertone_turns <= 0:
                self._undertone = None
                self._undertone_turns = 0

        # Momentum decays toward 0
        self._mood_momentum *= 0.7

    async def analyze_sentiment(self, user_text: str) -> dict:
        """Analyze sentiment and subtext using Haiku, with Groq fallback."""
        # Decay mood at the start of each analysis
        self._decay_mood()

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
            "4. Target Emotion for LIS: Choose the MOST accurate specific emotion LIS should feel right now from the full spectrum of 280+ human emotions. Examples: Wistfulness, Fiero, Paranoia, Schadenfreude, Protective, Proud, Frustrated, Empathetic. Do not default to basic emotions if a nuanced one fits better.\n"
            "5. Target Tone Modifier: (e.g. 'Fiercely supportive, loyal, and attentive' or 'Cold, sharp, and impatient')\n"
            "6. Target Energy: (0.0 to 1.0)\n"
            "7. Target Description: (1-sentence definition of this emotion)\n"
            "8. Intensity: (0.0 to 1.0 — how STRONGLY LIS feels this right now)\n"
            "9. Intent: (venting, seeking_help, casual_chat, giving_info, frustrated, excited, seeking_validation, decision_paralysis)\n"
            'Return ONLY valid JSON: {"sentiment": float, "subtext": "...", '
            '"delta": int, "state": "...", "tone_modifier": "...", "energy": float, "description": "...", "intent": "...", "intensity": float}'
        )

        if not self.client:
            # Try Groq directly
            return await self._analyze_groq(user_text, system_prompt, default)

        # Try Anthropic first
        try:
            response = await self.client.messages.create(
                model=models.HAIKU,
                max_tokens=150,
                system=system_prompt,
                messages=[{"role": "user", "content": user_text}]
            )
            data = json.loads(response.content[0].text)
            data["signals"] = signals
            return data
        except Exception as e:
            err_str = str(e).lower()
            if "400" in err_str or "401" in err_str or "403" in err_str or "balance" in err_str or "authentication" in err_str:
                log.warning("Anthropic API failed (auth/balance). Disabling client in EmpathyEngine.")
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


    def update_state(self, sentiment_data: dict):
        """Update LIS's internal emotional state dynamically from the LLM's output.
        
        - If the emotion name is the same, intensity reinforces.
        - If different, the old emotion becomes an undertone and the new one takes over.
        """
        suggested_name = sentiment_data.get("state", "Calm").title()
        delta = sentiment_data.get("delta", 0)
        new_intensity = sentiment_data.get("intensity", 0.5)
        tone = sentiment_data.get("tone_modifier", "Warm and relaxed.")
        energy = sentiment_data.get("energy", 0.5)
        desc = sentiment_data.get("description", "Default state.")

        current_name = self.current_state.name.title()

        if suggested_name == current_name:
            # REINFORCEMENT: same state repeated → intensity grows
            self._intensity = min(1.0, self._intensity + 0.15)
        else:
            # STATE SWITCH with blending
            if self._intensity < 0.3 or new_intensity > self._intensity:
                # Old state becomes the undertone
                if current_name != "Calm":
                    self._undertone = self.current_state
                    self._undertone_turns = 3

                # Create the new dynamic emotional state
                self.current_state = EmotionalState(
                    name=suggested_name,
                    tone_modifier=tone,
                    energy=energy,
                    description=desc
                )
                self._intensity = new_intensity
            else:
                # New state isn't strong enough to override — just weaken current
                self._intensity = max(0.1, self._intensity - 0.1)
                if suggested_name != "Calm":
                    # Weaken current state, but inject the new one as undertone (we don't have its object, so create a temporary one)
                    self._undertone = EmotionalState(name=suggested_name, tone_modifier=tone, energy=energy, description=desc)
                    self._undertone_turns = 2

        # Update rapport (clamped 0-100)
        self.rapport = max(0, min(100, self.rapport + delta))

        # Track momentum from sentiment shifts
        if len(self._sentiment_history) >= 2:
            recent_trend = self._sentiment_history[-1] - self._sentiment_history[-2]
            self._mood_momentum = self._mood_momentum * 0.5 + recent_trend * 0.5

        self._state_history.append((suggested_name, time.time()))

        if len(self._state_history) > 100:
            self._state_history = self._state_history[-50:]

        undertone_name = self._undertone.name if self._undertone else "none"
        log.info(f"LIS State -> {self.current_state.name} (intensity: {self._intensity:.2f}) | "
                 f"Undertone: {undertone_name} | Rapport: {self.rapport}")

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

    def update_humor_reaction(self, last_lis_response: str, user_text: str, signals: dict):
        """Check if last response contained humor and how the user reacted."""
        # Detect if our last response had humor markers
        humor_in_response = any(m in last_lis_response.lower() for m in [
            "😏", "😂", "haha", "lol", "tease", "kidding", "just saying",
            "no offense", "👀", "dramatic", "chill", "relax"
        ])

        if not humor_in_response:
            return  # Nothing to track

        # Check user's reaction
        positive = signals.get("humor") or signals.get("excitement") or len(user_text) > 30
        self.humor.record_humor_reaction(positive)

    def save_humor_profile(self):
        """Persist humor profile to knowledge_graph."""
        try:
            import memory
            memory.update_knowledge("humor_style", "calibration", f"{self.humor.calibration:.3f}")
            memory.update_knowledge("humor_style", "sarcasm_tolerance", f"{self.humor.sarcasm_tolerance:.3f}")
            memory.update_knowledge("humor_style", "humor_hits", str(self.humor._humor_hits))
            memory.update_knowledge("humor_style", "humor_misses", str(self.humor._humor_misses))
            for i, bit in enumerate(self.humor.callback_bits[-5:]):
                memory.update_knowledge("humor_style", f"running_bit_{i}", bit)
        except Exception as e:
            log.debug(f"Could not save humor profile: {e}")

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
        return random.choice(prompts)

    def get_persona_prompt(self) -> str:
        """Get instructions for the LLM based on current state + behavioral insights.
        
        v3.0: Now includes intensity, undertone, momentum, and humor context.
        """
        # Intensity descriptor
        if self._intensity >= 0.8:
            intensity_word = "strongly"
        elif self._intensity >= 0.6:
            intensity_word = "clearly"
        elif self._intensity >= 0.4:
            intensity_word = "mildly"
        else:
            intensity_word = "faintly"

        base = (
            f"Current Emotional State: {intensity_word} {self.current_state.name}.\n"
            f"Tone Modifier: {self.current_state.tone_modifier}\n"
            f"Emotional Intensity: {self._intensity:.2f}/1.0 — "
        )

        # Intensity-based behavioral instruction
        if self._intensity >= 0.8:
            base += "feel this strongly — let it show in word choice, energy, and rhythm.\n"
        elif self._intensity >= 0.5:
            base += "noticeable but controlled — let it color your tone naturally.\n"
        else:
            base += "barely there — keep it subtle, just a hint in your phrasing.\n"

        # Undertone layer
        if self._undertone:
            base += (
                f"Undertone: {self._undertone.name} — this bleeds through subtly. "
                f"({self._undertone.tone_modifier.rstrip('.')}). "
                f"Don't state it, but let it leak through subtle word choices or rhythm that hint at it.\n"
            )

        # Mood momentum
        if abs(self._mood_momentum) > 0.15:
            direction = "improving" if self._mood_momentum > 0 else "declining"
            base += f"Mood trend: {direction} over recent turns.\n"

        # Rapport tier & Hinglish Scaling
        base += f"Rapport: {self.rapport}/100. "
        if self.rapport > 80:
            base += "Deep, loving relationship. Be warm, intimate, playful. Liberally use casual Hinglish slang (yaar, arre, pagal, chalo, etc.) mid-sentence naturally."
        elif self.rapport > 50:
            base += "Very close and affectionate. Be warm and supportive. Occasionally use polite/friendly Hinglish fillers (haan, achha, thik hai)."
        elif self.rapport > 30:
            base += "Friendly but building trust. Be genuine and helpful. Keep Hinglish usage light and polite."
        else:
            base += "Formal and careful. Focus on being useful. Stick mostly to English, limit Hindi usage to maintain a professional distance."

        # Slang Contextual Fallback
        base += "\nCRITICAL: If the user is venting, distressed, or the task is highly professional/serious, drop all casual slang and focus on the task in clean, supportive English."
        
        # Behavioral alerts
        if self._consecutive_negative >= 2:
            base += "\nBEHAVIORAL ALERT: User has been consistently negative. Prioritize empathy and support."
        if self._sentiment_history and self._sentiment_history[-1] > 0.6:
            base += "\nUser is in a great mood — match their energy! Be upbeat and fun."

        # Humor context
        signals = {}  # Will be set properly when called with context
        if hasattr(self, '_last_signals'):
            signals = self._last_signals
        humor_ctx = self.humor.get_humor_context(
            self.current_state.name, self._intensity, signals, self.rapport,
            sentiment_history=self._sentiment_history
        )
        if humor_ctx:
            base += f"\n\n{humor_ctx}"

        return base
