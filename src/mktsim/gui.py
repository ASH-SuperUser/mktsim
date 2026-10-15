"""mktsim tkinter viewer for share-market simulation algorithms.

Run via the ``mktsim-gui`` entry point (or ``python -m mktsim.gui``)::

    mktsim-gui

How it works:

* **Autodiscovery** -- every simulator submodule of the ``mktsim`` package
  (except private ones, ``cli`` and ``gui``) is imported, and every public
  function defined in it is listed in the algorithm dropdown as
  ``submodule.function``. Drop a new simulator submodule into ``mktsim`` and
  it shows up automatically.
* **Dynamic arguments** -- selecting an algorithm inspects its signature and
  rebuilds the argument form (one widget per parameter, with types, defaults
  and required markers). Any algorithm that returns a list of numbers works.
* **Generate** plots one path; **Run N Times** overlays N dim outcome paths
  plus their bright average, with aggregate statistics.
* The argument panel is collapsible (▲/▼ button next to the dropdown) so the
  graph area can take the freed space.

Only requirement on an algorithm: a callable returning a list/tuple of
numbers (the price path). ``(prices, volumes)`` tuples and OHLCV bar lists
are plotted via prices/closes. If it accepts a ``seed`` parameter,
multi-run mode feeds it ``seed+i`` per run for independent but reproducible
streams.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import random
import statistics
import tkinter as tk
import types as _pytypes
import typing
from tkinter import messagebox, ttk

import mktsim

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# Submodules that provide runnable simulators (cli/gui themselves excluded).
_SIM_SKIP = frozenset({"cli", "gui"})

_EMPTY = inspect.Parameter.empty


# ------------------------------------------------------------- discovery
def discover_algorithms() -> dict[str, typing.Callable]:
    """Collect public simulator functions from ``mktsim`` submodules.

    Returns:
        Mapping of ``"submodule.function"`` label -> function, sorted by label.
        Modules that fail to import are skipped (reason printed to stdout).
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
        except Exception as exc:  # never let one broken file kill the UI
            print(f"[gui] skipping {mod_name}: {exc!r}")
            continue
        seen: set[int] = set()
        for func_name in sorted(vars(module)):
            if func_name.startswith("_"):
                continue
            obj = vars(module)[func_name]
            if not inspect.isfunction(obj):
                continue
            if obj.__module__ != module.__name__:  # imported helper, not defined here
                continue
            if id(obj) in seen:  # alias of an already-listed function
                continue
            seen.add(id(obj))
            found[f"{short}.{func_name}"] = obj
    return found


# ------------------------------------------------------- argument parsing
def _is_bool_ann(ann) -> bool:
    return ann is bool


def _union_numeric(ann):
    """If ``ann`` is Optional/Union with a single numeric member + None, return it."""
    origin = typing.get_origin(ann)
    if origin in (typing.Union, _pytypes.UnionType):
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(args) == 1 and args[0] in (int, float, bool, str):
            return args[0]
    return None


def convert_arg(text: str, param: inspect.Parameter):
    """Convert a textbox string to the value for ``param``.

    Empty text yields the parameter default (which may be None). Unannotated
    parameters fall back to smart parsing: int, then float, then string.
    """
    text = text.strip()
    default = param.default
    ann = param.annotation if param.annotation is not _EMPTY else None

    if text == "":
        if default is not _EMPTY:
            return default
        raise ValueError(f"missing required argument '{param.name}'")

    if ann is not None:
        target = _union_numeric(ann) or ann
        if _is_bool_ann(target):
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
        # Unknown annotation: fall through to smart parsing.

    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def call_algorithm(func: typing.Callable, values: dict) -> list:
    """Call ``func`` with ``values``, honouring positional-only parameters."""
    sig = inspect.signature(func)
    args, kwargs = [], {}
    for name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if name not in values:
            continue
        if param.kind is inspect.Parameter.POSITIONAL_ONLY:
            args.append(values[name])
        else:
            kwargs[name] = values[name]
    return func(*args, **kwargs)


