"""Tests for gaa.sources._index.index_to_100."""
import pytest
from gaa.sources._index import index_to_100


RAW = {
    "2024-01-01": 200.0,
    "2024-01-02": 400.0,
    "2024-01-03": 600.0,
    "2024-01-04": 100.0,
}


def test_first_kept_point_becomes_100():
    result = index_to_100(RAW, "2024-01-01", "2024-01-04")
    assert result["2024-01-01"] == pytest.approx(100.0)


def test_subsequent_points_scaled_relative_to_base():
    result = index_to_100(RAW, "2024-01-01", "2024-01-04")
    # base is 200.0 (value at 2024-01-01)
    assert result["2024-01-02"] == pytest.approx(200.0)  # 400/200 * 100
    assert result["2024-01-03"] == pytest.approx(300.0)  # 600/200 * 100
    assert result["2024-01-04"] == pytest.approx(50.0)   # 100/200 * 100


def test_filters_to_window():
    result = index_to_100(RAW, "2024-01-02", "2024-01-03")
    assert set(result.keys()) == {"2024-01-02", "2024-01-03"}
    # base is 400.0 (value at 2024-01-02)
    assert result["2024-01-02"] == pytest.approx(100.0)
    assert result["2024-01-03"] == pytest.approx(150.0)  # 600/400 * 100


def test_returns_empty_when_fewer_than_2_points_in_window():
    # Only one point in the window
    result = index_to_100(RAW, "2024-01-02", "2024-01-02")
    assert result == {}


def test_returns_empty_when_no_points_in_window():
    result = index_to_100(RAW, "2025-01-01", "2025-01-31")
    assert result == {}


def test_returns_empty_when_base_is_zero():
    raw_with_zero = {"2024-01-01": 0.0, "2024-01-02": 100.0}
    result = index_to_100(raw_with_zero, "2024-01-01", "2024-01-02")
    assert result == {}


def test_window_inclusive_boundaries():
    result = index_to_100(RAW, "2024-01-01", "2024-01-04")
    assert len(result) == 4
