"""
LIS Calendar Access — Free Google Calendar iCal + Microsoft Graph fallback.

Primary: Google Calendar iCal URL (free, no API key needed)
Fallback: Microsoft Graph API (if configured)
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger("lis.calendar")

# Free Google Calendar iCal URL
GOOGLE_CALENDAR_ICAL_URL = os.getenv("GOOGLE_CALENDAR_ICAL_URL", "")

# Optional MS Graph config
MS_GRAPH_CLIENT_ID = os.getenv("MS_GRAPH_CLIENT_ID", "")

_USE_GOOGLE = bool(GOOGLE_CALENDAR_ICAL_URL)
_USE_GRAPH = bool(MS_GRAPH_CLIENT_ID) and not _USE_GOOGLE

if _USE_GRAPH:
    from ms_graph_auth import make_graph_request

# IST timezone offset
IST = timezone(timedelta(hours=5, minutes=30))

def _check_configured():
    if not _USE_GOOGLE and not _USE_GRAPH:
        raise RuntimeError(
            "Calendar is not configured. Add GOOGLE_CALENDAR_ICAL_URL to .env "
            "for free Google Calendar access (Settings > Integrate > Secret iCal URL). "
            "Or set MS_GRAPH_CLIENT_ID for Outlook Calendar."
        )


# ═══════════════════════════════════════════════════════════════════
# Google Calendar iCal Parser (Free)
# ═══════════════════════════════════════════════════════════════════

def _parse_ical_events(ical_text: str, day_filter: datetime = None, hours_ahead: int = None) -> list[dict]:
    """Parse iCal text and extract events. Filters by day or hours_ahead."""
    events = []
    now = datetime.now(IST)

    if day_filter:
        filter_start = day_filter.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=IST)
        filter_end = day_filter.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=IST)
    elif hours_ahead:
        filter_start = now
        filter_end = now + timedelta(hours=hours_ahead)
    else:
        filter_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        filter_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Simple iCal parser (handles VEVENT blocks)
    in_event = False
    current = {}

    for line in ical_text.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            current = {}
        elif line == "END:VEVENT":
            in_event = False
            event = _process_ical_event(current, filter_start, filter_end)
            if event:
                events.append(event)
        elif in_event and ":" in line:
            # Handle property;params:value format
            key_part, _, value = line.partition(":")
            key = key_part.split(";")[0]  # Strip params like DTSTART;TZID=...
            current[key] = value

    # Sort by start time
    events.sort(key=lambda e: e.get("_sort_key", ""))
    return events

def _process_ical_event(props: dict, filter_start: datetime, filter_end: datetime) -> dict | None:
    """Process a single iCal event and check if it falls in the filter range."""
    summary = props.get("SUMMARY", "No Title")
    dtstart_str = props.get("DTSTART", "")
    dtend_str = props.get("DTEND", "")

    is_all_day = False

    try:
        if len(dtstart_str) == 8:  # All-day event: 20231027
            is_all_day = True
            dt_start = datetime.strptime(dtstart_str, "%Y%m%d").replace(tzinfo=IST)
        elif "T" in dtstart_str:
            # Remove trailing Z and parse
            clean = dtstart_str.replace("Z", "")
            dt_start = datetime.strptime(clean, "%Y%m%dT%H%M%S")
            if dtstart_str.endswith("Z"):
                dt_start = dt_start.replace(tzinfo=timezone.utc).astimezone(IST)
            else:
                dt_start = dt_start.replace(tzinfo=IST)
        else:
            return None
    except Exception:
        return None

    # Check if event falls within filter range
    if dt_start.date() < filter_start.date() or dt_start.date() > filter_end.date():
        # For non-all-day events, also check time
        if not is_all_day and (dt_start < filter_start or dt_start > filter_end):
            return None

    start_str = dt_start.strftime("%I:%M %p").lstrip("0") if not is_all_day else "All Day"

    return {
        "title": summary,
        "start": start_str,
        "all_day": is_all_day,
        "calendar": "",
        "_sort_key": dt_start.isoformat()
    }

async def _fetch_google_ical() -> str:
    """Fetch iCal data from Google Calendar."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(GOOGLE_CALENDAR_ICAL_URL)
            if resp.status_code == 200:
                return resp.text
            log.error(f"Google Calendar iCal fetch failed: HTTP {resp.status_code}")
            return ""
    except Exception as e:
        log.error(f"Google Calendar fetch error: {e}")
        return ""


# ═══════════════════════════════════════════════════════════════════
# Public API (auto-selects Google iCal or MS Graph)
# ═══════════════════════════════════════════════════════════════════

async def refresh_cache():
    """Refresh the event cache. Called from background loop."""
    pass  # Both iCal and Graph are fetched on-demand

async def get_todays_events() -> list[dict]:
    """Get today's events."""
    _check_configured()

    if _USE_GOOGLE:
        ical_text = await _fetch_google_ical()
        return _parse_ical_events(ical_text, day_filter=datetime.now(IST))

    # MS Graph fallback
    now = datetime.utcnow()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat() + "Z"
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat() + "Z"
    params = {
        "startDateTime": start_of_day,
        "endDateTime": end_of_day,
        "$select": "subject,start,end,isAllDay",
        "$orderby": "start/dateTime"
    }
    headers = {"Prefer": 'outlook.timezone="Asia/Kolkata"'}
    data = await make_graph_request("GET", "/me/calendarview", params=params, headers=headers)
    if not data or "value" not in data:
        return []
    return _parse_graph_events(data["value"])

async def get_upcoming_events(hours: int = 4) -> list[dict]:
    """Get events in the next N hours."""
    _check_configured()

    if _USE_GOOGLE:
        ical_text = await _fetch_google_ical()
        return _parse_ical_events(ical_text, hours_ahead=hours)

    # MS Graph fallback
    now = datetime.utcnow()
    end_time = (now + timedelta(hours=hours)).isoformat() + "Z"
    params = {
        "startDateTime": now.isoformat() + "Z",
        "endDateTime": end_time,
        "$select": "subject,start,end,isAllDay",
        "$orderby": "start/dateTime"
    }
    headers = {"Prefer": 'outlook.timezone="Asia/Kolkata"'}
    data = await make_graph_request("GET", "/me/calendarview", params=params, headers=headers)
    if not data or "value" not in data:
        return []
    return _parse_graph_events(data["value"])

async def get_next_event() -> dict | None:
    events = await get_upcoming_events(hours=24)
    return events[0] if events else None

async def get_calendar_names() -> list[str]:
    if _USE_GOOGLE:
        return ["Google Calendar"]
    _check_configured()
    data = await make_graph_request("GET", "/me/calendars", params={"$select": "name"})
    if not data or "value" not in data:
        return []
    return [c.get("name", "Unknown") for c in data["value"]]

def _parse_graph_events(graph_events: list) -> list[dict]:
    events = []
    for item in graph_events:
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
            "calendar": ""
        })
    return events


# ═══════════════════════════════════════════════════════════════════
# Formatting (unchanged)
# ═══════════════════════════════════════════════════════════════════

def format_events_for_context(events: list[dict]) -> str:
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
