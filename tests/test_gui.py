"""Tests for mktsim.gui pure helpers (no window is created)."""

import pytest

from mktsim import gui


def test_discover_finds_core_sims():
    algos = gui.discover_algorithms()
    assert "basic_interaday.basic_id_sim_1" in algos
    assert "basic_interaday.basic_id_sim_4" in algos
    assert "ohlcv.ticks_to_ohlcv" in algos
    # console modules must not leak into the dropdown
    assert not any(label.split(".")[0] in ("cli", "gui") for label in algos)


def test_validate_plain_series():
    assert gui.validate_series([1, 2.5], "x") == [1.0, 2.5]


def test_validate_price_volume_tuple():
    assert gui.validate_series(([10.0, 11.0], [0, 25]), "x") == [10.0, 11.0]


def test_validate_ohlcv_bars_use_closes():
    bars = [
        {"bar": 1, "open": 1.0, "high": 2.0, "low": 1.0, "close": 1.5, "volume": 9},
        {"bar": 2, "open": 1.5, "high": 3.0, "low": 1.2, "close": 2.5, "volume": 7},
    ]
    assert gui.validate_series(bars, "x") == [1.5, 2.5]


def test_validate_rejects_bad_output():
    with pytest.raises(TypeError):
        gui.validate_series("nope", "x")
    with pytest.raises(ValueError):
        gui.validate_series([], "x")
    with pytest.raises(TypeError):
        gui.validate_series([1.0, "x"], "x")
