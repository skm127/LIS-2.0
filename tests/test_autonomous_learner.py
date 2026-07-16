import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock

from autonomous_learner import AutonomousLearner, MAX_FETCHES_PER_HOUR, DOMAIN_ALLOWLIST

@pytest.fixture
def learner():
    import os
    os.environ["ENABLE_AUTONOMOUS_LEARNING"] = "True"
    return AutonomousLearner()

@pytest.mark.asyncio
async def test_extract_topics(learner):
    # Mock the LLM provider to return predictable string
    with patch.object(learner.llm, 'generate', new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = "React, useEffect, Hooks"
        topics = await learner.extract_topics("I need help with React hooks, specifically useEffect")
        assert len(topics) == 3
        assert "React" in topics
        assert "useEffect" in topics

def test_rate_limiter(learner):
    # Simulate a full hour of fetches
    learner._fetches_this_hour = MAX_FETCHES_PER_HOUR
    assert not learner._check_rate_limit()
    
    # Simulate an hour passing
    learner._hour_start = time.time() - 3601
    assert learner._check_rate_limit()
    assert learner._fetches_this_hour == 0

@pytest.mark.asyncio
async def test_domain_allowlist_rejection(learner):
    # Mock DuckDuckGo to return 1 allowed URL and 1 blocked URL
    urls = [
        "https://react.dev/reference/react/useEffect",
        "https://some-random-blog.com/react-tutorial"
    ]
    with patch.object(learner, '_search_duckduckgo', new_callable=AsyncMock) as mock_search:
        mock_search.return_value = urls
        
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><body>Some test content that is long enough to be indexed. " * 10 + "</body></html>"
            mock_get.return_value = mock_resp
            
            # Mock the RAG pipeline to prevent actual DB writes
            with patch.object(learner.rag, 'already_has', return_value=False):
                with patch.object(learner.rag, 'add', return_value=True):
                    await learner.search_and_ingest("React useEffect")
                    
                    # Check that we only fetched the allowed domain
                    called_urls = [call.args[0] for call in mock_get.call_args_list]
                    assert "https://react.dev/reference/react/useEffect" in called_urls
                    assert "https://some-random-blog.com/react-tutorial" not in called_urls

@pytest.mark.asyncio
async def test_deduplication(learner):
    # Set up learner to always hit an allowed URL
    urls = ["https://docs.python.org/3/library/asyncio.html"]
    
    with patch.object(learner, '_search_duckduckgo', new_callable=AsyncMock) as mock_search:
        mock_search.return_value = urls
        
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><body>Same exact content. " * 20 + "</body></html>"
            mock_get.return_value = mock_resp
            
            # First, mock already_has to False
            with patch.object(learner.rag, 'already_has', return_value=False):
                with patch.object(learner.rag, 'add', return_value=True) as mock_add:
                    await learner.search_and_ingest("asyncio")
                    assert mock_add.called
                    
            # Next, mock already_has to True
            with patch.object(learner.rag, 'already_has', return_value=True):
                with patch.object(learner.rag, 'add', return_value=True) as mock_add:
                    await learner.search_and_ingest("asyncio")
                    # Should NOT call add if already_has is True
                    assert not mock_add.called
