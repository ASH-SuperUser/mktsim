"""mktsim command-line interface: REPL + one-shot runs with CSV export.

Installed with the package (entry point ``mktsim``)::

    mktsim                         # REPL
    mktsim --list                  # list algorithms
    mktsim --algo basic_interaday.basic_id_sim_1 --param nums=375 ^
        --param initial_price=100 --param seed=1 ^
        --format ohlcv --bars 75 --out day.csv

One-shot mode always writes CSV (``--format ticks`` for raw
tick,price,volume or ``--format ohlcv`` for bar,open,high,low,close,volume).
``--runs N`` writes N files (``out_001.csv`` ...) with seeds ``seed+i`` and
prints aggregate stats. The REPL (``help`` command) supports the same flow
interactively. Stdlib only (matplotlib is optional, for ``--plot``).
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import os
import pkgutil
import statistics
import types as _pytypes
import typing

import mktsim
from mktsim.ohlcv import bars_to_csv, ticks_to_csv, ticks_to_ohlcv

# Submodules that provide runnable simulators (cli/gui themselves excluded).
_SIM_SKIP = frozenset({"cli", "gui"})

_EMPTY = inspect.Parameter.empty


# ------------------------------------------------------------- discovery
def discover_algorithms() -> dict[str, typing.Callable]:
    """Collect public simulator functions from ``mktsim`` submodules.

    Returns mapping of ``"submodule.function"`` label -> function, sorted
    by label. Modules that fail to import are skipped (reason printed).
    Aliases of the same function object appear only once.
    """
    found: dict[str, typing.Callable] = {}
    package_path = getattr(mktsim, "__path__", None)
    if package_path is None:  # pragma: no cover -- defensive
        return found
    for info in sorted(pkgutil.iter_modules(package_path), key=lambda m: m.name):
        short = info.name
        if short.startswith("_") or short in _SIM_SKIP:
            continue
        mod_name = f"mktsim.{short}"
        try:
            module = importlib.import_module(mod_name)
        except Exception as exc:  # never let one broken file kill the CLI
            print(f"[cli] skipping {mod_name}: {exc!r}")
            continue
        seen: set[int] = set()
        for func_name in sorted(vars(module)):
            if func_name.startswith("_"):
                continue
            obj = vars(module)[func_name]
            if not inspect.isfunction(obj):
                continue
            if obj.__module__ != module.__name__:
                continue
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            found[f"{short}.{func_name}"] = obj
    return found


def resolve_algo(algos: dict[str, typing.Callable], name: str) -> tuple[str, typing.Callable]:
    """Resolve ``name`` as ``module.func`` or bare ``func`` (must be unique)."""
    if name in algos:
        return name, algos[name]
    matches = [label for label in algos if label.split(".")[-1] == name]
    if len(matches) == 1:
        return matches[0], algos[matches[0]]
    if len(matches) > 1:
        raise KeyError(f"ambiguous algorithm '{name}': {sorted(matches)} -- use module.func")
    raise KeyError(f"unknown algorithm '{name}'. Available: {sorted(algos)}")


# ------------------------------------------------------- argument parsing
def _union_numeric(ann):
    origin = typing.get_origin(ann)
    if origin in (typing.Union, _pytypes.UnionType):
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(args) == 1 and args[0] in (int, float, bool, str):
            return args[0]
    return None


def convert_arg(text: str, param: inspect.Parameter):
    """Convert CLI string ``text`` to a value for ``param``."""
    text = text.strip()
    default = param.default
    ann = param.annotation if param.annotation is not _EMPTY else None
    if text == "":
        if default is not _EMPTY:
            return default
        raise ValueError(f"missing required argument '{param.name}'")
    if ann is not None:
        target = _union_numeric(ann) or ann
        if target is bool:
            low = text.lower()
            if low in ("1", "true", "yes", "y", "on"):
                return True
            if low in ("0", "false", "no", "n", "off"):
                return False
            raise ValueError(f"argument '{param.name}' must be true/false")
        if target is int:
            return int(text)
        if target is float:
            return float(text)
        if target is str:
            return text
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_param_kv(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise ValueError(f"param must be name=value, got {text!r}")
    name, _, value = text.partition("=")
    name = name.strip()
    if not name:
        raise ValueError(f"param must be name=value, got {text!r}")
    return name, value.strip()


def default_values(func: typing.Callable) -> dict:
    """Defaults for every non-variadic parameter (None when no default)."""
    values: dict = {}
    for name, param in inspect.signature(func).parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        values[name] = None if param.default is _EMPTY else param.default
    return values


def coerce_values(func: typing.Callable, raw: dict[str, str]) -> dict:
    """Coerce ``{name: text}`` to typed values; honours POSITIONAL_ONLY."""
    sig = inspect.signature(func)
    values: dict = {}
    for name, text in raw.items():
        if name not in sig.parameters:
            raise ValueError(f"unknown parameter '{name}' for {func.__name__}")
        values[name] = convert_arg(text, sig.parameters[name])
    return values


def split_seed(values: dict, func: typing.Callable) -> int | None:
    if "seed" not in inspect.signature(func).parameters:
        return None
    seed = values.get("seed")
    if seed is None:
        return None
    try:
        return int(seed)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------- simulation
def run_simulation(
    func: typing.Callable, values: dict, *, bars: int, fmt: str
) -> tuple[list[float], list[int] | None, list[dict] | None]:
    """Run ``func`` with ``values``; return (prices, volumes, ohlcv-or-None).

    Record-style simulators (e.g. ``adv_id_sim_1``) return one full bar
    record per output already, so their closes/volumes are extracted
    directly and ``--bars`` aggregation is skipped for them.
    """
    sig = inspect.signature(func)
    args, kwargs = [], {}
    for name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if name in ("return_volumes", "bars"):
            continue
        if name not in values:
            continue
        if param.kind is inspect.Parameter.POSITIONAL_ONLY:
            args.append(values[name])
        else:
            kwargs[name] = values[name]
    volumes: list[int] | None = None
    records: list[dict] | None = None
    if "return_volumes" in sig.parameters:
        kwargs["return_volumes"] = True
        result = func(*args, **kwargs)
        if isinstance(result, tuple) and len(result) == 2:
            prices, volumes = result
        else:  # pragma: no cover -- defensive
            prices = result
    else:
        result = func(*args, **kwargs)
        if isinstance(result, list) and result and isinstance(result[0], dict):
            records = result
            prices = [float(b["close"]) for b in records]
            volumes = [int(b.get("volume") or 0) for b in records]
        else:
            prices = result
    prices = [float(p) for p in prices]
    ohlcv = None
    if fmt == "ohlcv":
        if records is not None:
            ohlcv = [{"bar": i + 1, **b} for i, b in enumerate(records)]
        else:
            ohlcv = ticks_to_ohlcv(prices, volumes, bars=bars)
    return prices, volumes, ohlcv


def export_csv(
    prices: list[float],
    volumes: list[int] | None,
    ohlcv: list[dict] | None,
    *,
    fmt: str,
    out: str,
) -> str:
    if fmt == "ohlcv":
        assert ohlcv is not None
        return bars_to_csv(ohlcv, out)
    return ticks_to_csv(prices, volumes, out)


def summarize(paths: list[list[float]]) -> str:
    starts = [p[0] for p in paths]
    ends = [p[-1] for p in paths]
    up = sum(1 for s, e in zip(starts, ends) if e >= s) / len(paths) * 100
    rets = [(e - s) / s * 100 for s, e in zip(starts, ends) if s]
    return (
        f"runs={len(paths)} mean_end={statistics.mean(ends):.2f} "
        f"± {statistics.stdev(ends):.2f} " if len(ends) > 1 else f"runs={len(paths)} end={ends[0]:.2f} "
    ) + (
        f"up={up:.1f}% avg_return={statistics.mean(rets):+.2f}% "
        f"best={max(ends):.2f} worst={min(ends):.2f}"
    )


def maybe_plot(prices: list[float], title: str) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("[cli] matplotlib not installed -- skipping plot")
        return
    plt.figure()
    plt.plot(prices, linewidth=1.2)
    plt.title(title)
    plt.xlabel("tick")
    plt.ylabel("price")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


# ------------------------------------------------------------- one-shot
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Share-market simulator CLI (CSV export)")
    ap.add_argument("--list", action="store_true", help="list algorithms and exit")
    ap.add_argument("--algo", default=None, help="algorithm module.func or func")
    ap.add_argument("--param", action="append", default=[], metavar="name=value",
                    help="algorithm parameter (repeatable)")
    ap.add_argument("--format", choices=["ticks", "ohlcv"], default="ohlcv")
    ap.add_argument("--bars", type=int, default=75, help="OHLCV bars (ohlcv format)")
    ap.add_argument("--out", default="sim.csv", help="output CSV path (runs>1: stem_001.csv ...)")
    ap.add_argument("--runs", type=int, default=1, help="number of runs (>= 1)")
    ap.add_argument("--plot", action="store_true", help="show matplotlib plot (last run)")
    ap.add_argument("--repl", action="store_true", help="force REPL mode")
    return ap


def one_shot(ns: argparse.Namespace) -> int:
    algos = discover_algorithms()
    if ns.list or not ns.algo:
        print("algorithms:")
        for label in sorted(algos):
            print(f"  {label}")
        if ns.list or not ns.algo:
            if ns.list:
                return 0
            print("\nPass --algo <name> with --param name=value, or run without args for REPL.")
            return 2 if not ns.list else 0
    try:
        label, func = resolve_algo(algos, ns.algo)
    except KeyError as exc:
        print(f"[cli] {exc}")
        return 2
    raw: dict[str, str] = {}
    try:
        for item in ns.param:
            name, value = parse_param_kv(item)
            raw[name] = value
        values = default_values(func)
        values.update(coerce_values(func, raw))
    except ValueError as exc:
        print(f"[cli] bad parameter: {exc}")
        return 2
    if ns.runs < 1:
        print("[cli] --runs must be >= 1")
        return 2
    if ns.format == "ohlcv" and ns.bars < 1:
        print("[cli] --bars must be >= 1")
        return 2

    base_seed = split_seed(values, func)
    paths: list[list[float]] = []
    last: tuple[list[float], list[int] | None, list[dict] | None] | None = None
    stem, ext = os.path.splitext(ns.out)
    if not ext:
        ext = ".csv"
    try:
        for i in range(ns.runs):
            vals = dict(values)
            if base_seed is not None:
                vals["seed"] = base_seed + i
            prices, volumes, ohlcv = run_simulation(func, vals, bars=ns.bars, fmt=ns.format)
            paths.append(prices)
            last = (prices, volumes, ohlcv)
            out = ns.out if ns.runs == 1 else f"{stem}_{i + 1:03d}{ext}"
            export_csv(prices, volumes, ohlcv, fmt=ns.format, out=out)
            print(f"[{i + 1}/{ns.runs}] {label} n={len(prices)} "
                  f"start={prices[0]:.2f} end={prices[-1]:.2f} -> {out}")
    except (TypeError, ValueError) as exc:
        print(f"[cli] simulation error: {exc}")
        return 1
    print(summarize(paths))
    if ns.plot and last is not None:
        maybe_plot(last[0], label)
    return 0


# ------------------------------------------------------------- REPL
REPL_HELP = """commands:
  help                 this help
  list                 list algorithms
  use <algo>           select algorithm (module.func or func)
  show                 show current algorithm params + values
  doc                  show selected algorithm docstring
  set <name> <value>   set a parameter (blank clears to default/None)
  run [ticks|ohlcv]    run once (default ohlcv); sets last result
  bars <n>             set OHLCV bar count (default 75)
  export <path> [ticks|ohlcv]  write last run (or run now) to CSV
  plot                 plot last run (needs matplotlib)
  quit / exit          leave
