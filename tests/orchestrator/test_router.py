from gaa.orchestrator.router import classify_intent


def test_setup_intent():
    assert classify_intent("connect my data", has_active_profile=False) == "setup"
    assert classify_intent("here is my CSV to onboard", has_active_profile=True) == "setup"


def test_analysis_intent():
    assert classify_intent("why did revenue drop?", has_active_profile=True) == "analyze"


def test_defaults_to_setup_without_profile():
    assert classify_intent("what is going on?", has_active_profile=False) == "setup"


def test_greeting_with_profile_is_help():
    # The reported bug: "hi, what can you do?" used to run a full analysis.
    assert classify_intent("hi, what can you do?", has_active_profile=True) == "help"
    assert classify_intent("hi", has_active_profile=True) == "help"
    assert classify_intent("hello there", has_active_profile=True) == "help"


def test_capability_question_is_help():
    assert classify_intent("what can you do?", has_active_profile=True) == "help"
    assert classify_intent("who are you?", has_active_profile=True) == "help"
    assert classify_intent("how does this work?", has_active_profile=True) == "help"
    assert classify_intent("help", has_active_profile=True) == "help"


def test_analysis_request_with_help_word_still_analyzes():
    # Contains "help" but is clearly an analysis request — must not be misrouted to help.
    assert classify_intent("help me understand why my dau fell last week",
                           has_active_profile=True) == "analyze"
    assert classify_intent("what happened to my game?", has_active_profile=True) == "analyze"


def test_greeting_without_profile_still_routes_to_setup():
    # No data yet → onboarding guidance takes priority over the help blurb.
    assert classify_intent("hello", has_active_profile=False) == "setup"
