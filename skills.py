import asyncio
import logging
import time
import json
import difflib
import subprocess
import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Callable, Any

import memory
log = logging.getLogger("LIS.skills")

@dataclass
class SkillResult:
    success: bool
    confirmation: str
    data: Any = None

class Skill:
    name: str
    description: str
    
    async def execute(self, **kwargs) -> SkillResult:
        raise NotImplementedError

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self.agent_spawner: Optional[Callable] = None

    def register(self, skill: Skill):
        self._skills[skill.name] = skill
        log.info(f"Registered skill: {skill.name}")

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_all(self) -> List[Dict]:
        return [{"name": s.name, "description": s.description} for s in self._skills.values()]

registry = SkillRegistry()

# ---------------------------------------------------------------------------
# App Launcher Skill
# ---------------------------------------------------------------------------

class LaunchAppSkill(Skill):
    name = "launch_app"
    description = "Open any installed application on the system."
    
    # Common user aliases for Windows applications
    ALIASES = {
        "chrome": "Google Chrome",
        "browser": "Microsoft Edge",
        "code": "Visual Studio Code",
        "vscode": "Visual Studio Code",
        "terminal": "Command Prompt",
        "cmd": "Command Prompt",
        "powershell": "Windows PowerShell",
        "discord": "Discord",
        "spotify": "Spotify",
        "notepad": "Notepad"
    }

    def __init__(self):
        self._app_cache: List[Dict] = []
        self._last_scan = 0

    async def _scan_apps(self):
        """Fetch installed apps via PowerShell."""
        if time.time() - self._last_scan < 3600 and self._app_cache:
            return

        try:
            cmd = "powershell -Command \"Get-StartApps | ConvertTo-Json\""
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if stdout:
                self._app_cache = json.loads(stdout)
                self._last_scan = time.time()
        except Exception as e:
            log.error(f"Failed to scan apps: {e}")

    async def execute(self, app_name: str, **kwargs) -> SkillResult:
        # Direct launch shortcuts — 40+ common Windows apps
        DIRECT_LAUNCH = {
            # System
            "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe",
            "paint": "mspaint.exe", "cmd": "cmd.exe", "command prompt": "cmd.exe",
            "terminal": "wt.exe", "windows terminal": "wt.exe",
            "powershell": "powershell.exe", "explorer": "explorer.exe",
            "file explorer": "explorer.exe", "files": "explorer.exe",
            "task manager": "taskmgr.exe", "settings": "ms-settings:",
            "control panel": "control.exe", "device manager": "devmgmt.msc",
            "disk management": "diskmgmt.msc", "registry": "regedit.exe",
            "snipping tool": "SnippingTool.exe", "snip": "SnippingTool.exe",
            "character map": "charmap.exe", "magnifier": "magnify.exe",
            "sticky notes": "explorer.exe shell:AppsFolder\\Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App",
            "clock": "ms-clock:", "alarms": "ms-clock:",
            "camera": "microsoft.windows.camera:", "photos": "ms-photos:",
            "maps": "bingmaps:", "weather": "bingweather:",
            "store": "ms-windows-store:", "microsoft store": "ms-windows-store:",
            # Browsers
            "chrome": "chrome.exe", "google chrome": "chrome.exe",
            "brave": "brave.exe", "firefox": "firefox.exe",
            "edge": "msedge.exe", "microsoft edge": "msedge.exe",
            "opera": "opera.exe",
            # Microsoft Office
            "word": "winword.exe", "microsoft word": "winword.exe",
            "excel": "excel.exe", "microsoft excel": "excel.exe",
            "powerpoint": "powerpnt.exe", "ppt": "powerpnt.exe",
            "outlook": "outlook.exe", "onenote": "onenote.exe",
            "teams": "ms-teams:", "microsoft teams": "ms-teams:",
            # Dev Tools
            "code": "code.exe", "vscode": "code.exe", "visual studio code": "code.exe",
            "visual studio": "devenv.exe", "android studio": "studio64.exe",
            "git bash": "git-bash.exe", "postman": "Postman.exe",
            # Media & Entertainment
            "spotify": "spotify.exe", "vlc": "vlc.exe",
            "media player": "wmplayer.exe", "windows media player": "wmplayer.exe",
            "movies": "mswindowsvideo:", "groove": "mswindowsmusic:",
            # Social & Communication
            "discord": "discord.exe", "telegram": "telegram.exe",
            "whatsapp": "whatsapp:", "slack": "slack.exe",
            "zoom": "zoom.exe", "skype": "skype.exe",
            # Gaming
            "steam": "steam.exe", "epic games": "EpicGamesLauncher.exe",
            "xbox": "xbox:", "game bar": "gamebar:",
            # Utilities
            "obs": "obs64.exe", "obs studio": "obs64.exe",
            "audacity": "audacity.exe", "gimp": "gimp.exe",
            "blender": "blender.exe", "figma": "figma.exe",
            "notion": "Notion.exe", "obsidian": "Obsidian.exe",
        }
        
        app_name = str(app_name).strip()
        # Security: Strip potentially dangerous shell characters to prevent injection
        app_name = re.sub(r'[&|<>;"]', '', app_name)
        
        if not app_name:
             return SkillResult(False, "No valid application name provided.")

        direct = DIRECT_LAUNCH.get(app_name.lower())
        if direct:
            try:
                subprocess.Popen(f'start "" "{direct}"', shell=True)
                return SkillResult(True, f"Opening {app_name} for you!")
            except Exception as e:
                log.error(f"Direct launch failed: {e}")

        await self._scan_apps()
        if not self._app_cache:
            # Fallback: try start command directly
            try:
                subprocess.Popen(f'start "" "{app_name}"', shell=True)
                return SkillResult(True, f"Trying to open {app_name} for you!")
            except:
                return SkillResult(False, "Couldn't find any installed applications.")

        # Check aliases
        lookup_name = self.ALIASES.get(app_name.lower(), app_name.lower())
        
        # Fuzzy match against cached app names
        names = [app.get("Name", "") for app in self._app_cache]
        matches = difflib.get_close_matches(lookup_name, names, n=1, cutoff=0.3)
        
        if matches:
            match_name = matches[0]
            # Case-insensitive key lookup for AppId/AppID
            matched_app = next((app for app in self._app_cache if app.get("Name") == match_name), None)
            if matched_app:
                app_id = matched_app.get("AppId") or matched_app.get("AppID") or matched_app.get("appid", "")
                if app_id:
                    try:
                        launch_cmd = f'explorer.exe shell:AppsFolder\\{app_id}'
                        subprocess.Popen(launch_cmd, shell=True)
                        return SkillResult(True, f"Opening {match_name} for you!")
                    except Exception as e:
                        log.error(f"Launch failed: {e}")
        
        # Final fallback
        try:
            subprocess.Popen(f'start "" "{app_name}"', shell=True)
            return SkillResult(True, f"Trying to open {app_name}!")
        except:
            return SkillResult(False, f"Couldn't find {app_name}.")

