"""
LIS Mail Access — Microsoft Graph API integration.

On Windows, AppleScript (osascript) is not available. This module uses the
Microsoft Graph API to read Outlook Mail. If credentials are not
configured, it returns a clear "not configured" state.
"""

import asyncio
import logging
import os
from datetime import datetime

log = logging.getLogger("lis.mail")

MS_GRAPH_CLIENT_ID = os.getenv("MS_GRAPH_CLIENT_ID", "")
MS_GRAPH_TENANT_ID = os.getenv("MS_GRAPH_TENANT_ID", "common")

from ms_graph_auth import make_graph_request

def _check_configured():
    if not MS_GRAPH_CLIENT_ID:
        raise RuntimeError(
            "Microsoft Graph API is not configured. "
            "Please register an app in Azure AD and set MS_GRAPH_CLIENT_ID in .env "
            "to enable Mail access on Windows."
        )

async def get_accounts() -> list[str]:
    """Get list of configured mail account names."""
    _check_configured()
    # MS Graph typically operates on the main account, returning a placeholder
    return ["Outlook"]

async def get_unread_count() -> dict:
    """Get unread message count per account and total."""
    _check_configured()
    data = await make_graph_request("GET", "/me/mailFolders/inbox")
    if not data:
        return {"total": 0, "accounts": {}}
    
    count = data.get("unreadItemCount", 0)
    return {"total": count, "accounts": {"Outlook": count}}

async def get_recent_messages(count: int = 10) -> list[dict]:
    """Get most recent messages from unified inbox."""
    _check_configured()
    params = {
        "$top": count,
        "$select": "subject,sender,isRead,receivedDateTime",
        "$orderby": "receivedDateTime desc"
    }
    data = await make_graph_request("GET", "/me/messages", params=params)
    if not data or "value" not in data:
        return []
        
    return _parse_graph_messages(data["value"])

async def get_unread_messages(count: int = 10) -> list[dict]:
    """Get unread messages from unified inbox."""
    _check_configured()
    params = {
        "$top": count,
        "$filter": "isRead eq false",
        "$select": "subject,sender,isRead,receivedDateTime",
        "$orderby": "receivedDateTime desc"
    }
    data = await make_graph_request("GET", "/me/messages", params=params)
    if not data or "value" not in data:
        return []
        
    return _parse_graph_messages(data["value"])

async def get_messages_from_account(account_name: str, count: int = 10) -> list[dict]:
    """Get recent messages from a specific account's inbox."""
    # Since we only have one main account authenticated, just return recent messages
    return await get_recent_messages(count)

async def search_mail(query: str, count: int = 10) -> list[dict]:
    """Search mail by subject or sender keyword."""
    _check_configured()
    params = {
        "$top": count,
        "$search": f'"{query}"',
        "$select": "subject,sender,isRead,receivedDateTime",
        "$orderby": "receivedDateTime desc"
    }
    data = await make_graph_request("GET", "/me/messages", params=params)
    if not data or "value" not in data:
        return []
        
    return _parse_graph_messages(data["value"])

async def read_message(subject_match: str) -> dict | None:
    """Read the full content of a message matching the subject."""
    _check_configured()
    params = {
        "$top": 1,
        "$search": f'"subject:{subject_match}"',
        "$select": "subject,sender,isRead,receivedDateTime,body"
    }
    data = await make_graph_request("GET", "/me/messages", params=params)
    if not data or "value" not in data or not data["value"]:
        return None
        
    msg = data["value"][0]
    return {
        "subject": msg.get("subject", "No Subject"),
        "sender": msg.get("sender", {}).get("emailAddress", {}).get("name", "Unknown"),
        "date": msg.get("receivedDateTime", ""),
        "read": msg.get("isRead", True),
        "body": msg.get("body", {}).get("content", "")
    }

def _parse_graph_messages(graph_messages: list) -> list[dict]:
    """Convert MS Graph message format to internal format."""
    messages = []
    for m in graph_messages:
        messages.append({
            "subject": m.get("subject", "No Subject"),
            "sender": m.get("sender", {}).get("emailAddress", {}).get("name", "Unknown"),
            "date": m.get("receivedDateTime", ""),
            "read": m.get("isRead", True)
        })
    return messages

def format_unread_summary(unread: dict) -> str:
    """Format unread counts for voice."""
    total = unread.get("total", 0)
    if total == 0:
        return "Inbox is clear, sir. No unread messages."

    parts = []
    for acct, count in unread.get("accounts", {}).items():
        if count > 0:
            parts.append(f"{count} in {acct}")

    if len(parts) == 1:
        return f"You have {total} unread {'message' if total == 1 else 'messages'} — {parts[0]}."
    elif parts:
        return f"You have {total} unread messages: {', '.join(parts)}."
    else:
        return f"You have {total} unread {'message' if total == 1 else 'messages'}."

def format_messages_for_context(messages: list[dict], label: str = "Recent emails") -> str:
    """Format messages as context for the LLM."""
    if not messages:
        return f"{label}: None."

    lines = [f"{label}:"]
    for m in messages[:10]:
        read_marker = "" if m.get("read") else " [UNREAD]"
        line = f"  - {m.get('sender', 'Unknown')}: {m.get('subject', 'No Subject')}{read_marker}"
        if m.get("date"):
            date_str = m["date"]
            if " at " in date_str:
                date_str = date_str.split(" at ")[0].split(", ", 1)[-1] if ", " in date_str else date_str
            line += f" ({date_str})"
        lines.append(line)
    return "\n".join(lines)

def format_messages_for_voice(messages: list[dict]) -> str:
    """Format messages for voice response."""
    if not messages:
        return "No messages to report, sir."

    count = len(messages)
    if count == 1:
        m = messages[0]
        sender = _short_sender(m.get("sender", "Unknown"))
        return f"One message from {sender}: {m.get('subject', 'No Subject')}."

    summaries = []
    for m in messages[:5]:
        sender = _short_sender(m.get("sender", "Unknown"))
        summaries.append(f"{sender} regarding {m.get('subject', 'No Subject')}")

    result = f"You have {count} messages. "
    result += ". ".join(summaries[:3])
    if count > 3:
        result += f". And {count - 3} more."
    return result

def _short_sender(sender: str) -> str:
    """Extract just the name from an email sender string."""
    if "<" in sender:
        return sender.split("<")[0].strip().strip('"')
    if "@" in sender:
        return sender.split("@")[0]
    return sender
