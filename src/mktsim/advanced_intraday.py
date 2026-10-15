"""Ultra-realistic intraday session simulators with full bar records.

Two algorithms live here:

* :func:`adv_id_sim_1` -- flagship full-session simulator. Simulates at
  fine sub-tick resolution and aggregates to ``nums`` bars, each returned
  as a complete record (OHLC + share volume, trades, VWAP, bid/ask,
  spread, buy/sell split, imbalance, phase, halt flag). Takes a
  ``target_pct`` (percent, e.g. ``2.0`` = mean close ~2% above the start)
  instead of the older ``profitability`` / ``target_growth`` knobs.
* :func:`adv_id_sim_2` -- same engine with an event-day preset (wider
  gaps, fatter jumps, higher volatility, tighter circuits) for
  stress-testing.

Beyond the :mod:`mktsim.basic_interaday` engines, the realism upgrades
are: two-resolution simulation (genuine intra-bar high/low), a session
clock with market phases, Hawkes-style self-exciting trade arrivals
(trade clustering), Heston-like stochastic volatility with a leverage
effect, permanent + temporary price impact, a live spread model
(adverse selection + inventory + tick floor), VWAP-scheduled
institutional flow against retail noise, a news/event scheduler,
opening/closing auctions and circuit-filter halts.

Only the Python standard library is used (``random`` / ``math``).
"""

from __future__ import annotations

import math
import random
from typing import Any

__all__ = [
    "BAR_FIELDS",
    "NSE_OPEN_MIN",
    "NSE_CLOSE_MIN",
    "adv_id_sim_1",
    "adv_id_sim_2",
    "record_closes",
    "record_volumes",
]

#: Keys of every bar record, in CSV order.
BAR_FIELDS = (
    "time", "open", "high", "low", "close", "volume", "trades", "vwap",
    "bid", "ask", "spread_bps", "buy_vol", "sell_vol", "imbalance",
    "phase", "halted",
)

#: NSE-style cash session: 09:15 -> 15:30 (375 minutes).
NSE_OPEN_MIN = 9 * 60 + 15
NSE_CLOSE_MIN = 15 * 60 + 30


def _fmt_time(mins: float) -> str:
    h, m = divmod(int(round(mins)), 60)
    return f"{h:02d}:{m:02d}"


def _activity(u: float) -> float:
    """U-shaped intraday activity multiplier for normalized time u in [0, 1]."""
    smile = 1.0 + 0.9 * (2.0 * u - 1.0) ** 2
    open_spike = 0.55 * math.exp(-u * 14.0)
    close_spike = 0.35 * math.exp(-(1.0 - u) * 10.0)
    lunch_dip = 0.18 * math.exp(-((u - 0.52) ** 2) / 0.004)
    return max(0.35, smile + open_spike + close_spike - lunch_dip)


def _round_tick(x: float, tick_size: float, tick_floor: float) -> float:
    if tick_size and tick_size > 0:
        x = round(x / tick_size) * tick_size
    return max(round(x, 2), tick_floor)


