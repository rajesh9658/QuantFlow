"""Raw market data envelope emitted by exchange adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


@dataclass
class RawMarketData:
    """Common intermediate shape emitted by every adapter.

    Adapters extract fields from native frames into these keys;
    normalization/validation is done once by the MarketDataEngine.
    """

    exchange_id: str
    symbol_native: str
    kind: Literal["ticker", "orderbook", "trade"]
    data: dict[str, Any]
    received_at: datetime
