# GUI viewer (`mktsim-gui` entry point, `mktsim.gui`)

```powershell
mktsim-gui
```

Requires the `gui` extra (`pip install "mktsim[gui] @ git+https://github.com/ASH-SuperUser/mktsim.git"`).

1. Pick an algorithm from the dropdown (autodiscovered from the
   `mktsim` submodules; `cli`/`gui` themselves are excluded).
2. Fill the argument form — built from the function signature, with
   types, defaults and `*` required markers.
3. **Generate & Plot** draws one path (green when it finishes at or
   above the start, red otherwise) with start/end/min/max/return stats.
4. **Run N Times** (slider, 2–100) overlays N faint paths plus the bright
   average, with `mean_end ± std`, `up%`, `avg_return` and best/worst
   stats. Runs use `seed+i` when the algorithm takes `seed`.
5. Collapse the argument panel (▲/▼) for a larger chart.

`(prices, volumes)` tuples and OHLCV bar lists plot via prices/closes.