registry.register(LaunchAppSkill())

# ---------------------------------------------------------------------------
# System Control Skills
# ---------------------------------------------------------------------------

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

class SystemPowerSkill(Skill):
    name = "system_power"
    description = "Control system power states (lock, sleep, signout)."

    async def execute(self, action: str, **kwargs) -> SkillResult:
        # Commands for Windows
        cmds = {
            "lock": "rundll32.exe user32.dll,LockWorkStation",
            "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
            "signout": "shutdown /l"
        }
        cmd = cmds.get(action.lower())
        if not cmd:
             return SkillResult(False, "Invalid power action, sir.")
        
        try:
            subprocess.Popen(cmd, shell=True)
            return SkillResult(True, f"Executing {action} protocol, sir.")
        except Exception as e:
            return SkillResult(False, f"Failed to execute {action}: {e}")

registry.register(SystemPowerSkill())

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

class SystemKeysSkill(Skill):
    name = "system_keys"
    description = "Send keystrokes (Enter, Tab, etc.) to the active window."

    async def execute(self, keys: str, **kwargs) -> SkillResult:
        """Supported: {ENTER}, {TAB}, {ESC}, or literal text."""
        keys = str(keys)
        if len(keys) > 50:
             return SkillResult(False, "Key sequence too long.")
             
        # Block command injection attempts through key sequence
        forbidden = ["cmd", "powershell", "format", "del", "rmdir", "Invoke-WebRequest"]
        if any(f in keys.lower() for f in forbidden):
             return SkillResult(False, "Action restricted by security protocol.")
             
        try:
            # Use PowerShell SendKeys
            # Escape single quotes in keys if any
            escaped_keys = keys.replace("'", "''")
            ps_cmd = f"$wshell = New-Object -ComObject WScript.Shell; $wshell.SendKeys('{escaped_keys}')"
            subprocess.Popen(["powershell", "-Command", ps_cmd], shell=True)
            return SkillResult(True, f"Sent keys: {keys}, sir.")
        except Exception as e:
            return SkillResult(False, f"Keystroke failed: {e}")

registry.register(SystemKeysSkill())

# ---------------------------------------------------------------------------
# Time Skills (Alarms/Timers/Reminders - logical additions)
# ---------------------------------------------------------------------------
# Note: Persistence is handled in memory.py, these are the action wrappers.

class TimerSkill(Skill):
    name = "start_timer"
    description = "Start a countdown timer."

    async def execute(self, duration_sec: int, label: str = "", **kwargs) -> SkillResult:
        try:
            memory.add_timer(int(duration_sec), label)
            return SkillResult(True, f"Timer started for {duration_sec} seconds, sir.")
        except Exception as e:
            return SkillResult(False, f"Failed to start timer: {e}")

registry.register(TimerSkill())

class GenerateImageSkill(Skill):
    name = "generate_image"
    description = "Generate an AI image from a text prompt and display it."

    async def execute(self, prompt: str, **kwargs) -> SkillResult:
        try:
            import urllib.parse
            import urllib.request
            import os
            from pathlib import Path

            encoded_prompt = urllib.parse.quote(prompt)
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            
            save_path = Path.home() / "Desktop" / "LIS_Generated_Image.jpg"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response, open(save_path, 'wb') as out_file:
                out_file.write(response.read())
            
            # Open the image natively on Windows
            import subprocess
            subprocess.Popen(f'explorer.exe "{save_path}"', shell=True)
            
            return SkillResult(True, f"Image generated and opened, sir.")
        except Exception as e:
            return SkillResult(False, f"Image generation error: {e}")

registry.register(GenerateImageSkill())

class AlarmSkill(Skill):
    name = "set_alarm"
    description = "Set an alarm for a specific time."

    async def execute(self, time_str: str, label: str = "", **kwargs) -> SkillResult:
        try:
            memory.add_alarm(time_str, label)
            return SkillResult(True, f"Alarm set for {time_str}, sir.")
        except Exception as e:
            return SkillResult(False, f"Failed to set alarm: {e}")

registry.register(AlarmSkill())

class ReminderSkill(Skill):
    name = "create_reminder"
    description = "Create a reminder for a future time."

    async def execute(self, time_offset_minutes: int, content: str, **kwargs) -> SkillResult:
        try:
            trigger = time.time() + (int(time_offset_minutes) * 60)
            memory.add_reminder(trigger, content)
            return SkillResult(True, f"I will remind you about {content} in {time_offset_minutes} minutes, sir.")
        except Exception as e:
            return SkillResult(False, f"Failed to create reminder: {e}")

registry.register(ReminderSkill())

