"""Packaging sanity tests for the mktsim distribution."""

import re
from importlib import metadata

import mktsim


def test_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", mktsim.__version__)


def test_top_level_exports():
    for name in ("basic_id_sim_1", "basic_id_sim_2", "basic_id_sim_3",
                 "basic_id_sim_4", "simulate_intraday",
                 "ticks_to_ohlcv", "simulate_ohlcv", "bars_to_csv", "ticks_to_csv"):
        assert name in mktsim.__all__
        assert callable(getattr(mktsim, name))


def test_console_scripts_registered():
    eps = {ep.name: ep.value for ep in metadata.entry_points().select(group="console_scripts")}
    assert eps.get("mktsim") == "mktsim.cli:main"
    assert eps.get("mktsim-gui") == "mktsim.gui:main"


def test_distribution_metadata():
    dist = metadata.metadata("mktsim")
    assert dist["Name"] == "mktsim"
    license_text = dist.get("License-Expression") or dist.get("License") or ""
    assert "MIT" in license_text
