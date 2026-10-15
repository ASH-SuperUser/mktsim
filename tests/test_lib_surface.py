"""Package-as-library tests: mktsim must behave like a real installed lib.

These tests treat mktsim as a consumer would: top-level imports,
submodule imports, version/metadata consistency, console entry points,
stdlib-only core (no matplotlib needed unless gui is used), and an
end-to-end simulate -> OHLCV -> CSV flow using only the public API.
"""

import os
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

import mktsim
import mktsim.basic_interaday as core
import mktsim.cli as cli_mod
import mktsim.ohlcv as ohlcv_mod

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = str(ROOT / "venv" / "Scripts" / "python.exe")


def _run(*args, **kwargs):
    return subprocess.run(
        [VENV_PY, *args], capture_output=True, text=True, cwd=str(ROOT), **kwargs
    )


# ------------------------------------------------- import surface
def test_top_level_all_matches_dir():
    for name in mktsim.__all__:
        assert name in dir(mktsim), f"mktsim.__all__ lists {name!r} but it is missing"
    assert set(mktsim.__all__) >= {
        "__version__", "basic_id_sim_1", "basic_id_sim_2", "basic_id_sim_3",
        "basic_id_sim_4", "simulate_intraday", "ticks_to_ohlcv",
        "simulate_ohlcv", "bars_to_csv", "ticks_to_csv",
    }


def test_top_level_objects_are_submodule_objects():
    assert mktsim.basic_id_sim_1 is core.basic_id_sim_1
    assert mktsim.basic_id_sim_2 is core.basic_id_sim_2
    assert mktsim.basic_id_sim_3 is core.basic_id_sim_3
    assert mktsim.basic_id_sim_4 is core.basic_id_sim_4
    assert mktsim.ticks_to_ohlcv is ohlcv_mod.ticks_to_ohlcv
    assert mktsim.simulate_ohlcv is ohlcv_mod.simulate_ohlcv
    assert mktsim.bars_to_csv is ohlcv_mod.bars_to_csv
    assert mktsim.ticks_to_csv is ohlcv_mod.ticks_to_csv
    assert mktsim.simulate_intraday is core.simulate_intraday


def test_submodules_importable_standalone():
    # A consumer importing one piece must not need the rest (esp. not gui).
    proc = _run("-c", "import mktsim.basic_interaday, mktsim.ohlcv; print('ok')")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_core_does_not_need_matplotlib():
    proc = _run(
        "-c",
        "import sys, mktsim, mktsim.basic_interaday, mktsim.ohlcv; "
        "assert 'matplotlib' not in sys.modules, sorted(m for m in sys.modules if 'matplotlib' in m); "
        "print('stdlib-only')",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "stdlib-only"


def test_no_legacy_import_paths_remain():
    src = ROOT / "src" / "mktsim"
    pattern = re.compile(r"^\s*(from|import)\s+(algorithms|tests\.test_ui)\b", re.M)
    offenders = [p.name for p in src.glob("*.py") if pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == [], f"legacy imports in {offenders}"


# ------------------------------------------------- version / metadata
def test_version_sync_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    (match,) = re.findall(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert match == mktsim.__version__
    (dist_version,) = re.findall(r"^Version:\s*(\S+)", metadata.metadata("mktsim").as_string(), re.M)
    assert dist_version == mktsim.__version__


def test_optional_extras_declared():
    requires = metadata.requires("mktsim") or []
    assert any("matplotlib" in r and 'extra == "gui"' in r for r in requires)
    assert any("pytest" in r and 'extra == "test"' in r for r in requires)


def test_package_data_ships_py_typed():
    assert (Path(mktsim.__file__).parent / "py.typed").is_file()


# ------------------------------------------------- entry points as a consumer sees them
def test_console_script_mktsim_list():
    mktsim_exe = str(ROOT / "venv" / "Scripts" / "mktsim.exe")
    proc = subprocess.run([mktsim_exe, "--list"], capture_output=True, text=True, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr
    assert "basic_interaday.basic_id_sim_1" in proc.stdout


def test_module_invocation_cli():
    proc = _run("-m", "mktsim.cli", "--list")
    assert proc.returncode == 0, proc.stderr
    assert "basic_interaday.basic_id_sim_4" in proc.stdout


def test_cli_end_to_end_csv(tmp_path):
    out = tmp_path / "e2e.csv"
    proc = _run(
        "-m", "mktsim.cli", "--algo", "basic_id_sim_1",
        "--param", "nums=40", "--param", "initial_price=100", "--param", "seed=3",
        "--format", "ohlcv", "--bars", "4", "--out", str(out),
    )
    assert proc.returncode == 0, proc.stderr
    rows = out.read_text(encoding="utf-8").strip().splitlines()
    assert rows[0] == "bar,open,high,low,close,volume"
    assert len(rows) == 5


# ------------------------------------------------- end-to-end via public API only
def test_public_api_end_to_end(tmp_path):
    prices, volumes = mktsim.basic_id_sim_1(60, 100.0, 0.25, seed=8, return_volumes=True)
    bars = mktsim.ticks_to_ohlcv(prices, volumes, bars=6)
    assert len(bars) == 6
    path = mktsim.bars_to_csv(bars, str(tmp_path / "api.csv"))
    assert Path(path).is_file()
    assert mktsim.simulate_ohlcv(mktsim.basic_id_sim_3, 60, 100.0, seed=8, bars=6)[-1]["volume"] >= 0


def test_seeded_reproducibility_across_namespaces():
    assert mktsim.basic_id_sim_1(30, 50.0, seed=99) == core.basic_id_sim_1(30, 50.0, seed=99)
    assert cli_mod.resolve_algo(cli_mod.discover_algorithms(), "basic_id_sim_2")[1] is mktsim.basic_id_sim_2


def test_gui_module_importable_without_display():
    pytest.importorskip("tkinter")
    import mktsim.gui as gui_mod

    assert callable(gui_mod.validate_series)
    assert "basic_interaday.basic_id_sim_1" in gui_mod.discover_algorithms()
