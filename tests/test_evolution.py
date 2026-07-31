import pytest
from evolution import TemplateEvolver

def test_analyze_failures_on_empty_db(tmp_path):
    e = TemplateEvolver(db_path=str(tmp_path/"fresh.db"), templates_dir=str(tmp_path/"none"))
    result = e.analyze_failures("build")   # must not raise
    assert result.total_failures == 0