class SmartHomeSkill(Skill):
    name = "smart_home_control"
    description = "Control smart home devices (lights, plugs, etc.)."

    async def execute(self, device: str, state: str, **kwargs) -> SkillResult:
        # Placeholder for real smart home integration (e.g., HomeAssistant API)
        return SkillResult(True, f"Turned {state} the {device}, sir.")

registry.register(SmartHomeSkill())

class TeachingSkill(Skill):
    name = "teach_feature"
    description = "Explain a concept clearly using analogies and structured steps."

    async def execute(self, topic: str, **kwargs) -> SkillResult:
        # This skill doesn't perform a system action per se, 
        # but marks the mode for the LLM. 
        # The prompt will handle the pedagogical structure.
        return SkillResult(True, f"I would be happy to teach you about {topic}, sir. Let's start with the basics.")

registry.register(TeachingSkill())

class SuggestionsSkill(Skill):
    name = "get_suggestions"
    description = "Generate creative ideas, tips, or suggestions for a topic."

    async def execute(self, topic: str, count: int = 5, **kwargs) -> SkillResult:
        return SkillResult(True, f"I've prepared {count} suggestions regarding {topic} for you, sir.")

registry.register(SuggestionsSkill())

# ---------------------------------------------------------------------------
# Knowledge & Info Skills
# ---------------------------------------------------------------------------

class WikipediaSkill(Skill):
    name = "wiki_search"
    description = "Search Wikipedia for a brief summary of a topic."

    async def execute(self, query: str, **kwargs) -> SkillResult:
        try:
            # Use gzipped search to keep it fast
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}"
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    summary = data.get("extract", "I couldn't find a summary, sir.")
                    return SkillResult(True, f"According to Wikipedia: {summary}", data=summary)
                return SkillResult(False, f"I couldn't find anything on {query}, sir.")
        except Exception as e:
            return SkillResult(False, "Wikipedia is unreachable at the moment, sir.")

registry.register(WikipediaSkill())

class GoogleMapsSkill(Skill):
    name = "map_action"
    description = "Search for locations or get directions on Google Maps."

    async def execute(self, action: str, query: str = "", origin: str = "", destination: str = "", **kwargs) -> SkillResult:
        from urllib.parse import quote
        try:
            if action == "search":
                url = f"https://www.google.com/maps/search/{quote(query)}"
                msg = f"Pulling up a map for {query}, sir."
            elif action == "directions":
                url = f"https://www.google.com/maps/dir/{quote(origin)}/{quote(destination)}"
                msg = f"Charting a course from {origin} to {destination}, sir."
            else:
                return SkillResult(False, "Invalid map action, sir.")
            
            subprocess.Popen(f'start "" "{url}"', shell=True)
            return SkillResult(True, msg)
        except Exception as e:
            return SkillResult(False, f"Google Maps failed: {e}")

registry.register(GoogleMapsSkill())

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

class WeatherSkill(Skill):
    name = "get_weather"
    description = "Get the current weather forecast for any location."

    async def execute(self, location: str = "", **kwargs) -> SkillResult:
        try:
            import httpx
            # Step 1: Geocode the location
            if not location:
                location = "auto"  # Will use IP-based location
            
            async with httpx.AsyncClient(timeout=8.0) as client:
                # Use Open-Meteo geocoding for dynamic locations
                if location != "auto":
                    geo_resp = await client.get(f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1")
                    if geo_resp.status_code == 200 and geo_resp.json().get("results"):
                        geo = geo_resp.json()["results"][0]
                        lat, lon = geo["latitude"], geo["longitude"]
                        loc_name = geo.get("name", location)
                    else:
                        # Fallback to IP location if geocoding fails on specific name
                        ip_resp = await client.get("https://ipapi.co/json/")
                        if ip_resp.status_code == 200:
                            ip_data = ip_resp.json()
                            lat, lon = ip_data.get("latitude", 0), ip_data.get("longitude", 0)
                            loc_name = ip_data.get("city", "your area")
                        else:
                            return SkillResult(False, f"Sorry sir, I couldn't find {location} on the map.")
                else:
                    # IP-based geolocation
                    ip_resp = await client.get("https://ipapi.co/json/")
                    if ip_resp.status_code == 200:
                        ip_data = ip_resp.json()
                        lat, lon = ip_data.get("latitude", 0), ip_data.get("longitude", 0)
                        loc_name = ip_data.get("city", "your area")
                    else:
                        lat, lon, loc_name = 0, 0, "unknown"

                # Step 2: Fetch weather
                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weathercode,windspeed_10m&temperature_unit=celsius"
                resp = await client.get(url)
                if resp.status_code == 200:
                    d = resp.json().get("current", {})
                    temp = d.get("temperature_2m", "?")
                    humidity = d.get("relative_humidity_2m", "?")
                    wind = d.get("windspeed_10m", "?")
                    code = d.get("weathercode", 0)
                    
                    # Weather code descriptions
                    conditions = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                                  45: "Foggy", 48: "Depositing rime fog", 51: "Light drizzle", 61: "Light rain",
                                  63: "Moderate rain", 65: "Heavy rain", 71: "Light snow", 73: "Moderate snow",
                                  80: "Rain showers", 95: "Thunderstorm"}
                    condition = conditions.get(code, "Mixed conditions")
                    
                    # Track in adaptive learning
                    memory.remember(f"User asked weather for {loc_name}", "preference", importance=2)
                    
                    return SkillResult(True, 
                        f"The weather in {loc_name} is {temp} degrees with {condition.lower()}, sir. "
                        f"The humidity is {humidity} percent and the wind is at {wind} kilometers per hour. "
                        f"It feels quite nice, doesn't it?")
                return SkillResult(False, "I had a bit of trouble checking the weather, sir.")
        except Exception as e:
            log.error(f"Weather failed: {e}")
            return SkillResult(False, "I couldn't quite reach the weather station, I'm sorry.")

registry.register(WeatherSkill())

