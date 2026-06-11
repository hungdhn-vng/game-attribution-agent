import pandas as pd
from gaa.store.metrics_store import MetricsStore
from gaa.schema.canonical import validate_canonical


def _canon():
    return validate_canonical(pd.DataFrame({
        "date": pd.to_datetime(["2026-05-01", "2026-05-02"]),
        "metric": ["dau", "dau"], "value": [100.0, 90.0],
    }))


def test_save_and_load(tmp_path):
    store = MetricsStore(str(tmp_path))
    store.save("MyGame", _canon())
    df = store.load("MyGame")
    assert len(df) == 2 and set(df["metric"]) == {"dau"}


def test_load_missing_raises(tmp_path):
    store = MetricsStore(str(tmp_path))
    import pytest
    with pytest.raises(FileNotFoundError):
        store.load("ghost")
