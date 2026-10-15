# API reference

Hand-written overview. Fully rendered autodoc lives under **Reference**:

- [Package](reference/package.md) — `mktsim` top level.
- [basic_interaday](reference/basic_interaday.md) — simulators.
- [ohlcv](reference/ohlcv.md) — bars + CSV.
- [cli](reference/cli.md) — command line.
- [gui](reference/gui.md) — tkinter viewer.

Top-level (`import mktsim`, `mktsim.__version__`):

- `basic_id_sim_1`, `basic_id_sim_2`, `basic_id_sim_3`, `basic_id_sim_4`,
  `simulate_intraday` (alias of sim_1) — from `mktsim.basic_interaday`.
- `adv_id_sim_1`, `adv_id_sim_2`, `record_closes`, `record_volumes`,
  `BAR_FIELDS` — from `mktsim.advanced_intraday`.
- `ticks_to_ohlcv`, `simulate_ohlcv`, `bars_to_csv`, `bars_ex_to_csv`,
  `ticks_to_csv` — from `mktsim.ohlcv`.

## `mktsim.basic_interaday`

- `basic_id_sim_1(nums, initial_price, profitability=0.0, *, seed=None, tick_size=0.05, base_tick_vol=0.0012, return_volumes=False)`
- `basic_id_sim_2(nums, initial_price, profitability, max_growth, min_growth, *, seed=None, tick_size=0.05, base_tick_vol=0.0012, return_volumes=False)`
- `basic_id_sim_3(nums, initial_price, profitability=0.0, volatility=1.0, gap_std=0.004, circuit_pct=0.10, regime="auto", *, seed=None, tick_size=0.05, base_tick_vol=0.0012, return_volumes=False)`
- `basic_id_sim_4(nums, initial_price, profitability, target_growth, *, seed=None, tick_size=0.05, base_tick_vol=0.0012, return_volumes=False)`

Each returns `list[float]` of `nums` prices, or `(prices, volumes)` with
`return_volumes=True`. See [Simulators](algorithms.md) for semantics.

## `mktsim.advanced_intraday`

- `adv_id_sim_1(nums, initial_price, target_pct=0.0, *, seed=None, session="NSE", tick_size=0.05, lot_size=1, base_tick_vol=0.0012, sub_ticks=10, circuit_pct=0.10, gap_std=0.004)`
- `adv_id_sim_2(nums, initial_price, target_pct=0.0, *, ...)` — same engine, event-day preset
- `record_closes(bars)`, `record_volumes(bars)`, `BAR_FIELDS` (16 record keys)

Each returns `list[dict]` of `nums` bar records. See [Simulators](algorithms.md) for semantics.

## `mktsim.ohlcv`

- `ticks_to_ohlcv(prices, volumes=None, bars=75) -> list[dict]`
- `simulate_ohlcv(func, *args, bars=75, **kwargs) -> list[dict]`
- `bars_to_csv(bars, path) -> str`
- `bars_ex_to_csv(bars, path) -> str` — full record columns
- `ticks_to_csv(prices, volumes, path) -> str`

## `mktsim.cli`

- `discover_algorithms()`, `resolve_algo(algos, name)`,
  `convert_arg(text, param)`, `default_values(func)`,
  `coerce_values(func, raw)`, `run_simulation(func, values, *, bars, fmt)`,
  `export_csv(...)`, `summarize(paths)`, `one_shot(ns)`, `repl()`,
  `main(argv=None)` — console entry point `mktsim`.

## `mktsim.gui`

- `IntradayTestUI` (tkinter app), `discover_algorithms()`,
  `convert_arg(text, param)`, `call_algorithm(func, values)`,
  `validate_series(result, label)`, `main()` — console entry point
  `mktsim-gui`.
