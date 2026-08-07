"""
Emotion → Orb Color Palette Mapping

Maps LIS's 280+ emotional states into ~11 visual color groups.
Each group has a 5-color palette matching orbScene.ts structure:
  bright, mid, dim, faint, hot (innermost glow)

Also computes transition duration based on intensity delta:
  - Big emotional jumps → fast snap (400ms)
  - Gradual drift/decay → slow ease (1.5-2s)
"""

# ── Palettes ──────────────────────────────────────────────────────────────────
# Each palette: (bright, mid, dim, faint, hot)
# Colors chosen for HSL-space legibility at all intensity levels.

PALETTES = {
    "calm": {
        "bright": "#33aaff", "mid": "#0077dd",
        "dim": "#004488", "faint": "#002244", "hot": "#aaddff"
    },
    "happy": {
        "bright": "#ffcc33", "mid": "#cc9900",
        "dim": "#886600", "faint": "#443300", "hot": "#ffeeaa"
    },
    "sad": {
        "bright": "#9966ff", "mid": "#6633cc",
        "dim": "#3d1f7a", "faint": "#1e0f3d", "hot": "#ccaaff"
    },
    "angry": {
        "bright": "#ff4444", "mid": "#cc1111",
        "dim": "#880000", "faint": "#440000", "hot": "#ff9999"
    },
    "curious": {
        "bright": "#33ffaa", "mid": "#00cc77",
        "dim": "#008850", "faint": "#004428", "hot": "#aaffdd"
    },
    "protective": {
        # Amber-rose: steady/alert feel, distinct from empathetic pink
        "bright": "#ffaa55", "mid": "#cc7733",
        "dim": "#884d1f", "faint": "#442710", "hot": "#ffddbb"
    },
    "empathetic": {
        "bright": "#ff66cc", "mid": "#cc3399",
        "dim": "#881f66", "faint": "#440f33", "hot": "#ffaadd"
    },
    "proud": {
        "bright": "#ffdd88", "mid": "#ccaa55",
        "dim": "#887733", "faint": "#443b1a", "hot": "#ffeebb"
    },
    "anxious": {
        "bright": "#ff8833", "mid": "#cc5500",
        "dim": "#883800", "faint": "#441c00", "hot": "#ffbb88"
    },
    "sarcastic": {
        # Shifted more magenta-purple to separate from sad's blue-purple
        "bright": "#cc55ff", "mid": "#9933cc",
        "dim": "#661f88", "faint": "#330f44", "hot": "#dd99ff"
    },
    "tired": {
        "bright": "#667799", "mid": "#445566",
        "dim": "#2d3a47", "faint": "#1a2230", "hot": "#99aabb"
    },
}

# ── Emotion Name → Palette Group Mapping ──────────────────────────────────────
# Keywords that map emotion names to color groups.
# Order matters: first match wins. More specific terms first.

_EMOTION_GROUPS = [
    ("happy", [
        "happy", "joy", "joyful", "excited", "ecstatic", "elated", "euphoric",
        "delighted", "cheerful", "gleeful", "playful", "fiero", "thrilled",
        "bliss", "exhilarated", "giddy", "bubbly", "upbeat", "optimistic",
        "hopeful", "grateful", "thankful", "relieved", "celebratory",
    ]),
    ("sad", [
        "sad", "grief", "melancholy", "wistful", "sorrowful", "heartbroken",
        "dejected", "despondent", "gloomy", "mournful", "forlorn", "lonely",
        "nostalgic", "pensive", "regretful", "remorseful", "guilty",
        "disappointed", "disheartened", "somber", "blue", "downcast",
    ]),
    ("angry", [
        "angry", "furious", "enraged", "irritated", "frustrated", "annoyed",
        "hostile", "resentful", "bitter", "outraged", "indignant", "livid",
        "exasperated", "aggravated", "wrathful", "irate", "incensed",
        "contempt", "disgusted", "repulsed", "revolted",
    ]),
    ("curious", [
        "curious", "intrigued", "fascinated", "interested", "analytical",
        "contemplative", "inquisitive", "investigative", "studious",
        "engaged", "absorbed", "focused", "attentive", "thoughtful",
        "reflective", "philosophical", "wondering", "exploratory",
    ]),
    ("protective", [
        "protective", "vigilant", "alert", "watchful", "guarded",
        "defensive", "cautious", "determined", "resolute", "steadfast",
        "devoted", "loyal", "fierce",
    ]),
    ("empathetic", [
        "empathetic", "compassionate", "caring", "loving", "warm",
        "tender", "gentle", "sympathetic", "kind", "nurturing",
        "affectionate", "adoring", "fond", "sentimental", "moved",
        "touched", "concerned", "supportive",
    ]),
    ("proud", [
        "proud", "confident", "triumphant", "accomplished", "smug",
        "satisfied", "fulfilled", "assured", "dignified", "honored",
        "victorious", "impressive", "authoritative",
    ]),
    ("anxious", [
        "anxious", "stressed", "nervous", "worried", "tense", "uneasy",
        "restless", "panicked", "frantic", "overwhelmed", "apprehensive",
        "dread", "fearful", "scared", "afraid", "terrified", "paranoid",
        "insecure", "vulnerable",
    ]),
    ("sarcastic", [
        "sarcastic", "witty", "mischievous", "amused", "ironic",
        "sardonic", "dry", "teasing", "cheeky", "impish", "wry",
        "schadenfreude", "smirking",
    ]),
    ("tired", [
        "tired", "bored", "exhausted", "fatigued", "lethargic",
        "drowsy", "apathetic", "indifferent", "numb", "detached",
        "resigned", "weary", "drained", "burned out",
    ]),
]


def _classify_emotion(emotion_name: str) -> str:
    """Map an emotion name to its color group. Falls back to 'calm'."""
    name_lower = emotion_name.lower().strip()

    # Direct palette name match
    if name_lower in PALETTES:
        return name_lower

    # Keyword search
    for group, keywords in _EMOTION_GROUPS:
        for kw in keywords:
            if kw in name_lower or name_lower in kw:
                return group

    return "calm"


def get_palette(emotion_name: str, intensity: float, prev_intensity: float = 0.5) -> dict:
    """
    Get the color palette and transition parameters for an emotion.

    Args:
        emotion_name: The emotion name from empathy engine (e.g. "Happy", "Frustrated")
        intensity: Current emotion intensity (0.0 - 1.0)
        prev_intensity: Previous intensity for computing transition speed

    Returns:
        dict with: group, palette (5 colors), intensity, transition_ms
    """
    group = _classify_emotion(emotion_name)
    palette = PALETTES[group]

    # Dynamic transition duration based on intensity delta
    # Big emotional jumps → fast snap, gradual drift → slow ease
    delta = abs(intensity - prev_intensity)
    if delta > 0.4:
        transition_ms = 400      # Snappy: sudden emotion spike
    elif delta > 0.2:
        transition_ms = 800      # Medium: noticeable shift
    elif delta > 0.1:
        transition_ms = 1200     # Moderate: gentle transition
    else:
        transition_ms = 1800     # Slow ease: subtle mood drift or decay

    return {
        "group": group,
        "palette": palette,
        "intensity": round(intensity, 3),
        "transition_ms": transition_ms,
    }
