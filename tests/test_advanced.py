"""Tests for mktsim.advanced_intraday + record plumbing."""

import csv
import math
import statistics

import pytest

import mktsim
from mktsim import BAR_FIELDS, adv_id_sim_1, adv_id_sim_2, bars_ex_to_csv
from mktsim import record_closes, record_volumes
from mktsim import cli as cli_mod


def test_record_shape():
    bars = adv_id_sim_1(30, 100.0, seed=1)
    assert len(bars) == 30
    assert tuple(bars[0].keys()) == BAR_FIELDS
    assert len(BAR_FIELDS) == 16


def test_bar_invariants():
    bars = adv_id_sim_1(100, 100.0, 1.0, seed=2)
    for b in bars:
        assert b["high"] >= max(b["open"], b["close"])
        assert b["low"] <= min(b["open"], b["close"])
        assert b["bid"] <= b["low"] and b["ask"] >= b["high"]
        assert b["spread_bps"] >= 0
        assert b["low"] <= b["vwap"] <= b["high"]
        assert isinstance(b["volume"], int) and b["volume"] >= 0
        assert isinstance(b["trades"], int) and b["trades"] >= 0
        assert b["buy_vol"] + b["sell_vol"] == b["volume"]
        expect_imb = round((b["buy_vol"] - b["sell_vol"]) / b["volume"], 3) if b["volume"] else 0.0
        assert b["imbalance"] == pytest.approx(expect_imb)
        assert b["phase"] in ("auction", "morning", "midday", "afternoon", "close")
        assert isinstance(b["halted"], bool)
        assert all(p > 0 for p in (b["open"], b["high"], b["low"], b["close"], b["vwap"]))


def test_lot_size_multiple():
    bars = adv_id_sim_1(50, 100.0, seed=3, lot_size=10)
    assert all(b["volume"] % 10 == 0 for b in bars)
    assert sum(b["volume"] for b in bars) > 0


def test_nse_clock_375():
    bars = adv_id_sim_1(375, 100.0, seed=4)
    assert bars[0]["time"] == "09:15"
    assert bars[-1]["time"] == "15:29"  # 1-minute bar opens (closes 15:30)
    assert [b["time"] for b in bars] == sorted(b["time"] for b in bars)


def test_session_none_index():
    bars = adv_id_sim_1(20, 100.0, seed=4, session=None)
    assert [b["time"] for b in bars] == list(range(20))


def test_phases_present():
    bars = adv_id_sim_1(375, 100.0, seed=5)
    phases = [b["phase"] for b in bars]
    assert phases[0] == "auction" and phases[-1] == "close"
    assert {"morning", "midday", "afternoon"} <= set(phases)


def test_determinism():
    assert adv_id_sim_1(40, 50.0, 1.0, seed=42) == adv_id_sim_1(40, 50.0, 1.0, seed=42)
    assert adv_id_sim_1(40, 50.0, 1.0, seed=42) != adv_id_sim_1(40, 50.0, 1.0, seed=43)


def test_validation():
    with pytest.raises((TypeError, ValueError)):
        adv_id_sim_1(1, 100.0)
    with pytest.raises(ValueError):
        adv_id_sim_1(10, -5.0)
    with pytest.raises(ValueError):
        adv_id_sim_1(10, 100.0, -100.0)
    with pytest.raises(ValueError):
        adv_id_sim_1(10, 100.0, 1000.1)
    with pytest.raises(TypeError):
        adv_id_sim_1(10, 100.0, True)
    with pytest.raises(ValueError):
        adv_id_sim_1(10, 100.0, lot_size=0)
    with pytest.raises(ValueError):
        adv_id_sim_1(10, 100.0, sub_ticks=0)
    with pytest.raises(ValueError):
        adv_id_sim_1(10, 100.0, session="NYSE")
    with pytest.raises(ValueError):
        adv_id_sim_1(10, 100.0, circuit_pct=1.5)


def test_target_mean():
    ends = [adv_id_sim_1(200, 100.0, 2.0, seed=s)[-1]["close"] for s in range(25)]
    assert statistics.mean(ends) == pytest.approx(102.0, abs=4.0)
    assert min(ends) < 102.0 < max(ends)


def test_target_direction():
    up = statistics.mean(adv_id_sim_1(150, 100.0, 5.0, seed=s)[-1]["close"] for s in range(15))
    down = statistics.mean(adv_id_sim_1(150, 100.0, -5.0, seed=s)[-1]["close"] for s in range(15))
    assert up > down + 5.0