class WebSearchSkill(Skill):
    name = "search_web"
    description = "Search the web for information using the default browser."

    async def execute(self, query: str, **kwargs) -> SkillResult:
        try:
            from urllib.parse import quote
            url = f"https://www.google.com/search?q={quote(query)}"
            subprocess.Popen(f'start "" "{url}"', shell=True)
            return SkillResult(True, f"Let me look that up for you, sir.")
        except Exception as e:
            return SkillResult(False, "I had a bit of trouble reaching the web, sorry.")

registry.register(WebSearchSkill())

# ---------------------------------------------------------------------------
# Smart Skills — Calculator, Converter, Translator, etc.
# ---------------------------------------------------------------------------

class CalculatorSkill(Skill):
    name = "calculate"
    description = "Evaluate a math expression safely."

    async def execute(self, expression: str, **kwargs) -> SkillResult:
        import math
        try:
            # Safe eval with math functions only
            allowed = {
                "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
                "pow": pow, "int": int, "float": float,
                "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
                "log": math.log, "log10": math.log10, "pi": math.pi, "e": math.e,
                "ceil": math.ceil, "floor": math.floor
            }
            result = eval(expression, {"__builtins__": {}}, allowed)
            return SkillResult(True, f"The result is {result}, sir.")
        except Exception as e:
            return SkillResult(False, f"I couldn't calculate that: {e}, sir.")

registry.register(CalculatorSkill())

class UnitConverterSkill(Skill):
    name = "convert_unit"
    description = "Convert between units (km to miles, kg to lbs, C to F, etc.)."

    CONVERSIONS = {
        ("km", "miles"): lambda x: x * 0.621371,
        ("miles", "km"): lambda x: x * 1.60934,
        ("kg", "lbs"): lambda x: x * 2.20462,
        ("lbs", "kg"): lambda x: x / 2.20462,
        ("celsius", "fahrenheit"): lambda x: x * 9/5 + 32,
        ("fahrenheit", "celsius"): lambda x: (x - 32) * 5/9,
        ("c", "f"): lambda x: x * 9/5 + 32,
        ("f", "c"): lambda x: (x - 32) * 5/9,
        ("meters", "feet"): lambda x: x * 3.28084,
        ("feet", "meters"): lambda x: x / 3.28084,
        ("liters", "gallons"): lambda x: x * 0.264172,
        ("gallons", "liters"): lambda x: x / 0.264172,
        ("cm", "inches"): lambda x: x / 2.54,
        ("inches", "cm"): lambda x: x * 2.54,
        ("grams", "ounces"): lambda x: x * 0.035274,
        ("ounces", "grams"): lambda x: x / 0.035274,
    }

    async def execute(self, value: float, from_unit: str, to_unit: str, **kwargs) -> SkillResult:
        try:
            value = float(value)
            key = (from_unit.lower(), to_unit.lower())
            if key in self.CONVERSIONS:
                result = self.CONVERSIONS[key](value)
                return SkillResult(True, f"{value} {from_unit} is {round(result, 4)} {to_unit}, sir.")
            return SkillResult(False, f"I don't know how to convert {from_unit} to {to_unit} yet, sir.")
        except Exception as e:
            return SkillResult(False, f"Conversion failed: {e}")

registry.register(UnitConverterSkill())

class TranslatorSkill(Skill):
    name = "translate"
    description = "Translate text between languages using free API."

    async def execute(self, text: str, to_lang: str = "en", from_lang: str = "auto", **kwargs) -> SkillResult:
        try:
            import httpx
            from urllib.parse import quote
            url = f"https://api.mymemory.translated.net/get?q={quote(text)}&langpair={from_lang}|{to_lang}"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    translated = data.get("responseData", {}).get("translatedText", "")
                    if translated:
                        return SkillResult(True, f"Translation: {translated}", data=translated)
            return SkillResult(False, "Translation service unavailable, sir.")
        except Exception as e:
            return SkillResult(False, f"Translation failed: {e}")

registry.register(TranslatorSkill())

class NewsSkill(Skill):
    name = "get_news"
    description = "Fetch top news headlines."

    async def execute(self, topic: str = "top", **kwargs) -> SkillResult:
        try:
            import httpx
            from urllib.parse import quote
            # Use free RSS-to-JSON service
            rss_url = f"https://news.google.com/rss/search?q={quote(topic)}&hl=en-IN&gl=IN&ceid=IN:en"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(rss_url)
                if resp.status_code == 200:
                    # Parse RSS XML for titles
                    import re
                    titles = re.findall(r'<title>(.*?)</title>', resp.text)
                    # Skip first two (feed title + Google News)
                    headlines = [t for t in titles[2:7] if t and 'Google' not in t]
                    if headlines:
                        news_text = ". ".join(headlines[:5])
                        return SkillResult(True, f"Here are the top headlines: {news_text}, sir.")
            return SkillResult(False, "I couldn't fetch the news right now, sir.")
        except Exception as e:
            return SkillResult(False, f"News service failed: {e}")

registry.register(NewsSkill())

class DateTimeSkill(Skill):
    name = "get_datetime"
    description = "Get current date, time, or timezone information."

    async def execute(self, query: str = "now", timezone: str = "", **kwargs) -> SkillResult:
        from datetime import datetime, timedelta
        import time as time_mod
        try:
            now = datetime.now()
            
            if "date" in query.lower():
                return SkillResult(True, f"Today is {now.strftime('%A, %B %d, %Y')}, sir.")
            elif "time" in query.lower():
                return SkillResult(True, f"The current time is {now.strftime('%I:%M %p')}, sir.")
            elif "day" in query.lower():
                return SkillResult(True, f"Today is {now.strftime('%A')}, sir.")
            elif "year" in query.lower():
                return SkillResult(True, f"The year is {now.year}, sir.")
            else:
                return SkillResult(True, f"It's {now.strftime('%A, %B %d, %Y at %I:%M %p')}, sir.")
        except Exception as e:
            return SkillResult(False, f"Date/time error: {e}")

