"""
LIS — Shared .env file loader.

Centralised so the identical loading logic isn't copy-pasted into
server.py, healer.py, monitor.py, etc.
"""

import os
from pathlib import Path


def load_env(env_path: Path | str | None = None) -> None:
    """Read a .env file and set missing keys into ``os.environ``.

    Keys that already exist in the environment are **not** overwritten
    (``os.environ.setdefault`` semantics).

    Args:
        env_path: Explicit path to the .env file.  When *None* the file is
                  looked up next to **this** module (i.e. the project root).
    """
    if env_path is None:
        env_path = Path(__file__).parent / ".env"
    else:
        env_path = Path(env_path)

    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def reload_env(env_path: Path | str | None = None) -> None:
    """Read a .env file and overwrite keys into ``os.environ``.
    This is used for live toggling of settings without a server restart.
    """
    if env_path is None:
        env_path = Path(__file__).parent / ".env"
    else:
        env_path = Path(env_path)

    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip().strip('"').strip("'")
