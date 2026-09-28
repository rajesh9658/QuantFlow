"""Market Data Engine: normalize, validate, publish raw exchange data."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from quantflow.common.events import OrderBookEvent, TickEvent, TradeEvent
from quantflow.core.clock import Clock, SystemClock
from quantflow.core.event_bus import AsyncEventBus
from quantflow.core.logging import get_logger

logger = get_logger("market_data_engine")

# ── constants ────────────────────────────────────────────────────

_SYMBOL_RE = re.compile(r"^[A-Z0-9/]+$")
_MIN_TS = datetime(2010, 1, 1, tzinfo=UTC)
_MAX_DRIFT_S = 5  # seconds of allowed clock skew into the future


# ── sequence tracker (per-symbol) ────────────────────────────────

class _SeqTracker:
    """Tracks last accepted sequence id for one symbol's order book."""

    __slots__ = ("last_u",)

    def __init__(self) -> None:
        self.last_u: int | None = None


# ── engine ───────────────────────────────────────────────────────

SnapshotCallback = Callable[[str], Awaitable[None]]


class MarketDataEngine:
    """Normalizes, validates, and publishes raw exchange data to the EventBus.

    Zero trading logic — pure infrastructure.
    """

    def __init__(
        self,
        event_bus: AsyncEventBus,
        clock: Clock | None = None,
    ) -> None:
        self._bus = event_bus
        self.clock = clock or SystemClock()
        self._trackers: dict[str, _SeqTracker] = {}
        self._snapshot_cbs: dict[str, SnapshotCallback] = {}

    # ── snapshot callback registration ───────────────────────────

    def register_snapshot_callback(
        self, symbol: str, cb: SnapshotCallback
    ) -> None:
        self._snapshot_cbs[symbol] = cb

    # ── public entry points ──────────────────────────────────────

    async def process_ticker(self, symbol: str, raw: dict[str, Any]) -> None:
        if not _valid_symbol(symbol):
            return
        bid = _float(raw, "bid")
        ask = _float(raw, "ask")
        last = _float(raw, "last")
        volume = _float(raw, "volume", default=0.0)
        ts = _parse_ts(raw.get("timestamp_ms") or raw.get("timestamp"), clock=self.clock)

        if not _positive(bid, "bid", symbol):
            return
        if not _positive(ask, "ask", symbol):
            return
        if not _positive(last, "last", symbol):
            return
        if volume < 0:
            logger.warning("ticker %s: volume=%s must be >= 0", symbol, volume)
            return
        if not _valid_ts(ts, symbol, clock=self.clock):
            return

        await self._bus.publish(
            TickEvent(
                symbol=symbol,
                exchange="binance",
                bid_price=bid,
                ask_price=ask,
                bid_size=_float(raw, "bidVolume", default=0.0),
                ask_size=_float(raw, "askVolume", default=0.0),
                last_price=last,
                last_size=volume,
                timestamp=ts,
            )
        )

    async def process_orderbook(
        self, symbol: str, raw: dict[str, Any]
    ) -> None:
        if not _valid_symbol(symbol):
            return
        bids = _norm_levels(raw.get("bids", []))
        asks = _norm_levels(raw.get("asks", []))
        ts = _parse_ts(raw.get("timestamp_ms") or raw.get("timestamp"), clock=self.clock)

        if not bids and not asks:
            logger.warning("orderbook %s: empty book", symbol)
            return
        if not _valid_levels(bids, symbol) or not _valid_levels(asks, symbol):
            return
        if not _valid_ts(ts, symbol, clock=self.clock):
            return

        # sequence validation
        u: int | None = raw.get("u")
        pu: int | None = raw.get("pu")
        if u is not None:
            ok = await self._check_seq(symbol, u, pu)
            if not ok:
                return

        await self._bus.publish(
            OrderBookEvent(
                symbol=symbol,
                exchange="binance",
                bids=bids,
                asks=asks,
                timestamp=ts,
            )
        )

    async def process_trade(self, symbol: str, raw: dict[str, Any]) -> None:
        if not _valid_symbol(symbol):
            return
        price = _float(raw, "price")
        size = _float(raw, "size", default=_float(raw, "amount"))
        trade_id = str(raw.get("trade_id", raw.get("id", "")))
        ts = _parse_ts(raw.get("timestamp_ms") or raw.get("timestamp"), clock=self.clock)

        if not _positive(price, "price", symbol):
            return
        if not _positive(size, "size", symbol):
            return
        if not _valid_ts(ts, symbol, clock=self.clock):
            return

        await self._bus.publish(
            TradeEvent(
                symbol=symbol,
                exchange="binance",
                price=price,
                size=size,
                trade_id=trade_id,
                timestamp=ts,
            )
        )

    # ── sequence check ───────────────────────────────────────────

    async def _check_seq(
        self, symbol: str, u: int, pu: int | None
    ) -> bool:
        tracker = self._trackers.setdefault(symbol, _SeqTracker())

        # first event
        if tracker.last_u is None:
            tracker.last_u = u
            return True

        # duplicate / stale
        if u <= tracker.last_u:
            logger.debug(
                "orderbook %s: stale u=%d <= last=%d, dropping",
                symbol, u, tracker.last_u,
            )
            return False

        # gap (pu provided and doesn't match)
        if pu is not None and pu != tracker.last_u:
            logger.warning(
                "orderbook %s: gap detected, expected pu=%d got %d (u=%d). "
                "Triggering resync.",
                symbol, tracker.last_u, pu, u,
            )
            cb = self._snapshot_cbs.get(symbol)
            if cb:
                try:
                    await cb(symbol)
                except Exception:
                    logger.exception("snapshot callback failed for %s", symbol)
            return False

        # clean
        tracker.last_u = u
        return True


