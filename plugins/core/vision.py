from skills import Skill, SkillResult, registry
import asyncio
import logging
import time
import json
import difflib
import subprocess
import re
import memory
from typing import Optional, List, Dict, Callable, Any

log = logging.getLogger("LIS.plugins")

class VisionSkill(Skill):
    name = "analyze_screen"
    description = "Take a screenshot and answer questions about what is on the screen using Gemini Vision."

    async def execute(self, query: str = "Explain what is on my screen.", **kwargs) -> SkillResult:
        try:
            import os
            import httpx
            from screen import take_screenshot
            
            gemini_key = os.getenv("GEMINI_API_KEY", "")
            if not gemini_key:
                return SkillResult(False, "Gemini API key is not configured for vision tasks.")

            screenshot_b64 = await take_screenshot()
            if not screenshot_b64:
                return SkillResult(False, "Failed to capture the screen.")

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
            
            payload = {
                "contents": [{
                    "parts": [
                        {"text": f"You are LIS, the user's AI assistant. The user asked: '{query}'. Based on the provided screenshot, give a concise and helpful answer."},
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": screenshot_b64
                            }
                        }
                    ]
                }],
                "generationConfig": {"maxOutputTokens": 300}
            }

            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {}).get("parts", [])
                        if content:
                            answer = content[0].get("text", "I'm not sure what to make of it.")
                            return SkillResult(True, answer, data=answer)
                
                return SkillResult(False, f"Vision API returned an error: {resp.status_code}")

        except Exception as e:
            return SkillResult(False, f"Vision processing failed: {e}")


# Aliases — the LLM often uses these names instead of analyze_screen
registry.register(VisionSkill())

class TakeScreenshotSkill(Skill):
    name = "take_screenshot"
    description = "Take a screenshot and save it to the user's desktop."

    async def execute(self, **kwargs) -> SkillResult:
        try:
            import pyautogui
            import os
            from datetime import datetime
            import asyncio
            
            img = await asyncio.to_thread(pyautogui.screenshot)
            
            save_dir = os.path.join(os.path.expanduser("~"), "Desktop", "lis_captures")
            os.makedirs(save_dir, exist_ok=True)
            
            filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            filepath = os.path.join(save_dir, filename)
            
            await asyncio.to_thread(img.save, filepath)
            
            return SkillResult(True, f"Screenshot taken and saved to {filepath}")
        except ImportError:
            return SkillResult(False, "pyautogui is not installed. Please install it to take screenshots.")
        except Exception as e:
            return SkillResult(False, f"Failed to take screenshot: {e}")
registry.register(TakeScreenshotSkill())

class DescribeScreenSkill(Skill):
    name = "describe_screen"
    description = "Describe what the user is currently looking at on their screen."

    async def execute(self, **kwargs) -> SkillResult:
        vision = VisionSkill()
        return await vision.execute(query=kwargs.get("query", "Describe what apps and content are visible on this screen."))



# Productivity & Lists
registry.register(DescribeScreenSkill())

class WebcamCaptureSkill(Skill):
    """
    Takes a photo from the system webcam and returns the image path.
    Requires opencv-python (cv2).
    """
    name = "webcam_capture"
    description = "Takes a photo using the webcam. Returns the absolute file path."

    async def execute(self, **kwargs) -> SkillResult:
        try:
            import cv2
            import os
            from datetime import datetime
            
            import asyncio
            
            def _capture():
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    return False, None
                ret, frame = cap.read()
                cap.release()
                return ret, frame
                
            ret, frame = await asyncio.to_thread(_capture)
            
            if not ret:
                return SkillResult(False, "Failed to capture frame from webcam.")
                
            save_dir = os.path.join(os.path.expanduser("~"), "Desktop", "lis_captures")
            os.makedirs(save_dir, exist_ok=True)
            
            filename = f"webcam_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            filepath = os.path.join(save_dir, filename)
            
            await asyncio.to_thread(cv2.imwrite, filepath, frame)
            return SkillResult(True, f"Webcam photo captured and saved to {filepath}")
            
        except ImportError:
            return SkillResult(False, "OpenCV is not installed. Run: pip install opencv-python")
        except Exception as e:
            return SkillResult(False, f"Webcam capture failed: {e}")
registry.register(WebcamCaptureSkill())

