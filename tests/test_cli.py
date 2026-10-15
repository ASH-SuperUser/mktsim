"""Tests for mktsim.cli discovery, arg coercion, simulation and CSV export."""

import csv
import inspect
import os

import pytest

from mktsim import cli
from mktsim import basic_id_sim_1


def test_discover_finds_core_algos():
    algos = cli.discover_algorithms()
    assert "basic_interaday.basic_id_sim_1" in algos
    assert "basic_interaday.basic_id_sim_4" in algos
    assert "ohlcv.ticks_to_ohlcv" in algos


def test_resolve_bare_and_full():
    algos = cli.discover_algorithms()
    full, _ = cli.resolve_algo(algos, "basic_interaday.basic_id_sim_1")
    assert full == "basic_interaday.basic_id_sim_1"
    bare, _ = cli.resolve_algo(algos, "basic_id_sim_1")
    assert bare == full
    with pytest.raises(KeyError):
        cli.resolve_algo(algos, "no_such_algo")


def test_convert_arg_types():
    sig = inspect.signature(basic_id_sim_1)
    assert cli.convert_arg("10", sig.parameters["nums"]) == 10
    assert cli.convert_arg("1.5", sig.parameters["profitability"]) == 1.5
    assert cli.convert_arg("", sig.parameters["seed"]) is None
    assert cli.convert_arg("7", sig.parameters["seed"]) == 7
    assert cli.coerce_values(basic_id_sim_1, {"nums": "20"}) == {"nums": 20}
    with pytest.raises(ValueError):
        cli.coerce_values(basic_id_sim_1, {"bogus": "1"})


def test_run_simulation_ticks_and_ohlcv():
    values = {"nums": 40, "initial_price": 100.0, "profitability": 0.0,
              "seed": 5, "tick_size": 0.05, "base_tick_vol": 0.0012,
              "return_volumes": False}
    prices, volumes, ohlcv = cli.run_simulation(basic_id_sim_1, values, bars=8, fmt="ohlcv")
    assert len(prices) == 40 and ohlcv is not None and len(ohlcv) == 8
    assert volumes is not None and len(volumes) == 40
    prices2, _, ohlcv2 = cli.run_simulation(basic_id_sim_1, values, bars=8, fmt="ticks")
    assert ohlcv2 is None and prices2 == prices


def test_one_shot_list(capsys):
    assert cli.one_shot(cli.build_parser().parse_args(["--list"])) == 0
    assert "basic_id_sim_1" in capsys.readouterr().out


def test_one_shot_ohlcv_csv(tmp_path):
    out = str(tmp_path / "day.csv")
    argv = ["--algo", "basic_id_sim_1", "--param", "nums=60", "--param", "initial_price=100",
            "--param", "seed=2", "--format", "ohlcv", "--bars", "6", "--out", out]
    assert cli.one_shot(cli.build_parser().parse_args(argv)) == 0
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 6
    assert set(rows[0]) == {"bar", "open", "high", "low", "close", "volume"}


def test_one_shot_ticks_and_multi_run(tmp_path):
    out = str(tmp_path / "ticks.csv")
    argv = ["--algo", "basic_id_sim_1", "--param", "nums=30", "--param", "initial_price=50",
            "--param", "seed=1", "--format", "ticks", "--out", out]
    assert cli.one_shot(cli.build_parser().parse_args(argv)) == 0
    with open(out, newline="", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 30

    stem = str(tmp_path / "run.csv")
    argv = ["--algo", "basic_id_sim_1", "--param", "nums=30", "--param", "initial_price=50",
            "--param", "seed=1", "--format", "ticks", "--runs", "3", "--out", stem]
    assert cli.one_shot(cli.build_parser().parse_args(argv)) == 0
    root, ext = os.path.splitext(stem)
    for i in (1, 2, 3):
        assert os.path.isfile(f"{root}_{i:03d}{ext}")


def test_one_shot_bad_algo_and_param():
    assert cli.one_shot(cli.build_parser().parse_args(["--algo", "nope"])) == 2
    argv = ["--algo", "basic_id_sim_1", "--param", "bogus=1"]
    assert cli.one_shot(cli.build_parser().parse_args(argv)) == 2


def test_repl_quit(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _p: "quit")
    assert cli.repl() == 0


def test_repl_run_export_flow(monkeypatch, tmp_path, capsys):
    out = str(tmp_path / "repl.csv")
    inputs = iter(["use basic_id_sim_1", "set nums 20", "set initial_price 100",
                     "run", f"export {out}", "quit"])
    monkeypatch.setattr("builtins.input", lambda _p: next(inputs))
    assert cli.repl() == 0
    assert os.path.isfile(out)
    assert "start=" in capsys.readouterr().out