registry.register(DateTimeSkill())

class CurrencyConverterSkill(Skill):
    name = "convert_currency"
    description = "Convert between currencies using live exchange rates."

    async def execute(self, amount: float, from_currency: str, to_currency: str, **kwargs) -> SkillResult:
        try:
            import httpx
            amount = float(amount)
            fr = from_currency.upper()
            to = to_currency.upper()
            url = f"https://api.exchangerate-api.com/v4/latest/{fr}"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    rates = resp.json().get("rates", {})
                    if to in rates:
                        result = amount * rates[to]
                        return SkillResult(True, f"{amount} {fr} is {round(result, 2)} {to}, sir.")
                    return SkillResult(False, f"Currency {to} not found, sir.")
            return SkillResult(False, "Exchange rate service unavailable, sir.")
        except Exception as e:
            return SkillResult(False, f"Currency conversion failed: {e}")

registry.register(CurrencyConverterSkill())

class DictionarySkill(Skill):
    name = "define_word"
    description = "Look up the definition of a word."

    async def execute(self, word: str, **kwargs) -> SkillResult:
        try:
            import httpx
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and isinstance(data, list):
                        meanings = data[0].get("meanings", [])
                        if meanings:
                            part = meanings[0].get("partOfSpeech", "")
                            defn = meanings[0].get("definitions", [{}])[0].get("definition", "")
                            return SkillResult(True, f"{word} ({part}): {defn}", data=defn)
            return SkillResult(False, f"I couldn't find a definition for {word}, sir.")
        except Exception as e:
            return SkillResult(False, f"Dictionary lookup failed: {e}")

registry.register(DictionarySkill())

class AutoSearchSkill(Skill):
    name = "auto_search"
    description = "Automatically search the web and return a summarized answer."

    async def execute(self, query: str, **kwargs) -> SkillResult:
        """Search DuckDuckGo instant answers API for quick facts."""
        try:
            import httpx
            from urllib.parse import quote
            url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    # Try Abstract first
                    abstract = data.get("AbstractText", "")
                    if abstract:
                        return SkillResult(True, f"{abstract[:500]}", data=abstract)
                    # Try Answer
                    answer = data.get("Answer", "")
                    if answer:
                        return SkillResult(True, f"{answer}", data=answer)
                    # Try Related Topics
                    topics = data.get("RelatedTopics", [])
                    if topics and isinstance(topics[0], dict):
                        text = topics[0].get("Text", "")
                        if text:
                            return SkillResult(True, f"{text[:500]}", data=text)
            # Fallback: open browser
            from urllib.parse import quote as q
            subprocess.Popen(f'start "" "https://www.google.com/search?q={q(query)}"', shell=True)
            return SkillResult(True, f"I've opened a search for {query} in your browser, sir.")
        except Exception as e:
            return SkillResult(False, f"Auto-search failed: {e}")

registry.register(AutoSearchSkill())

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

registry.register(VisionSkill())

# Aliases — the LLM often uses these names instead of analyze_screen
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

class DescribeScreenSkill(Skill):
    name = "describe_screen"
    description = "Describe what the user is currently looking at on their screen."

    async def execute(self, **kwargs) -> SkillResult:
        vision = VisionSkill()
        return await vision.execute(query=kwargs.get("query", "Describe what apps and content are visible on this screen."))

registry.register(TakeScreenshotSkill())
registry.register(DescribeScreenSkill())


# ---------------------------------------------------------------------------
# Productivity & Lists
# ---------------------------------------------------------------------------

class ManageListSkill(Skill):
    name = "manage_list"
    description = "Add or remove items from a persistent list (shopping, todo, etc.)."

    async def execute(self, list_name: str, action: str, item: str = None, **kwargs) -> SkillResult:
        current_items = memory.get_list(list_name)
        
        if action == "add" and item:
            if item not in current_items:
                current_items.append(item)
                memory.update_list(list_name, current_items)
            return SkillResult(True, f"I've added {item} to your {list_name} list, sir.")
        
        elif action == "remove" and item:
            if item in current_items:
                current_items.remove(item)
                memory.update_list(list_name, current_items)
                return SkillResult(True, f"I've removed {item} from your {list_name} list, sir.")
            return SkillResult(False, f"{item} wasn't on your {list_name} list, sir.")
        
        elif action == "read":
            if not current_items:
                return SkillResult(True, f"Your {list_name} list is currently empty, sir.")
            items_str = ", ".join(current_items)
            return SkillResult(True, f"Your {list_name} list contains: {items_str}, sir.")
        
        return SkillResult(False, "Invalid list action, sir.")

registry.register(ManageListSkill())

# ---------------------------------------------------------------------------
# Entertainment & Fun
# ---------------------------------------------------------------------------

class FunSkill(Skill):
    name = "fun_action"
    description = "Flip a coin, roll a dice, or tell a joke."

    async def execute(self, type: str, **kwargs) -> SkillResult:
        import random
        if type == "flip_coin":
            res = random.choice(["Heads", "Tails"])
            return SkillResult(True, f"It's {res}, sir.")
        elif type == "roll_dice":
            res = random.randint(1, 6)
            return SkillResult(True, f"You rolled a {res}, sir.")
        elif type == "joke":
            jokes = [
                "Why don't scientists trust atoms? Because they make up everything.",
                "What do you call a fake noodle? An Impasta.",
                "I told my computer I needed a break, and now it won't stop sending me KitKats.",
                "Why did the programmer quit his job? Because he didn't get arrays.",
                "What's a computer's favorite snack? Microchips.",
                "Why do Java developers wear glasses? Because they can't C-sharp."
            ]
            return SkillResult(True, random.choice(jokes))
        elif type == "fact":
            facts = [
                "A group of flamingos is called a flamboyance.",
                "Honey never spoils. Archaeologists have found 3000-year-old honey that was still edible.",
                "Octopuses have three hearts and blue blood.",
                "The inventor of the Pringles can is buried in one.",
                "A day on Venus is longer than a year on Venus."
            ]
            return SkillResult(True, f"Here's a fun fact: {random.choice(facts)}")
        return SkillResult(False, "Invalid fun type, sir.")