"""


def repl() -> int:
    algos = discover_algorithms()
    if not algos:
        print("[cli] no simulator functions found in the mktsim package")
        return 1
    print("share-market simulator -- type 'help' for commands.")
    label: str | None = None
    func: typing.Callable | None = None
    values: dict = {}
    bars = 75
    last: tuple[list[float], list[int] | None, list[dict] | None] | None = None
    last_fmt = "ohlcv"

    while True:
        try:
            line = input("sim> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()

        if cmd in ("quit", "exit"):
            return 0
        if cmd == "help":
            print(REPL_HELP)
        elif cmd == "list":
            for lb in sorted(algos):
                mark = " *" if lb == label else ""
                print(f"  {lb}{mark}")
        elif cmd == "use":
            if len(parts) < 2:
                print("usage: use <algo>")
                continue
            try:
                label, func = resolve_algo(algos, parts[1])
            except KeyError as exc:
                print(f"[cli] {exc}")
                continue
            values = default_values(func)
            last = None
            print(f"using {label} ({len(values)} params) -- 'show' to inspect, 'set' to change.")
        elif cmd in ("show", "doc"):
            if func is None:
                print("select an algorithm first: use <algo>")
                continue
            if cmd == "doc":
                print(inspect.getdoc(func) or "(no docstring)")
                continue
            for name, param in inspect.signature(func).parameters.items():
                if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                    continue
                default = "(required)" if param.default is _EMPTY else repr(param.default)
                print(f"  {name} = {values.get(name)!r}  [default {default}]")
            print(f"  [bars = {bars}]")
        elif cmd == "set":
            if func is None:
                print("select an algorithm first: use <algo>")
                continue
            if len(parts) < 2:
                print("usage: set <name> <value>")
                continue
            name = parts[1]
            text = line.split(None, 2)[2] if len(line.split(None, 2)) == 3 else ""
            sig = inspect.signature(func)
            if name not in sig.parameters:
                print(f"[cli] unknown parameter '{name}'")
                continue
            if text == "":
                values[name] = None if sig.parameters[name].default is _EMPTY else sig.parameters[name].default
            else:
                try:
                    values[name] = convert_arg(text, sig.parameters[name])
                except ValueError as exc:
                    print(f"[cli] {exc}")
                    continue
            last = None
            print(f"{name} = {values[name]!r}")
        elif cmd == "bars":
            if len(parts) != 2:
                print("usage: bars <n>")
                continue
            try:
                bars = int(parts[1])
                if bars < 1:
                    raise ValueError
            except ValueError:
                print("[cli] bars must be an int >= 1")
                continue
            print(f"bars = {bars}")
        elif cmd == "run":
            if func is None:
                print("select an algorithm first: use <algo>")
                continue
            fmt = parts[1].lower() if len(parts) > 1 else "ohlcv"
            if fmt not in ("ticks", "ohlcv"):
                print("usage: run [ticks|ohlcv]")
                continue
            try:
                prices, volumes, ohlcv = run_simulation(func, values, bars=bars, fmt=fmt)
            except (TypeError, ValueError) as exc:
                print(f"[cli] simulation error: {exc}")
                continue
            last, last_fmt = (prices, volumes, ohlcv), fmt
            ret = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] else float("nan")
            extra = f" bars={len(ohlcv)}" if ohlcv is not None else ""
            print(f"[{label}] n={len(prices)} start={prices[0]:.2f} end={prices[-1]:.2f} "
                  f"min={min(prices):.2f} max={max(prices):.2f} return={ret:+.2f}%{extra}")
        elif cmd == "export":
            if func is None:
                print("select an algorithm first: use <algo>")
                continue
            if len(parts) < 2:
                print("usage: export <path> [ticks|ohlcv]")
                continue
            path = parts[1]
            fmt = parts[2].lower() if len(parts) > 2 else last_fmt
            if fmt not in ("ticks", "ohlcv"):
                print("usage: export <path> [ticks|ohlcv]")
                continue
            try:
                if last is None or fmt != last_fmt:
                    prices, volumes, ohlcv = run_simulation(func, values, bars=bars, fmt=fmt)
                    last, last_fmt = (prices, volumes, ohlcv), fmt
                else:
                    prices, volumes, ohlcv = last
                export_csv(prices, volumes, ohlcv, fmt=fmt, out=path)
            except (TypeError, ValueError, OSError) as exc:
                print(f"[cli] export error: {exc}")
                continue
            print(f"wrote {fmt} -> {path}")
        elif cmd == "plot":
            if last is None:
                print("nothing to plot -- 'run' first")
                continue
            maybe_plot(last[0], label or "simulation")
        else:
            print(f"unknown command '{cmd}' -- type 'help'")
    return 0


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.repl or (not ns.algo and not ns.list):
        if ns.algo or ns.param or ns.list:
            return one_shot(ns)
        return repl()
    return one_shot(ns)


if __name__ == "__main__":
    raise SystemExit(main())
