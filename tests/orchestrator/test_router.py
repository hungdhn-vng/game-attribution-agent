from gaa.orchestrator.router import classify_intent


def test_setup_intent():
    assert classify_intent("connect my data", has_active_profile=False) == "setup"
    assert classify_intent("here is my CSV to onboard", has_active_profile=True) == "setup"


def test_analysis_intent():
    assert classify_intent("why did revenue drop?", has_active_profile=True) == "analyze"


def test_defaults_to_setup_without_profile():
    assert classify_intent("what is going on?", has_active_profile=False) == "setup"
