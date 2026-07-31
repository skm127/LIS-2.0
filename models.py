"""
LIS — Canonical Model Identifiers

Single source of truth for all LLM model IDs used across the codebase.
Update versions here when models are rotated/deprecated.
"""

# ── Anthropic ──────────────────────────────────────────────────────────────
HAIKU = "claude-3-5-haiku-20241022"
SONNET = "claude-3-5-sonnet-20241022"

# ── Groq ───────────────────────────────────────────────────────────────────
GROQ_DEFAULT = "llama-3.3-70b-versatile"

# ── Google ─────────────────────────────────────────────────────────────────
GEMINI_DEFAULT = "gemini-2.0-flash"

# ── Cerebras ───────────────────────────────────────────────────────────────
CEREBRAS_DEFAULT = "llama3.1-8b"

# ── OpenRouter ─────────────────────────────────────────────────────────────
OPENROUTER_DEFAULT = "meta-llama/llama-3.1-8b-instruct:free"

# ── NVIDIA NeMo ────────────────────────────────────────────────────────────
NVIDIA_DEFAULT = "meta/llama-3.3-70b-instruct"
NVIDIA_VISION_DEFAULT = "meta/llama-3.2-90b-vision-instruct"
NVIDIA_EMBED_DEFAULT = "nvidia/nv-embedqa-e5-v5"

# ── Ollama (local) ─────────────────────────────────────────────────────────
OLLAMA_DEFAULT = "llama3.2:3b"
