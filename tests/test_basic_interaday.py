"""Contract + behaviour tests for mktsim.basic_interaday."""

import statistics

import pytest

from mktsim import basic_interaday as bi


ALL_SIMS = ["basic_id_sim_1", "basic_id_sim_2", "basic_id_sim_3", "basic_id_sim_4"]


def _call(name, nums=50, price=100.0, seed=1, **kw):
    if name == "basic_id_sim_1":
        return bi.basic_id_sim_1(nums, price, kw.pop("profitability", 0.0), seed=seed, **kw)
    if name == "basic_id_sim_2":
        return bi.basic_id_sim_2(nums, price, kw.pop("profitability", 0.0),
                                 kw.pop("max_growth", 0.05), kw.pop("min_growth", -0.05),
                                 seed=seed, **kw)
    if name == "basic_id_sim_3":
        return bi.basic_id_sim_3(nums, price, seed=seed, **kw)
    if name == "basic_id_sim_4":
        return bi.basic_id_sim_4(nums, price, kw.pop("profitability", 0.0),
                                 kw.pop("target_growth", 0.05), seed=seed, **kw)
    raise AssertionError(name)


@pytest.mark.parametrize("name", ALL_SIMS)
def test_contract_length_first_positive(name):
    prices = _call(name, nums=60, price=100.0, seed=11)
    assert len(prices) == 60
    assert all(isinstance(p, float) for p in prices)
    assert all(p > 0 for p in prices)
    # sim_3 opens after an overnight gap; others start exactly at initial.
    if name == "basic_id_sim_3":
        assert prices[0] > 0
    else:
        assert prices[0] == pytest.approx(100.0)


@pytest.mark.parametrize("name", ALL_SIMS)
def test_seed_deterministic(name):
    assert _call(name, seed=42) == _call(name, seed=42)
    assert _call(name, seed=42) != _call(name, seed=43)


def test_bool_rejected_as_int():
    with pytest.raises(TypeError):
        bi.basic_id_sim_1(True, 100.0)
    with pytest.raises(TypeError):
        bi.basic_id_sim_1(10, True)


@pytest.mark.parametrize("bad_nums", [0, 1, -5, 3.5, "10", None])
def test_bad_nums(bad_nums):
    with pytest.raises((TypeError, ValueError)):
        bi.basic_id_sim_1(bad_nums, 100.0)


@pytest.mark.parametrize("bad_price", [0.0, -1.0, float("inf"), float("nan")])
def test_bad_initial_price(bad_price):
    with pytest.raises(ValueError):
        bi.basic_id_sim_1(10, bad_price)


@pytest.mark.parametrize("bad_p", [-1.5, 1.5, float("nan")])
def test_bad_profitability(bad_p):
    with pytest.raises(ValueError):
        bi.basic_id_sim_1(10, 100.0, bad_p)


def test_sim2_clamp_respected():
    prices = bi.basic_id_sim_2(120, 50.0, 0.5, 0.01, -0.01, seed=3)
    steps = [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices))]
    tol = 0.01 / 50.0  # half-cent display rounding
    assert min(steps) >= -0.01 - tol
    assert max(steps) <= 0.01 + tol


def test_sim2_bad_bounds():
    with pytest.raises(ValueError):
        bi.basic_id_sim_2(10, 100.0, 0.0, -0.02, 0.02)  # min > max
    with pytest.raises(ValueError):
        bi.basic_id_sim_2(10, 100.0, 0.0, 0.02, -1.5)  # <= -1


def test_profitability_skews_direction():
    def up_rate(profit):
        ups = sum(1 for s in range(60)
                  if bi.basic_id_sim_1(200, 100.0, profit, seed=s)[-1] >= 100.0)
        return ups / 60
    pos, neg, flat = up_rate(1.0), up_rate(-1.0), up_rate(0.0)
    assert pos > neg + 0.30
    assert pos > 0.60
    assert neg < 0.40
    assert 0.30 < flat < 0.70


def test_sim4_target_growth_mean():
    for target, expect in ((0.05, 105.0), (-0.03, 97.0)):
        ends = [bi.basic_id_sim_4(200, 100.0, 0.0, target, seed=s)[-1] for s in range(40)]
        assert statistics.mean(ends) == pytest.approx(expect, abs=4.0)


def test_sim4_bad_target():
    with pytest.raises(ValueError):
        bi.basic_id_sim_4(10, 100.0, 0.0, -1.0)
    with pytest.raises(ValueError):
        bi.basic_id_sim_4(10, 100.0, 0.0, 11.0)
    with pytest.raises(TypeError):
        bi.basic_id_sim_4(10, 100.0, 0.0, True)


def test_sim3_validation():
    with pytest.raises(ValueError):
        bi.basic_id_sim_3(10, 100.0, volatility=0.0)
    with pytest.raises(ValueError):
        bi.basic_id_sim_3(10, 100.0, gap_std=-0.1)
    with pytest.raises(ValueError):
        bi.basic_id_sim_3(10, 100.0, circuit_pct=1.5)
    with pytest.raises(ValueError):
        bi.basic_id_sim_3(10, 100.0, regime="nope")


def test_sim3_no_circuit_runs_clean():
    prices = bi.basic_id_sim_3(100, 100.0, seed=5, circuit_pct=0)
    assert len(prices) == 100 and all(p > 0 for p in prices)


@pytest.mark.parametrize("name", ALL_SIMS)
def test_return_volumes(name):
    kw: dict = {"return_volumes": True}
    if name == "basic_id_sim_2":
        res = bi.basic_id_sim_2(40, 100.0, 0.0, 0.05, -0.05, seed=7, **kw)
    elif name == "basic_id_sim_4":
        res = bi.basic_id_sim_4(40, 100.0, 0.0, 0.05, seed=7, **kw)
    elif name == "basic_id_sim_3":
        res = bi.basic_id_sim_3(40, 100.0, seed=7, **kw)
    else:
        res = bi.basic_id_sim_1(40, 100.0, seed=7, **kw)
    prices, volumes = res
    assert len(prices) == len(volumes) == 40
    assert all(isinstance(v, int) and v >= 0 for v in volumes)
    if name == "basic_id_sim_3":
        assert volumes[0] == 150  # opening-auction cross
    else:
        assert volumes[0] == 0
        # same seed without flag gives identical prices
        plain = _call(name, nums=40, price=100.0, seed=7)
        assert list(prices) == list(plain)


def test_alias():
    assert bi.simulate_intraday is bi.basic_id_sim_1
