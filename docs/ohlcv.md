# OHLCV (`mktsim.ohlcv`)

## Volumes

Pass `return_volumes=True` to any simulator to get `(prices, volumes)`:

```python
prices, volumes = basic_id_sim_2(120, 50.0, 0.5, 0.01, -0.01,
                                 seed=3, return_volumes=True)
```

`volumes[i]` is the simulated order count behind tick `i` (`volumes[0]`
is `0`, except sim_3's opening-cross `150`). Prices are identical with or
without the flag for the same seed.

## Bars

```python
from mktsim import ticks_to_ohlcv, simulate_ohlcv, bars_to_csv

bars = ticks_to_ohlcv(prices, volumes, bars=75)
bars = simulate_ohlcv(basic_id_sim_1, 375, 100.0, 0.0, seed=1, bars=75)
bars_to_csv(bars, "day.csv")
```

Ticks are split into `bars` consecutive groups as evenly as possible
(first groups take one extra tick on remainders). Each bar is a dict:

| Key | Meaning |
|---|---|
| `bar` | 1-based bar index |
| `open` / `close` | first / last tick price of the group |
| `high` / `low` | max / min tick price of the group |
| `volume` | summed tick volumes (or tick count when volumes are absent) |

`bars >= len(prices)` yields one bar per tick; `bars=1` yields a single
day bar. Invariants: `bars[0]["open"] == prices[0]`,
`bars[-1]["close"] == prices[-1]`, volumes sum to the tick total.

## CSV formats

- OHLCV: `bar,open,high,low,close,volume` (via `bars_to_csv`).
- Ticks: `tick,price,volume` (via `ticks_to_csv`).
