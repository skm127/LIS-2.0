"""
LIS System Tray — Run LIS as a background Windows service.

Creates a system tray icon with right-click menu for controlling LIS.
Launches the server in the background and opens the browser UI on demand.

Usage:
    python tray.py          # Start LIS with system tray
    pythonw tray.py         # Start silently (no console)
"""

import os
import sys
import time
import signal
import subprocess
import threading
import webbrowser
import logging
from pathlib import Path

log = logging.getLogger("lis.tray")

PORT = int(os.getenv("LIS_PORT", "8340"))
SERVER_SCRIPT = Path(__file__).parent / "server.py"
ICON_PATH = Path(__file__).parent / "frontend" / "public" / "icon-192.png"

_server_proc = None


def _start_server():
    """Start the LIS server as a subprocess."""
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        return  # Already running

    env = os.environ.copy()
    _server_proc = subprocess.Popen(
        [sys.executable, str(SERVER_SCRIPT), "--port", str(PORT)],
        cwd=str(SERVER_SCRIPT.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    log.info(f"LIS server started (PID: {_server_proc.pid}) on port {PORT}")


def _stop_server():
    """Stop the LIS server subprocess."""
    global _server_proc
    if _server_proc:
        try:
            _server_proc.terminate()
            _server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
        except Exception:
            pass
        _server_proc = None
        log.info("LIS server stopped")


def _open_ui(icon=None, item=None):
    """Open the LIS UI in the default browser."""
    webbrowser.open(f"http://localhost:{PORT}")


def _restart_server(icon=None, item=None):
    """Restart the LIS server."""
    _stop_server()
    time.sleep(1)
    _start_server()


def _quit(icon, item):
    """Clean shutdown."""
    _stop_server()
    icon.stop()


def _create_default_icon():
    """Create a simple icon if none exists."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Draw a cyan circle with "L" for LIS
        draw.ellipse([4, 4, 60, 60], fill=(14, 165, 233, 255))
        draw.text((22, 16), "L", fill=(255, 255, 255, 255))
        return img
    except ImportError:
        return None


def run_tray():
    """Main entry point — start server and show tray icon."""
    try:
        import pystray
        from pystray import MenuItem as Item
    except ImportError:
        print("pystray not installed. Run: pip install pystray Pillow")
        print("Falling back to console mode...")
        _start_server()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            _stop_server()
        return

    # Load or create icon
    icon_image = None
    if ICON_PATH.exists():
        try:
            from PIL import Image
            icon_image = Image.open(str(ICON_PATH))
            icon_image = icon_image.resize((64, 64))
        except Exception:
            icon_image = _create_default_icon()
    else:
        icon_image = _create_default_icon()

    if not icon_image:
        print("Could not create tray icon. Install Pillow: pip install Pillow")
        _start_server()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            _stop_server()
        return

    # Start server
    _start_server()

    # Wait briefly for server to boot
    time.sleep(2)

    # Create tray icon
    menu = pystray.Menu(
        Item("Open LIS", _open_ui, default=True),
        Item("Restart Server", _restart_server),
        pystray.Menu.SEPARATOR,
        Item("Quit", _quit),
    )

    icon = pystray.Icon("LIS", icon_image, "LIS — AI Assistant", menu)

    # Auto-open browser on first launch
    threading.Timer(1.0, _open_ui).start()

    log.info("LIS system tray active")
    icon.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    run_tray()