registry.register(FunSkill())

# ---------------------------------------------------------------------------
# Adaptive Learning Tracker
# ---------------------------------------------------------------------------

class AdaptiveLearningSkill(Skill):
    name = "adaptive_learn"
    description = "Track user preferences and patterns for smarter responses."

    async def execute(self, action: str = "summary", **kwargs) -> SkillResult:
        try:
            if action == "summary":
                recent = memory.get_recent_memories(limit=10)
                prefs = [m for m in recent if m.get("type") == "preference"]
                facts = [m for m in recent if m.get("type") == "fact"]
                return SkillResult(True, 
                    f"I've learned {len(prefs)} preferences and {len(facts)} facts about you, sir. "
                    f"I'm continuously adapting to serve you better.")
            elif action == "forget":
                return SkillResult(True, "Memory cleared for the specified topic, sir.")
            return SkillResult(True, "Adaptive learning is always active, sir.")
        except Exception as e:
            return SkillResult(False, f"Learning tracker error: {e}")

registry.register(AdaptiveLearningSkill())

# ---------------------------------------------------------------------------
# Market Intelligence (v2.0)
# ---------------------------------------------------------------------------

class StockPriceSkill(Skill):
    name = "get_stock"
    description = "Fetch real-time stock or index price."

    async def execute(self, symbol: str, **kwargs) -> SkillResult:
        try:
            import httpx
            symbol = symbol.upper().strip()

            # Common Indian aliases
            aliases = {
                "NIFTY": "^NSEI", "SENSEX": "^BSESN",
                "BANK NIFTY": "^NSEBANK", "BANKNIFTY": "^NSEBANK",
                "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS",
                "INFOSYS": "INFY.NS", "INFY": "INFY.NS",
                "HDFC": "HDFCBANK.NS", "WIPRO": "WIPRO.NS",
                "TATA MOTORS": "TATAMOTORS.NS", "ITC": "ITC.NS",
            }
            yahoo_symbol = aliases.get(symbol, symbol)
            # If no exchange suffix for Indian stocks, add .NS
            if not any(yahoo_symbol.startswith("^") or yahoo_symbol.endswith(s) for s in [".NS", ".BO", ".L", ".HK"]):
                # Check if it's likely a US stock or needs .NS
                pass

            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=1d&range=5d"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    data = resp.json()
                    meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                    price = meta.get("regularMarketPrice", 0)
                    prev_close = meta.get("previousClose") or meta.get("chartPreviousClose", 0)
                    currency = meta.get("currency", "USD")
                    name = meta.get("shortName", symbol)

                    if price and prev_close:
                        change = price - prev_close
                        pct = (change / prev_close) * 100
                        direction = "up" if change > 0 else "down"
                        emoji = "📈" if change > 0 else "📉"
                        return SkillResult(True,
                            f"{emoji} {name} is at {currency} {price:.2f}, "
                            f"{direction} {abs(pct):.2f}% from yesterday's close of {prev_close:.2f}.")
                    elif price:
                        return SkillResult(True, f"{name} is currently at {currency} {price:.2f}.")

            return SkillResult(False, f"Couldn't fetch data for {symbol}, sir. Check the ticker symbol?")
        except Exception as e:
            log.error(f"Stock fetch failed: {e}")
            return SkillResult(False, f"Market data unavailable right now: {e}")

registry.register(StockPriceSkill())


class CryptoPriceSkill(Skill):
    name = "get_crypto"
    description = "Fetch real-time cryptocurrency price from CoinGecko."

    # Common aliases
    ALIASES = {
        "btc": "bitcoin", "eth": "ethereum", "sol": "solana",
        "doge": "dogecoin", "xrp": "ripple", "ada": "cardano",
        "bnb": "binancecoin", "dot": "polkadot", "matic": "matic-network",
        "avax": "avalanche-2", "link": "chainlink", "shib": "shiba-inu",
        "ltc": "litecoin", "uni": "uniswap", "atom": "cosmos",
    }

    async def execute(self, coin: str, **kwargs) -> SkillResult:
        try:
            import httpx
            coin_id = self.ALIASES.get(coin.lower().strip(), coin.lower().strip())

            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd,inr&include_24hr_change=true"
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if coin_id in data:
                        info = data[coin_id]
                        usd = info.get("usd", 0)
                        inr = info.get("inr", 0)
                        change_24h = info.get("usd_24h_change", 0)
                        emoji = "📈" if change_24h > 0 else "📉"
                        return SkillResult(True,
                            f"{emoji} {coin.upper()} is at ${usd:,.2f} (₹{inr:,.2f}), "
                            f"{'up' if change_24h > 0 else 'down'} {abs(change_24h):.2f}% in 24h.")

            return SkillResult(False, f"Couldn't find crypto data for {coin}.")
        except Exception as e:
            log.error(f"Crypto fetch failed: {e}")
            return SkillResult(False, f"Crypto data unavailable: {e}")

registry.register(CryptoPriceSkill())