def test_sim2_more_volatile():
    def day_range(seed, func):
        b = func(200, 100.0, 0.0, seed=seed)
        return max(x["high"] for x in b) - min(x["low"] for x in b)

    r1 = statistics.mean(day_range(s, adv_id_sim_1) for s in range(10))
    r2 = statistics.mean(day_range(s, adv_id_sim_2) for s in range(10))
    assert r2 > r1 + 0.5


def test_sim2_event_defaults():
    import inspect

    p1 = inspect.signature(adv_id_sim_1).parameters
    p2 = inspect.signature(adv_id_sim_2).parameters
    assert p2["circuit_pct"].default == 0.05
    assert p2["gap_std"].default == 0.012
    assert p1["circuit_pct"].default == 0.10


def test_circuit_halts():
    bars = adv_id_sim_1(60, 100.0, 0.0, seed=1, circuit_pct=0.001)
    halted = [b for b in bars if b["halted"]]
    assert halted, "a 0.1% band must halt"
    for b in halted:
        assert b["volume"] == 0 and b["trades"] == 0
        assert b["open"] == b["high"] == b["low"] == b["close"]
        assert b["close"] in (100.10, 99.90)


def test_no_circuit_clean():
    bars = adv_id_sim_1(60, 100.0, seed=1, circuit_pct=0)
    assert not any(b["halted"] for b in bars)


def test_fat_tails():
    rets = []
    for s in range(8):
        closes = [b["close"] for b in adv_id_sim_1(300, 100.0, 0.0, seed=s)]
        rets += [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = statistics.mean(rets)
    kurt = statistics.mean([(r - mean) ** 4 for r in rets]) / statistics.variance(rets) ** 2
    assert kurt > 3.0


def test_u_shaped_volume():
    vols = [b["volume"] for b in adv_id_sim_1(375, 100.0, 0.0, seed=4)]
    n = len(vols)
    thirds = (sum(vols[:n // 3]), sum(vols[n // 3:2 * n // 3]), sum(vols[2 * n // 3:]))
    assert thirds[0] > thirds[1] and thirds[2] > thirds[1]


def test_sub_ticks_one_and_generic_session():
    bars = adv_id_sim_2(25, 50.0, -2.0, seed=9, session=None, sub_ticks=1)
    assert len(bars) == 25 and bars[0]["phase"] == "auction"


def test_record_adapters():
    bars = adv_id_sim_1(20, 100.0, seed=1)
    assert record_closes(bars) == [b["close"] for b in bars]
    assert record_volumes(bars) == [b["volume"] for b in bars]
    with pytest.raises(ValueError):
        record_closes([])
    with pytest.raises(TypeError):
        record_closes([{"nope": 1}])


def test_bars_ex_csv_roundtrip(tmp_path):
    bars = adv_id_sim_1(20, 100.0, seed=1)
    path = str(tmp_path / "ex.csv")
    assert bars_ex_to_csv(bars, path) == path
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0].keys()) == list(BAR_FIELDS)
    assert len(rows) == 20
    assert float(rows[0]["open"]) == bars[0]["open"]
    with pytest.raises(ValueError):
        bars_ex_to_csv([], str(tmp_path / "empty.csv"))


def test_top_level_exports():
    for name in ("adv_id_sim_1", "adv_id_sim_2", "record_closes",
                 "record_volumes", "bars_ex_to_csv", "BAR_FIELDS"):
        assert name in mktsim.__all__
    assert mktsim.adv_id_sim_1 is adv_id_sim_1


def test_cli_handles_records():
    values = {"nums": 30, "initial_price": 100.0, "target_pct": 1.0,
              "seed": 6, "session": "NSE", "tick_size": 0.05, "lot_size": 1,
              "base_tick_vol": 0.0012, "sub_ticks": 5,
              "circuit_pct": 0.10, "gap_std": 0.004}
    prices, volumes, ohlcv = cli_mod.run_simulation(adv_id_sim_1, values, bars=75, fmt="ohlcv")
    assert len(prices) == 30 and ohlcv is not None and len(ohlcv) == 30
    assert all(set(b) >= {"open", "high", "low", "close", "volume"} for b in ohlcv)
    p2, v2, t2 = cli_mod.run_simulation(adv_id_sim_1, values, bars=75, fmt="ticks")
    assert t2 is None and p2 == prices and v2 == volumes
