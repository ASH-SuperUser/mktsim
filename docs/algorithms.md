# Simulators (`mktsim.basic_interaday`)

Stdlib only (`random`/`math`). Every simulator takes `nums` (tick count,
≥ 2), `initial_price` (> 0), `seed` (reproducibility), `tick_size`
(rounding, default 0.05), `base_tick_vol` (per-tick volatility, default
0.0012 ≈ 0.12%) and `return_volumes` (default `False`; when `True` the
return is `(prices, volumes)` with per-tick simulated order counts).

## Choosing a simulator

| You want… | Use |
|---|---|
| A believable intraday wiggle with an up/down bias | `basic_id_sim_1` + `profitability` |
| Enforced step limits (price bands, circuit-style clipping) | `basic_id_sim_2` |
| A full day: gap open, regimes, halts, closing auction | `basic_id_sim_3` |
| The average outcome to land on a target return | `basic_id_sim_4` + `target_growth` |

## `basic_id_sim_1` — order-flow intraday

`basic_id_sim_1(nums, initial_price, profitability=0.0, *, ...)`

Microstructure ingredients: U-shaped intraday activity (busy open, lunch
lull, busy close), GARCH(1,1) volatility clustering, Kyle-style price
impact (`1.35 × imbalance × σ`), momentum-chasing flow, VWAP mean
reversion, noise-trader sentiment (OU process), bid/ask bounce and rare
news jumps.

!!! note "What `profitability` means"
    `profitability ∈ [-1, +1]` only biases the persistent buy/sell flow
    (`+1` ≈ 75–80% chance to finish up, `-1` mirrored, `0` ≈ 50/50).
    Individual paths can always go against it — that is the point.

`prices[0] == initial_price`.

## `basic_id_sim_2` — growth bands

`basic_id_sim_2(nums, initial_price, profitability, max_growth, min_growth, *, ...)`

Identical engine; each tick's simple return is clipped into
`[min_growth, max_growth]` (e.g. `0.02` = +2% cap). Internal trackers see
the clamped prints, mimicking price bands / circuit filters (band holds
up to half a cent of display rounding).

## `basic_id_sim_3` — full session

`basic_id_sim_3(nums, initial_price, profitability=0.0, volatility=1.0,
gap_std=0.004, circuit_pct=0.10, regime="auto", *, ...)`

Here `initial_price` is the **previous close**: the path starts with the
opening-auction print after a simulated overnight gap (plus rare
earnings-style gaps), runs the session and ends with the closing-auction
print (blended toward VWAP). Adds day regimes (`normal/trend/range/event/
calm`, or `"auto"` drawn per seed), autocorrelated institutional flow,
fat-tailed shocks, leverage-like asymmetry (downticks breed volatility),
volatility-scaled spreads and circuit-filter halts at
`prev_close × (1 ± circuit_pct)` (`0` disables). `volumes[0]` is the
opening-cross volume (150); halted ticks print volume 0.

!!! warning "First tick is not the previous close"
    Unlike the other simulators, `prices[0]` is the **open print after the
    overnight gap**, not `initial_price`. Halted prints jitter half a tick
    around the band for display but carry zero volume.

## `basic_id_sim_4` — growth target

`basic_id_sim_4(nums, initial_price, profitability, target_growth, *, ...)`

Same core as sim_1 plus activity-weighted log-drift totalling
`log(1 + target_growth)`, with VWAP-drag compensation and
trend-volatility scaling so large targets stay jagged. The **mean** end
price lands at `initial_price × (1 + target_growth)`; `profitability`
shifts the distribution around that target.

`simulate_intraday` is a backwards-compatible alias of `basic_id_sim_1`.

## `adv_id_sim_1` — ultra-realistic session (`mktsim.advanced_intraday`)

`adv_id_sim_1(nums, initial_price, target_pct=0.0, *, seed=None,
session="NSE", tick_size=0.05, lot_size=1, base_tick_vol=0.0012,
sub_ticks=10, circuit_pct=0.10, gap_std=0.004)`

Flagship simulator for when tick-level realism matters. It simulates at
fine sub-tick resolution (`sub_ticks` per bar, default 10) and returns
one **full record per bar** — genuine intra-bar high/low, share volume
in whole lots, trade count, VWAP, live bid/ask + spread, buy/sell split,
imbalance, session phase and a halt flag — instead of a bare price list.

New ingredients over the basic engines: Hawkes-style self-exciting trade
arrivals (bursts breed bursts), Heston-like stochastic volatility with a
leverage effect, permanent + temporary price impact, a spread model
(adverse selection + inventory + tick floor), VWAP-scheduled
institutional flow against retail noise, and a news/event scheduler.

- `target_pct` is a plain percent: `2.0` aims the mean close ~2% above
  the start (negative allowed); single sessions scatter around it.
- `session="NSE"` stamps bars on a 09:15–15:30 phased clock
  (`auction/morning/midday/afternoon/close`); `session=None` returns
  plain integer bar indices.
- `lot_size` makes volumes whole multiples (e.g. NSE equity lots).

`adv_id_sim_2` is the same engine with an event-day preset (1.35x
volatility, 2.5x jump activity, `gap_std=0.012`, `circuit_pct=0.05`).
Use `mktsim.record_closes` / `record_volumes` to drop back to price and
volume lists, and `mktsim.bars_ex_to_csv` for the full 16-column export.

## Tuning knobs

- `tick_size` — exchange tick used for rounding (default 0.05). Larger
  values give visibly stepped paths; must stay small relative to price.
- `base_tick_vol` — per-tick volatility (default ≈ 0.12%). Scale down for
  calm grinds, up for wild sessions. Sim_4 scales this automatically with
  the drift so big targets stay jagged instead of turning into ramps.
- `nums` — tick count. ~375 approximates a full session at 1-minute bars;
  aggregate to OHLCV with fewer `bars` for higher timeframes.
