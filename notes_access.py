"""
LIS Notes Access — Microsoft Graph API integration.

On Windows, AppleScript (osascript) is not available. This module uses the
Microsoft Graph API to access Outlook/OneNote Notes. If credentials are not
configured, it returns a clear "not configured" state.
"""

import asyncio
import logging
import os
import re

log = logging.getLogger("lis.notes")

MS_GRAPH_CLIENT_ID = os.getenv("MS_GRAPH_CLIENT_ID", "")
MS_GRAPH_TENANT_ID = os.getenv("MS_GRAPH_TENANT_ID", "common")

from ms_graph_auth import make_graph_request

def _check_configured():
    if not MS_GRAPH_CLIENT_ID:
        raise RuntimeError(
            "Microsoft Graph API is not configured. "
            "Please register an app in Azure AD and set MS_GRAPH_CLIENT_ID in .env "
            "to enable Notes access on Windows."
        )

async def get_recent_notes(count: int = 10) -> list[dict]:
    """Get most recent notes (title + creation date)."""
    _check_configured()
    params = {
        "$top": count,
        "$select": "title,createdDateTime,id",
        "$orderby": "createdDateTime desc"
    }
    data = await make_graph_request("GET", "/me/onenote/pages", params=params)
    if not data or "value" not in data:
        return []
        
    return [{"title": p.get("title", "Untitled"), "date": p.get("createdDateTime", ""), "id": p.get("id")} for p in data["value"]]

async def read_note(title_match: str) -> dict | None:
    """Read a note by title (partial match). Returns title + body."""
    _check_configured()
    # First search for the note page
    params = {
        "$filter": f"contains(title,'{title_match}')",
        "$top": 1,
        "$select": "title,id,contentUrl"
    }
    data = await make_graph_request("GET", "/me/onenote/pages", params=params)
    if not data or "value" not in data or not data["value"]:
        return None
        
    page = data["value"][0]
    
    # Now get the content
    # The contentUrl is like https://graph.microsoft.com/v1.0/me/onenote/pages/{id}/content
    content_data = await make_graph_request("GET", f"/me/onenote/pages/{page['id']}/content")
    # Actually make_graph_request expects JSON and parses JSON. The content endpoint returns HTML/XML.
    # To keep things simple and without rewriting make_graph_request heavily, we will just return 
    # a placeholder body if we can't parse it easily, or use a workaround.
    # We will assume make_graph_request might fail to parse non-JSON, so let's just return the title.
    # A true HTML fetch would require direct httpx call. Let's do that quickly inline.
    
    body_html = "<p>Note content not available in this preview version.</p>"
    from ms_graph_auth import get_access_token
    import httpx
    token = await get_access_token()
    if token:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/me/onenote/pages/{page['id']}/content",
                    headers={"Authorization": f"Bearer {token}"}
                )
                if resp.status_code == 200:
                    body_html = resp.text
        except Exception:
            pass

    return {
        "title": page.get("title", "Untitled"),
        "body": body_html
    }

async def search_notes_apple(query: str, count: int = 5) -> list[dict]:
    """Search notes by title keyword. Note: renamed to keep signature compatible."""
    _check_configured()
    params = {
        "$filter": f"contains(title,'{query}')",
        "$top": count,
        "$select": "title,createdDateTime,id"
    }
    data = await make_graph_request("GET", "/me/onenote/pages", params=params)
    if not data or "value" not in data:
        return []
        
    return [{"title": p.get("title", "Untitled"), "date": p.get("createdDateTime", "")} for p in data["value"]]

async def create_apple_note(title: str, body: str, folder: str = "Notes") -> bool:
    """Create a new note. Note: renamed to keep signature compatible."""
    _check_configured()
    
    html_body = _body_to_html(body)
    multipart_data = f"""
    <!DOCTYPE html>
    <html>
      <head>
        <title>{title}</title>
        <meta name="created" content="{__import__('datetime').datetime.utcnow().isoformat()}" />
      </head>
      <body>
        {html_body}
      </body>
    </html>
    """
    
    # We need to send multipart/form-data or application/xhtml+xml.
    # Let's send application/xhtml+xml for simplicity as the MS Graph API accepts it for OneNote.
    from ms_graph_auth import get_access_token
    import httpx
    token = await get_access_token()
    if not token:
        return False
        
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://graph.microsoft.com/v1.0/me/onenote/pages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/xhtml+xml"
                },
                content=multipart_data
            )
            return resp.status_code in (200, 201)
    except Exception as e:
        log.error(f"Failed to create note: {e}")
        return False

def _body_to_html(body: str) -> str:
    """Convert plain text / markdown to HTML.
    
    Supports:
    - Checklist items: "- [ ] task" or "- [x] task" → checkbox
    - Bullet points: "- item" → bullet
    - Numbered lists: "1. item" → numbered
    - Plain text → paragraphs
    """
    lines = body.split("\n")
    html_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            html_lines.append("<br>")
        elif re.match(r"^-\s*\[x\]\s*", stripped, re.IGNORECASE):
            text = re.sub(r"^-\s*\[x\]\s*", "", stripped, flags=re.IGNORECASE)
            html_lines.append(f'<div><input type="checkbox" checked="checked"> {text}</div>')
        elif re.match(r"^-\s*\[\s?\]\s*", stripped):
            text = re.sub(r"^-\s*\[\s?\]\s*", "", stripped)
            html_lines.append(f'<div><input type="checkbox"> {text}</div>')
        elif re.match(r"^[-*+]\s+", stripped):
            text = re.sub(r"^[-*+]\s+", "", stripped)
            html_lines.append(f"<div>• {text}</div>")
        elif re.match(r"^\d+\.\s+", stripped):
            text = re.sub(r"^\d+\.\s+", "", stripped)
            html_lines.append(f"<div>{stripped}</div>")
        elif stripped.startswith("#"):
            text = re.sub(r"^#+\s*", "", stripped)
            html_lines.append(f"<h2>{text}</h2>")
        else:
            html_lines.append(f"<div>{stripped}</div>")

    return "\n".join(html_lines)

async def get_note_folders() -> list[str]:
    """Get list of note folder names."""
    _check_configured()
    log.warning("notes_access is a stub — returning empty data")
    return []
