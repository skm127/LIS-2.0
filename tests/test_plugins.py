import pytest
from pathlib import Path
import ast
import plugin_loader

def test_all_plugins_load_cleanly():
    """
    Test that all plugins parse cleanly and there are no syntax errors.
    This prevents plugins from silently failing to load in CI.
    """
    plugin_loader.discover_plugins()
    
    import skills
    loaded_skills = skills.registry.list_all()
    assert len(loaded_skills) >= 10, f"Expected at least 10 skills, but only got {len(loaded_skills)}"
    
    # assert nothing was silently skipped due to SyntaxError
    plugin_dir = Path(__file__).parent.parent / "plugins" / "core"
    for f in plugin_dir.glob("*.py"):
        try:
            ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as e:
            pytest.fail(f"SyntaxError in {f.name}: {e}")
