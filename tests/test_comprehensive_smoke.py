import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import asyncio

# ── 1. Memory round-trip ──
def test_memory_remember_and_recall():
    import memory
    memory.remember("test_key_smoke", "smoke test value 12345")
    result = memory.recall("smoke test")
    assert result is not None
    assert len(result) > 0
    # No 'forget' method exists — clean up manually via DB
    try:
        conn = memory._get_db()
        conn.execute("DELETE FROM memories WHERE content LIKE '%smoke test value 12345%'")
        conn.commit()
        conn.close()
    except Exception:
        pass  # cleanup is best-effort

# ── 2. Brain intent classification ──
# CognitiveCore.classify_intent(user_text, sentiment_data) is the real API
def test_brain_classify_intent():
    from brain import CognitiveCore
    core = CognitiveCore()
    # classify_intent needs (user_text, sentiment_data_dict)
    result = core.classify_intent("open YouTube", {"signals": {}, "intent": ""})
    assert isinstance(result, str)
    assert result == "command"  # starts with "open "

def test_brain_classify_build():
    from brain import CognitiveCore
    core = CognitiveCore()
    result = core.classify_intent("build me a todo app", {"signals": {}, "intent": ""})
    assert isinstance(result, str)
    # No "open/play/search" prefix → falls to casual_chat (no LLM intent provided)
    assert result in ["casual_chat", "seeking_help", "command", "giving_info"]

# ── 3. Empathy detection ──
# EmpathyEngine has no detect_signals method; detect_text_signals is a module-level function
def test_empathy_detect():
    from empathy import detect_text_signals
    signals = detect_text_signals("I'm feeling really frustrated with this project")
    assert isinstance(signals, dict)

def test_empathy_engine_init():
    from empathy import EmpathyEngine
    engine = EmpathyEngine()
    assert engine.rapport == 90.0
    assert engine.current_state is not None

# ── 4. Work mode ──
# WorkSession, not WorkModeManager
def test_work_mode_toggle():
    from work_mode import WorkSession
    ws = WorkSession()
    assert ws.active is False  # starts inactive
    assert ws.status == "idle"

# ── 5. Conversation session ──
def test_conversation_session_lifecycle():
    from conversation import PlanningSession
    s = PlanningSession()
    assert s.is_active
    s.add_exchange("user", "Build me a website")
    s.add_decision("project", "my-website")
    assert s.current_plan.project == "my-website"
    s.modify_plan("add a contact form")
    assert "contact form" in s.current_plan.features
    assert s.current_plan.features.count("contact form") == 1  # NOT duplicated
    s.modify_plan("remove contact form")
    assert "contact form" not in [f for f in s.current_plan.features if "contact form" in f]
    context = s.get_context()
    assert "PLANNING SESSION CONTEXT" in context
    s.close()
    assert not s.is_active

# ── 6. Evolution on fresh DB ──
def test_evolution_fresh_db(tmp_path):
    from evolution import TemplateEvolver
    e = TemplateEvolver(db_path=str(tmp_path / "fresh.db"), templates_dir=str(tmp_path / "tpl"))
    result = e.analyze_failures("build")
    assert result.total_failures == 0
    assert len(result.suggested_improvements) > 0
    e.close()

# ── 7. Monitor first-message check ──
def test_monitor_first_message():
    from monitor import ConversationMonitor
    m = ConversationMonitor()
    m.add_message("lis", "I'd be happy to help!")
    assert len(m.issues) > 0  # Should flag bad pattern

def test_monitor_complaint_detection():
    from monitor import ConversationMonitor
    m = ConversationMonitor()
    m.add_message("lis", "Hello sir, how can I assist you today?")
    m.add_message("user", "you forgot what I told you earlier")
    assert any("COMPLAINT" in i for i in m.issues)

# ── 8. Dispatch registry ──
def test_dispatch_registry_lifecycle():
    from dispatch_registry import DispatchRegistry
    dr = DispatchRegistry()
    did = dr.register("smoke-test-project", "C:/tmp/smoke", "test prompt")
    assert did > 0
    active = dr.get_active()
    assert any(d["project_name"] == "smoke-test-project" for d in active)
    dr.update_status(did, "completed", response="done", summary="test complete")
    prompt_text = dr.format_for_prompt()
    assert isinstance(prompt_text, str)

