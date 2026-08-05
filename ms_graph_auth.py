import os
import logging
import asyncio
import httpx
from pathlib import Path

try:
    import msal
except ImportError:
    msal = None

log = logging.getLogger("lis.graph_auth")

MS_GRAPH_CLIENT_ID = os.getenv("MS_GRAPH_CLIENT_ID", "")
MS_GRAPH_TENANT_ID = os.getenv("MS_GRAPH_TENANT_ID", "common")

# Default permissions needed for Calendar, Mail, and Notes
SCOPES = ["Mail.Read", "Calendars.Read", "Notes.Read.All", "User.Read"]

AUTHORITY = f"https://login.microsoftonline.com/{MS_GRAPH_TENANT_ID}"
CACHE_FILE = Path(__file__).parent / "data" / "ms_graph_token_cache.bin"

_token_cache = None
_msal_app = None

def _get_token_cache():
    global _token_cache
    if _token_cache is None:
        if not msal:
            raise ImportError("msal library is not installed. Please install it to use Microsoft Graph API.")
        _token_cache = msal.SerializableTokenCache()
        if CACHE_FILE.exists():
            try:
                _token_cache.deserialize(CACHE_FILE.read_text())
            except Exception as e:
                log.warning(f"Failed to load MSAL token cache: {e}")
    return _token_cache

def _save_token_cache():
    if _token_cache and _token_cache.has_state_changed:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(_token_cache.serialize())

def _get_msal_app():
    global _msal_app
    if _msal_app is None:
        if not MS_GRAPH_CLIENT_ID:
            raise ValueError("MS_GRAPH_CLIENT_ID is not set.")
        _msal_app = msal.PublicClientApplication(
            MS_GRAPH_CLIENT_ID,
            authority=AUTHORITY,
            token_cache=_get_token_cache()
        )
    return _msal_app

async def get_access_token() -> str | None:
    """Gets a valid access token, initiating Device Code Flow if necessary."""
    if not MS_GRAPH_CLIENT_ID:
        log.error("Microsoft Graph API is not configured (MS_GRAPH_CLIENT_ID missing).")
        return None

    app = _get_msal_app()
    
    # 1. Try to get token from cache silently
    accounts = app.get_accounts()
    if accounts:
        # Assuming single user for now
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save_token_cache()
            return result["access_token"]
            
    # 2. If no token in cache, initiate Device Code Flow
    log.warning("No valid Microsoft Graph token found. Initiating Device Code Flow...")
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        log.error(f"Failed to create device flow. Err: {flow.get('error')}")
        return None
        
    print("\n" + "="*60)
    print("🚨 ACTION REQUIRED: MICROSOFT LOGIN 🚨")
    print(flow["message"])
    print("="*60 + "\n")
    
    # We run the blocking acquire_token_by_device_flow in an executor
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, app.acquire_token_by_device_flow, flow)
    
    if "access_token" in result:
        print("✅ Microsoft Graph API authenticated successfully!")
        _save_token_cache()
        return result["access_token"]
    else:
        log.error(f"Failed to authenticate: {result.get('error')} - {result.get('error_description')}")
        return None

async def make_graph_request(method: str, endpoint: str, params: dict = None, json_data: dict = None, headers: dict = None) -> dict | None:
    """Helper to make an authenticated request to MS Graph API."""
    token = await get_access_token()
    if not token:
        return None
        
    url = f"https://graph.microsoft.com/v1.0{endpoint}"
    req_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    if headers:
        req_headers.update(headers)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            request_kwargs = {"headers": req_headers}
            if params:
                request_kwargs["params"] = params
            if json_data:
                request_kwargs["json"] = json_data
                
            if method.upper() == "GET":
                resp = await client.get(url, **request_kwargs)
            elif method.upper() == "POST":
                resp = await client.post(url, **request_kwargs)
            elif method.upper() == "PATCH":
                resp = await client.patch(url, **request_kwargs)
            elif method.upper() == "DELETE":
                resp = await client.delete(url, **request_kwargs)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
            if resp.status_code in (200, 201, 202, 204):
                if resp.status_code == 204:
                    return {}
                return resp.json()
            else:
                log.error(f"MS Graph API Error ({resp.status_code}) on {endpoint}: {resp.text}")
                return None
    except Exception as e:
        log.error(f"Exception making MS Graph request to {endpoint}: {e}")
        return None