class MarketSummarySkill(Skill):
    name = "market_summary"
    description = "Get a quick overview of major market indices."

    async def execute(self, **kwargs) -> SkillResult:
        try:
            import httpx
            indices = {
                "^NSEI": "Nifty 50",
                "^BSESN": "Sensex",
                "^GSPC": "S&P 500",
                "^DJI": "Dow Jones",
            }
            results = []
            async with httpx.AsyncClient(timeout=10.0) as client:
                for symbol, name in indices.items():
                    try:
                        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
                        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                        if resp.status_code == 200:
                            data = resp.json()
                            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                            price = meta.get("regularMarketPrice", 0)
                            prev = meta.get("previousClose") or meta.get("chartPreviousClose", 0)
                            if price and prev:
                                pct = ((price - prev) / prev) * 100
                                emoji = "📈" if pct > 0 else "📉"
                                results.append(f"{emoji} {name}: {price:,.0f} ({pct:+.2f}%)")
                    except Exception:
                        continue

            if results:
                summary = ". ".join(results)
                return SkillResult(True, f"Market snapshot: {summary}.")

            return SkillResult(False, "Markets are closed or data is unavailable right now.")
        except Exception as e:
            log.error(f"Market summary failed: {e}")
            return SkillResult(False, f"Market data unavailable: {e}")

registry.register(MarketSummarySkill())

# ---------------------------------------------------------------------------
# MCP Integration Skill
# ---------------------------------------------------------------------------

class MCPActionSkill(Skill):
    name = "mcp_call"
    description = "Execute a tool on an external MCP (Model Context Protocol) server."

    async def execute(self, server_name: str, tool_name: str, arguments: str = "{}", **kwargs) -> SkillResult:
        try:
            import json
            from mcp_client import mcp_manager
            
            args_dict = json.loads(arguments) if isinstance(arguments, str) else arguments
            
            client = mcp_manager.clients.get(server_name)
            if not client:
                return SkillResult(False, f"MCP Server '{server_name}' is not configured.")
                
            result = await client.call_tool(tool_name, args_dict)
            if result.get("success"):
                return SkillResult(True, f"Successfully executed {tool_name} on {server_name}.", data=result.get("data"))
            else:
                return SkillResult(False, f"MCP execution failed: {result.get('error')}")
                
        except Exception as e:
            return SkillResult(False, f"MCP call error: {e}")

registry.register(MCPActionSkill())

# ---------------------------------------------------------------------------
# Omniscience (Phase 1)
# ---------------------------------------------------------------------------

class LocalDocumentSearchSkill(Skill):
    name = "search_documents"
    description = "Semantically search the user's local documents, PDFs, and codebases for specific information."

    async def execute(self, query: str, **kwargs) -> SkillResult:
        try:
            from vector_memory import VectorMemory
            vmem = VectorMemory()
            results = vmem.search(query, top_k=5)
            
            if not results:
                return SkillResult(False, "No relevant documents found.")
                
            # Format results
            snippets = []
            for r in results:
                meta = r.get("metadata", {})
                source = meta.get("filename", "Unknown Document")
                score = r.get("score", 0)
                # Ensure the text is brief to not overflow context
                text = r.get("text", "")[:500]
                snippets.append(f"Source [{source}] (Relevance {int(score*100)}%):\n{text}...")
                
            combined = "\n\n".join(snippets)
            return SkillResult(True, f"Found relevant information in local documents:\n{combined}")
        except Exception as e:
            return SkillResult(False, f"Document search failed: {e}")

registry.register(LocalDocumentSearchSkill())

class ComputerControlSkill(Skill):
    name = "computer_control"
    description = "Move the mouse, click, or type on the screen. IMPORTANT: You must get user confirmation before using this skill."

    async def execute(self, action: str, x: int = 0, y: int = 0, text: str = "", **kwargs) -> SkillResult:
        try:
            import pyautogui
            x, y = int(x), int(y)
            
            if action == "move":
                await asyncio.to_thread(pyautogui.moveTo, x, y, duration=0.5)
                return SkillResult(True, f"Moved mouse to ({x}, {y}).")
            elif action == "click":
                await asyncio.to_thread(pyautogui.click, x, y)
                return SkillResult(True, f"Clicked at ({x}, {y}).")
            elif action == "type":
                if not text:
                    return SkillResult(False, "No text provided to type.")
                await asyncio.to_thread(pyautogui.write, text, interval=0.01)
                return SkillResult(True, f"Typed text: {text[:20]}...")
            elif action == "press":
                if not text:
                    return SkillResult(False, "No key provided to press.")
                await asyncio.to_thread(pyautogui.press, text)
                return SkillResult(True, f"Pressed key: {text}")
            else:
                return SkillResult(False, f"Unknown computer control action: {action}")
                
        except ImportError:
            return SkillResult(False, "pyautogui is not installed. Run: pip install pyautogui")
        except Exception as e:
            return SkillResult(False, f"Computer control failed: {e}")

registry.register(ComputerControlSkill())

# ---------------------------------------------------------------------------
# Swarm Agents (Phase 3)
# ---------------------------------------------------------------------------

class SubAgentSkill(Skill):
    name = "spawn_agent"
    description = "Spawn a specialized sub-agent to handle a long-running or complex background task. Returns the final summary from the agent."

    async def execute(self, task_description: str, **kwargs) -> SkillResult:
        if not registry.agent_spawner:
            return SkillResult(False, "Agent spawner is not configured in the registry.")
            
        try:
            log.info(f"Spawning sub-agent for task: {task_description}")
            # Call the injected spawner
            result = await registry.agent_spawner(task_description)
            return SkillResult(True, f"Sub-agent completed the task. Result: {result}")
        except Exception as e:
            return SkillResult(False, f"Sub-agent failed: {e}")

registry.register(SubAgentSkill())

# ---------------------------------------------------------------------------
# Smart Home IoT (Phase 4)
# ---------------------------------------------------------------------------

