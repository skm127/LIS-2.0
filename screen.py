"""
LIS Screen Awareness — see what's on the user's screen.

Two capabilities:
1. Window/app list via PowerShell (fast, text-based)
2. Screenshot via pyautogui → Gemini Vision API (sees everything)
"""

import asyncio
import base64
import io
import json
import logging
from pathlib import Path

log = logging.getLogger("lis.screen")


try:
    import pyautogui
except ImportError:
    pyautogui = None
    log.warning("pyautogui not installed — screenshot disabled")


async def get_active_windows() -> list[dict]:
    """Get list of visible windows on Windows.
    
    Uses PowerShell to list processes with main window titles.
    Returns list of {"app": str, "title": str, "frontmost": bool}.
    """
    script = "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object -Property ProcessName, MainWindowTitle | ConvertTo-Json"
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-Command", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)

        if proc.returncode != 0:
            log.warning(f"get_active_windows failed: {stderr.decode()[:200]}")
            return []

        raw = stdout.decode().strip()
        if not raw:
            return []

        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]

        windows = []
        for item in data:
            windows.append({
                "app": item.get("ProcessName", "Unknown"),
                "title": item.get("MainWindowTitle", ""),
                "frontmost": False,
            })
        return windows

    except Exception as e:
        log.warning(f"get_active_windows error: {e}")
        return []


async def get_running_apps() -> list[str]:
    """Get list of running application names on Windows."""
    script = "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object -ExpandProperty ProcessName"
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-Command", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0:
            return list(set(stdout.decode().strip().split("\r\n")))
        return []
    except Exception as e:
        log.warning(f"get_running_apps error: {e}")
        return []


async def take_screenshot(display_only: bool = True) -> str | None:
    """Take a screenshot on Windows using PyAutoGUI."""
    if not pyautogui:
        return None
    try:
        img = await asyncio.to_thread(pyautogui.screenshot)
        
        # Resize for efficiency
        width, height = img.size
        if width > 1280:
            ratio = 1280 / width
            img = img.resize((1280, int(height * ratio)))
        
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode()

    except Exception as e:
        log.warning(f"Screenshot error: {e}")
        return None


async def describe_screen(anthropic_client=None) -> str:
    """Describe what's on the user's screen using Gemini Vision (free)."""
    screenshot_b64 = await take_screenshot()
    
    if screenshot_b64:
        # Try Gemini Vision first (free, always available)
        try:
            from vision import analyze_with_gemini
            png_bytes = base64.b64decode(screenshot_b64)
            description = await analyze_with_gemini(png_bytes)
            if description and "error" not in description.lower()[:20]:
                return description
        except ImportError:
            log.warning("vision.py not available for screen analysis")
        except Exception as e:
            log.warning(f"Gemini vision failed: {e}")
        
        # Fallback: try Anthropic if available
        if anthropic_client:
            try:
                response = await anthropic_client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=300,
                    system=(
                        "You are LIS analyzing a screenshot of the user's desktop. "
                        "Describe what you see concisely: which apps are open, what the user "
                        "appears to be working on, any notable content visible. "
                        "2-4 sentences max. No markdown."
                    ),
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": screenshot_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": "What's on my screen right now?",
                            },
                        ],
                    }],
                )
                return response.content[0].text
            except Exception as e:
                log.warning(f"Anthropic vision fallback failed: {e}")

    # Final fallback to window list
    windows = await get_active_windows()
    if windows:
        titles = [f"{w['app']}: {w['title']}" for w in windows if w['title']]
        return "I can see these windows: " + ", ".join(titles[:5]) + "."
    
    return "I wasn't able to see your screen, sir."


def format_windows_for_context(windows: list[dict]) -> str:
    """Format window list context for the LLM."""
    if not windows:
        return ""
    lines = ["Currently open windows:"]
    for w in windows:
        if w['title']:
            lines.append(f"  - {w['app']}: {w['title']}")
    return "\n".join(lines)
