# CLI (`mktsim` entry point, `mktsim.cli`)

## One-shot

```powershell
mktsim --list
mktsim --algo basic_interaday.basic_id_sim_1 --param nums=375 --param initial_price=100 --param seed=1 --format ohlcv --bars 75 --out day.csv
```

| Option | Meaning |
|---|---|
| `--list` | list algorithms and exit |
| `--algo NAME` | `submodule.function`, or a bare `function` when unambiguous |
| `--param name=value` | repeatable; values are coerced from the function's annotations (bool accepts true/false, 1/0, yes/no, on/off) |
| `--format {ticks,ohlcv}` | `ticks` writes `tick,price,volume`; `ohlcv` (default) writes `bar,open,high,low,close,volume` |
| `--bars N` | OHLCV bar count (default 75) |
| `--out PATH` | output CSV (`--runs N` writes `stem_001.csv`, …) |
| `--runs N` | repeat with seeds `seed+i`; prints aggregate stats (`mean_end ± std`, `up%`, `avg_return`, best/worst) |
| `--plot` | show the last run (needs the `gui` extra) |
| `--repl` | force REPL mode |

Full reference: `mktsim --help`.

## REPL

```powershell
mktsim
```

```text
sim> help
sim> list
sim> use basic_id_sim_1
sim> show
sim> set profitability 0.5
sim> run
sim> export day.csv
sim> quit
```

| Command | Meaning |
|---|---|
| `help` | this help |
| `list` | list algorithms (`*` marks the selected one) |
| `use <algo>` | select algorithm (`submodule.function` or bare `function`) |
| `show` / `doc` | current params + values / selected algorithm's docstring |
| `set <name> <value>` | set a parameter (blank clears to default/`None`) |
| `run [ticks\|ohlcv]` | run once (default `ohlcv`); stores the result |
| `bars <n>` | OHLCV bar count (default 75) |
| `export <path> [ticks\|ohlcv]` | write the last run (or run now) to CSV |
| `plot` | plot the last run (needs matplotlib) |
| `quit` / `exit` | leave |

Required parameters start empty — `set` them before `run`.
