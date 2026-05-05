"""
LIS Action Executor — AppleScript-based system actions.

Execute actions IMMEDIATELY, before generating any LLM response.
Each function returns {"success": bool, "confirmation": str}.
"""

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger("LIS.actions")

DESKTOP_PATH = Path.home() / "Desktop"


async def _mark_terminal_as_LIS(revert_after: float = 5.0):
    """Placeholder for Windows — theme color switching is Terminal-specific."""
    pass


async def _revert_terminal_theme(profile_name: str):
    """Placeholder for Windows."""
    pass


async def open_terminal(command: str = "") -> dict:
    """Open Windows Command Prompt and optionally run a command."""
    try:
        if command:
            # cmd /k keeps the window open after execution
            cmd_proc = f'start cmd.exe /k "{command}"'
        else:
            cmd_proc = 'start cmd.exe'
        
        # Use shell=True for 'start' command on Windows
        proc = await asyncio.create_subprocess_shell(
            cmd_proc,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return {
            "success": True,
            "confirmation": "Terminal is open, sir.",
        }
    except Exception as e:
        log.error(f"open_terminal failed: {e}")
        return {"success": False, "confirmation": "I couldn't open the terminal, sir."}



async def open_browser(url: str, browser: str = "msedge") -> dict:
    """Open URL in user's default browser on Windows."""
    try:
        # 'start' uses the default browser associated with HTTP/HTTPS
        cmd = f'start "" "{url}"'
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return {
            "success": True,
            "confirmation": f"Pulled that up for you, sir.",
        }
    except Exception as e:
        log.error(f"open_browser failed: {e}")
        return {"success": False, "confirmation": "I had trouble opening the browser, sir."}


# Keep backward compat
async def open_chrome(url: str) -> dict:
    return await open_browser(url, "msedge")


async def open_claude_in_project(project_dir: str, prompt: str) -> dict:
    """Open cmd, cd to project dir, run Claude Code interactively on Windows."""
    # Write prompt to CLAUDE.md — claude reads this automatically
    claude_md = Path(project_dir) / "CLAUDE.md"
    claude_md.write_text(f"# Task\n\n{prompt}\n\nBuild this completely. If web app, make index.html work standalone.\n")

    try:
        # Launch claude interactive — it reads CLAUDE.md on its own
        # Using /d for cd to handle drive changes correctly on Windows
        cmd = f'start cmd.exe /k "cd /d {project_dir} && claude --dangerously-skip-permissions"'
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return {
            "success": True,
            "confirmation": "Claude Code is running in Terminal, sir. You can watch the progress."
        }
    except Exception as e:
        log.error(f"open_claude_in_project failed: {e}")
        return {"success": False, "confirmation": "Had trouble spawning Claude Code, sir."}


async def prompt_existing_terminal(project_name: str, prompt: str) -> dict:
    """Simplified for Windows: opens a new terminal in the project directory."""
    project_dir = str(DESKTOP_PATH / project_name)
    if os.path.exists(project_dir):
        return await open_claude_in_project(project_dir, prompt)
    return {"success": False, "confirmation": f"Couldn't find the {project_name} project, sir."}


async def get_chrome_tab_info() -> dict:
    """Placeholder for Windows — requires browser-specific APIs or extensions."""
    return {}



async def monitor_build(project_dir: str, ws=None, synthesize_fn=None) -> None:
    """Monitor a Claude Code build for completion. Notify via WebSocket when done."""
    import base64

    output_file = Path(project_dir) / ".LIS_output.txt"
    start = time.time()
    timeout = 600  # 10 minutes

    while time.time() - start < timeout:
        await asyncio.sleep(5)
        if output_file.exists():
            content = output_file.read_text()
            if "--- LIS TASK COMPLETE ---" in content:
                log.info(f"Build complete in {project_dir}")
                if ws and synthesize_fn:
                    try:
                        msg = "The build is complete, sir."
                        audio_bytes = await synthesize_fn(msg)
                        if audio_bytes:
                            encoded = base64.b64encode(audio_bytes).decode()
                            await ws.send_json({"type": "status", "state": "speaking"})
                            await ws.send_json({"type": "audio", "data": encoded, "text": msg})
                            await ws.send_json({"type": "status", "state": "idle"})
                    except Exception as e:
                        log.warning(f"Build notification failed: {e}")
                return

    log.warning(f"Build timed out in {project_dir}")


async def execute_action(intent: dict, projects: list = None) -> dict:
    """Route a classified intent to the right action function.

    Args:
        intent: {"action": str, "target": str} from classify_intent()
        projects: list of known project dicts for resolving working dirs

    Returns: {"success": bool, "confirmation": str, "project_dir": str | None}
    """
    action = intent.get("action", "chat")
    target = intent.get("target", "")

    if action == "open_terminal":
        result = await open_terminal("claude --dangerously-skip-permissions")
        result["project_dir"] = None
        return result

    elif action == "browse":
        if target.startswith("http://") or target.startswith("https://"):
            url = target
        else:
            url = f"https://www.google.com/search?q={quote(target)}"

        # Detect which browser user wants
        target_lower = target.lower()
        if "firefox" in target_lower:
            browser = "firefox"
        else:
            browser = "chrome"

        result = await open_browser(url, browser)
        result["project_dir"] = None
        return result

    elif action == "build":
        # Create project folder on Desktop, spawn Claude Code
        project_name = _generate_project_name(target)
        project_dir = str(DESKTOP_PATH / project_name)
        os.makedirs(project_dir, exist_ok=True)
        result = await open_claude_in_project(project_dir, target)
        result["project_dir"] = project_dir
        return result

    else:
        return {"success": False, "confirmation": "", "project_dir": None}


def _generate_project_name(prompt: str) -> str:
    """Generate a kebab-case project folder name from the prompt."""
    # First: check for a quoted name like "tiktok-analytics-dashboard"
    quoted = re.search(r'"([^"]+)"', prompt)
    if quoted:
        name = quoted.group(1).strip()
        # Already kebab-case or close to it
        name = re.sub(r"[^a-zA-Z0-9\s-]", "", name).strip()
        if name:
            return re.sub(r"[\s]+", "-", name.lower())

    # Second: check for "called X" or "named X" pattern
    called = re.search(r'(?:called|named)\s+(\S+(?:[-_]\S+)*)', prompt, re.IGNORECASE)
    if called:
        name = re.sub(r"[^a-zA-Z0-9-]", "", called.group(1))
        if len(name) > 3:
            return name.lower()

    # Fallback: extract meaningful words
    words = re.sub(r"[^a-zA-Z0-9\s]", "", prompt.lower()).split()
    skip = {"a", "the", "an", "me", "build", "create", "make", "for", "with", "and",
            "to", "of", "i", "want", "need", "new", "project", "directory", "called",
            "on", "desktop", "that", "application", "app", "full", "stack", "simple",
            "web", "page", "site", "named"}
    meaningful = [w for w in words if w not in skip and len(w) > 2][:4]
    return "-".join(meaningful) if meaningful else "LIS-project"