# ── pure helpers ─────────────────────────────────────────────────


def _float(d: dict[str, Any], key: str, default: float = 0.0) -> float:
    v = d.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_ts(v: Any, clock: Clock | None = None) -> datetime:
    if v is None:
        return clock.now() if clock else datetime.now(UTC)
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, (int, float)):
        # millis
        if v > 1e15:  # nanos
            v /= 1_000_000
        elif v > 1e12:  # micros
            v /= 1_000
        return datetime.fromtimestamp(v / 1000, tz=UTC)
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return clock.now() if clock else datetime.now(UTC)


def _valid_symbol(sym: str) -> bool:
    if not sym or not _SYMBOL_RE.match(sym):
        logger.warning("invalid symbol: %r", sym)
        return False
    return True


def _positive(val: float, name: str, sym: str) -> bool:
    if val <= 0:
        logger.warning("%s %s: %s=%s must be > 0", "data", sym, name, val)
        return False
    return True


def _valid_ts(ts: datetime, ctx: str, clock: Clock | None = None) -> bool:
    if ts < _MIN_TS:
        logger.warning("%s: timestamp %s before genesis", ctx, ts)
        return False
    now = clock.now() if clock else datetime.now(UTC)
    if (ts - now).total_seconds() > _MAX_DRIFT_S:
        logger.warning("%s: timestamp %s too far in future", ctx, ts)
        return False
    return True


def _norm_levels(raw: list[Any]) -> list[list[float]]:
    """Convert exchange levels to [[price, size], ...]."""
    out: list[list[float]] = []
    for lv in raw:
        if isinstance(lv, (list, tuple)) and len(lv) >= 2:
            out.append([float(lv[0]), float(lv[1])])
        elif isinstance(lv, dict):
            p = lv.get("price") or lv.get("p")
            s = lv.get("size") or lv.get("q") or lv.get("amount")
            if p is not None and s is not None:
                out.append([float(p), float(s)])
    return out


def _valid_levels(levels: list[list[float]], sym: str) -> bool:
    for p, s in levels:
        if p <= 0:
            logger.warning("orderbook %s: price %s <= 0", sym, p)
            return False
        if s < 0:
            logger.warning("orderbook %s: size %s < 0", sym, s)
            return False
    return True
