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
            except Exception:
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
        except Exception:
            return SkillResult(False, f"Couldn't find {app_name}.")
registry.register(LaunchAppSkill())

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


# Note: Persistence is handled in memory.py, these are the action wrappers.
registry.register(SystemKeysSkill())

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


# Swarm Agents (Phase 3)
registry.register(ComputerControlSkill())