def _validate_adv(
    nums: int,
    initial_price: float,
    target_pct: float,
    tick_size: float,
    lot_size: int,
    base_tick_vol: float,
    sub_ticks: int,
    circuit_pct: float,
    gap_std: float,
    session: str | None,
) -> tuple[int, float, float, float, int, float, int, float, float, str | None]:
    if not isinstance(nums, int) or isinstance(nums, bool):
        raise TypeError("nums must be an int")
    if nums < 2:
        raise ValueError("nums must be >= 2")
    if not isinstance(initial_price, (int, float)) or isinstance(initial_price, bool):
        raise TypeError("initial_price must be a number")
    if not math.isfinite(initial_price) or initial_price <= 0:
        raise ValueError("initial_price must be a positive finite number")
    if not isinstance(target_pct, (int, float)) or isinstance(target_pct, bool):
        raise TypeError("target_pct must be a number")
    if not math.isfinite(target_pct) or not -100.0 < target_pct <= 1000.0:
        raise ValueError("target_pct must be within (-100, 1000]")
    if not isinstance(tick_size, (int, float)) or isinstance(tick_size, bool):
        raise TypeError("tick_size must be a number")
    if not math.isfinite(tick_size) or tick_size < 0:
        raise ValueError("tick_size must be a finite number >= 0")
    if not isinstance(lot_size, int) or isinstance(lot_size, bool):
        raise TypeError("lot_size must be an int")
    if lot_size < 1:
        raise ValueError("lot_size must be >= 1")
    if not isinstance(base_tick_vol, (int, float)) or isinstance(base_tick_vol, bool):
        raise TypeError("base_tick_vol must be a number")
    if not math.isfinite(base_tick_vol) or base_tick_vol <= 0:
        raise ValueError("base_tick_vol must be a positive finite number")
    if not isinstance(sub_ticks, int) or isinstance(sub_ticks, bool):
        raise TypeError("sub_ticks must be an int")
    if sub_ticks < 1:
        raise ValueError("sub_ticks must be >= 1")
    if not isinstance(circuit_pct, (int, float)) or isinstance(circuit_pct, bool):
        raise TypeError("circuit_pct must be a number")
    if not math.isfinite(circuit_pct) or not 0.0 <= circuit_pct <= 1.0:
        raise ValueError("circuit_pct must be within [0, 1] (0 disables halts)")
    if not isinstance(gap_std, (int, float)) or isinstance(gap_std, bool):
        raise TypeError("gap_std must be a number")
    if not math.isfinite(gap_std) or not 0.0 <= gap_std <= 0.5:
        raise ValueError("gap_std must be within [0, 0.5]")
    # Accept "None"/"none" strings (e.g. from CLI text input) as None.
    if isinstance(session, str) and session.strip().lower() in ("none", "null", ""):
        session = None
    if session is not None:
        if not isinstance(session, str):
            raise TypeError("session must be 'NSE' or None")
        if session.strip().upper() != "NSE":
            raise ValueError("session must be 'NSE' or None")
        session = "NSE"
    return (nums, float(initial_price), float(target_pct), float(tick_size),
            int(lot_size), float(base_tick_vol), int(sub_ticks),
            float(circuit_pct), float(gap_std), session)


