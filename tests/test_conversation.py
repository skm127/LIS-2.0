import pytest
from conversation import PlanningSession

def test_modify_plan_add_is_not_duplicated():
    s = PlanningSession()
    s.modify_plan("add a contact form")
    assert s.current_plan.features == ["contact form"]   # not duplicated
