"""Local order book maintainer: dict + bisect sorted list per side."""

from __future__ import annotations

import asyncio
import bisect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

SnapshotCallback = Callable[[str], Awaitable[None]]


class LocalOrderBook:
    """In-memory order book for a single symbol.

    Bids stored as negative prices in a sorted-ascending list so
    ``sorted_bids[0]`` is the most-negative = highest price = best bid.
    Asks stored as positive prices in a sorted-ascending list so
    ``sorted_asks[0]`` is the lowest price = best ask.
    """

    def __init__(
        self,
        symbol: str,
        *,
        max_depth: int = 100,
        snapshot_callback: SnapshotCallback | None = None,
    ) -> None:
        self.symbol = symbol
        self.max_depth = max_depth
        self._snapshot_cb = snapshot_callback

        # price → size
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}

        # sorted price rails
        self._bid_neg: list[float] = []  # ascending negative (-price)
        self._ask_asc: list[float] = []  # ascending positive (price)

        # sequence tracking
        self._last_u: int | None = None
        self._initialized = False
        self._lock = asyncio.Lock()

    # ── queries (lock-free, read-only) ───────────────────────────

    @property
    def initialized(self) -> bool:
        return self._initialized

    def best_bid(self) -> tuple[float, float] | None:
        """Return (price, size) of best bid, or None."""
        for neg in self._bid_neg:
            p = -neg
            s = self._bids.get(p, 0.0)
            if s > 0:
                return (p, s)
        return None

    def best_ask(self) -> tuple[float, float] | None:
        for p in self._ask_asc:
            s = self._asks.get(p, 0.0)
            if s > 0:
                return (p, s)
        return None

    def depth(self, n: int) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
        """Return (bids[:n], asks[:n]) as lists of (price, size)."""
        bids = [(- neg, self._bids[-neg]) for neg in self._bid_neg[:n] if self._bids.get(-neg, 0) > 0]
        asks = [(p, self._asks[p]) for p in self._ask_asc[:n] if self._asks.get(p, 0) > 0]
        return bids, asks

    def mid_price(self) -> float | None:
        bb = self.best_bid()
        ba = self.best_ask()
        if bb and ba:
            return (bb[0] + ba[0]) / 2.0
        return None

    def spread(self) -> float | None:
        bb = self.best_bid()
        ba = self.best_ask()
        if bb and ba:
            return ba[0] - bb[0]
        return None

    # ── mutations (under lock) ───────────────────────────────────

    async def apply_snapshot(
        self, bids: list[list[float]], asks: list[list[float]], update_id: int
    ) -> None:
        """Replace entire book with a REST snapshot."""
        async with self._lock:
            self._bids.clear()
            self._asks.clear()
            self._bid_neg.clear()
            self._ask_asc.clear()

            for p, s in bids:
                if s > 0 and p > 0:
                    self._bids[p] = s
                    bisect.insort(self._bid_neg, -p)
            for p, s in asks:
                if s > 0 and p > 0:
                    self._asks[p] = s
                    bisect.insort(self._ask_asc, p)

            self._last_u = update_id
            self._initialized = True
            logger.debug("snapshot applied %s update_id=%d", self.symbol, update_id)

    async def apply_diff(
        self,
        bids: list[list[float]],
        asks: list[list[float]],
        u: int,
        pu: int | None,
    ) -> bool:
        """Apply incremental diff. Returns False on gap (triggers resync)."""
        async with self._lock:
            if not self._initialized:
                logger.warning("%s: not initialized, requesting snapshot", self.symbol)
                await self._request_snapshot()
                return False

            # duplicate / stale
            assert self._last_u is not None
            if u <= self._last_u:
                logger.debug(
                    "%s: stale u=%d <= last=%d, dropping", self.symbol, u, self._last_u
                )
                return False

            # gap
            if pu is not None and pu != self._last_u:
                logger.warning(
                    "%s: gap detected, expected pu=%d got %d (u=%d). Resyncing.",
                    self.symbol, self._last_u, pu, u,
                )
                self._initialized = False
                await self._request_snapshot()
                return False

            # apply
            self._apply_levels(bids, self._bids, self._bid_neg, is_bid=True)
            self._apply_levels(asks, self._asks, self._ask_asc, is_bid=False)
            self._last_u = u
            return True

    # ── internals ────────────────────────────────────────────────

    def _apply_levels(
        self,
        levels: list[list[float]],
        book: dict[float, float],
        rail: list[float],
        *,
        is_bid: bool,
    ) -> None:
        for p, s in levels:
            if p <= 0:
                continue
            key = -p if is_bid else p
            old = book.get(p, 0.0)
            if s == 0:
                # delete
                if p in book:
                    del book[p]
                    idx = bisect.bisect_left(rail, key)
                    if idx < len(rail) and rail[idx] == key:
                        rail.pop(idx)
            else:
                # upsert
                if old == 0:
                    bisect.insort(rail, key)
                book[p] = s

    async def _request_snapshot(self) -> None:
        if self._snapshot_cb:
            try:
                await self._snapshot_cb(self.symbol)
            except Exception:
                logger.exception("snapshot callback failed for %s", self.symbol)
        else:
            logger.error("no snapshot callback for %s", self.symbol)
