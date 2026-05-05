"""
LIS Plugin System v1.0 — Auto-discover and load skills from plugins/ directory.

Drop a .py file in plugins/ with a class that inherits from Skill,
and it auto-registers when the server starts.

Example plugin (plugins/my_skill.py):

    from skills import Skill, SkillResult, registry

    class MyCustomSkill(Skill):
        name = "my_skill"
        description = "Does something cool."

        async def execute(self, **kwargs) -> SkillResult:
            return SkillResult(True, "Done!")

    registry.register(MyCustomSkill())
"""

import importlib
import importlib.util
import logging
import os
from pathlib import Path

log = logging.getLogger("lis.plugins")

PLUGINS_DIR = Path(__file__).parent / "plugins"


def discover_plugins() -> int:
    """Scan plugins/ directory and import all .py files.

    Each plugin is expected to self-register its skills
    by calling registry.register() at module level.
    Returns the number of plugins loaded.
    """
    if not PLUGINS_DIR.exists():
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        # Create example plugin
        _create_example_plugin()
        log.info(f"Created plugins/ directory with example plugin")
        return 0

    loaded = 0
    for file in PLUGINS_DIR.glob("*.py"):
        if file.name.startswith("_"):
            continue  # Skip __init__.py, __pycache__, etc.

        module_name = f"plugins.{file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                loaded += 1
                log.info(f"Loaded plugin: {file.name}")
        except Exception as e:
            log.error(f"Failed to load plugin {file.name}: {e}")

    return loaded


def _create_example_plugin():
    """Create an example plugin file for reference."""
    example = PLUGINS_DIR / "_example_plugin.py"
    example.write_text('''"""
Example LIS Plugin — Use this as a template for custom skills.

To create a new skill:
1. Copy this file and rename it (e.g., my_skill.py)
2. Modify the class name, skill name, description, and execute method
3. Restart the server — your skill auto-loads!

The LLM will use your skill when the user's intent matches.
Add a corresponding action tag in the system prompt for best results.
"""

from skills import Skill, SkillResult, registry


class ExamplePlugin(Skill):
    name = "example_plugin"
    description = "An example skill that demonstrates the plugin system."

    async def execute(self, message: str = "Hello!", **kwargs) -> SkillResult:
        return SkillResult(True, f"Example plugin says: {message}")


# Uncomment the line below to register this plugin:
# registry.register(ExamplePlugin())
''')
