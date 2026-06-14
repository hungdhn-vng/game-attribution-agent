from gaa.core.orchestrator.planner import parse_query
from gaa.core.render.markdown import to_markdown
from gaa.core.schema.hypothesis import AttributionHypothesis, Causes
from gaa.core.schema.confidence import Confidence


def test_parse_detects_metric_and_direction():
    p = parse_query("why did revenue drop 25% in May?")
    assert p["metric"] == "revenue" and p["direction"] == "down"


def test_parse_open_ended_is_scan():
    p = parse_query("what's going on with my game?")
    assert p["metric"] is None  # scan mode


def test_day1_retention_routes_to_d1_not_d7():
    # "day 1 retention" must map to retention_d1; previously the bare alias
    # "retention" on retention_d7 (checked first) hijacked any D1 question.
    p = parse_query("why did my day 1 retention drop?")
    assert p["metric"] == "retention_d1" and p["direction"] == "down"


def test_markdown_includes_story_and_confidence():
    h = AttributionHypothesis(main_story="Mostly internal.",
                              confidence=Confidence(likelihood="Likely",
                                                    evidence_quality="Moderate"),
                              causes=Causes())
    md = to_markdown(h)
    assert "Mostly internal." in md and "Likely" in md and "Moderate" in md
