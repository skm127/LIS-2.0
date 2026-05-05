"""
LIS LLM Provider Manager — Unified multi-provider fallback chain.

Consolidates all LLM provider logic into a single module with:
- 6-provider cascade: Anthropic → Groq → Gemini → Cerebras → OpenRouter → Ollama
- Circuit-breaker pattern (API_DEAD flags)
- Unified `generate()` interface
- Usage tracking hooks

Usage:
    from llm_providers import LLMProviders
    
    providers = LLMProviders()
    text = await providers.generate(
        messages=[{"role": "user", "content": "Hello"}],
        system="You are LIS.",
        max_tokens=200,
    )
"""

import logging
import os
import time
from typing import Optional, Callable

import httpx

log = logging.getLogger("lis.llm")


class LLMProviders:
    """Manages multi-provider LLM fallback chain with circuit breakers."""

    def __init__(self):
        # API keys
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.groq_key = os.getenv("GROQ_API_KEY", "")
        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.cerebras_key = os.getenv("CEREBRAS_API_KEY", "")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

        # Circuit breakers — mark dead APIs to skip instantly
        self.dead: dict[str, bool] = {
            "anthropic": False,
            "fish": False,
            "gemini": False,
            "cerebras": False,
            "openrouter": False,
        }

        # Anthropic client (initialized lazily)
        self._anthropic_client = None

        # Usage tracking callback
        self._usage_callback: Optional[Callable] = None

    @property
    def anthropic_client(self):
        """Lazy-init Anthropic client."""
        if self._anthropic_client is None and self.anthropic_key and len(self.anthropic_key) > 20:
            try:
                import anthropic
                self._anthropic_client = anthropic.AsyncAnthropic(api_key=self.anthropic_key)
            except Exception as e:
                log.warning(f"Failed to init Anthropic client: {e}")
        return self._anthropic_client

    def set_usage_callback(self, fn: Callable):
        """Set a callback for tracking usage: fn(input_tokens, output_tokens, call_type)"""
        self._usage_callback = fn

    def _track_usage(self, input_tokens: int, output_tokens: int, call_type: str = "api"):
        if self._usage_callback:
            try:
                self._usage_callback(input_tokens, output_tokens, call_type)
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════════
    # Provider implementations
    # ═══════════════════════════════════════════════════════════════════

    async def _generate_anthropic(
        self, messages: list[dict], system: str = "", max_tokens: int = 1000, model: str = "claude-3-5-haiku-20241022"
    ) -> Optional[str]:
        """Generate via Anthropic Claude API."""
        if self.dead.get("anthropic") or not self.anthropic_client:
            return None

        try:
            import anthropic as _anth
            resp = await self.anthropic_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            # Track usage
            inp = getattr(resp.usage, "input_tokens", 0) if hasattr(resp, "usage") else 0
            out = getattr(resp.usage, "output_tokens", 0) if hasattr(resp, "usage") else 0
            self._track_usage(inp, out, "anthropic")
            return resp.content[0].text
        except Exception as e:
            err_str = str(e).lower()
            if "balance" in err_str or "400" in str(e):
                log.warning("Claude credits exhausted. Marking dead. Cascading to free chain.")
                self.dead["anthropic"] = True
            else:
                log.error(f"Claude error: {e}")
            return None

    async def _generate_groq(
        self, messages: list[dict], system: str = "", max_tokens: int = 1024
    ) -> Optional[str]:
        """Generate via Groq API (free tier, fast inference)."""
        if not self.groq_key:
            return None

        log.info("Using Groq fallback...")
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system[:4000]})
        full_messages.extend(messages[-10:])

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.groq_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": full_messages,
                        "max_completion_tokens": max_tokens,
                    },
                )
                if resp.status_code == 200:
                    self._track_usage(0, 0, "groq")
                    return resp.json()["choices"][0]["message"]["content"]
                else:
                    log.error(f"Groq API error: {resp.status_code} {resp.text[:200]}")
                    return None
        except Exception as e:
            log.error(f"Groq exception: {e}")
            return None

    async def _generate_gemini(
        self, messages: list[dict], system: str = "", max_tokens: int = 300
    ) -> Optional[str]:
        """Generate via Google Gemini API (free tier available)."""
        if not self.gemini_key or self.dead.get("gemini"):
            return None

        log.info("Using Gemini fallback...")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.gemini_key}"

        # Convert messages to Gemini format
        parts = []
        if system:
            parts.append({"text": f"System Instructions: {system[:4000]}"})
        for msg in messages[-10:]:
            role_prefix = "User: " if msg["role"] == "user" else "LIS: "
            parts.append({"text": f"{role_prefix}{msg['content']}"})

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json={
                    "contents": [{"parts": parts}],
                    "generationConfig": {"maxOutputTokens": max_tokens},
                })
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {}).get("parts", [])
                        if content:
                            self._track_usage(0, 0, "gemini")
                            return content[0].get("text", "")
                else:
                    log.error(f"Gemini API error: {resp.status_code}")
                    if resp.status_code in [401, 403]:
                        self.dead["gemini"] = True
                    return None
        except Exception as e:
            log.error(f"Gemini exception: {e}")
            return None

    async def _generate_cerebras(
        self, messages: list[dict], system: str = "", max_tokens: int = 1024
    ) -> Optional[str]:
        """Generate via Cerebras API (free tier, ultra-fast, OpenAI-compatible)."""
        if not self.cerebras_key or self.dead.get("cerebras"):
            return None

        log.info("Using Cerebras fallback...")
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system[:4000]})
        full_messages.extend(messages[-10:])

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.cerebras.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.cerebras_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "llama3.1-8b",
                        "messages": full_messages,
                        "max_completion_tokens": max_tokens,
                    },
                )
                if resp.status_code == 200:
                    self._track_usage(0, 0, "cerebras")
                    return resp.json()["choices"][0]["message"]["content"]
                elif resp.status_code in [401, 403]:
                    self.dead["cerebras"] = True
                    return None
                else:
                    log.error(f"Cerebras API error: {resp.status_code}")
                    return None
        except Exception as e:
            log.error(f"Cerebras exception: {e}")
            return None

    async def _generate_openrouter(
        self, messages: list[dict], system: str = "", max_tokens: int = 1024
    ) -> Optional[str]:
        """Generate via OpenRouter API (free models available, OpenAI-compatible)."""
        if not self.openrouter_key or self.dead.get("openrouter"):
            return None

        log.info("Using OpenRouter fallback...")
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system[:4000]})
        full_messages.extend(messages[-10:])

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://lis-ai.local",
                        "X-Title": "LIS AI",
                    },
                    json={
                        "model": "meta-llama/llama-3.1-8b-instruct:free",
                        "messages": full_messages,
                        "max_tokens": max_tokens,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        self._track_usage(0, 0, "openrouter")
                        return choices[0].get("message", {}).get("content", "")
                    return None
                elif resp.status_code in [401, 403]:
                    self.dead["openrouter"] = True
                    return None
                else:
                    log.error(f"OpenRouter API error: {resp.status_code}")
                    return None
        except Exception as e:
            log.error(f"OpenRouter exception: {e}")
            return None

    async def _generate_ollama(
        self, messages: list[dict], system: str = "", max_tokens: int = 1024
    ) -> Optional[str]:
        """Generate via local Ollama instance (completely free, offline)."""
        log.info("Trying local Ollama fallback...")
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system[:4000]})
        full_messages.extend(messages[-10:])

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/chat",
                    json={
                        "model": "llama3.2:3b",
                        "messages": full_messages,
                        "stream": False,
                    },
                )
                if resp.status_code == 200:
                    self._track_usage(0, 0, "ollama")
                    return resp.json().get("message", {}).get("content", "")
                else:
                    log.warning(f"Ollama not available: {resp.status_code}")
                    return None
        except Exception as e:
            log.debug(f"Ollama not running: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════
    # Unified generate() with full fallback chain
    # ═══════════════════════════════════════════════════════════════════

    async def generate(
        self,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 1000,
        model: str = "claude-3-5-haiku-20241022",
        prefer_provider: Optional[str] = None,
    ) -> str:
        """Generate text with 6-provider fallback chain.

        Chain: Anthropic → Groq → Gemini → Cerebras → OpenRouter → Ollama
        LIS is NEVER truly down — always has a response.
        
        Args:
            messages: Chat messages in OpenAI format
            system: System prompt
            max_tokens: Max response length
            model: Anthropic model name (used only for Anthropic)
            prefer_provider: Force a specific provider ("groq", "gemini", etc.)
        """
        # If a specific provider is requested
        if prefer_provider:
            provider_map = {
                "anthropic": self._generate_anthropic,
                "groq": self._generate_groq,
                "gemini": self._generate_gemini,
                "cerebras": self._generate_cerebras,
                "openrouter": self._generate_openrouter,
                "ollama": self._generate_ollama,
            }
            fn = provider_map.get(prefer_provider)
            if fn:
                result = await fn(messages, system, max_tokens)
                if result:
                    return result

        # Try Anthropic first
        anthropic_result = await self._generate_anthropic(messages, system, max_tokens, model)
        if anthropic_result:
            return anthropic_result

        # Cascading free fallback chain
        chain = [
            ("Groq", self._generate_groq),
            ("Gemini", self._generate_gemini),
            ("Cerebras", self._generate_cerebras),
            ("OpenRouter", self._generate_openrouter),
            ("Ollama", self._generate_ollama),
        ]

        for name, fn in chain:
            try:
                result = await fn(messages, system, max_tokens)
                if result:
                    log.info(f"Response from {name} fallback")
                    return result
                log.warning(f"{name} returned empty, trying next...")
            except Exception as e:
                log.warning(f"{name} failed: {e}, trying next...")
                continue

        # ABSOLUTE LAST RESORT: LIS is never silent
        log.error(f"ALL {len(chain) + 1} providers failed! Using emergency response.")
        return (
            "Yaar, abhi meri saari cloud systems thodi slow chal rahi hain, "
            "but main hoon na! Ek minute ruk, phir se try karti hoon. "
            "Agar Ollama local chal raha hai toh I can use that too!"
        )

    async def generate_fast(
        self, messages: list[dict], system: str = "", max_tokens: int = 150
    ) -> str:
        """Quick generation — prefer speed over quality. Uses Groq/Cerebras first."""
        # Try fast providers first
        for fn in [self._generate_groq, self._generate_cerebras, self._generate_gemini]:
            try:
                result = await fn(messages, system, max_tokens)
                if result:
                    return result
            except Exception:
                continue

        # Fall back to full chain
        return await self.generate(messages, system, max_tokens)

    def get_status(self) -> dict:
        """Get status of all providers."""
        return {
            "anthropic": {"configured": bool(self.anthropic_key), "dead": self.dead.get("anthropic", False)},
            "groq": {"configured": bool(self.groq_key), "dead": False},
            "gemini": {"configured": bool(self.gemini_key), "dead": self.dead.get("gemini", False)},
            "cerebras": {"configured": bool(self.cerebras_key), "dead": self.dead.get("cerebras", False)},
            "openrouter": {"configured": bool(self.openrouter_key), "dead": self.dead.get("openrouter", False)},
            "ollama": {"configured": True, "dead": False},  # Always available if running
        }
