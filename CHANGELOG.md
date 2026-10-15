# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.2.0] — 2026-10-15

### Added

- Ultra-realistic session simulators `adv_id_sim_1` (flagship) and
  `adv_id_sim_2` (event-day preset): sub-tick engine, NSE session clock
  (or plain index), full 16-field bar records (OHLC, share volume, trades,
  VWAP, bid/ask, spread, buy/sell, imbalance, phase, halted) and a
  `target_pct` percent knob for the mean outcome.
- `bars_ex_to_csv` full-record CSV export; `record_closes` /
  `record_volumes` adapters; CLI runs record simulators natively.
- 21 new tests (contracts, calibration, stylized facts, halts, plumbing).

## [0.1.0] — 2026-10-13

### Added

- Four order-flow intraday simulators (`basic_id_sim_1`–`basic_id_sim_4`)
  with seeded reproducibility and optional per-tick volumes.
- Tick → OHLCV aggregation and CSV export (`mktsim.ohlcv`).
- `mktsim` command: one-shot runs, multi-run batches, interactive REPL.
- `mktsim-gui` tkinter viewer with dynamic argument forms and N-run overlays.
- Publishable packaging: `src` layout, PEP 621 metadata, typed (`py.typed`),
  MIT license, console entry points.
- MkDocs documentation with mkdocstrings autodoc and 16 executed examples.
- 77-test pytest suite covering simulators, OHLCV, CLI, GUI helpers and
  packaging surface.