def validate_series(result, label: str) -> list[float]:
    """Ensure an algorithm returned a usable price path (list of numbers).

    Also accepts ``(prices, volumes)`` tuples (uses prices) and OHLCV bar
    lists (``[{"close": ...}]`` -- uses closes) so volume/OHLCV helpers can
    be plotted too.
    """
    if isinstance(result, tuple) and len(result) == 2:
        result = result[0]
    if isinstance(result, (list, tuple)) and result and isinstance(result[0], dict):
        try:
            result = [float(b["close"]) for b in result]
        except (KeyError, TypeError, ValueError):
            raise TypeError(f"{label} OHLCV bars must each contain a numeric 'close'")
    if not isinstance(result, (list, tuple)):
        raise TypeError(f"{label} must return a list of prices, got {type(result).__name__}")
    if len(result) == 0:
        raise ValueError(f"{label} returned an empty list")
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in result):
        raise TypeError(f"{label} must return a list of numbers (floats)")
    return [float(x) for x in result]


# ------------------------------------------------------------------- UI
class IntradayTestUI(tk.Tk):
    def __init__(self, algos: dict[str, typing.Callable] | None = None) -> None:
        super().__init__()
        self.title("mktsim - simulator viewer")
        self.geometry("1000x700")
        self.minsize(820, 600)

        self.algos = algos if algos is not None else discover_algorithms()
        if not self.algos:
            messagebox.showerror("No algorithms",
                                 "No public simulator functions found in mktsim.\n"
                                 "Add a simulator function to the package first.")
        self._func: typing.Callable | None = None
        self._arg_vars: dict[str, tuple[tk.Variable, inspect.Parameter]] = {}
        self._args_visible = True

        self._build_top()
        self._build_args_frame()
        self._build_bottom()
        self._build_plot()
        self._select_algo(next(iter(self.algos)) if self.algos else "")

    # ------------------------------------------------------------ layout
    def _build_top(self) -> None:
        top = ttk.Frame(self, padding=(10, 10, 10, 0))
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="algorithm:").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        self.algo_var = tk.StringVar()
        self.algo_box = ttk.Combobox(top, textvariable=self.algo_var,
                                     values=sorted(self.algos), state="readonly", width=42)
        self.algo_box.grid(row=0, column=1, columnspan=3, sticky=tk.EW, padx=4, pady=4)
        self.algo_box.bind("<<ComboboxSelected>>", lambda _e: self._select_algo(self.algo_var.get()))
        self.args_toggle = ttk.Button(top, text="▲ Hide arguments", width=18,
                                      command=self._toggle_args)
        self.args_toggle.grid(row=0, column=4, padx=4, pady=4)
        top.columnconfigure(1, weight=1)

    def _toggle_args(self) -> None:
        """Collapse/expand the argument panel so the graph gets more room."""
        if self._args_visible:
            self.args_frame.pack_forget()
            self.args_toggle.config(text="▼ Show arguments")
        else:
            self.args_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=6,
                                 before=self._bottom)
            self.args_toggle.config(text="▲ Hide arguments")
        self._args_visible = not self._args_visible

    def _build_args_frame(self) -> None:
        holder = ttk.LabelFrame(self, text="arguments (* required)", padding=10)
        holder.pack(side=tk.TOP, fill=tk.X, padx=10, pady=6)
        self.args_frame = holder

    def _build_bottom(self) -> None:
        bottom = ttk.Frame(self, padding=(10, 0, 10, 0))
        bottom.pack(side=tk.TOP, fill=tk.X)
        self._bottom = bottom

        ttk.Button(bottom, text="Generate & Plot", command=self.on_generate) \
            .grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(bottom, text="Run N Times", command=self.on_run_n) \
            .grid(row=0, column=1, padx=4, pady=4)

        ttk.Label(bottom, text="N runs:").grid(row=0, column=2, sticky=tk.E, padx=4, pady=4)
        self.n_var = tk.IntVar(value=20)
        tk.Scale(bottom, from_=2, to=100, variable=self.n_var,
                 orient=tk.HORIZONTAL, length=200, showvalue=True) \
            .grid(row=0, column=3, sticky=tk.EW, padx=4, pady=4)

        self.stats_var = tk.StringVar(value="Pick an algorithm, fill arguments, then Generate.")
        ttk.Label(bottom, textvariable=self.stats_var, foreground="#333",
                  wraplength=960, justify=tk.LEFT) \
            .grid(row=1, column=0, columnspan=4, sticky=tk.W, padx=4, pady=4)
        bottom.columnconfigure(3, weight=1)

    def _build_plot(self) -> None:
        container = ttk.Frame(self, padding=(10, 0, 10, 10))
        container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.fig = Figure(figsize=(9.0, 4.8), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=container)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------ dynamic args
    def _select_algo(self, label: str) -> None:
        self._func = self.algos.get(label)
        if label:
            self.algo_var.set(label)
        for child in self.args_frame.winfo_children():
            child.destroy()
        self._arg_vars.clear()
        if self._func is None:
            ttk.Label(self.args_frame, text="No algorithm available.") \
                .grid(row=0, column=0, sticky=tk.W)
            self._plot_placeholder("No algorithms discovered.")
            return

        doc = inspect.getdoc(self._func) or ""
        first_line = doc.splitlines()[0] if doc else ""
        if first_line:
            ttk.Label(self.args_frame, text=first_line, foreground="#555") \
                .grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 6))

        row = 1
        n_params = 0
        for name, param in inspect.signature(self._func).parameters.items():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            n_params += 1
            required = param.default is _EMPTY
            ann = param.annotation if param.annotation is not _EMPTY else None
            type_name = getattr(ann, "__name__", str(ann)) if ann is not None else "?"
            if ann is not None and _union_numeric(ann) is not None:
                inner = _union_numeric(ann)
                type_name = f"{getattr(inner, '__name__', inner)} | None"
            hint = f"{name}ᴾᴼ" if param.kind is inspect.Parameter.POSITIONAL_ONLY else name
            ttk.Label(self.args_frame,
                      text=f"{hint}: {type_name}{' *' if required else ''}") \
                .grid(row=row, column=0, sticky=tk.W, padx=4, pady=3)

            if ann is bool:
                var: tk.Variable = tk.BooleanVar(
                    value=bool(param.default) if param.default is not _EMPTY else False)
                ttk.Checkbutton(self.args_frame, variable=var).grid(row=row, column=1, sticky=tk.W)
            else:
                default_text = "" if param.default is _EMPTY else (
                    "" if param.default is None else str(param.default))
                var = tk.StringVar(value=default_text)
                ttk.Entry(self.args_frame, textvariable=var, width=22) \
                    .grid(row=row, column=1, sticky=tk.EW, padx=4, pady=3)
                if param.default is None:
                    ttk.Label(self.args_frame, text="(blank = None)", foreground="#888") \
                        .grid(row=row, column=2, sticky=tk.W)
            self._arg_vars[name] = (var, param)
            row += 1

        if n_params == 0:
            ttk.Label(self.args_frame, text="No parameters -- just press Generate.") \
                .grid(row=row, column=0, columnspan=3, sticky=tk.W)
        self.args_frame.columnconfigure(1, weight=1)
        self._plot_placeholder(f"{label}\nFill arguments and press Generate or Run N Times.")

    # ------------------------------------------------------------ helpers
    def _plot_placeholder(self, msg: str) -> None:
        self.ax.clear()
        self.ax.text(0.5, 0.5, msg, ha="center", va="center", transform=self.ax.transAxes)
        self.ax.set_title("simulation")
        self.canvas.draw()

    def _style_axes(self, title: str, start: float) -> None:
        self.ax.set_title(title)
        self.ax.set_xlabel("tick")
        self.ax.set_ylabel("price")
        self.ax.grid(True, alpha=0.3)
        self.ax.axhline(start, color="gray", linestyle="--", linewidth=0.8,
                        label=f"start {start:.2f}")
        self.ax.legend(loc="best")
        self.fig.tight_layout()

    def _read_values(self) -> dict:
        """Read + convert every argument widget. Raises ValueError on bad input."""
        values = {}
        for name, (var, param) in self._arg_vars.items():
            text = "1" if isinstance(var, tk.BooleanVar) and var.get() else (
                "0" if isinstance(var, tk.BooleanVar) else var.get())
            try:
                values[name] = convert_arg(text, param)
            except ValueError as exc:
                raise ValueError(str(exc))
        return values

    def _seed_base(self, values: dict):
        """Base seed for multi-run mode, or None. Only used if algo takes `seed`."""
        if self._func is None:
            return None
        if "seed" not in inspect.signature(self._func).parameters:
            return None
        seed = values.get("seed")
        if seed is None:
            return None
        try:
            return int(seed)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------ actions
    def on_generate(self) -> None:
        if self._func is None:
            messagebox.showerror("No algorithm", "No algorithm selected.")
            return
        label = self.algo_var.get()
        try:
            values = self._read_values()
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return
        try:
            prices = validate_series(call_algorithm(self._func, values), label)
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Simulation error", str(exc))
            return

        color = "#15803d" if prices[-1] >= prices[0] else "#b91c1c"
        self.ax.clear()
        self.ax.plot(prices, color=color, linewidth=1.2)
        self._style_axes(label, prices[0])
        self.canvas.draw()

        ret = (prices[-1] - prices[0]) / prices[0] * 100 if prices[0] else float("nan")
        self.stats_var.set(
            f"[{label}] n={len(prices)}  start={prices[0]:.2f}  end={prices[-1]:.2f}  "
            f"min={min(prices):.2f}  max={max(prices):.2f}  return={ret:+.2f}%"
        )

    def on_run_n(self) -> None:
        if self._func is None:
            messagebox.showerror("No algorithm", "No algorithm selected.")
            return
        label = self.algo_var.get()
        try:
            values = self._read_values()
            n = int(self.n_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return
        if n < 2:
            messagebox.showerror("Invalid input", "N must be >= 2.")
            return

        base_seed = self._seed_base(values)
        run_seeds = ([base_seed + i for i in range(n)] if base_seed is not None
                     else [random.randint(0, 2 ** 31 - 1) for _ in range(n)])

        self.stats_var.set(f"Running {label} x{n} ...")
        self.update_idletasks()
        paths: list[list[float]] = []
        try:
            for i in range(n):
                vals = dict(values)
                if base_seed is not None or "seed" in vals:
                    if self._seed_accepts():
                        vals["seed"] = run_seeds[i]
                paths.append(validate_series(call_algorithm(self._func, vals), label))
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Simulation error", str(exc))
            self.stats_var.set("Run failed -- see error.")
            return

        # Truncate to the shortest path so mixed-length algorithms still work.
        L = min(len(p) for p in paths)
        paths = [p[:L] for p in paths]
        avg = [statistics.mean(tick) for tick in zip(*paths)]
        starts = [p[0] for p in paths]
        ends = [p[-1] for p in paths]
        mean_end = statistics.mean(ends)
        std_end = statistics.stdev(ends)
        up_pct = sum(1 for s, e in zip(starts, ends) if e >= s) / n * 100
        rets = [(e - s) / s * 100 for s, e in zip(starts, ends) if s]
        mean_ret = statistics.mean(rets) if rets else float("nan")

        self.ax.clear()
        for p in paths:
            self.ax.plot(p, color="gray", alpha=0.25, linewidth=0.8)
        self.ax.plot(avg, color="#1d4ed8", linewidth=2.2, label=f"average of {n}")
        self._style_axes(f"{label} x{n}", paths[0][0])
        self.canvas.draw()

        self.stats_var.set(
            f"[{label} x{n}] mean_end={mean_end:.2f} ± {std_end:.2f}  "
            f"up={up_pct:.1f}%  avg_return={mean_ret:+.2f}%  "
            f"best_end={max(ends):.2f}  worst_end={min(ends):.2f}  "
            f"avg_min={min(avg):.2f}  avg_max={max(avg):.2f}"
        )

    def _seed_accepts(self) -> bool:
        return self._func is not None and "seed" in inspect.signature(self._func).parameters


def main() -> None:
    app = IntradayTestUI()
    app.mainloop()


if __name__ == "__main__":
    main()
