from gaa.sensortower import guard

def _resolver(label):
    return {"self": {"id": 111, "id_type": "app_id"}}.get(label)

def test_need_app_id_when_unresolved():
    out = guard.build("st_app_performance", {"labels": ["self", "ghost"],
                      "start_date": "2024-01-01", "end_date": "2024-03-01"},
                      resolver=_resolver, today="2024-06-01")
    assert out == {"status": "error", "error": "need_app_id", "labels": ["ghost"]}

def test_build_fills_defaults_and_maps_ids():
    out = guard.build("st_app_performance", {"app_ids": [111],
                      "start_date": "2024-01-01", "end_date": "2024-03-01"},
                      resolver=_resolver, today="2024-06-01")
    b = out["built"]
    assert b["st_tool"] == "app_performance_api_v2_app_performance_get"
    p = b["params"]
    assert p["app_id"] == [111]
    assert p["devices"] == ["ios-all", "android-all"]
    assert p["granularity"] == "monthly"
    assert p["bundles"] == ["download_revenue"]
    assert p["countries"] == ["US"]

def test_labels_resolve_and_merge():
    out = guard.build("st_app_performance", {"labels": ["self"], "app_ids": [222],
                      "start_date": "2024-01-01", "end_date": "2024-02-01"},
                      resolver=_resolver, today="2024-06-01")
    assert sorted(out["built"]["params"]["app_id"]) == [111, 222]

def test_default_date_range_90d_when_unspecified():
    out = guard.build("st_app_performance", {"app_ids": [111]},
                      resolver=_resolver, today="2024-06-01")
    p = out["built"]["params"]
    assert p["end_date"] == "2024-06-01" and p["start_date"] == "2024-03-03"  # 90 days back

def test_budget_trim_countries(monkeypatch):
    monkeypatch.setattr(guard, "_CAP", 10)
    out = guard.build("st_app_store", {"app_ids": [111], "countries": ["US","VN","JP","KR","GB"],
                      "start_date": "2024-01-01", "end_date": "2024-01-05"},
                      resolver=_resolver, today="2024-06-01")
    assert len(out["built"]["params"]["countries"]) < 5
    assert "countries" in (out.get("scope_trimmed") or [])

def test_apps_cap_10():
    out = guard.build("st_app_performance", {"app_ids": list(range(20)),
                      "start_date": "2024-01-01", "end_date": "2024-02-01"},
                      resolver=_resolver, today="2024-06-01")
    assert len(out["built"]["params"]["app_id"]) <= 10

def test_unified_uses_unified_app_id():
    out = guard.build("st_unified_app_performance", {"app_ids": [111],
                      "start_date": "2024-01-01", "end_date": "2024-02-01"},
                      resolver=_resolver, today="2024-06-01")
    p = out["built"]["params"]
    assert p["unified_app_id"] == [111] and p["devices"] == ["all"]
    assert out["built"]["st_tool"] == "unified_app_performance_api_v2_unified_app_performance_g"
