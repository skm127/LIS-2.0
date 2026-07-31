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

class VolumeControlSkill(Skill):
    name = "volume_control"
    description = "Adjust system volume (up, down, mute, unmute)."

    async def execute(self, direction: str, **kwargs) -> SkillResult:
        # 175 = Vol up, 174 = Vol down, 173 = Mute
        keys = {"up": 175, "down": 174, "mute": 173, "unmute": 173}
        key = keys.get(direction.lower())
        if not key:
            return SkillResult(False, "Invalid volume direction, sir.")
        
        try:
            cmd = f"powershell -Command \"(New-Object -ComObject WScript.Shell).SendKeys([char]{key})\""
            # Repeat a few times for volume changes
            repeats = 3 if direction in ["up", "down"] else 1
            for _ in range(repeats):
                subprocess.run(cmd, shell=True)
            return SkillResult(True, f"Volume adjusted, sir.")
        except Exception as e:
            log.error(f"Volume change failed: {e}")
            return SkillResult(False, "I couldn't adjust the volume, sir.")
registry.register(VolumeControlSkill())

class BrightnessControlSkill(Skill):
    name = "brightness_set"
    description = "Set screen brightness (0-100)."

    async def execute(self, level: int, **kwargs) -> SkillResult:
        level = max(0, min(100, int(level)))
        try:
            cmd = f"powershell -Command \"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {level})\""
            subprocess.run(cmd, shell=True)
            return SkillResult(True, f"Brightness set to {level} percent, sir.")
        except Exception as e:
            log.error(f"Brightness change failed: {e}")
            return SkillResult(False, "I had trouble adjusting the brightness, sir.")
registry.register(BrightnessControlSkill())

class MediaControlSkill(Skill):
    name = "media_control"
    description = "Control system media playback (play, pause, next, prev)."

    async def execute(self, action: str, **kwargs) -> SkillResult:
        # Virtual Key codes for media keys
        keys = {
            "play": "0xB3", "pause": "0xB3", "play_pause": "0xB3",
            "next": "0xB0", "prev": "0xB1", "stop": "0xB2",
            "volume_up": "0xAF", "volume_down": "0xAE", "mute": "0xAD"
        }
        vk = keys.get(action.lower())
        if not vk:
             return SkillResult(False, "Invalid media action, sir.")
        
        try:
            # Use PowerShell to send virtual key
            ps_cmd = f"$wshell = New-Object -ComObject WScript.Shell; $wshell.SendKeys([char]{vk})"
            subprocess.Popen(["powershell", "-Command", ps_cmd], shell=True)
            return SkillResult(True, f"Media {action} executed, sir.")
        except Exception as e:
            return SkillResult(False, f"Media control failed: {e}")
registry.register(MediaControlSkill())

class MusicSkill(Skill):
    name = "play_music"
    description = "Search for and play a song, artist, or playlist on Spotify or YouTube."

    async def execute(self, query: str, platform: str = "youtube", **kwargs) -> SkillResult:
        from urllib.parse import quote
        platform = platform.lower().strip()

        try:
            if platform == "spotify" or "spotify" in query.lower():
                # Clean query of platform mentions
                clean_q = query.lower().replace("on spotify", "").replace("spotify", "").strip()
                # Open Spotify search URI — launches the desktop app directly
                spotify_uri = f"spotify:search:{quote(clean_q)}"
                subprocess.Popen(f'start "" "{spotify_uri}"', shell=True)
                return SkillResult(True, f"Playing {clean_q} on Spotify for you! ▶")
            else:
                # YouTube — open search results
                clean_q = query.lower().replace("on youtube", "").replace("youtube", "").strip()
                url = f"https://www.youtube.com/results?search_query={quote(clean_q + ' music')}"
                subprocess.Popen(f'start "" "{url}"', shell=True)
                return SkillResult(True, f"Setting the mood with {clean_q} on YouTube! ▶")
        except Exception as e:
            return SkillResult(False, f"Music playback error: {e}")
registry.register(MusicSkill())

