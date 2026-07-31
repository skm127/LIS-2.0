"""
LIS Calendar Access — Microsoft Graph API integration.

On Windows, AppleScript (osascript) is not available. This module uses the
Microsoft Graph API to read Outlook Calendar events. If credentials are not
configured, it returns a clear "not configured" state.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

log = logging.getLogger("lis.calendar")

MS_GRAPH_CLIENT_ID = os.getenv("MS_GRAPH_CLIENT_ID", "")
MS_GRAPH_TENANT_ID = os.getenv("MS_GRAPH_TENANT_ID", "common")

from ms_graph_auth import make_graph_request

def _check_configured():
    if not MS_GRAPH_CLIENT_ID:
        raise RuntimeError(
            "Microsoft Graph API is not configured. "
            "Please register an app in Azure AD and set MS_GRAPH_CLIENT_ID in .env "
            "to enable Calendar access on Windows."
        )

async def refresh_cache():
    """Refresh the event cache. Called from background loop."""
    if not MS_GRAPH_CLIENT_ID:
        log.debug("Calendar refresh skipped: MS_GRAPH_CLIENT_ID not configured.")
        return
    # Token refresh happens implicitly inside make_graph_request via MSAL
    pass

async def get_todays_events() -> list[dict]:
    """Get today's events from MS Graph."""
    _check_configured()
    now = datetime.utcnow()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + "Z"
    
    params = {
        "startDateTime": start_of_day,
        "endDateTime": end_of_day,
        "$select": "subject,start,end,isAllDay",
        "$orderby": "start/dateTime"
    }
    
    data = await make_graph_request("GET", "/me/calendarview", params=params)
    if not data or "value" not in data:
        return []
        
    return _parse_graph_events(data["value"])

async def get_upcoming_events(hours: int = 4) -> list[dict]:
    """Get events in the next N hours from MS Graph."""
    _check_configured()
    now = datetime.utcnow()
    end_time = (now + timedelta(hours=hours)).isoformat() + "Z"
    
    params = {
        "startDateTime": now.isoformat() + "Z",
        "endDateTime": end_time,
        "$select": "subject,start,end,isAllDay",
        "$orderby": "start/dateTime"
    }
    
    data = await make_graph_request("GET", "/me/calendarview", params=params)
    if not data or "value" not in data:
        return []
        
    return _parse_graph_events(data["value"])

async def get_next_event() -> dict | None:
    """Get the single next upcoming event."""
    events = await get_upcoming_events(hours=24)
    return events[0] if events else None

async def get_calendar_names() -> list[str]:
    """Get list of all calendar names."""
    _check_configured()
    data = await make_graph_request("GET", "/me/calendars", params={"$select": "name"})
    if not data or "value" not in data:
        return []
    return [c.get("name", "Unknown") for c in data["value"]]

def _parse_graph_events(graph_events: list) -> list[dict]:
    """Convert MS Graph event format to internal format."""
    events = []
    for item in graph_events:
        # Example graph time: '2023-10-27T10:00:00.0000000'
        # Parse and format beautifully
        try:
            start_dt = item["start"]["dateTime"].split(".")[0]
            dt_obj = datetime.fromisoformat(start_dt)
            start_str = dt_obj.strftime("%I:%M %p").lstrip("0")
        except Exception:
            start_str = item.get("start", {}).get("dateTime", "Unknown")
            
        events.append({
            "title": item.get("subject", "No Title"),
            "start": start_str,
            "all_day": item.get("isAllDay", False),
            "calendar": "" # Not fetched in this simple view
        })
    return events

def format_events_for_context(events: list[dict]) -> str:
    """Format events as context for the LLM."""
    if not events:
        return "No events scheduled today."

    lines = []
    for evt in events:
        if evt.get("all_day"):
            entry = f"  All day — {evt['title']}"
        else:
            entry = f"  {evt['start']} — {evt['title']}"
        if evt.get("calendar"):
            entry += f" [{evt['calendar']}]"
        lines.append(entry)

    return "\n".join(lines)

def format_schedule_summary(events: list[dict]) -> str:
    """Format a brief voice-friendly summary of the schedule."""
    if not events:
        return "Your schedule is clear today, sir."

    count = len(events)
    if count == 1:
        evt = events[0]
        if evt.get("all_day"):
            return f"You have one all-day event: {evt['title']}."
        return f"You have one event: {evt['title']} at {evt['start']}."

    summaries = []
    for evt in events[:5]:
        if evt.get("all_day"):
            summaries.append(f"{evt['title']} all day")
        else:
            summaries.append(f"{evt['title']} at {evt['start']}")

    result = f"You have {count} events today. "
    result += ". ".join(summaries[:3])
    if count > 3:
        result += f". And {count - 3} more."
    return result