class SmartHomeSkill(Skill):
    name = "smart_home_control"
    description = "Control physical smart home devices like lights, locks, and thermostats via Home Assistant."

    async def execute(self, entity_id: str, action: str, **kwargs) -> SkillResult:
        import os
        ha_url = os.environ.get("HA_URL")
        ha_token = os.environ.get("HA_TOKEN")
        
        if not ha_url or not ha_token:
            return SkillResult(False, "Home Assistant is not configured. HA_URL and HA_TOKEN must be set in .env")
            
        try:
            import aiohttp
            
            headers = {
                "Authorization": f"Bearer {ha_token}",
                "Content-Type": "application/json",
            }
            
            domain = entity_id.split('.')[0]
            # e.g. turn_on, turn_off, toggle
            endpoint = f"{ha_url.rstrip('/')}/api/services/{domain}/{action}"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, headers=headers, json={"entity_id": entity_id}) as resp:
                    if resp.status in [200, 201]:
                        return SkillResult(True, f"Successfully executed {action} on {entity_id}.")
                    else:
                        error_text = await resp.text()
                        return SkillResult(False, f"Home Assistant error ({resp.status}): {error_text}")
                        
        except ImportError:
            return SkillResult(False, "aiohttp is not installed. Run: pip install aiohttp")
        except Exception as e:
            return SkillResult(False, f"Failed to connect to Smart Home: {e}")

registry.register(SmartHomeSkill())

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

class KnowledgeGraphSkill(Skill):
    """
    Maps entities to a procedural knowledge graph or queries it.
    action: 'add' or 'query'
    """
    name = "knowledge_graph"
    description = "Adds or queries relationships in the memory palace. Actions: 'add', 'query'. Provide subject, predicate, obj for 'add'. Provide entity for 'query'."

    async def execute(self, action: str, subject: str = "", predicate: str = "", obj: str = "", entity: str = "", **kwargs) -> SkillResult:
        try:
            from knowledge_graph import kg
            
            if action == "add":
                if not (subject and predicate and obj):
                    return SkillResult(False, "Missing subject, predicate, or object for adding to graph.")
                kg.add_relation(subject, predicate, obj)
                return SkillResult(True, f"Added relationship: {subject} {predicate} {obj}")
                
            elif action == "query":
                if not entity:
                    return SkillResult(False, "Missing entity to query.")
                results = kg.query(entity)
                if not results:
                    return SkillResult(False, f"I don't know anything about {entity}.")
                return SkillResult(True, f"Knowledge about {entity}:\n" + "\n".join(results))
                
            return SkillResult(False, "Invalid action. Use 'add' or 'query'.")
        except ImportError:
            return SkillResult(False, "knowledge_graph.py module not found or networkx missing.")
        except Exception as e:
            return SkillResult(False, f"Knowledge Graph operation failed: {e}")

registry.register(KnowledgeGraphSkill())

class FinanceSkill(Skill):
    """
    LIS 4.0 Financial Orchestration.
    Fetches cryptocurrency prices via CoinGecko.
    """
    name = "get_crypto_price"
    description = "Fetches the current price of a cryptocurrency in USD."

    async def execute(self, coin_id: str, **kwargs) -> SkillResult:
        try:
            import aiohttp
            clean_id = coin_id.lower().strip()
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={clean_id}&vs_currencies=usd"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if clean_id in data:
                            price = data[clean_id]["usd"]
                            return SkillResult(True, f"The current price of {coin_id} is ${price:,.2f} USD.")
                        else:
                            return SkillResult(False, f"Could not find price data for '{coin_id}'.")
                    else:
                        return SkillResult(False, f"CoinGecko API error: {resp.status}")
                        
        except ImportError:
            return SkillResult(False, "aiohttp is not installed.")
        except Exception as e:
            return SkillResult(False, f"Failed to fetch crypto price: {e}")

registry.register(FinanceSkill())

# ---------------------------------------------------------------------------
# Communication & Edge Browser Skills
# ---------------------------------------------------------------------------

class BrowseEdgeSkill(Skill):
    name = "browse_edge"
    description = "Open Microsoft Edge and navigate to a specific URL or perform a web search."
    
    async def execute(self, query_or_url: str, **kwargs) -> SkillResult:
        try:
            import urllib.parse
            import asyncio
            if query_or_url.startswith("http"):
                url = query_or_url
            else:
                url = f"https://www.google.com/search?q={urllib.parse.quote(query_or_url)}"
            
            cmd = f'start msedge "{url}"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return SkillResult(True, f"Opened Edge for: {query_or_url}")
        except Exception as e:
            return SkillResult(False, f"Failed to open Edge: {e}")

class SendEmailSkill(Skill):
    name = "send_email"
    description = "Open Microsoft Edge to compose an email via Gmail."
    
    async def execute(self, to: str = "", subject: str = "", body: str = "", **kwargs) -> SkillResult:
        try:
            import urllib.parse
            import asyncio
            
            url = f"https://mail.google.com/mail/?view=cm&fs=1"
            if to: url += f"&to={urllib.parse.quote(to)}"
            if subject: url += f"&su={urllib.parse.quote(subject)}"
            if body: url += f"&body={urllib.parse.quote(body)}"
            
            cmd = f'start msedge "{url}"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return SkillResult(True, "Opened Gmail compose window in Edge.")
        except Exception as e:
            return SkillResult(False, f"Failed to open Email: {e}")

class WhatsAppSkill(Skill):
    name = "send_whatsapp"
    description = "Open Microsoft Edge to send a WhatsApp message."
    
    async def execute(self, phone: str = "", message: str = "", **kwargs) -> SkillResult:
        try:
            import urllib.parse
            import asyncio
            
            url = "https://web.whatsapp.com/send?"
            if phone:
                clean_phone = ''.join(c for c in phone if c.isdigit() or c == '+')
                url += f"phone={clean_phone}&"
            if message:
                url += f"text={urllib.parse.quote(message)}"
            
            cmd = f'start msedge "{url}"'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return SkillResult(True, "Opened WhatsApp Web in Edge.")
        except Exception as e:
            return SkillResult(False, f"Failed to open WhatsApp: {e}")

registry.register(BrowseEdgeSkill())
registry.register(SendEmailSkill())
registry.register(WhatsAppSkill())
