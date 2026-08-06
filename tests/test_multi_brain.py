import pytest
from unittest.mock import AsyncMock, patch

from llm_providers import LLMProviders

@pytest.fixture
def providers():
    # Set fake keys to force it to try the providers rather than skipping them instantly
    p = LLMProviders()
    p.anthropic_key = "sk-fake-anthropic----------------"
    p.groq_key = "gsk_fake_groq"
    p.gemini_key = "fake_gemini"
    p.cerebras_key = "fake_cerebras"
    p.openrouter_key = "fake_openrouter"
    
    # Mock Anthropic Client
    p._anthropic_client = AsyncMock()
    return p

@pytest.mark.asyncio
async def test_full_fallback_chain(providers):
    """Test that it falls back through all 6 providers if they fail, returning emergency text."""
    
    # We want ALL of them to fail to see the fallback chain
    providers._anthropic_client.messages.create.side_effect = Exception("Anthropic failure")
    
    with patch('llm_providers.httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        # Make all HTTP requests fail
        mock_post.side_effect = Exception("HTTP failure")
        
        result = await providers.generate([{"role": "user", "content": "Hello"}])
        
        # Should return the emergency fallback text
        assert "Yaar, abhi meri saari cloud systems thodi slow chal rahi hain" in result
        
        # Verify it tried the HTTP endpoints for the rest of the chain
        assert mock_post.call_count >= 5  # Groq, Gemini, Cerebras, OpenRouter, Ollama

@pytest.mark.asyncio
async def test_fallback_success_midway(providers):
    """Test that it stops falling back once a provider succeeds."""
    providers._anthropic_client.messages.create.side_effect = Exception("Anthropic failure")
    
    with patch('llm_providers.httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        # First call (Groq) fails, second call (Gemini) succeeds
        
        class FakeResponse:
            def __init__(self, json_data, status_code=200):
                self._json = json_data
                self.status_code = status_code
            def json(self):
                return self._json
                
        def mock_post_side_effect(*args, **kwargs):
            if "nvidia" in args[0].lower():
                raise Exception("Nvidia down")
            elif "groq.com" in args[0].lower():
                raise Exception("Groq down")
            elif "generativelanguage.googleapis.com" in args[0].lower():
                return FakeResponse({
                    "candidates": [{"content": {"parts": [{"text": "Hello from Gemini"}]}}]
                })
            else:
                return FakeResponse({}, status_code=500)
                
        mock_post.side_effect = mock_post_side_effect
        
        result = await providers.generate([{"role": "user", "content": "Hello"}])
        
        assert result == "Hello from Gemini"
        
        # It should have called Anthropic (mocked out), then NVIDIA, Groq, and Gemini, then stopped.
        assert mock_post.call_count == 3
