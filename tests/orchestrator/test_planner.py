from gaa.orchestrator.planner import parse_query
from gaa.render.markdown import to_markdown
from gaa.schema.hypothesis import AttributionHypothesis, Causes
from gaa.schema.confidence import Confidence


def test_parse_detects_metric_and_direction():
    p = parse_query("why did revenue drop 25% in May?")
    assert p["metric"] == "revenue" and p["direction"] == "down"


def test_parse_open_ended_is_scan():
    p = parse_query("what's going on with my game?")
    assert p["metric"] is None  # scan mode


def test_markdown_includes_story_and_confidence():
    h = AttributionHypothesis(main_story="Mostly internal.",
                              confidence=Confidence(likelihood="Likely",
                                                    evidence_quality="Moderate"),
                              causes=Causes())
    md = to_markdown(h)
    assert "Mostly internal." in md and "Likely" in md and "Moderate" in md
