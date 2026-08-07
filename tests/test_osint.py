import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import os
import json

# Import the modules we need to test
import osint_store
from plugins.core.osint import (
    DomainReconSkill, 
    UsernameSearchSkill, 
    BreachCheckSkill,
    ArchiveLookupSkill,
    MetadataExtractSkill
)
from plugins.core.web import (
    AutoSearchSkill,
    DeepResearchSkill
)

# 1. Test osint_store secret redaction
def test_osint_store_redaction():
    # Fake API keys and passwords
    raw_data = {
        "status": "success",
        "aws_key": "AKIAIOSFODNN7EXAMPLE",
        "nested": {
            "bearer": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwi"
        },
        "log": "login attempt with password=super_secret_123!"
    }
    
    redacted_json = osint_store._redact_secrets(raw_data)
    
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted_json
    assert "eyJhbGciOiJIUz" not in redacted_json
    assert "super_secret_123!" not in redacted_json
    assert "[REDACTED]" in redacted_json

# 2. Test domain_recon calls log_evidence
@pytest.mark.asyncio
@patch('osint_store.log_evidence')
@patch('httpx.AsyncClient.get', new_callable=AsyncMock)
@patch('asyncio.to_thread', new_callable=AsyncMock)
async def test_domain_recon_happy_path(mock_to_thread, mock_get, mock_log_evidence):
    # Setup mocks
    def to_thread_side_effect(func, *args, **kwargs):
        if getattr(func, '__name__', '') == 'whois':
            return MagicMock(registrar="TestRegistrar", creation_date="2020-01-01", name_servers=["ns1.test.com"])
        elif getattr(func, '__name__', '') == 'resolve':
            return ["127.0.0.1"]
        return MagicMock()
        
    mock_to_thread.side_effect = to_thread_side_effect
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [{"name_value": "www.test.com\nmail.test.com"}]
    mock_get.return_value = mock_resp
    
    skill = DomainReconSkill()
    res = await skill.execute("test.com")
    
    assert res.success is True
    assert "Completed domain recon" in res.confirmation
    
    # Verify asyncio.to_thread was called for blocking ops
    assert mock_to_thread.call_count >= 2
    
    # Verify evidence was logged
    mock_log_evidence.assert_called_once()
    args, kwargs = mock_log_evidence.call_args
    assert args[0] == "domain_recon"
    assert args[1] == "test.com"
    # Ensure our mocked subdomains are in the logged data separately
    assert "www.test.com" in args[3]["subdomains"]
    assert "mail.test.com" in args[3]["subdomains"]

@pytest.mark.asyncio
@patch('httpx.AsyncClient.get', new_callable=AsyncMock)
async def test_archive_lookup_error(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_get.return_value = mock_resp
    
    skill = ArchiveLookupSkill()
    res = await skill.execute("test.com")
    
    assert res.success is False
    assert "status 500" in res.confirmation
    assert res is not None

@pytest.mark.asyncio
@patch('osint_store.log_evidence')
@patch('os.path.exists')
@patch('asyncio.to_thread', new_callable=AsyncMock)
async def test_metadata_extract_to_thread(mock_to_thread, mock_exists, mock_log):
    mock_exists.return_value = True
    # subprocess.run returns a CompletedProcess, not raw bytes
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b'[{"FileName": "test.jpg", "FileSize": "1024"}]'
    mock_result.stderr = b''
    mock_to_thread.return_value = mock_result
    
    skill = MetadataExtractSkill()
    res = await skill.execute("test.jpg")
    
    assert res.success is True
    mock_to_thread.assert_called_once()

# 3. Test username_search graceful denial when purpose is empty
@pytest.mark.asyncio
@patch('httpx.AsyncClient.head', new_callable=AsyncMock)
async def test_username_search_no_purpose(mock_head):
    skill = UsernameSearchSkill()
    
    # Missing purpose
    res = await skill.execute("testuser")
    assert res.success is False
    assert "Missing purpose" in res.confirmation
    mock_head.assert_not_called()
    
    # Empty purpose
    res = await skill.execute("testuser", purpose="   ")
    assert res.success is False
    assert "Missing purpose" in res.confirmation
    mock_head.assert_not_called()

# 4. Test breach_check graceful skip when HIBP_API_KEY is missing
@pytest.mark.asyncio
@patch.dict(os.environ, clear=True) # Ensure HIBP_API_KEY is unset
@patch('httpx.AsyncClient.get', new_callable=AsyncMock)
async def test_breach_check_no_key(mock_get):
    skill = BreachCheckSkill()
    res = await skill.execute("test@example.com")
    
    assert res.success is False
    assert "Breach checking isn't configured" in res.confirmation
    mock_get.assert_not_called()

# 5. Test auto_search fallback when PERPLEXITY_API_KEY is unset
@pytest.mark.asyncio
@patch.dict(os.environ, {}, clear=True) # Ensure PERPLEXITY_API_KEY is unset
@patch('httpx.AsyncClient.post', new_callable=AsyncMock)
@patch('httpx.AsyncClient.get', new_callable=AsyncMock)
async def test_auto_search_fallback_to_ddg(mock_get, mock_post):
    # Mock DDG returning a snippet
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '<html><body><a class="result__snippet">DDG fallback result</a></body></html>'
    mock_post.return_value = mock_resp
    
    skill = AutoSearchSkill()
    res = await skill.execute("What is OSINT?")
    
    assert res.success is True
    assert "DDG fallback result" in res.data
    # Perplexity API should NOT have been called (which happens in post to api.perplexity.ai)
    # The post that IS called should be duckduckgo
    called_url = mock_post.call_args[0][0]
    assert "duckduckgo.com" in called_url

# 6. Test deep_research graceful failure when PERPLEXITY_API_KEY is unset
@pytest.mark.asyncio
@patch.dict(os.environ, clear=True)
@patch('httpx.AsyncClient.post', new_callable=AsyncMock)
async def test_deep_research_no_key(mock_post):
    skill = DeepResearchSkill()
    res = await skill.execute("Complex OSINT topic")
    
    assert res.success is False
    assert "Deep research isn't configured" in res.confirmation
    mock_post.assert_not_called()
