"""
LIS Vision — Screen capture and AI-powered understanding.

Captures screenshots using pyautogui and sends them to a vision-capable
LLM (Gemini) for analysis. Enables LIS to literally see what's on screen.

Usage:
    from vision import capture_and_analyze
    result = await capture_and_analyze()
    # result = {"description": "User has VS Code open with Python file...", "apps_visible": [...]}
"""

import asyncio
import base64
import io
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("lis.vision")

SCREENSHOT_DIR = Path(__file__).parent / "data" / "screenshots"


async def capture_screenshot() -> bytes | None:
    """Capture the current screen as PNG bytes."""
    try:
        import pyautogui
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        
        screenshot = await asyncio.to_thread(pyautogui.screenshot)
        
        # Resize for efficiency (max 1280px wide)
        width, height = screenshot.size
        if width > 1280:
            ratio = 1280 / width
            new_size = (1280, int(height * ratio))
            screenshot = screenshot.resize(new_size)
        
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG", optimize=True)
        png_bytes = buf.getvalue()
        
        # Save latest screenshot for debugging
        latest = SCREENSHOT_DIR / "latest.png"
        latest.write_bytes(png_bytes)
        
        log.info(f"Screenshot captured: {len(png_bytes)} bytes, {screenshot.size}")
        return png_bytes
    except ImportError:
        log.warning("pyautogui not installed. Run: pip install pyautogui")
        return None
    except Exception as e:
        log.error(f"Screenshot failed: {e}")
        return None


async def analyze_with_gemini(image_bytes: bytes, question: str = "") -> str:
    """Send screenshot to Gemini Vision for analysis."""
    import httpx
    
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return "Gemini API key not configured. Cannot analyze screenshot."
    
    b64_image = base64.b64encode(image_bytes).decode()
    
    prompt = question or (
        "Describe what's on this computer screen. Include:\n"
        "1. What application(s) are visible\n"
        "2. What the user appears to be working on\n"
        "3. Any notable text, errors, or content visible\n"
        "Keep it concise (2-3 sentences max)."
    )
    
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": b64_image
                    }
                }
            ]
        }],
        "generationConfig": {
            "maxOutputTokens": 300,
            "temperature": 0.3
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                log.info(f"Vision analysis: {text[:80]}...")
                return text.strip()
            else:
                log.warning(f"Gemini vision failed: {resp.status_code} {resp.text[:200]}")
                return f"Vision analysis failed (HTTP {resp.status_code})"
    except Exception as e:
        log.error(f"Gemini vision error: {e}")
        return f"Vision analysis error: {str(e)[:100]}"


async def capture_and_analyze(question: str = "") -> dict:
    """Full pipeline: capture screenshot → analyze with vision LLM."""
    image_bytes = await capture_screenshot()
    if not image_bytes:
        return {
            "success": False,
            "description": "Could not capture screenshot.",
            "apps_visible": []
        }
    
    description = await analyze_with_gemini(image_bytes, question)
    
    return {
        "success": True,
        "description": description,
        "screenshot_size": len(image_bytes),
        "timestamp": time.time()
    }


async def describe_screen_for_context() -> str:
    """Quick screen description for injecting into LLM context."""
    result = await capture_and_analyze(
        "In one sentence, what application is the user currently using and what are they doing?"
    )
    if result.get("success"):
        return result["description"]
    return "Screen not available."
