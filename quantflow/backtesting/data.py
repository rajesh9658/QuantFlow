"""Validated historical top-of-book CSV input, with no invented spreads/depth."""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path

from quantflow.common.events import TickEvent
from quantflow.replay.event_store import InMemoryEventStoreReader


def read_quotes(path: str | Path) -> InMemoryEventStoreReader:
    events = []
    required = {"timestamp", "symbol", "bid", "ask", "bid_size", "ask_size", "last"}
    previous: dict[str, datetime] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        if not required.issubset(rows.fieldnames or []):
            raise ValueError("CSV requires: " + ", ".join(sorted(required)))
        for line, row in enumerate(rows, 2):
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                raise ValueError(
                    f"Line {line}: timestamp must have an explicit timezone"
                )
            ts = ts.astimezone(UTC)
            bid, ask, bs, az, last = [
                float(row[k]) for k in ("bid", "ask", "bid_size", "ask_size", "last")
            ]
            if (
                not all(map(math.isfinite, (bid, ask, bs, az, last)))
                or min(bid, ask, last) <= 0
                or min(bs, az) < 0
                or bid > ask
            ):
                raise ValueError(f"Line {line}: invalid quote or depth")
            symbol = row["symbol"].strip()
            if not symbol or ts <= previous.get(
                symbol, datetime.min.replace(tzinfo=UTC)
            ):
                raise ValueError(
                    f"Line {line}: symbol missing or timestamps duplicated/out of order"
                )
            previous[symbol] = ts
            events.append(
                TickEvent(
                    event_id=f"csv_{line}",
                    symbol=symbol,
                    exchange=row.get("exchange", "historical"),
                    timestamp=ts,
                    timestamp_received=ts,
                    bid_price=bid,
                    ask_price=ask,
                    bid_size=bs,
                    ask_size=az,
                    last_price=last,
                    last_size=0,
                )
            )
    if not events:
        raise ValueError("Historical dataset is empty")
    return InMemoryEventStoreReader(events)
