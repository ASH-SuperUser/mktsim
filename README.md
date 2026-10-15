# mktsim

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python ≥ 3.10](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](https://www.python.org/)
[![Docs with MkDocs](https://img.shields.io/badge/docs-MkDocs-green.svg)](docs/)

Realistic intraday share-market simulators driven by simulated buy/sell
order flow — not random walks. Tick-level microstructure (volume smile,
volatility clustering, price impact, momentum, mean reversion, news
jumps, circuit halts), aggregated to OHLCV on demand, with a CLI and a
desktop viewer included.

- **Stdlib-only core** — `import mktsim` needs nothing but Python ≥ 3.10.
- **Reproducible** — every simulator takes `seed`; same seed, same market.
- **Batteries included** — `mktsim` command (REPL + CSV export),
  `mktsim-gui` viewer, tick → OHLCV helpers.
- **Typed & tested** — annotations throughout (`py.typed`), 77-test suite.
- **Documented** — MkDocs + mkdocstrings autodoc and 16 executed examples.

> [!NOTE]
> `mktsim` generates **synthetic** data for research, testing and
> education. It is not a market model for live trading, and nothing here
> is financial advice.

- [Installation](#installation)
- [Quickstart](#quickstart)
- [CLI](#cli)
- [GUI viewer](#gui-viewer)
- [API overview](#api-overview)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Documentation](#documentation)
- [Contributing & changelog](#contributing--changelog)
- [License](#license)

## Simulators

Four tick-level simulators live in `mktsim.basic_interaday`, plus two
session simulators with full bar records in `mktsim.advanced_intraday`:

| Simulator | What it does |
|---|---|
| `basic_id_sim_1` | Order-flow intraday path (volume smile, GARCH volatility, Kyle price impact, momentum, VWAP reversion, sentiment, bid/ask bounce, news jumps). `profitability ∈ [-1, 1]` biases buy/sell flow. |
| `basic_id_sim_2` | Same engine + per-tick growth bands (`min_growth`/`max_growth`), like price bands / circuit filters. |
| `basic_id_sim_3` | Full session engine: overnight gap + opening auction, regimes (`normal`/`trend`/`range`/`event`/`calm`), fat tails, circuit halts, closing auction. Takes the previous close as `initial_price`. |
| `basic_id_sim_4` | Same core + calibrated drift so the **mean** outcome hits `target_growth` (e.g. `0.05` = +5%). |
| `adv_id_sim_1` | Ultra-realistic session: sub-tick engine, full bar records (OHLC, share volume, trades, VWAP, bid/ask, spread, imbalance, phase, halts), NSE session clock, `target_pct` in percent. |
| `adv_id_sim_2` | Same engine with an event-day preset (higher vol, fatter jumps, tighter circuits). |

Plus `mktsim.ohlcv` (tick → OHLCV bars + CSV), `mktsim.cli` (`mktsim`
command: REPL + one-shot CSV export) and `mktsim.gui` (`mktsim-gui`
command: tkinter viewer).

## Installation

Requirements: Python 3.10+ and `pip`. Always install into a virtual
environment — nothing global. (On macOS/Linux, use `python3` and
`venv/bin/python` in place of the Windows commands below.)

### Option A — install from GitHub (recommended for users)

```powershell
py -m venv venv
.\venv\Scripts\python.exe -m pip install "mktsim[gui] @ git+https://github.com/ASH-SuperUser/mktsim.git"
```

This installs the `mktsim` / `mktsim-gui` commands plus `matplotlib` for
the viewer. For the library alone without plotting:

```powershell
.\venv\Scripts\python.exe -m pip install "git+https://github.com/ASH-SuperUser/mktsim.git"
```

Pin to a tag/branch/commit with `@<ref>`, e.g.
`git+https://github.com/ASH-SuperUser/mktsim.git@v0.1.0`.

### Option B — clone and install editable (for development)

```powershell
git clone https://github.com/ASH-SuperUser/mktsim.git
cd mktsim
py -m venv venv
.\venv\Scripts\python.exe -m pip install -e ".[gui,test]"
```

### Extras

| Extra | Adds | For |
|---|---|---|
| *(none)* | stdlib only | using the simulators as a library |
| `[gui]` | `matplotlib` | `mktsim-gui` viewer, `mktsim --plot` |
| `[test]` | `pytest` | running the test suite |
| `[docs]` | `mkdocs`, `mkdocstrings`, `ruff` | building these docs |
| `[dev]` | all of the above + `build`, `twine` | release work |

### Verify the install

```powershell
.\venv\Scripts\python.exe -c "import mktsim; print(mktsim.__version__)"
.\venv\Scripts\mktsim.exe --list
```

## Quickstart

```python
from mktsim import basic_id_sim_1, simulate_ohlcv

ticks = basic_id_sim_1(375, 100.0, profitability=0.5, seed=1)
print(len(ticks), ticks[0], ticks[-1])  # 375 100.0 97.95

prices, volumes = basic_id_sim_1(375, 100.0, seed=1, return_volumes=True)
bars = simulate_ohlcv(basic_id_sim_1, 375, 100.0, 0.0, seed=1, bars=75)
print(bars[0])  # {'bar': 1, 'open': ..., 'high': ..., 'low': ..., 'close': ..., 'volume': ...}
```

See [docs/examples.md](docs/examples.md) for 20 end-to-end examples with
real executed output.

## CLI

```powershell
mktsim --list
mktsim --algo basic_id_sim_1 --param nums=375 --param initial_price=100 --param seed=1 --format ohlcv --bars 75 --out day.csv
mktsim --algo basic_id_sim_4 --param nums=200 --param initial_price=100 --param profitability=0 --param target_growth=0.05 --param seed=1 --runs 5 --out sim.csv
mktsim          # interactive REPL (help, list, use, show, doc, set, run, bars, export, plot, quit)
```

`--format ticks` writes raw `tick,price,volume`; `--format ohlcv`
(default) writes `bar,open,high,low,close,volume`. `--runs N` writes
`out_001.csv…` with seeds `seed+i` and prints aggregate stats.

## GUI viewer

```powershell
mktsim-gui
```

Pick an algorithm, fill arguments, **Generate & Plot** a single path or
**Run N Times** to overlay N paths plus their average.

## API overview

```python
basic_id_sim_1(nums, initial_price, profitability=0.0, *, seed=None,
               tick_size=0.05, base_tick_vol=0.0012, return_volumes=False)
basic_id_sim_2(nums, initial_price, profitability, max_growth, min_growth, *, ...)
basic_id_sim_3(nums, initial_price, profitability=0.0, volatility=1.0, gap_std=0.004,
               circuit_pct=0.10, regime="auto", *, ...)
basic_id_sim_4(nums, initial_price, profitability, target_growth, *, ...)
adv_id_sim_1(nums, initial_price, target_pct=0.0, *, seed=None, session="NSE",
             tick_size=0.05, lot_size=1, base_tick_vol=0.0012, sub_ticks=10, ...)
adv_id_sim_2(nums, initial_price, target_pct=0.0, *, ...)  # event-day preset
ticks_to_ohlcv(prices, volumes=None, bars=75) -> list[dict]
simulate_ohlcv(func, *args, bars=75, **kwargs) -> list[dict]
bars_to_csv(bars, path) / ticks_to_csv(prices, volumes, path)
```

All simulators are seeded (`random.Random(seed)`) and reproducible.
`prices[0]` equals `initial_price` — except sim_3, where `initial_price`
is the previous close and `prices[0]` is the open print after the
overnight gap. Full signatures with autodoc:
[docs/reference/](https://github.com/ASH-SuperUser/mktsim/tree/main/docs/reference).

## Project structure

```text
src/mktsim/          # the library: basic_interaday, ohlcv, cli, gui
tests/               # pytest suite (sims, ohlcv, cli, gui, packaging)
docs/                # MkDocs source (guides + executed examples + autodoc stubs)
mkdocs.yml           # docs site config
pyproject.toml       # PEP 621 metadata, entry points, extras
```

## Testing

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

## Documentation

```powershell
.\venv\Scripts\python.exe -m pip install -e ".[docs]"
.\venv\Scripts\mkdocs.exe serve               # live preview
.\venv\Scripts\mkdocs.exe build --strict      # verify, outputs site/
```

`docs/examples.md` is generated from executed code — after changing
simulator behaviour, regenerate it with
`.\venv\Scripts\python.exe docs/gen_examples.py`.

## Contributing & changelog

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and
[CHANGELOG.md](CHANGELOG.md) for release history.

## License

MIT © 2026 ASH-SuperUser — see [LICENSE](LICENSE).
