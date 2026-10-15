"""OHLCV helpers: aggregate tick simulations into bars + CSV export.

Only the Python standard library is used.
"""

from __future__ import annotations

import csv
import inspect
from typing import Any, Callable, Sequence

__all__ = ["ticks_to_ohlcv", "simulate_ohlcv", "bars_to_csv", "bars_ex_to_csv", "ticks_to_csv"]


def _validate_ticks(prices: Sequence[float], volumes: Sequence[int] | None) -> tuple[list[float], list[int] | None]:
    if not isinstance(prices, (list, tuple)) or len(prices) == 0:
        raise ValueError("prices must be a non-empty list/tuple of numbers")
    clean: list[float] = []
    for x in prices:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise TypeError("prices must contain only numbers")
        clean.append(float(x))
    vols: list[int] | None = None
    if volumes is not None:
        if not isinstance(volumes, (list, tuple)) or len(volumes) != len(clean):
            raise ValueError("volumes must be a list/tuple with the same length as prices")
        vols = []
        for v in volumes:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise TypeError("volumes must contain only numbers")
            if v < 0:
                raise ValueError("volumes must be >= 0")
            vols.append(int(v))
    return clean, vols


def ticks_to_ohlcv(
    prices: Sequence[float],
    volumes: Sequence[int] | None = None,
    bars: int = 75,
) -> list[dict[str, Any]]:
    """Aggregate tick prices (and per-tick volumes) into OHLCV bars.

    Ticks are split into ``bars`` consecutive groups as evenly as possible
    (first groups get one extra tick when ``len(prices)`` is not divisible
    by ``bars``). Each bar is ``{"bar", "open", "high", "low", "close",
    "volume"}`` with 1-based ``bar`` index. ``volume`` is the sum of tick
    volumes in the group, or the tick count when ``volumes`` is None.

    Args:
        prices: Tick price path (non-empty).
        volumes: Optional per-tick volumes, same length as ``prices``.
        bars: Number of bars to produce (>= 1). When ``bars >= len(prices)``
            each tick becomes its own bar (O=H=L=C=tick price).

    Returns:
        List of ``bars`` (or ``len(prices)`` when capped) OHLCV dicts.
    """
    clean, vols = _validate_ticks(prices, volumes)
    if not isinstance(bars, int) or isinstance(bars, bool):
        raise TypeError("bars must be an int")
    if bars < 1:
        raise ValueError("bars must be >= 1")
    n = len(clean)
    n_bars = min(bars, n)
    base, extra = divmod(n, n_bars)
    out: list[dict[str, Any]] = []
    idx = 0
    for b in range(1, n_bars + 1):
        size = base + (1 if b <= extra else 0)
        chunk = clean[idx: idx + size]
        vol = sum(vols[idx: idx + size]) if vols is not None else size
        out.append({
            "bar": b,
            "open": chunk[0],
            "high": max(chunk),
            "low": min(chunk),
            "close": chunk[-1],
            "volume": int(vol),
        })
        idx += size
    return out


def simulate_ohlcv(
    func: Callable[..., Any],
    *args: Any,
    bars: int = 75,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Run a tick simulator and aggregate its output into OHLCV bars.

    If ``func`` accepts ``return_volumes`` it is called with
    ``return_volumes=True`` to get real simulated volumes; otherwise it is
    called normally and bar volume falls back to tick counts. Any extra
    ``bars`` kwarg meant for this wrapper is consumed here, not forwarded.

    Args:
        func: Callable returning a price list (or ``(prices, volumes)`` when
            ``return_volumes=True`` is supported).
        *args: Positional args forwarded to ``func``.
        bars: Number of OHLCV bars to produce.
        **kwargs: Keyword args forwarded to ``func``.

    Returns:
        OHLCV bar list (see :func:`ticks_to_ohlcv`).
    """
    kwargs = dict(kwargs)
    if "return_volumes" in inspect.signature(func).parameters:
        kwargs["return_volumes"] = True
        result = func(*args, **kwargs)
    else:
        result = func(*args, **kwargs)
    if isinstance(result, tuple) and len(result) == 2:
        prices, volumes = result
        return ticks_to_ohlcv(prices, volumes, bars=bars)
    return ticks_to_ohlcv(result, None, bars=bars)


def bars_to_csv(bars: Sequence[dict[str, Any]], path: str) -> str:
    """Write OHLCV bars to ``path`` as CSV. Returns ``path``."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["bar", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for b in bars:
            writer.writerow({k: b[k] for k in ("bar", "open", "high", "low", "close", "volume")})
    return path


def bars_ex_to_csv(bars: Sequence[dict[str, Any]], path: str) -> str:
    """Write full bar records (e.g. from ``adv_id_sim_1``) to ``path`` as CSV.

    Columns are ``mktsim.advanced_intraday.BAR_FIELDS`` in order; every
    record must contain all of them. Returns ``path``.
    """
    from .advanced_intraday import BAR_FIELDS

    rows = list(bars)
    if not rows:
        raise ValueError("bars must be a non-empty list of bar records")
    for b in rows:
        if not isinstance(b, dict) or any(k not in b for k in BAR_FIELDS):
            raise TypeError(f"bars must be bar records with keys {BAR_FIELDS}")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(BAR_FIELDS))
        writer.writeheader()
        for b in rows:
            writer.writerow({k: b[k] for k in BAR_FIELDS})
    return path


def ticks_to_csv(
    prices: Sequence[float],
    volumes: Sequence[int] | None,
    path: str,
) -> str:
    """Write raw ticks to ``path`` as CSV (tick,price,volume). Returns ``path``."""
    clean, vols = _validate_ticks(prices, volumes)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["tick", "price", "volume"])
        for i, p in enumerate(clean):
            writer.writerow([i, f"{p:.2f}", vols[i] if vols is not None else ""])
    return path