def _run_advanced(
    nums: int,
    initial_price: float,
    target_pct: float,
    *,
    seed: int | None,
    session: str | None,
    tick_size: float,
    lot_size: int,
    base_tick_vol: float,
    sub_ticks: int,
    circuit_pct: float,
    gap_std: float,
    vol_mult: float,
    jump_mult: float,
) -> list[dict[str, Any]]:
    """Shared two-resolution session engine (see module docstring)."""
    (nums, price0, target_pct, tick_size, lot_size, base_tick_vol,
     sub_ticks, circuit_pct, gap_std, session) = _validate_adv(
        nums, initial_price, target_pct, tick_size, lot_size,
        base_tick_vol, sub_ticks, circuit_pct, gap_std, session)
    rng = random.Random(seed)
    tick_floor = round(tick_size or 0.01, 2)

    # ---- drift schedule: mean close lands on target -----------------------
    drift_total = math.log1p(target_pct / 100.0)
    comp = 0.07 * drift_total * abs(drift_total) * math.sqrt(nums / 375.0)
    comp = max(-0.12, min(0.12, comp))
    drift_total += comp
    base_vol = base_tick_vol * vol_mult
    signal = abs(drift_total / nums) / base_vol
    base_vol *= math.sqrt(1.0 + signal * signal)
    acts = [_activity((i + 0.5) / nums) for i in range(nums)]
    asum = sum(acts)
    bar_drift = [drift_total * a / asum for a in acts]

    # ---- latent state ------------------------------------------------------
    log_p = math.log(price0)
    long_var = base_vol ** 2
    omega = long_var * (1.0 - 0.08 - 0.88)
    var_t = long_var
    inst = 0.0       # persistent institutional flow bias
    sent = 0.0       # fast retail sentiment
    mom_s = 0.0      # slow momentum (trend followers)
    mom_f = 0.0      # fast momentum (stop cascades)
    temp = 0.0       # temporary impact deviation (mean-reverting)
    exc = 0.0        # Hawkes excitation (trade clustering)
    inv = 0.0        # dealer inventory pressure (widens spread)
    prev_r = 0.0
    side = 1
    last_print = price0
    ses_vol = 0.0
    ses_pv = 0.0

    upper = price0 * (1.0 + circuit_pct) if circuit_pct > 0 else math.inf
    lower = price0 * (1.0 - circuit_pct) if circuit_pct > 0 else 0.0
    span = NSE_CLOSE_MIN - NSE_OPEN_MIN
    n_close = min(5, max(1, nums // 10))

    def bar_time(i: int) -> str | int:
        if session is None:
            return i
        return _fmt_time(NSE_OPEN_MIN + i * span / nums)

    def phase_of(i: int) -> str:
        if i == 0:
            return "auction"
        if i >= nums - n_close:
            return "close"
        u = (i + 0.5) / nums
        if u < 0.25:
            return "morning"
        if u < 0.65:
            return "midday"
        return "afternoon"

    bars: list[dict[str, Any]] = []

    # ---- opening auction ---------------------------------------------------
    gap = rng.gauss(0.0, gap_std)
    if rng.random() < 0.06:
        gap += rng.choice((-1.0, 1.0)) * rng.uniform(0.005, 0.03)
    gap = max(gap, -0.5)
    log_p = math.log(price0) + math.log1p(gap)
    open_px = _round_tick(math.exp(log_p + 0.00006 * rng.choice((-1.0, 1.0))),
                          tick_size, tick_floor)
    if not (lower < open_px < upper):
        px = _round_tick(upper if open_px >= upper else lower, tick_size, tick_floor)
        log_p = math.log(px)
        bars.append({
            "time": bar_time(0), "open": px, "high": px, "low": px, "close": px,
            "volume": 0, "trades": 0, "vwap": px, "bid": px, "ask": px,
            "spread_bps": 0.0, "buy_vol": 0, "sell_vol": 0, "imbalance": 0.0,
            "phase": "auction", "halted": True,
        })
    else:
        auct_vol = 150 * lot_size
        auct_tr = 150
        buy = sum(1 for _ in range(auct_tr) if rng.random() < 0.5) * lot_size
        sell = auct_vol - buy
        hi = _round_tick(open_px + tick_size, tick_size, tick_floor)
        lo = _round_tick(open_px - tick_size, tick_size, tick_floor)
        hs = 0.00006 + 0.12 * base_vol
        bid = min(_round_tick(open_px * (1.0 - hs), tick_size, tick_floor), lo)
        ask = max(_round_tick(open_px * (1.0 + hs), tick_size, tick_floor), hi)
        bars.append({
            "time": bar_time(0), "open": open_px, "high": hi, "low": lo, "close": open_px,
            "volume": auct_vol, "trades": auct_tr, "vwap": open_px, "bid": bid, "ask": ask,
            "spread_bps": round((ask - bid) / open_px * 1e4, 1),
            "buy_vol": buy, "sell_vol": sell,
            "imbalance": round((buy - sell) / auct_vol, 3),
            "phase": "auction", "halted": False,
        })
        last_print = open_px
        ses_vol += auct_vol
        ses_pv += open_px * auct_vol

    # ---- continuous session -------------------------------------------------
    for i in range(1, nums):
        u = (i + 0.5) / nums
        act = acts[i]
        b_hi = -math.inf
        b_lo = math.inf
        b_vol = 0
        b_tr = 0
        b_buy = 0
        b_pv = 0.0
        b_open: float | None = None
        b_close = last_print
        halted = False
        hs_last = 0.00006

        for k in range(sub_ticks):
            # Volatility: GARCH persistence + leverage asymmetry.
            var_t = omega + 0.08 * prev_r * prev_r + 0.88 * var_t
            var_t = min(max(var_t, (base_vol * 0.3) ** 2), (base_vol * 4.0) ** 2)
            sigma_bar = math.sqrt(var_t * act)
            sigma = sigma_bar / math.sqrt(sub_ticks)
            sigma *= 1.0 + min(0.30, 25.0 * max(0.0, -prev_r))

            # Flows: persistent institutional + fast retail sentiment.
            inst += (1.0 - 0.990) * (0.0 - inst) + rng.gauss(0.0, 0.0035)
            sent = 0.90 * sent + rng.gauss(0.0, 0.020)

            # VWAP pull, strengthening into the close (MOC pinning).
            ses_vw = ses_pv / ses_vol if ses_vol > 0 else last_print
            vwap_dev = math.log(max(last_print, 1e-9) / max(ses_vw, 1e-9))
            close_w = max(0.0, (u - 0.88) / 0.12) ** 1.5
            mr_pull = -0.55 * (1.0 + 2.5 * close_w) * vwap_dev

            mom_term = (max(-0.10, min(0.10, 14.0 * mom_s))
                        + max(-0.05, min(0.05, 5.0 * mom_f)))
            buy_prob = (0.5 + inst + 0.06 * sent + mom_term + mr_pull * 0.10
                        + rng.gauss(0.0, 0.02))
            buy_prob = min(max(buy_prob, 0.25), 0.75)

            # Hawkes-style arrivals: bursts excite further bursts.
            lam = max(2.0, 14.0 * act * (1.0 + 1.5 * exc))
            n_tr = max(1, int(rng.gauss(lam, math.sqrt(lam))))
            if n_tr > lam * 1.6:
                exc += 0.25
            exc *= 0.95

            # Share volume in whole lots.
            mean_lots = 3.0 + 7.0 * act * (1.0 + exc)
            lots = max(1, int(rng.gauss(mean_lots, math.sqrt(mean_lots))))
            shares = lots * lot_size
            buy = int(round(shares * buy_prob))
            sell = shares - buy
            imb = (buy - sell) / shares

            # News jump + fat-tailed shock.
            p_jump = (0.004 * (0.5 + 0.5 * act)
                      + 0.010 * math.exp(-u * 8.0)) * jump_mult
            jump = 0.0
            if rng.random() < p_jump:
                jm = rng.gauss(0.0, 3.2 * sigma)
                jump = jm + math.copysign(abs(jm) * 0.4,
                                          inst + mom_s + rng.gauss(0, 0.01))
            shock = rng.gauss(0.0, 1.0)
            if rng.random() < 0.02:
                shock *= 5.0

            # Permanent impact accumulates; temporary impact mean-reverts.
            drift_sub = bar_drift[i] / sub_ticks
            perm = 0.30 * imb * sigma
            r_t = drift_sub + perm + sigma * shock * 0.85 + jump
            log_p += r_t
            temp = 0.88 * temp + 0.55 * imb * sigma

            # Circuit filter on the efficient price.
            if not (lower < math.exp(log_p) < upper):
                halted = True
                break

            # Quoted print with bid/ask bounce around efficient + temp.
            hs_last = (0.00006 + 0.12 * sigma
                       + min(0.0004, 2e-6 * abs(inv)))
            if rng.random() < 0.62:
                side = -side
            pr = _round_tick(math.exp(log_p + temp + hs_last * side
                                      * (0.7 + 0.6 * rng.random())),
                             tick_size, tick_floor)
            if b_open is None:
                b_open = pr
            b_close = pr
            b_hi = max(b_hi, pr)
            b_lo = min(b_lo, pr)
            b_vol += shares
            b_tr += n_tr
            b_buy += buy
            b_pv += pr * shares

            # Trackers see detrended surprises (drift can't loop).
            surprise = r_t - drift_sub
            mom_s = 0.90 * mom_s + 0.10 * surprise
            mom_f = 0.50 * mom_f + 0.50 * surprise
            inv += (buy - sell) * 0.0005
            prev_r = surprise
            last_print = pr

        if halted:
            px = _round_tick(upper if math.exp(log_p) >= upper else lower,
                             tick_size, tick_floor)
            log_p = math.log(px)
            mom_s *= 0.9
            mom_f *= 0.9
            prev_r = 0.0
            last_print = px
            bars.append({
                "time": bar_time(i), "open": px, "high": px, "low": px, "close": px,
                "volume": 0, "trades": 0, "vwap": px, "bid": px, "ask": px,
                "spread_bps": 0.0, "buy_vol": 0, "sell_vol": 0, "imbalance": 0.0,
                "phase": phase_of(i), "halted": True,
            })
            continue

        # Closing auction: blend the last print toward session VWAP.
        if i == nums - 1 and ses_vol > 0:
            ses_vw = ses_pv / ses_vol
            b_close = _round_tick(0.65 * b_close + 0.35 * ses_vw,
                                  tick_size, tick_floor)
            b_hi = max(b_hi, b_close)
            b_lo = min(b_lo, b_close)
            last_print = b_close

        b_sell = b_vol - b_buy
        vwap = round(b_pv / b_vol, 2)
        bid = min(_round_tick(b_close * (1.0 - hs_last), tick_size, tick_floor), b_lo)
        ask = max(_round_tick(b_close * (1.0 + hs_last), tick_size, tick_floor), b_hi)
        bars.append({
            "time": bar_time(i),
            "open": b_open if b_open is not None else b_close,
            "high": b_hi, "low": b_lo, "close": b_close,
            "volume": int(b_vol), "trades": int(b_tr), "vwap": vwap,
            "bid": bid, "ask": ask,
            "spread_bps": round((ask - bid) / b_close * 1e4, 1) if b_close > 0 else 0.0,
            "buy_vol": int(b_buy), "sell_vol": int(b_sell),
            "imbalance": round((b_buy - b_sell) / b_vol, 3) if b_vol else 0.0,
            "phase": phase_of(i), "halted": False,
        })
        ses_vol += b_vol
        ses_pv += b_pv

    return bars


def record_closes(bars: list[dict[str, Any]]) -> list[float]:
    """Extract closes from bar records (adapter for price-list tooling)."""
    if not isinstance(bars, (list, tuple)) or not bars:
        raise ValueError("bars must be a non-empty list of bar records")
    try:
        return [float(b["close"]) for b in bars]
    except (KeyError, TypeError, ValueError):
        raise TypeError("bars must be bar records with numeric 'close'")


def record_volumes(bars: list[dict[str, Any]]) -> list[int]:
    """Extract share volumes from bar records."""
    if not isinstance(bars, (list, tuple)) or not bars:
        raise ValueError("bars must be a non-empty list of bar records")
    try:
        return [int(b["volume"]) for b in bars]
    except (KeyError, TypeError, ValueError):
        raise TypeError("bars must be bar records with numeric 'volume'")


def adv_id_sim_1(
    nums: int,
    initial_price: float,
    target_pct: float = 0.0,
    *,
    seed: int | None = None,
    session: str | None = "NSE",
    tick_size: float = 0.05,
    lot_size: int = 1,
    base_tick_vol: float = 0.0012,
    sub_ticks: int = 10,
    circuit_pct: float = 0.10,
    gap_std: float = 0.004,
) -> list[dict[str, Any]]:
    """Simulate an ultra-realistic intraday session, bar by bar.

    Two-resolution engine: fine sub-ticks aggregate to ``nums`` bars, so
    every bar carries genuine open/high/low/close, share volume (whole
    lots), trade count, VWAP, live bid/ask + spread, buy/sell split,
    imbalance, session phase and a halt flag.

    Args:
        nums: Number of bars to return (>= 2). ~375 ≈ one full session.
        initial_price: Session reference price (> 0). Bar 0 is the
            opening-auction print after the overnight gap.
        target_pct: Target mean move in percent, e.g. ``2.0`` aims the
            mean close ~2% above the start; may be negative. Within
            (-100, 1000]. Individual sessions scatter around it.
        seed: Optional random seed for reproducibility.
        session: ``"NSE"`` for a 09:15-15:30 phased clock with ``HH:MM``
            stamps, or ``None`` for plain integer bar indices.
        tick_size: Exchange tick size used for rounding (default 0.05).
        lot_size: Share lot; volumes are whole multiples (default 1).
        base_tick_vol: Base per-tick volatility (~0.12% default).
        sub_ticks: Fine ticks simulated per bar (default 10). Higher is
            more realistic but slower.
        circuit_pct: Circuit band vs reference, e.g. 0.10 = 10%.
            Must be in [0, 1]; 0 disables halts.
        gap_std: Std-dev of the overnight gap (fraction, default 0.004).

    Returns:
        List of ``nums`` bar-record dicts (see ``BAR_FIELDS``).

    Raises:
        ValueError: If arguments are out of range.
        TypeError: If argument types are wrong.
    """
    return _run_advanced(
        nums, initial_price, target_pct, seed=seed, session=session,
        tick_size=tick_size, lot_size=lot_size, base_tick_vol=base_tick_vol,
        sub_ticks=sub_ticks, circuit_pct=circuit_pct, gap_std=gap_std,
        vol_mult=1.0, jump_mult=1.0,
    )


def adv_id_sim_2(
    nums: int,
    initial_price: float,
    target_pct: float = 0.0,
    *,
    seed: int | None = None,
    session: str | None = "NSE",
    tick_size: float = 0.05,
    lot_size: int = 1,
    base_tick_vol: float = 0.0012,
    sub_ticks: int = 10,
    circuit_pct: float = 0.05,
    gap_std: float = 0.012,
) -> list[dict[str, Any]]:
    """Event-day session simulator: same engine, stress preset.

    Identical to :func:`adv_id_sim_1` except the defaults describe a
    high-volatility event day: 1.35x volatility, 2.5x jump activity,
    wider overnight gaps (``gap_std=0.012``) and tighter circuits
    (``circuit_pct=0.05``). All arguments keep the same meaning; pass
    explicit values to override any preset.

    Returns:
        List of ``nums`` bar-record dicts (see ``BAR_FIELDS``).
    """
    return _run_advanced(
        nums, initial_price, target_pct, seed=seed, session=session,
        tick_size=tick_size, lot_size=lot_size, base_tick_vol=base_tick_vol,
        sub_ticks=sub_ticks, circuit_pct=circuit_pct, gap_std=gap_std,
        vol_mult=1.35, jump_mult=2.5,
    )
