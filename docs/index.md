# mktsim documentation

Realistic intraday share-market simulators driven by simulated buy/sell
order flow. Stdlib-only core, reproducible by seed, with a CLI, a desktop
viewer and tick → OHLCV tooling built in.

**Start here:** [Quickstart](quickstart.md) · **See it work:**
[Examples](examples.md) · **Look it up:** [API reference](api.md)

## Guides

- [Quickstart](quickstart.md) — install, first simulation, first CSV.
- [Simulators](algorithms.md) — the four engines, how to choose, tuning knobs.
- [OHLCV](ohlcv.md) — volumes, bar aggregation, CSV formats.
- [CLI](cli.md) — one-shot runs, multi-run batches, REPL.
- [GUI](gui.md) — tkinter viewer walkthrough.
- [Examples](examples.md) — 20 copy-pasteable examples (library + CLI) with real executed output.

## Reference

- [API reference](api.md) — module/function index.
- [Reference](reference/package.md) — autodoc rendered from docstrings.

Built with [MkDocs](https://www.mkdocs.org/) +
[mkdocstrings](https://mkdocstrings.github.io/): `mkdocs serve` to preview,
`mkdocs build --strict` to verify.
