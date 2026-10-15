"""Basic intraday share-market simulators driven by simulated buy/sell order flow.

Four algorithms live here:

* :func:`basic_id_sim_1` -- simulates ``nums`` intraday price ticks starting
  at ``initial_price`` from realistic microstructure ingredients
  (U-shaped volume profile, volatility clustering, order-flow price impact,
  momentum, VWAP mean-reversion, sentiment, bid/ask bounce, news jumps).
  ``profitability`` in [-1, +1] only biases the buy/sell flow, so any single
  path can still go against it.
* :func:`basic_id_sim_2` -- same engine plus per-step growth clamps
  (``max_growth`` / ``min_growth``): no single tick may grow more than
  ``max_growth`` or less than ``min_growth`` (simple returns). Trackers
  (momentum, VWAP, volatility) see the clamped prints, like a market with
  price bands / circuit filters.
* :func:`basic_id_sim_3` -- market-session engine: ``initial_price`` is the
  previous close, the path starts with an opening-auction print after an
  overnight gap, runs a full session (morning news digestion, midday lull,
  MOC-pinned close, closing auction), and supports day regimes (trend /
  range / event / calm), volatility-scaled spreads, fat-tailed shocks,
  autocorrelated institutional flow and circuit-filter halts.
* :func:`basic_id_sim_4` -- same order-flow core as :func:`basic_id_sim_1`
  plus a calibrated per-tick drift so that the **average** outcome reaches
  ``target_growth`` (e.g. 0.05 means the mean end price is ~5% above the
  start). Like ``profitability`` it is only a target -- individual paths
  deviate around it.

Only the Python standard library is used (``random`` / ``math``).
"""

from __future__ import annotations

import math
import random

__all__ = ["basic_id_sim_1", "basic_id_sim_2", "basic_id_sim_3", "basic_id_sim_4", "simulate_intraday"]


def _intraday_activity(u: float) -> float:
    """U-shaped activity multiplier for normalized time u in [0, 1].

    ~1.9x at the open, ~0.7x midday, ~1.6x into the close, plus a small
    lunch-lull dip. Matches the classic intraday volume smile.
    """
    smile = 1.0 + 0.9 * (2.0 * u - 1.0) ** 2          # U shape
    open_spike = 0.55 * math.exp(-u * 14.0)            # opening auction rush
    close_spike = 0.35 * math.exp(-(1.0 - u) * 10.0)   # closing rush
    lunch_dip = 0.18 * math.exp(-((u - 0.52) ** 2) / 0.004)  # lunch lull
    return max(0.35, smile + open_spike + close_spike - lunch_dip)


def _validate_common(nums: int, initial_price: float, profitability: float) -> tuple[int, float, float]:
    """Validate the arguments shared by both algorithms."""
    if not isinstance(nums, int) or isinstance(nums, bool):
        raise TypeError("nums must be an int")
    if nums < 2:
        raise ValueError("nums must be >= 2")
    if not isinstance(initial_price, (int, float)) or isinstance(initial_price, bool):
        raise TypeError("initial_price must be a number")
    if not math.isfinite(initial_price) or initial_price <= 0:
        raise ValueError("initial_price must be a positive finite number")
    if not isinstance(profitability, (int, float)) or isinstance(profitability, bool):
        raise TypeError("profitability must be a number")
    if not math.isfinite(profitability) or not -1.0 <= profitability <= 1.0:
        raise ValueError("profitability must be within [-1, 1]")
    return nums, float(initial_price), float(profitability)


