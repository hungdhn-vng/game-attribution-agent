from gaa.analytics.adtributor import adtributor_dimension


def test_isolates_the_dominant_element():
    # SEA collapses 1000->400, NA barely moves 800->770
    forecast = {"SEA": 1000.0, "NA": 800.0}
    actual = {"SEA": 400.0, "NA": 770.0}
    res = adtributor_dimension(forecast, actual)
    top = res["elements"][0]
    assert top["key"] == "SEA"
    assert 0.9 <= top["ep"] <= 1.0          # SEA explains ~95% of the drop
    assert res["surprise"] >= 0             # JS-divergence based, non-negative


def test_explanatory_power_signs_track_aggregate():
    # aggregate fell 200->150 (-50); A drove it, B offset
    res = adtributor_dimension({"A": 100.0, "B": 100.0}, {"A": 40.0, "B": 110.0})
    eps = {e["key"]: e["ep"] for e in res["elements"]}
    assert eps.get("A", 0) > 0


def test_handles_zero_segment_without_error():
    res = adtributor_dimension({"X": 100.0, "Y": 50.0}, {"X": 0.0, "Y": 50.0})
    assert res["elements"][0]["key"] == "X"
