"""
LIS Mail Access — Free Gmail IMAP + Microsoft Graph fallback.

Primary: Gmail IMAP (free, just needs app password)
Fallback: Microsoft Graph API (if configured)
"""

import asyncio
import imaplib
import email
from email.header import decode_header
import logging
import os
from datetime import datetime

log = logging.getLogger("lis.mail")

# Free Gmail IMAP config
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# Optional MS Graph config (fallback)
MS_GRAPH_CLIENT_ID = os.getenv("MS_GRAPH_CLIENT_ID", "")

_USE_GMAIL = bool(GMAIL_ADDRESS and GMAIL_APP_PASSWORD)
_USE_GRAPH = bool(MS_GRAPH_CLIENT_ID) and not _USE_GMAIL

if _USE_GRAPH:
    from ms_graph_auth import make_graph_request

def _check_configured():
    if not _USE_GMAIL and not _USE_GRAPH:
        raise RuntimeError(
            "Email is not configured. Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD "
            "to .env for free Gmail access. Or set MS_GRAPH_CLIENT_ID for Outlook."
        )

# ═══════════════════════════════════════════════════════════════════
# Gmail IMAP (Free)
# ═══════════════════════════════════════════════════════════════════

def _decode_mime_header(header_val: str) -> str:
    """Decode MIME encoded header (e.g., =?utf-8?B?...?=)."""
    if not header_val:
        return "Unknown"
    decoded_parts = decode_header(header_val)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)

def _gmail_fetch_messages(folder: str = "INBOX", count: int = 10, unread_only: bool = False) -> list[dict]:
    """Fetch messages from Gmail via IMAP. Runs synchronously (use in executor)."""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select(folder, readonly=True)

        if unread_only:
            status, data = mail.search(None, "UNSEEN")
        else:
            status, data = mail.search(None, "ALL")

        if status != "OK" or not data[0]:
            mail.logout()
            return []

        msg_ids = data[0].split()
        # Get most recent N messages
        msg_ids = msg_ids[-count:] if len(msg_ids) > count else msg_ids
        msg_ids.reverse()  # newest first

        messages = []
        for msg_id in msg_ids:
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = _decode_mime_header(msg.get("Subject", "No Subject"))
            sender = _decode_mime_header(msg.get("From", "Unknown"))
            date_str = msg.get("Date", "")

            # Parse date
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_str)
                date_str = dt.strftime("%Y-%m-%d %I:%M %p")
            except Exception:
                pass

            # Check if read (IMAP flags)
            status2, flags_data = mail.fetch(msg_id, "(FLAGS)")
            is_read = b"\\Seen" in flags_data[0][1] if flags_data else True

            messages.append({
                "subject": subject,
                "sender": _short_sender(sender),
                "date": date_str,
                "read": is_read,
            })

        mail.logout()
        return messages
    except Exception as e:
        log.error(f"Gmail IMAP error: {e}")
        return []

def _gmail_unread_count() -> int:
    """Get unread count from Gmail."""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("INBOX", readonly=True)
        status, data = mail.search(None, "UNSEEN")
        mail.logout()
        if status == "OK" and data[0]:
            return len(data[0].split())
        return 0
    except Exception as e:
        log.error(f"Gmail unread count error: {e}")
        return 0

def _gmail_search(query: str, count: int = 10) -> list[dict]:
    """Search Gmail by subject/sender."""
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("INBOX", readonly=True)
        # IMAP search by subject or from
        status, data = mail.search(None, f'(OR SUBJECT "{query}" FROM "{query}")')
        if status != "OK" or not data[0]:
            mail.logout()
            return []

        msg_ids = data[0].split()[-count:]
        msg_ids.reverse()

        messages = []
        for msg_id in msg_ids:
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = _decode_mime_header(msg.get("Subject", "No Subject"))
            sender = _decode_mime_header(msg.get("From", "Unknown"))
            messages.append({
                "subject": subject,
                "sender": _short_sender(sender),
                "date": msg.get("Date", ""),
                "read": True,
            })

        mail.logout()
        return messages
    except Exception as e:
        log.error(f"Gmail search error: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════
# Public API (auto-selects Gmail or MS Graph)
# ═══════════════════════════════════════════════════════════════════

async def get_accounts() -> list[str]:
    _check_configured()
    if _USE_GMAIL:
        return ["Gmail"]
    data = await make_graph_request("GET", "/me/mailFolders/inbox")
    return ["Outlook"]

async def get_unread_count() -> dict:
    _check_configured()
    if _USE_GMAIL:
        count = await asyncio.to_thread(_gmail_unread_count)
        return {"total": count, "accounts": {"Gmail": count}}
    data = await make_graph_request("GET", "/me/mailFolders/inbox")
    if not data:
        return {"total": 0, "accounts": {}}
    count = data.get("unreadItemCount", 0)
    return {"total": count, "accounts": {"Outlook": count}}

async def get_recent_messages(count: int = 10) -> list[dict]:
    _check_configured()
    if _USE_GMAIL:
        return await asyncio.to_thread(_gmail_fetch_messages, "INBOX", count, False)
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
    _check_configured()
    if _USE_GMAIL:
        return await asyncio.to_thread(_gmail_fetch_messages, "INBOX", count, True)
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
    return await get_recent_messages(count)

async def search_mail(query: str, count: int = 10) -> list[dict]:
    _check_configured()
    if _USE_GMAIL:
        return await asyncio.to_thread(_gmail_search, query, count)
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
    _check_configured()
    if _USE_GMAIL:
        # For Gmail, search and return first match with body
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            mail.select("INBOX", readonly=True)
            status, data = mail.search(None, f'SUBJECT "{subject_match}"')
            if status != "OK" or not data[0]:
                mail.logout()
                return None
            msg_id = data[0].split()[-1]  # latest match
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            mail.logout()
            if status != "OK":
                return None
            msg = email.message_from_bytes(msg_data[0][1])
            # Extract text body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors="replace")
            return {
                "subject": _decode_mime_header(msg.get("Subject", "No Subject")),
                "sender": _short_sender(_decode_mime_header(msg.get("From", "Unknown"))),
                "date": msg.get("Date", ""),
                "read": True,
                "body": body[:2000]
            }
        except Exception as e:
            log.error(f"Gmail read_message error: {e}")
            return None
    # MS Graph fallback
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

# ═══════════════════════════════════════════════════════════════════
# Formatting (unchanged)
# ═══════════════════════════════════════════════════════════════════

def format_unread_summary(unread: dict) -> str:
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
    if "<" in sender:
        return sender.split("<")[0].strip().strip('"')
    if "@" in sender:
        return sender.split("@")[0]
    return sender
