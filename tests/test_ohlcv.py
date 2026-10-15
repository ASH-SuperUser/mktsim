"""Tests for mktsim.ohlcv tick -> OHLCV aggregation + CSV."""

import csv

import pytest

from mktsim.ohlcv import bars_to_csv, simulate_ohlcv, ticks_to_csv, ticks_to_ohlcv
from mktsim import basic_id_sim_1


def test_even_split():
    bars = ticks_to_ohlcv([1, 2, 3, 4, 5, 6], [10, 10, 10, 10, 10, 10], bars=2)
    assert bars == [
        {"bar": 1, "open": 1.0, "high": 3.0, "low": 1.0, "close": 3.0, "volume": 30},
        {"bar": 2, "open": 4.0, "high": 6.0, "low": 4.0, "close": 6.0, "volume": 30},
    ]


def test_single_bar():
    bars = ticks_to_ohlcv([3, 1, 2], bars=1)
    assert bars == [{"bar": 1, "open": 3.0, "high": 3.0, "low": 1.0, "close": 2.0, "volume": 3}]


def test_bars_capped_at_tick_count():
    bars = ticks_to_ohlcv([10, 20], bars=99)
    assert len(bars) == 2
    assert bars[0] == {"bar": 1, "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1}
    assert bars[1]["close"] == 20.0


def test_uneven_split_first_bars_get_extra():
    bars = ticks_to_ohlcv([1, 2, 3, 4, 5], bars=2)
    assert len(bars) == 2
    assert (bars[0]["open"], bars[0]["close"]) == (1.0, 3.0)
    assert (bars[1]["open"], bars[1]["close"]) == (4.0, 5.0)


def test_volume_none_uses_tick_counts():
    bars = ticks_to_ohlcv([1, 2, 3, 4], bars=2)
    assert [b["volume"] for b in bars] == [2, 2]


def test_validation():
    with pytest.raises(ValueError):
        ticks_to_ohlcv([], bars=2)
    with pytest.raises(ValueError):
        ticks_to_ohlcv([1, 2], bars=0)
    with pytest.raises(TypeError):
        ticks_to_ohlcv([1, 2], bars=True)
    with pytest.raises(ValueError):
        ticks_to_ohlcv([1, 2], [1], bars=1)
    with pytest.raises(ValueError):
        ticks_to_ohlcv([1, 2], [1, -1], bars=1)
    with pytest.raises(TypeError):
        ticks_to_ohlcv([1, "x"], bars=1)


def test_simulate_ohlcv_invariants():
    bars = simulate_ohlcv(basic_id_sim_1, 100, 100.0, 0.0, seed=9, bars=10)
    assert len(bars) == 10
    for b in bars:
        assert b["high"] >= max(b["open"], b["close"])
        assert b["low"] <= min(b["open"], b["close"])
        assert b["volume"] > 0
    prices, volumes = basic_id_sim_1(100, 100.0, 0.0, seed=9, return_volumes=True)
    assert bars[0]["open"] == pytest.approx(prices[0])
    assert bars[-1]["close"] == pytest.approx(prices[-1])
    assert sum(b["volume"] for b in bars) == sum(volumes)


def test_simulate_ohlcv_fallback_without_volumes():
    def plain(nums, seed=None):
        return [100.0 + i for i in range(nums)]

    bars = simulate_ohlcv(plain, 6, seed=1, bars=2)
    assert [b["volume"] for b in bars] == [3, 3]


def test_bars_csv_roundtrip(tmp_path):
    bars = ticks_to_ohlcv([1, 5, 2, 4], [4, 4, 4, 4], bars=2)
    path = str(tmp_path / "bars.csv")
    assert bars_to_csv(bars, path) == path
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["close"] for r in rows] == ["5.0", "4.0"]
    assert rows[0].keys() == {"bar", "open", "high", "low", "close", "volume"}


def test_ticks_csv_roundtrip(tmp_path):
    path = str(tmp_path / "ticks.csv")
    assert ticks_to_csv([10.0, 10.5], [0, 25], path) == path
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0] == {"tick": "0", "price": "10.00", "volume": "0"}
    assert rows[1]["volume"] == "25"