def _validate_growth(value: float, name: str) -> float:
    """Validate a per-step growth bound (simple return, e.g. 0.02 = +2%)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(value) or value <= -1.0:
        raise ValueError(f"{name} must be finite and > -1 (got {value!r})")
    return float(value)


def _run_order_flow(
    nums: int,
    initial_price: float,
    profitability: float,
    *,
    seed: int | None,
    tick_size: float,
    base_tick_vol: float,
    min_step_growth: float | None,
    max_step_growth: float | None,
    drift_total: float = 0.0,
    return_volumes: bool = False,
) -> list[float] | tuple[list[float], list[int]]:
    """Shared order-flow engine. Bounds of None mean "unclamped" (sim_1).

    ``drift_total`` is 0.0 for sim_1/sim_2 (all drift emerges from order
    flow); sim_4 passes ``log(1 + target_growth)`` so the mean outcome hits
    the growth target. The total is distributed across ticks in proportion
    to intraday activity -- trends advance on volume, midday chops -- which
    keeps trending paths jagged like real markets instead of smooth ramps.

    When ``return_volumes`` is True, returns ``(prices, volumes)`` where
    ``volumes[i]`` is the simulated order count behind tick ``i``
    (``volumes[0]`` is 0 -- the start print has no orders behind it).
    Default False returns just ``prices`` (backwards compatible).
    """
    nums, initial_price, profitability = _validate_common(nums, initial_price, profitability)
    clamped = min_step_growth is not None or max_step_growth is not None
    lo = min_step_growth if min_step_growth is not None else -1.0 + 1e-9
    hi = max_step_growth if max_step_growth is not None else math.inf

    # Precompute the drift schedule: total log-drift split across ticks in
    # proportion to intraday activity. Sums to drift_total exactly (0.0 for
    # sim_1/sim_2, which are therefore bit-identical to having no schedule).
    drift_w: list[float] | None = None
    if drift_total:
        acts = [_intraday_activity(i / (nums - 1)) for i in range(1, nums)]
        act_sum = sum(acts)
        drift_w = [drift_total * a / act_sum for a in acts]

    rng = random.Random(seed)

    # ---- drift calibration ------------------------------------------------
    # There is NO artificial drift added to returns: all drift must emerge
    # from the simulated buy/sell order flow itself. A persistent bias `c`
    # in buy probability creates mean imbalance E[imb] ~= 2*c*p, which via
    # Kyle price impact gives per-tick mean ~= kyle * 2*c*p * sigma_t.
    # c ~= 0.022 puts profitability=+-1 at P(favourable end) ~= 85-90% --
    # a strong chance, but single paths can and do still go the other way.
    flow_bias = 0.022 * profitability

    # ---- GARCH(1,1)-style volatility state -------------------------------
    alpha, beta = 0.08, 0.88
    long_var = base_tick_vol ** 2
    omega = long_var * (1.0 - alpha - beta)
    var_t = long_var

    # ---- latent states ----------------------------------------------------
    log_p = math.log(initial_price)   # efficient (mid) log-price
    sentiment = 0.0                   # noise-trader sentiment (OU process)
    momentum = 0.0                    # EMA of past returns (trend followers)
    vwap = initial_price              # running VWAP proxy for mean reversion
    cum_vol = 0.0
    cum_pv = 0.0
    spread_side = 1                   # current quoted side for bid/ask bounce
    prev_r = 0.0

    prices: list[float] = [round(initial_price, 2)]
    volumes: list[int] = [0]
    tick_floor = round(tick_size or 0.01, 2)

    # Half-spread in log terms (~3 bps round-trip).
    half_spread = 0.00015

    for i in range(1, nums):
        u = i / (nums - 1)
        activity = _intraday_activity(u)

        # --- stochastic volatility update (clustering) ---
        var_t = omega + alpha * prev_r * prev_r + beta * var_t
        var_t = min(max(var_t, (base_tick_vol * 0.3) ** 2), (base_tick_vol * 4.0) ** 2)
        sigma_t = math.sqrt(var_t * activity)

        # --- latent sentiment: mean-reverting noise-trader mood ---
        sentiment = 0.985 * sentiment + rng.gauss(0.0, 0.018)

        # --- mean reversion to VWAP (dealers fading deviations) ---
        vwap_dev = math.log(max(prices[-1], 1e-9) / max(vwap, 1e-9))
        mr_pull = -0.55 * vwap_dev  # pull expressed in imbalance units

        # --- buy probability from order-flow imbalance ---
        # profitability nudges the flow; momentum + sentiment + MR modulate it.
        mom_term = 14.0 * momentum
        mom_term = max(-0.10, min(0.10, mom_term))
        buy_prob = (
            0.5
            + flow_bias                 # persistent institutional bias
            + 0.9 * sentiment * 0.10  # noise-trader mood
            + mom_term                # trend followers
            + mr_pull * 0.10          # contrarians fading VWAP deviation
            + rng.gauss(0.0, 0.02)    # fleeting imbalance noise
        )
        buy_prob = min(max(buy_prob, 0.30), 0.70)

        # --- simulate the order book for this tick ---
        # More orders when activity is high (Poisson-ish via Gaussian approx).
        expected_orders = max(6.0, 26.0 * activity)
        n_orders = max(2, int(rng.gauss(expected_orders, math.sqrt(expected_orders))))
        buys = sum(1 for _ in range(n_orders) if rng.random() < buy_prob)
        sells = n_orders - buys
        imbalance = (buys - sells) / n_orders  # in [-1, 1]

        # --- news jump: rare, large, sentiment-signed shock ---
        jump = 0.0
        if rng.random() < 0.008 * (0.6 + activity * 0.4):
            jump_mag = rng.gauss(0.0, 3.0 * sigma_t)
            # jumps lean with sentiment/momentum (herding on news)
            jump = jump_mag + math.copysign(abs(jump_mag) * 0.4, sentiment + momentum + rng.gauss(0, 0.01))

        # --- efficient-price return: drift + impact + noise + jump ---
        # drift_t is 0.0 unless sim_4 targets growth; otherwise trend comes
        # only from the order-flow imbalance above, i.e. from (simulated)
        # buy/sell orders.
        drift_t = drift_w[i - 1] if drift_w is not None else 0.0
        kyle_lambda = 1.35  # price impact strength
        shock = rng.gauss(0.0, 1.0)
        r_t = (drift_t + kyle_lambda * imbalance * sigma_t
               + sigma_t * shock * 0.85 + jump)

        log_p += r_t

        # --- bid/ask bounce: observed trade flickers around efficient price ---
        if rng.random() < 0.62:  # bounce to the other side most ticks
            spread_side = -spread_side
        observed = math.exp(log_p + half_spread * spread_side * (0.7 + 0.6 * rng.random()))

        # --- tick-size rounding, keep strictly positive ---
        if tick_size and tick_size > 0:
            observed = round(observed / tick_size) * tick_size
        observed = max(round(observed, 2), tick_floor)

        prev_obs = prices[-1]
        if clamped:
            # Enforce the per-step growth band on the printed price, then
            # re-round to cents for a clean print (band holds up to half a
            # cent of display rounding).
            g = observed / prev_obs - 1.0
            gc = min(max(g, lo), hi)
            observed = max(round(prev_obs * (1.0 + gc), 2), tick_floor)
            # Trackers see the clamped prints, like a market with price bands.
            realized_r = math.log(observed / prev_obs)
            momentum = 0.90 * momentum + 0.10 * realized_r
            tick_vol = n_orders
            cum_vol += tick_vol
            cum_pv += observed * tick_vol
            vwap = cum_pv / cum_vol
            prev_r = realized_r
        else:
            # --- update momentum / volatility trackers ---
            # Followers chase surprises, not known drift: when a drift
            # schedule is active (sim_4), momentum and GARCH see the
            # detrended return so a big target can't saturate trend-following
            # into a feedback loop (smooth ramp + overshoot). VWAP still
            # tracks real prints. Identical to r_t when drift_t is 0.0.
            surprise = r_t - drift_t
            momentum = 0.90 * momentum + 0.10 * surprise
            tick_vol = n_orders
            tick_price = math.exp(log_p)
            cum_vol += tick_vol
            cum_pv += tick_price * tick_vol
            vwap = cum_pv / cum_vol
            prev_r = surprise

        prices.append(float(observed))
        volumes.append(int(n_orders))

    # Guarantee the contract: first tick is exactly the requested start.
    prices[0] = float(round(initial_price, 2))
    if return_volumes:
        return prices, volumes
    return prices


def basic_id_sim_1(
    nums: int,
    initial_price: float,
    profitability: float = 0.0,
    *,
    seed: int | None = None,
    tick_size: float = 0.05,
    base_tick_vol: float = 0.0012,
    return_volumes: bool = False,
) -> list[float] | tuple[list[float], list[int]]:
    """Simulate an intraday price path via buy/sell order flow.

    Args:
        nums: Number of prices to return (number of ticks). Must be >= 2.
        initial_price: Price the simulation starts at (> 0).
            The first element of the returned list equals this value.
        profitability: Bias in [-1, 1]. +1 means a very high chance to end
            higher than the start, -1 a very high chance to end lower,
            0 means roughly 50/50. It is only a drift bias -- individual
            paths can still go against it.
        seed: Optional random seed for reproducibility.
        tick_size: Exchange tick size used for rounding (default 0.05).
        base_tick_vol: Base per-tick volatility (~0.12% default).
        return_volumes: When True, return ``(prices, volumes)`` where
            ``volumes[i]`` is the simulated order count behind tick ``i``.
            Default False returns just the price list.

    Returns:
        List of ``nums`` floats, or ``(prices, volumes)`` when
        ``return_volumes`` is True.

    Raises:
        ValueError: If arguments are out of range.
        TypeError: If argument types are wrong.
    """
    return _run_order_flow(
        nums, initial_price, profitability,
        seed=seed, tick_size=tick_size, base_tick_vol=base_tick_vol,
        min_step_growth=None, max_step_growth=None,
        return_volumes=return_volumes,
    )


def basic_id_sim_2(
    nums: int,
    initial_price: float,
    profitability: float,
    max_growth: float,
    min_growth: float,
    *,
    seed: int | None = None,
    tick_size: float = 0.05,
    base_tick_vol: float = 0.0012,
    return_volumes: bool = False,
) -> list[float] | tuple[list[float], list[int]]:
    """Simulate an intraday path with per-step growth bands.

    Same order-flow engine as :func:`basic_id_sim_1`, but every tick's
    simple return ``(p_t - p_{t-1}) / p_{t-1}`` is clipped into
    ``[min_growth, max_growth]`` -- e.g. ``max_growth=0.02`` caps any single
    step at +2%. The internal trackers (momentum, VWAP, volatility) observe
    the clamped prints, mimicking a market with price bands / circuit
    filters. Bounds hold up to half a cent of display rounding.

    Args:
        nums: Number of prices to return (number of ticks). Must be >= 2.
        initial_price: Price the simulation starts at (> 0).
        profitability: Bias in [-1, 1], same meaning as in
            :func:`basic_id_sim_1`.
        max_growth: Maximum allowed per-step simple return, e.g. 0.02 for
            +2%. Must be > -1 and >= ``min_growth``.
        min_growth: Minimum allowed per-step simple return, e.g. -0.02 for
            -2%. May be negative or positive. Must be > -1.
        seed: Optional random seed for reproducibility.
        tick_size: Exchange tick size used for rounding (default 0.05).
        base_tick_vol: Base per-tick volatility (~0.12% default).
        return_volumes: When True, return ``(prices, volumes)``.
            Default False returns just the price list.

    Returns:
        List of ``nums`` floats, or ``(prices, volumes)`` when
        ``return_volumes`` is True.

    Raises:
        ValueError: If arguments are out of range (including
            ``min_growth > max_growth``).
        TypeError: If argument types are wrong.
    """
    max_growth = _validate_growth(max_growth, "max_growth")
    min_growth = _validate_growth(min_growth, "min_growth")
    if min_growth > max_growth:
        raise ValueError(f"min_growth ({min_growth}) must be <= max_growth ({max_growth})")
    return _run_order_flow(
        nums, initial_price, profitability,
        seed=seed, tick_size=tick_size, base_tick_vol=base_tick_vol,
        min_step_growth=min_growth, max_step_growth=max_growth,
        return_volumes=return_volumes,
    )


# Day-regime table for basic_id_sim_3: momentum gain, mean-reversion gain,
# volatility multiplier, jump multiplier, institutional-flow persistence.
_REGIMES = {
    "normal": {"mom": 1.0, "mr": 1.0, "vol": 1.0, "jump": 1.0, "phi": 0.990},
    "trend": {"mom": 1.9, "mr": 0.6, "vol": 1.15, "jump": 1.0, "phi": 0.996},
    "range": {"mom": 0.4, "mr": 1.9, "vol": 0.9, "jump": 0.7, "phi": 0.985},
    "event": {"mom": 1.2, "mr": 0.8, "vol": 1.8, "jump": 3.0, "phi": 0.990},
    "calm": {"mom": 0.8, "mr": 1.2, "vol": 0.55, "jump": 0.4, "phi": 0.990},
}
_REGIME_WEIGHTS = (("normal", 0.50), ("trend", 0.15), ("range", 0.15),
                   ("event", 0.08), ("calm", 0.12))


def basic_id_sim_3(
    nums: int,
    initial_price: float,
    profitability: float = 0.0,
    volatility: float = 1.0,
    gap_std: float = 0.004,
    circuit_pct: float = 0.10,
    regime: str = "auto",
    *,
    seed: int | None = None,
    tick_size: float = 0.05,
    base_tick_vol: float = 0.0012,
    return_volumes: bool = False,
) -> list[float] | tuple[list[float], list[int]]:
    """Simulate a full market session: gap open, continuous trading, auctions.

    ``initial_price`` is the **previous close** (reference price). The
    returned path starts with the opening-auction print after a simulated
    overnight gap, runs the session -- busy open with news digestion, calm
    midday, closing-auction run-up pinned toward VWAP by MOC flow -- and ends
    with the closing-auction print. Real-market ingredients on top of the
    :func:`basic_id_sim_1` order-flow core:

    * autocorrelated institutional order flow (order splitting) + fast noise
    * fat-tailed shocks (jump mixture) and a leverage-like asymmetry where
      downticks breed slightly higher volatility
    * spread that widens at the open and with volatility, tightens midday
    * circuit-filter halts: if the efficient price touches
      ``prev_close * (1 +- circuit_pct)`` trading halts and prints freeze
      at the band (``circuit_pct <= 0`` disables halts)

    Args:
        nums: Number of prices to return (ticks across the session). >= 2.
        initial_price: Previous close / reference price (> 0).
        profitability: Session bias in [-1, 1], same flow-bias meaning as
            :func:`basic_id_sim_1`. The overnight gap itself stays random.
        volatility: Day volatility multiplier, e.g. 0.6 for a calm day,
            2.0 for an event day. Must be in (0, 10].
        gap_std: Std-dev of the overnight gap (simple return, e.g. 0.004 =
            0.4%). Must be in [0, 0.5]. ~6% of days also get a large
            earnings-style gap of 0.5-3%.
        circuit_pct: Circuit band vs previous close, e.g. 0.10 = 10%.
            Must be in [0, 1]; 0 disables halts.
        regime: Day type -- "auto" (drawn per seed), "normal", "trend",
            "range", "event" or "calm".
        seed: Optional random seed for reproducibility.
        tick_size: Exchange tick size used for rounding (default 0.05).
        base_tick_vol: Base per-tick volatility (~0.12% default).
        return_volumes: When True, return ``(prices, volumes)`` where
            ``volumes[0]`` is the opening-auction volume (150) and the rest
            are per-tick order counts (0 on halted ticks). Default False
            returns just the price list.

    Returns:
        List of ``nums`` floats (open auction, session ticks, close
        auction), or ``(prices, volumes)`` when ``return_volumes`` is True.

    Raises:
        ValueError: If arguments are out of range.
        TypeError: If argument types are wrong.
    """
    nums, prev_close, profitability = _validate_common(nums, initial_price, profitability)

    if not isinstance(volatility, (int, float)) or isinstance(volatility, bool):
        raise TypeError("volatility must be a number")
    if not math.isfinite(volatility) or not 0.0 < volatility <= 10.0:
        raise ValueError("volatility must be within (0, 10]")
    if not isinstance(gap_std, (int, float)) or isinstance(gap_std, bool):
        raise TypeError("gap_std must be a number")
    if not math.isfinite(gap_std) or not 0.0 <= gap_std <= 0.5:
        raise ValueError("gap_std must be within [0, 0.5]")
    if not isinstance(circuit_pct, (int, float)) or isinstance(circuit_pct, bool):
        raise TypeError("circuit_pct must be a number")
    if not math.isfinite(circuit_pct) or not 0.0 <= circuit_pct <= 1.0:
        raise ValueError("circuit_pct must be within [0, 1] (0 disables halts)")
    if not isinstance(regime, str) or (regime != "auto" and regime not in _REGIMES):
        raise ValueError(f"regime must be one of 'auto', {sorted(_REGIMES)}")

    rng = random.Random(seed)
    volatility, gap_std, circuit_pct = float(volatility), float(gap_std), float(circuit_pct)

    # ---- day regime -------------------------------------------------------
    if regime == "auto":
        roll, day = rng.random(), "normal"
        cum = 0.0
        for name, w in _REGIME_WEIGHTS:
            cum += w
            if roll < cum:
                day = name
                break
    else:
        day = regime
    R = _REGIMES[day]
    vol_scale = volatility * R["vol"]

    # ---- overnight gap -> opening auction ---------------------------------
    gap = rng.gauss(0.0, gap_std)
    if rng.random() < 0.06:  # earnings-style large gap, either direction
        gap += rng.choice((-1.0, 1.0)) * rng.uniform(0.005, 0.03)
    gap = max(gap, -0.5)
    tick_floor = round(tick_size or 0.01, 2)
    log_p = math.log(prev_close) + math.log1p(gap)

    def _round_tick(x: float) -> float:
        if tick_size and tick_size > 0:
            x = round(x / tick_size) * tick_size
        return max(round(x, 2), tick_floor)

    open_hs = 0.00006 + 0.15 * base_tick_vol * vol_scale * 3.0  # wide open spread
    prices: list[float] = [_round_tick(math.exp(log_p + open_hs * rng.choice((-1.0, 1.0))))]
    volumes: list[int] = [150]  # opening-auction cross volume

    # Circuit bands vs previous close.
    upper = prev_close * (1.0 + circuit_pct) if circuit_pct > 0 else math.inf
    lower = prev_close * (1.0 - circuit_pct) if circuit_pct > 0 else 0.0
    halted = not (lower < prices[0] < upper)
    halt_px = min(max(prices[0], lower), upper) if halted else 0.0
    if halted:  # gapped straight into the band: freeze at the open print
        prices[0] = halt_px = _round_tick(halt_px)

    # ---- session state ----------------------------------------------------
    flow_bias = 0.022 * profitability
    inst_target = flow_bias            # mean buy-prob bias from institutions
    inst = inst_target                # persistent (autocorrelated) flow
    sent = 0.0                        # fast noise-trader mood
    mom_slow, mom_fast = 0.0, 0.0
    alpha, beta = 0.08, 0.88
    long_var = base_tick_vol ** 2
    omega = long_var * (1.0 - alpha - beta)
    var_t = long_var
    prev_r = 0.0
    spread_side = 1
    # Auction volume anchors VWAP near the open, like a real opening cross.
    cum_vol, cum_pv = 150.0, prices[0] * 150.0
    vwap = prices[0]

    for i in range(1, nums):
        u = i / (nums - 1)
        activity = _intraday_activity(u)
        if i >= nums - 5:  # closing-auction run-up
            activity *= 2.0

        # --- volatility: GARCH persistence + leverage asymmetry + regime ---
        var_t = omega + alpha * prev_r * prev_r + beta * var_t
        var_t = min(max(var_t, (base_tick_vol * 0.3) ** 2), (base_tick_vol * 4.0) ** 2)
        sigma_t = math.sqrt(var_t * activity) * vol_scale
        sigma_t *= 1.0 + min(0.30, 25.0 * max(0.0, -prev_r))  # downticks breed vol

        # --- flows: persistent institutional + fast sentiment ----------------
        phi = R["phi"]
        inst += (1.0 - phi) * (inst_target - inst) + rng.gauss(0.0, 0.0035)
        sent = 0.90 * sent + rng.gauss(0.0, 0.020)

        # --- VWAP pull, strengthening into the close (MOC pinning) ---------
        vwap_dev = math.log(max(prices[-1], 1e-9) / max(vwap, 1e-9))
        close_w = max(0.0, (u - 0.88) / 0.12) ** 1.5
        mr_pull = -0.55 * R["mr"] * (1.0 + 2.5 * close_w) * vwap_dev

        # --- nonlinear momentum (trend followers + stop cascades) -----------
        mom_term = R["mom"] * (max(-0.10, min(0.10, 14.0 * mom_slow))
                               + max(-0.05, min(0.05, 5.0 * mom_fast)))
        buy_prob = (0.5 + inst + 0.06 * sent + mom_term + mr_pull * 0.10
                    + rng.gauss(0.0, 0.02))
        buy_prob = min(max(buy_prob, 0.25), 0.75)

        # --- order book ------------------------------------------------------
        expected_orders = max(6.0, 26.0 * activity)
        n_orders = max(2, int(rng.gauss(expected_orders, math.sqrt(expected_orders))))
        buys = sum(1 for _ in range(n_orders) if rng.random() < buy_prob)
        imbalance = (buys - (n_orders - buys)) / n_orders

        # --- news: morning digestion + rare fat jumps -------------------------
        p_jump = (0.006 * (0.5 + 0.5 * activity) + 0.012 * math.exp(-u * 8.0)) * R["jump"]
        jump = 0.0
        if rng.random() < p_jump:
            jump_mag = rng.gauss(0.0, 3.2 * sigma_t)
            jump = jump_mag + math.copysign(abs(jump_mag) * 0.4,
                                            inst + mom_slow + rng.gauss(0, 0.01))

        # --- fat-tailed idiosyncratic shock (2% of ticks hit ~5x) -------------
        shock = rng.gauss(0.0, 1.0)
        if rng.random() < 0.02:
            shock *= 5.0
        r_t = 1.35 * imbalance * sigma_t + sigma_t * shock * 0.85 + jump

        if not halted:
            log_p += r_t
        eff = math.exp(log_p)

        # --- circuit filter ---------------------------------------------------
        if not halted and not (lower < eff < upper):
            halted = True
            halt_px = _round_tick(upper if eff >= upper else lower)
        if halted:
            observed = _round_tick(halt_px + rng.choice((-1.0, 1.0)) * tick_floor * 0.5)
            mom_slow *= 0.9
            mom_fast *= 0.9
            prev_r = 0.0
            prices.append(float(observed))
            volumes.append(0)  # halted: prints frozen, no real volume
            continue

        # --- dynamic spread: wide at open / in stress, tight midday ----------
        hs_t = (0.00006 + 0.15 * sigma_t) * (1.0 + 1.5 * math.exp(-u * 20.0))
        if rng.random() < 0.62:
            spread_side = -spread_side
        observed = _round_tick(math.exp(log_p + hs_t * spread_side * (0.7 + 0.6 * rng.random())))

        # --- closing auction: blend the last print toward VWAP ----------------
        if i == nums - 1:
            observed = _round_tick(0.65 * observed + 0.35 * vwap
                                   + rng.gauss(0.0, 0.2 * sigma_t) * observed)

        # --- trackers see the prints ------------------------------------------
        realized_r = math.log(max(observed, 1e-9) / max(prices[-1], 1e-9))
        mom_slow = 0.90 * mom_slow + 0.10 * realized_r
        mom_fast = 0.50 * mom_fast + 0.50 * realized_r
        cum_vol += n_orders
        cum_pv += observed * n_orders
        vwap = cum_pv / cum_vol
        prev_r = realized_r

        prices.append(float(observed))
        volumes.append(int(n_orders))

    if return_volumes:
        return prices, volumes
    return prices


def basic_id_sim_4(
    nums: int,
    initial_price: float,
    profitability: float,
    target_growth: float,
    *,
    seed: int | None = None,
    tick_size: float = 0.05,
    base_tick_vol: float = 0.0012,
    return_volumes: bool = False,
) -> list[float] | tuple[list[float], list[int]]:
    """Simulate an intraday path that targets a given total growth on average.

    Same order-flow engine as :func:`basic_id_sim_1`, combining two forces:

    * ``profitability`` -- the usual buy/sell flow tilt from sim_1. It is
      fully active here: at a fixed target, ``profitability=+1`` vs ``-1``
      shifts the mean outcome by roughly +-4% and skews the odds of beating
      the target, exactly as in sim_1 it skews the odds of ending up.
    * ``target_growth`` (a fraction, e.g. 0.05 = +5%) -- sustained net
      demand of ``log(1 + target_growth)`` in total, distributed across
      ticks in proportion to intraday activity (trends advance on volume,
      midday chops). The **mean** end price lands at
      ``initial_price * (1 + target_growth)``; individual paths deviate
      around it via volatility, jumps and order-flow noise.

    Big trends stay jagged: tick volatility scales up with the drift rate
    (real trending sessions are volatile), so even large targets print
    pullbacks and chop instead of smooth ramps.

    Args:
        nums: Number of prices to return (number of ticks). Must be >= 2.
        initial_price: Price the simulation starts at (> 0).
            The first element of the returned list equals this value.
        profitability: Flow bias in [-1, 1], same meaning as in
            :func:`basic_id_sim_1`. Shifts the distribution around the target.
        target_growth: Target total simple growth as a fraction, e.g. 0.05
            aims the mean outcome ~5% above the start; may be negative
            (e.g. -0.03). Must be within (-1, 10].
        seed: Optional random seed for reproducibility.
        tick_size: Exchange tick size used for rounding (default 0.05).
        base_tick_vol: Base per-tick volatility (~0.12% default).
        return_volumes: When True, return ``(prices, volumes)``.
            Default False returns just the price list.

    Returns:
        List of ``nums`` floats, or ``(prices, volumes)`` when
        ``return_volumes`` is True.

    Raises:
        ValueError: If arguments are out of range.
        TypeError: If argument types are wrong.
    """
    if not isinstance(target_growth, (int, float)) or isinstance(target_growth, bool):
        raise TypeError("target_growth must be a number")
    if not math.isfinite(target_growth) or not -1.0 < target_growth <= 10.0:
        raise ValueError("target_growth must be within (-1, 10]")
    if not isinstance(base_tick_vol, (int, float)) or isinstance(base_tick_vol, bool):
        raise TypeError("base_tick_vol must be a number")
    if not math.isfinite(base_tick_vol) or base_tick_vol <= 0:
        raise ValueError("base_tick_vol must be a positive finite number")
    nums, initial_price, profitability = _validate_common(nums, initial_price, profitability)
    drift_total = math.log1p(float(target_growth))
    # MR-to-VWAP drag compensation: in a sustained trend VWAP trails the
    # price, so contrarian flow drags outcomes back toward flat -- growing
    # roughly quadratically with total drift (measured ~0.07 log-err per
    # drift^2 at 375 ticks, scaling with sqrt(nums)). Added back here so the
    # mean stays on target even for outsized moves; capped as best-effort
    # beyond the calibrated range.
    comp = 0.07 * drift_total * abs(drift_total) * math.sqrt(nums / 375.0)
    comp = max(-0.12, min(0.12, comp))
    drift_total += comp
    # Trend-volatility scaling: keep the drift/noise ratio market-like so
    # large targets stay jagged. signal ~= per-tick drift in vol units;
    # k ~= 1 for everyday targets, growing for outsized ones.
    signal = abs(drift_total / nums) / float(base_tick_vol)
    trend_k = math.sqrt(1.0 + signal * signal)
    return _run_order_flow(
        nums, initial_price, profitability,
        seed=seed, tick_size=tick_size, base_tick_vol=float(base_tick_vol) * trend_k,
        min_step_growth=None, max_step_growth=None,
        drift_total=drift_total,
        return_volumes=return_volumes,
    )


# Backwards-compatible alias for the original name.
simulate_intraday = basic_id_sim_1


if __name__ == "__main__":  # quick manual smoke check
    import argparse
    import statistics

    ap = argparse.ArgumentParser(description="Basic intraday simulator smoke check")
    ap.add_argument("--algo", choices=["basic_id_sim_1", "basic_id_sim_2", "basic_id_sim_3",
                                     "basic_id_sim_4"],
                    default="basic_id_sim_1")
    ap.add_argument("--nums", type=int, default=375)
    ap.add_argument("--initial-price", type=float, default=100.0)
    ap.add_argument("--profitability", type=float, default=0.0)
    ap.add_argument("--max-growth", type=float, default=0.02)
    ap.add_argument("--min-growth", type=float, default=-0.02)
    ap.add_argument("--volatility", type=float, default=1.0)
    ap.add_argument("--gap-std", type=float, default=0.004)
    ap.add_argument("--circuit-pct", type=float, default=0.10)
    ap.add_argument("--regime", default="auto",
                    choices=["auto", "normal", "trend", "range", "event", "calm"])
    ap.add_argument("--target-growth", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    if args.algo == "basic_id_sim_2":
        path = basic_id_sim_2(args.nums, args.initial_price, args.profitability,
                              args.max_growth, args.min_growth, seed=args.seed)
    elif args.algo == "basic_id_sim_3":
        path = basic_id_sim_3(args.nums, args.initial_price, args.profitability,
                              args.volatility, args.gap_std, args.circuit_pct,
                              args.regime, seed=args.seed)
    elif args.algo == "basic_id_sim_4":
        path = basic_id_sim_4(args.nums, args.initial_price, args.profitability,
                              args.target_growth, seed=args.seed)
    else:
        path = basic_id_sim_1(args.nums, args.initial_price, args.profitability, seed=args.seed)
    print(f"ticks={len(path)} start={path[0]:.2f} end={path[-1]:.2f} "
          f"min={min(path):.2f} max={max(path):.2f} mean={statistics.mean(path):.2f}")