# ── 9. AB Testing ──
# ABTester uses select_template(task_type) → (PromptTemplate, experiment_id)
# and record_result(experiment_id, template_version, success)
def test_ab_testing_lifecycle(tmp_path):
    from ab_testing import ABTester
    ab = ABTester(
        db_path=str(tmp_path / "ab_smoke.db"),
        templates_dir=str(tmp_path / "tpl"),
    )
    template, experiment_id = ab.select_template("smoke_test")
    assert template is not None
    assert isinstance(experiment_id, str)
    ab.record_result(experiment_id, template.version, success=True)
    stats = ab.get_version_stats("smoke_test")
    assert isinstance(stats, dict)
    ab.close()

# ── 10. Tracking ──
# SuccessTracker uses log_task() not record(), and get_success_rate returns a dict
def test_tracking_success_rate(tmp_path):
    from tracking import SuccessTracker
    tracker = SuccessTracker(db_path=str(tmp_path / "tracking_smoke.db"))
    tracker.log_task("smoke", "test prompt 1", success=True)
    tracker.log_task("smoke", "test prompt 2", success=False)
    rate = tracker.get_success_rate("smoke")
    assert isinstance(rate, dict)
    assert rate["total"] == 2
    assert rate["passed"] == 1
    assert rate["failed"] == 1
    assert 0 <= rate["rate"] <= 100
    tracker.close()

# ── 11. Learning context suggestions ──
# UsageLearner, not ContextLearner; suggest_context(user_text, known_projects)
def test_learning_context(tmp_path):
    from learning import UsageLearner
    ul = UsageLearner(db_path=str(tmp_path / "learning_smoke.db"))
    # With no known projects, returns None
    result = ul.suggest_context("build", known_projects=None)
    assert result is None
    # With a matching project, returns a ContextSuggestion
    result = ul.suggest_context("build the dashboard", known_projects=[
        {"name": "dashboard", "path": "C:/projects/dashboard"}
    ])
    assert result is not None
    assert result.confidence > 0
    ul.close()

# ── 12. Knowledge graph ──
# KnowledgeGraph has add_relation(subject, predicate, obj) — no add_entity
def test_knowledge_graph(tmp_path):
    from knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph(db_path=str(tmp_path / "kg_smoke.json"))
    kg.add_relation("Python", "used_for", "LIS")
    result = kg.query("Python")
    assert result is not None
    assert len(result) > 0
    assert any("used_for" in r for r in result)

# ── 13. Screen formatting ──
# format_windows_for_context is the real function, not format_code_block
def test_screen_formatting():
    from screen import format_windows_for_context
    result = format_windows_for_context([
        {"app": "Code", "title": "test.py - Visual Studio Code"},
        {"app": "Chrome", "title": "Google"},
    ])
    assert "Code" in result
    assert "test.py" in result

def test_screen_formatting_empty():
    from screen import format_windows_for_context
    result = format_windows_for_context([])
    assert result == ""

# ── 14. Actions project name generation ──
def test_project_name_generation():
    from actions import _generate_project_name
    name = _generate_project_name('build me a "tiktok-analytics" dashboard')
    assert "tiktok" in name.lower()

# ── 15. Env loader ──
def test_env_loader():
    from env_loader import load_env, reload_env
    load_env()
    reload_env()
    # Should not crash
    assert True

# ── 16. LLM Providers status ──
def test_llm_providers_status():
    from llm_providers import LLMProviders
    llm = LLMProviders()
    status = llm.get_status()
    assert isinstance(status, dict)
    assert "groq" in status or "gemini" in status or "nvidia" in status

# ── 17. split_skills idempotency ──
import subprocess
def test_split_skills_idempotent():
    result = subprocess.run(
        [sys.executable, "split_skills.py"],
        capture_output=True, text=True, cwd="C:/Users/SKM/jarvis"
    )
    assert result.returncode == 0
    assert "already split" in result.stdout.lower()
