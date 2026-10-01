QuantFlow Multi-Exchange Extension Spec
Overview
Extend QuantFlow from a single-exchange system (Binance) to a multi-exchange system where N adapters run concurrently, events carry an explicit exchange_id, and Risk/Execution route orders to the correct exchange without any exchange-specific branching. The change surface is:

ExchangeRegistry — holds N adapters, starts/stops them concurrently with failure isolation, exposes per-exchange status.

SymbolMapper — config-driven canonical ↔ native symbol translation.

Config schema — exchanges becomes a list of per-exchange blocks.

Event schema — payloads gain exchange_id.

Market Data Engine — subscribes across N adapters and tags every event, reusing the same normalization/validation code.

The existing single-exchange code is treated as the N=1 case of the new design, so no if exchange_id == "binance" branches anywhere.

1. Canonical Symbol Format
Chosen format: BASE/QUOTE in uppercase (e.g., BTC/USDT), with an optional venue suffix BASE/QUOTE:VENUE for derivatives (e.g., BTC/USDT:PERP).

Justification:

It matches CCXT's unified symbol (BTC/USDT), which both the Binance and Bybit adapters already use internally. No translation is needed at the CCXT layer — only at the exchange's raw API layer.

It's the de facto standard across the Python quant ecosystem: pandas-ta, backtrader, vectorbt, ccxt, and most data providers (CoinGecko, CoinAPI) accept or emit it.

It's unambiguous (no dash-vs-underscore confusion), human-readable, and case-normalized to uppercase to avoid btc/usdt vs BTC/USDT drift.

The :VENUE suffix (spot omitted, :PERP/:FUT/:OPT present) keeps spot and derivatives of the same pair distinct without introducing a second dimension in every API.

Rejected alternatives:

BTCUSDT (Binance native): ambiguous without an exchange context; not portable.

BTC-USDT (Bybit native): same problem.

BTC_USDT: not used by any major library.

Normalization rule: The SymbolMapper uppercases all inputs and rejects anything that doesn't match ^[A-Z0-9]+/[A-Z0-9]+(:[A-Z]+)?$.

2. ExchangeRegistry
python
# core/exchange_registry.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Callable
import asyncio

from core.interfaces import ExchangeAdapter
from config_manager import ConfigManager
from clock import Clock
from logging_setup import get_logger


@dataclass
class ExchangeStatus:
    """Snapshot of an adapter's current lifecycle state."""
    exchange_id: str
    enabled: bool
    connected: bool
    connected_since: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    last_error: Optional[str] = None
    reconnect_count: int = 0


AdapterBuilder = Callable[[str, dict, ConfigManager, Clock], ExchangeAdapter]
"""Signature: (exchange_id, exchange_cfg, config, clock) -> ExchangeAdapter."""


class ExchangeRegistry:
    """
    Holds N ExchangeAdapter instances keyed by exchange_id.
    Concurrent lifecycle with independent failure isolation:
    one adapter failing to connect does not prevent others from starting.
    """

    def __init__(
        self,
        config: ConfigManager,
        clock: Clock,
        adapter_builders: Dict[str, AdapterBuilder],
    ):
        """
        :param config: layered config manager (Sprint 1)
        :param clock: time source (Sprint 13) — used for status timestamps
        :param adapter_builders: mapping from `type` (in YAML) to a builder function.
        """
        self._config = config
        self._clock = clock
        self._builders = adapter_builders
        self._adapters: Dict[str, ExchangeAdapter] = {}
        self._status: Dict[str, ExchangeStatus] = {}
        self._start_tasks: Dict[str, asyncio.Task] = {}
        self._logger = get_logger("exchange_registry")

    async def register(self, exchange_id: str, adapter: ExchangeAdapter) -> None:
        """Register an already-constructed adapter (used by tests / DI)."""
        if exchange_id in self._adapters:
            raise ValueError(f"Exchange '{exchange_id}' already registered")
        self._adapters[exchange_id] = adapter
        self._status[exchange_id] = ExchangeStatus(
            exchange_id=exchange_id, enabled=True, connected=False,
        )

    async def start_all(self) -> Dict[str, Exception]:
        """
        Concurrently connect all enabled adapters.
        Failure isolation: each adapter's connect() runs in its own task;
        an exception is captured per-exchange and does NOT abort the others.
        Returns a dict of {exchange_id: exception} for any that failed.
        """
        enabled = self._read_exchange_configs(enabled_only=True)
        coros = [self._start_one(cfg) for cfg in enabled]
        results = await asyncio.gather(*coros, return_exceptions=True)

        failures: Dict[str, Exception] = {}
        for cfg, result in zip(enabled, results):
            if isinstance(result, Exception):
                failures[cfg["exchange_id"]] = result
                self._logger.error(
                    f"Exchange {cfg['exchange_id']} failed to start: {result}",
                    exc_info=result,
                )
        return failures

    async def stop_all(self) -> None:
        """Concurrently disconnect all adapters. Errors are logged, not raised."""
        coros = [self._stop_one(eid) for eid in list(self._adapters.keys())]
        await asyncio.gather(*coros, return_exceptions=True)

    async def start(self, exchange_id: str) -> None:
        """Start a single adapter (used for hot-enable)."""
        cfg = self._find_config(exchange_id)
        await self._start_one(cfg)

    async def stop(self, exchange_id: str) -> None:
        """Stop a single adapter (used for hot-disable / maintenance)."""
        await self._stop_one(exchange_id)

    def get(self, exchange_id: str) -> ExchangeAdapter:
        """Return the adapter. Raises KeyError if unknown."""
        if exchange_id not in self._adapters:
            raise KeyError(f"No exchange registered with id '{exchange_id}'")
        return self._adapters[exchange_id]

    def get_status(self, exchange_id: str) -> ExchangeStatus:
        """Return a status snapshot for a single exchange."""
        if exchange_id not in self._status:
            raise KeyError(f"No exchange registered with id '{exchange_id}'")
        return self._status[exchange_id]

    def get_all_status(self) -> Dict[str, ExchangeStatus]:
        """Return status snapshots for every registered exchange."""
        return dict(self._status)

    # ---------- Internal ----------

    async def _start_one(self, cfg: dict) -> None:
        exchange_id = cfg["exchange_id"]
        adapter_type = cfg["type"]

        if exchange_id in self._adapters:
            self._logger.debug(f"Exchange {exchange_id} already started")
            return

        builder = self._builders.get(adapter_type)
        if builder is None:
            raise ValueError(
                f"No adapter builder registered for type '{adapter_type}' "
                f"(exchange_id={exchange_id})"
            )

        adapter = builder(exchange_id, cfg, self._config, self._clock)
        self._adapters[exchange_id] = adapter
        self._status[exchange_id] = ExchangeStatus(
            exchange_id=exchange_id,
            enabled=cfg.get("enabled", True),
            connected=False,
        )

        try:
            await adapter.connect()
            self._status[exchange_id].connected = True
            self._status[exchange_id].connected_since = self._clock.now()
            self._logger.info(f"Exchange {exchange_id} connected")
        except Exception:
            self._status[exchange_id].connected = False
            self._status[exchange_id].last_error = "connect() failed"
            raise

    async def _stop_one(self, exchange_id: str) -> None:
        adapter = self._adapters.get(exchange_id)
        if adapter is None:
            return
        try:
            await adapter.disconnect()
        except Exception as e:
            self._logger.warning(f"Exchange {exchange_id} disconnect error: {e}")
        finally:
            self._status[exchange_id].connected = False
            self._logger.info(f"Exchange {exchange_id} stopped")

    def _read_exchange_configs(self, enabled_only: bool = False) -> List[dict]:
        exchanges = self._config.get("exchanges", [])
        if enabled_only:
            return [e for e in exchanges if e.get("enabled", True)]
        return exchanges

    def _find_config(self, exchange_id: str) -> dict:
        for e in self._read_exchange_configs():
            if e["exchange_id"] == exchange_id:
                return e
        raise KeyError(f"No config found for exchange '{exchange_id}'")
Failure isolation guarantee: asyncio.gather(..., return_exceptions=True) ensures one adapter's connect() exception does not cancel the others. The failing adapter is recorded in _status with connected=False and last_error populated, but the registry continues operating for the rest.

3. SymbolMapper
python
# core/symbol_mapper.py
import re
from typing import Dict, List, Optional
from config_manager import ConfigManager


_CANONICAL_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+(:[A-Z]+)?$")


class SymbolMappingError(ValueError):
    """Raised when a symbol cannot be mapped between canonical and native forms."""


class SymbolMapper:
    """
    Config-driven bidirectional mapping between canonical and native symbols.
    Config shape (per exchange):

        exchanges:
          - exchange_id: binance
            symbols:
              "BTC/USDT": "BTCUSDT"
              "ETH/USDT": "ETHUSDT"

    No per-exchange if/else logic: mapping is entirely data-driven from YAML.
    """

    def __init__(self, config: ConfigManager):
        self._config = config
        # exchange_id -> {canonical: native}
        self._canonical_to_native: Dict[str, Dict[str, str]] = {}
        # exchange_id -> {native: canonical}
        self._native_to_canonical: Dict[str, Dict[str, str]] = {}
        self._load()

    # ---------- Public API ----------

    def to_native(self, canonical: str, exchange_id: str) -> str:
        """Translate a canonical symbol to the exchange's native format.
        Raises SymbolMappingError if the exchange does not support it."""
        canonical_norm = self._normalize_canonical(canonical)
        table = self._canonical_to_native.get(exchange_id)
        if table is None:
            raise SymbolMappingError(f"Exchange '{exchange_id}' is not configured")
        native = table.get(canonical_norm)
        if native is None:
            raise SymbolMappingError(
                f"Symbol '{canonical_norm}' not supported on '{exchange_id}'"
            )
        return native

    def to_canonical(self, native: str, exchange_id: str) -> str:
        """Translate an exchange-native symbol to canonical form."""
        table = self._native_to_canonical.get(exchange_id)
        if table is None:
            raise SymbolMappingError(f"Exchange '{exchange_id}' is not configured")
        canonical = table.get(native)
        if canonical is None:
            raise SymbolMappingError(
                f"Native symbol '{native}' is not mapped for '{exchange_id}'"
            )
        return canonical

    def is_supported(self, canonical: str, exchange_id: str) -> bool:
        """Return True if the canonical symbol is enabled for this exchange."""
        try:
            canonical_norm = self._normalize_canonical(canonical)
        except SymbolMappingError:
            return False
        return canonical_norm in self._canonical_to_native.get(exchange_id, {})

    def supported_symbols(self, exchange_id: str) -> List[str]:
        """List all canonical symbols configured for an exchange."""
        return sorted(self._canonical_to_native.get(exchange_id, {}).keys())

    def exchanges_for(self, canonical: str) -> List[str]:
        """List exchanges that support a given canonical symbol."""
        canonical_norm = self._normalize_canonical(canonical)
        return [
            eid for eid, table in self._canonical_to_native.items()
            if canonical_norm in table
        ]

    # ---------- Internal ----------

    def _load(self) -> None:
        for exch in self._config.get("exchanges", []):
            exchange_id = exch["exchange_id"]
            raw_map = exch.get("symbols", {})
            if not isinstance(raw_map, dict):
                raise SymbolMappingError(
                    f"Exchange '{exchange_id}' symbols must be a mapping"
                )
            canonical_to_native: Dict[str, str] = {}
            native_to_canonical: Dict[str, str] = {}
            for canonical, native in raw_map.items():
                canonical_norm = self._normalize_canonical(canonical)
                if native in native_to_canonical:
                    raise SymbolMappingError(
                        f"Duplicate native symbol '{native}' on '{exchange_id}'"
                    )
                canonical_to_native[canonical_norm] = native
                native_to_canonical[native] = canonical_norm
            self._canonical_to_native[exchange_id] = canonical_to_native
            self._native_to_canonical[exchange_id] = native_to_canonical

    @staticmethod
    def _normalize_canonical(symbol: str) -> str:
        if not isinstance(symbol, str) or not symbol:
            raise SymbolMappingError(f"Invalid canonical symbol: {symbol!r}")
        upper = symbol.upper()
        if not _CANONICAL_RE.match(upper):
            raise SymbolMappingError(
                f"Canonical symbol '{symbol}' does not match BASE/QUOTE[:VENUE]"
            )
        return upper
Design note: The mapper is instantiated once and injected into every adapter and into the Market Data Engine. It is the only place symbol translation happens — no other module imports exchange names.

4. Config Schema Change
4.1 Old shape (single exchange)
yaml
exchanges:
  - name: binance
    type: binance
    config:
      base_url: "https://api.binance.com"
      api_key: "{{secret:binance_api_key}}"
      api_secret: "{{secret:binance_api_secret}}"
4.2 New shape (list of exchange instances)
yaml
exchanges:
  - exchange_id: binance            # unique instance id (used in events, orders)
    type: binance                   # adapter implementation key
    enabled: true
    credentials_ref: "vault:secret/quantflow/binance"
    symbols:
      "BTC/USDT": "BTCUSDT"
      "ETH/USDT": "ETHUSDT"
      "SOL/USDT": "SOLUSDT"
    rate_limit_overrides:
      requests_per_second: 20
      websocket_streams: 200
    reconnect:
      max_retries: 10
      base_delay_seconds: 1.0
      max_delay_seconds: 60.0

  - exchange_id: bybit
    type: bybit
    enabled: true
    credentials_ref: "vault:secret/quantflow/bybit"
    symbols:
      "BTC/USDT": "BTCUSDT"
      "ETH/USDT": "ETHUSDT"
      "SOL/USDT": "SOLUSDT"
    rate_limit_overrides:
      requests_per_second: 10
      websocket_streams: 100
    reconnect:
      max_retries: 10
      base_delay_seconds: 1.0
      max_delay_seconds: 60.0

  # Future: multiple instances of the same type (e.g., sub-accounts)
  # - exchange_id: bybit-alt
  #   type: bybit
  #   enabled: false
  #   credentials_ref: "vault:secret/quantflow/bybit-alt"
  #   ...
Field semantics:

Field	Meaning
exchange_id	Unique instance identifier. Appears verbatim in every SignalEvent and OrderEvent. Allows multiple instances of the same type (e.g., sub-accounts).
type	Selects which AdapterBuilder to use. Maps to an implementation in ADAPTER_BUILDERS.
enabled	If false, the registry skips this exchange during start_all().
credentials_ref	"vault:path/to/secret" or "env:VAR_NAME". Resolved by the SecretsProvider (Sprint 1).
symbols	Map of canonical → native. Consumed by SymbolMapper at startup.
rate_limit_overrides	Per-exchange throttling. Adapter reads these; defaults apply if absent.
reconnect	Per-exchange backoff parameters (Binance and Bybit may need different tuning).
ConfigManager support: The _read_exchange_configs() helper in ExchangeRegistry handles the list shape. The old single-block shape is not supported — the migration is a one-time YAML edit. This is intentional: keeping two shapes alive creates drift.

5. Event Schema Changes
Every market data and order-related payload gains an explicit exchange_id: str field. This is the single mechanism by which Risk, Execution, Portfolio, and Analytics know which exchange an event refers to — without any exchange-specific logic.

5.1 Updated payloads
python
# events.py (relevant excerpt)
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class TickerPayload(BaseModel):
    exchange_id: str                  # NEW
    symbol: str                       # canonical
    bid: float
    ask: float
    last: float
    volume: float
    timestamp: datetime


class OrderBookLevel(BaseModel):
    price: float
    size: float


class OrderBookPayload(BaseModel):
    exchange_id: str                  # NEW
    symbol: str                       # canonical
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    timestamp: datetime


class TradePayload(BaseModel):
    exchange_id: str                  # NEW
    symbol: str
    price: float
    size: float
    trade_id: str
    timestamp: datetime


class SignalDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class SignalPayload(BaseModel):
    exchange_id: str                  # NEW — where this signal should be executed
    strategy_id: str
    symbol: str                       # canonical
    direction: SignalDirection
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime


class ApprovedSignalPayload(BaseModel):
    exchange_id: str                  # NEW — copied from SignalPayload
    signal_id: str
    strategy_id: str
    symbol: str
    direction: SignalDirection
    confidence: float
    timestamp: datetime


class RejectedSignalPayload(BaseModel):
    exchange_id: str                  # NEW
    signal_id: str
    reason: str
    timestamp: datetime


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderPayload(BaseModel):
    exchange_id: str                  # NEW — routing target
    order_id: str
    symbol: str                       # canonical
    side: OrderSide
    order_type: OrderType
    quantity: float
    limit_price: Optional[float] = None
    time_in_force: str = "GTC"
    timestamp: datetime


class FillPayload(BaseModel):
    exchange_id: str                  # NEW
    order_id: str
    fill_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    commission: float = 0.0
    timestamp: datetime
5.2 How Risk and Execution route without exchange-specific logic
Risk Engine (_handle_signal):

python
async def _handle_signal(self, event: SignalEvent) -> None:
    exchange_id = event.payload.exchange_id
    # Per-exchange risk limits come from config: risk.exchanges.<exchange_id>.*
    limits = self.config.get(f"risk.exchanges.{exchange_id}", default={})
    approved, reason = await self._validate_signal(event, limits)
    if approved:
        # Emit ApprovedSignalEvent preserving exchange_id
        await self._approve(event)
    else:
        await self._reject(event, reason)
No branching on exchange_id. If the config has no per-exchange section, global defaults apply.

Execution Handler (submit_order):

python
async def submit_order(self, order: OrderPayload) -> str:
    adapter = self.registry.get(order.exchange_id)   # ← single routing line
    native_symbol = self.symbol_mapper.to_native(order.symbol, order.exchange_id)
    # Adapter interface is already exchange-agnostic (Sprint 3)
    return await adapter.send_order(order, native_symbol)
Execution does not know whether order.exchange_id is "binance" or "bybit". It looks up the adapter from the registry and calls the same method. The only per-exchange adaptation (native symbol format) is delegated to SymbolMapper.

Strategy:

A strategy generating a signal picks the target exchange based on its own config (or per-symbol routing rules). It sets exchange_id on the payload; the rest of the pipeline is unchanged.

6. Market Data Engine — Multi-Adapter
6.1 Design
The Market Data Engine owns a single MarketDataEngine instance that:

Receives raw frames from every registered adapter via a shared RawMarketData envelope.

Applies the same normalization + validation code to every frame, with exchange_id and the native symbol carried through.

Publishes canonical TickerEvent / OrderBookEvent / TradeEvent with exchange_id set in the payload.

Per-exchange logic is confined to the adapters — they translate native WS frames into a small common shape. The engine has zero adapter-specific code.

text
┌──────────────┐   RawMarketData   ┌───────────────────┐   TickerEvent   ┌──────────┐
│ BinanceAdapter├──────────────────►│                   │   OrderBookEvent│          │
└──────────────┘                   │  MarketDataEngine ├────────────────►│ EventBus │
┌──────────────┐                   │  (single instance)│                 └──────────┘
│  BybitAdapter ├──────────────────►│                   │
└──────────────┘                   └───────────────────┘
6.2 Raw envelope
python
# market_data/raw.py
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Dict, Any


@dataclass
class RawMarketData:
    """
    Common intermediate shape emitted by every adapter.
    Adapters extract fields from native frames into these keys;
    normalization/validation is done once by the MarketDataEngine.
    """
    exchange_id: str
    symbol_native: str
    kind: Literal["ticker", "orderbook", "trade"]
    data: Dict[str, Any]
    received_at: datetime
data for each kind uses a fixed key schema:

Kind	Keys
ticker	bid, ask, last, volume, timestamp_ms
orderbook	bids, asks, u (update id), pu (prev update id), lastUpdateId (snapshot), timestamp_ms
trade	price, size, trade_id, timestamp_ms
Adapters do minimal work: pull fields from the native frame into these keys. Field-level validation happens in the engine.

6.3 Updated Market Data Engine
python
# market_data/engine.py
from typing import Dict, Tuple, Optional
from datetime import datetime, timezone
from uuid import uuid4

from events import (
    TickerEvent, OrderBookEvent, TradeEvent,
    TickerPayload, OrderBookPayload, TradePayload, OrderBookLevel,
    EventType,
)
from interfaces import EventBus
from clock import Clock
from core.symbol_mapper import SymbolMapper
from market_data.raw import RawMarketData
from logging_setup import get_logger


class MarketDataEngine:
    """
    Single instance, N adapters. Normalization and validation are shared;
    exchange-specific parsing lives inside each adapter.
    """

    def __init__(
        self,
        event_bus: EventBus,
        clock: Clock,
        symbol_mapper: SymbolMapper,
    ):
        self.event_bus = event_bus
        self.clock = clock
        self.symbol_mapper = symbol_mapper
        self.logger = get_logger("market_data_engine")
        # (exchange_id, symbol_native) -> last update id
        self._seq: Dict[Tuple[str, str], int] = {}

    # ---------- Sink entrypoint (called by every adapter) ----------

    async def on_raw_market_data(self, raw: RawMarketData) -> None:
        """Single entrypoint for all adapters. Dispatches by kind."""
        try:
            canonical = self.symbol_mapper.to_canonical(
                raw.symbol_native, raw.exchange_id
            )
        except Exception as e:
            self.logger.warning(
                f"Unmapped symbol {raw.symbol_native!r} on {raw.exchange_id}: {e}"
            )
            return

        if raw.kind == "ticker":
            await self._process_ticker(raw, canonical)
        elif raw.kind == "orderbook":
            await self._process_orderbook(raw, canonical)
        elif raw.kind == "trade":
            await self._process_trade(raw, canonical)
        else:
            self.logger.warning(f"Unknown raw kind: {raw.kind}")

    # ---------- Ticker ----------

    async def _process_ticker(self, raw: RawMarketData, canonical: str) -> None:
        d = raw.data
        bid, ask, last = d.get("bid"), d.get("ask"), d.get("last")
        volume = d.get("volume", 0.0)
        ts_ms = d.get("timestamp_ms")

        if not self._validate_prices(bid, ask, last):
            return
        if volume < 0:
            return
        ts = self._to_datetime(ts_ms)
        if not self._validate_timestamp(ts):
            return

        payload = TickerPayload(
            exchange_id=raw.exchange_id,
            symbol=canonical,
            bid=float(bid), ask=float(ask), last=float(last),
            volume=float(volume),
            timestamp=ts,
        )
        await self.event_bus.publish(TickerEvent(
            event_id=uuid4(),
            event_type=EventType.TICKER,
            schema_version=2,                # bumped: exchange_id added
            timestamp_exchange=ts,
            timestamp_received=self.clock.now(),
            source=raw.exchange_id,          # source mirrors exchange_id
            payload=payload,
        ))

    # ---------- OrderBook ----------

    async def _process_orderbook(self, raw: RawMarketData, canonical: str) -> None:
        d = raw.data
        bids = d.get("bids", [])
        asks = d.get("asks", [])
        u = d.get("u")
        pu = d.get("pu")

        # Sequence validation is per (exchange_id, native symbol)
        key = (raw.exchange_id, raw.symbol_native)
        last = self._seq.get(key)
        if u is not None:
            if last is not None and u <= last:
                return  # duplicate/stale
            if last is not None and pu is not None and pu != last:
                self.logger.warning(
                    f"Gap on {raw.exchange_id}/{raw.symbol_native}: "
                    f"expected {last}, got pu={pu}, u={u}"
                )
                # Adapter will receive the resync signal out-of-band (Sprint 5).
                return
            self._seq[key] = u

        if not self._validate_levels(bids) or not self._validate_levels(asks):
            return
        if not bids and not asks:
            return

        ts = self._to_datetime(d.get("timestamp_ms"))
        if not self._validate_timestamp(ts):
            return

        payload = OrderBookPayload(
            exchange_id=raw.exchange_id,
            symbol=canonical,
            bids=[OrderBookLevel(price=p, size=s) for p, s in bids],
            asks=[OrderBookLevel(price=p, size=s) for p, s in asks],
            timestamp=ts,
        )
        await self.event_bus.publish(OrderBookEvent(
            event_id=uuid4(),
            event_type=EventType.ORDER_BOOK,
            schema_version=2,
            timestamp_exchange=ts,
            timestamp_received=self.clock.now(),
            source=raw.exchange_id,
            payload=payload,
        ))

    # ---------- Trade ----------

    async def _process_trade(self, raw: RawMarketData, canonical: str) -> None:
        d = raw.data
        price, size = d.get("price"), d.get("size")
        if price is None or price <= 0:
            return
        if size is None or size <= 0:
            return

        ts = self._to_datetime(d.get("timestamp_ms"))
        if not self._validate_timestamp(ts):
            return

        payload = TradePayload(
            exchange_id=raw.exchange_id,
            symbol=canonical,
            price=float(price),
            size=float(size),
            trade_id=str(d.get("trade_id", "")),
            timestamp=ts,
        )
        await self.event_bus.publish(TradeEvent(
            event_id=uuid4(),
            event_type=EventType.TRADE,
            schema_version=2,
            timestamp_exchange=ts,
            timestamp_received=self.clock.now(),
            source=raw.exchange_id,
            payload=payload,
        ))

    # ---------- Shared validators (unchanged from Sprint 5) ----------

    def _validate_prices(self, bid, ask, last) -> bool:
        return all(x is not None and x > 0 for x in (bid, ask, last))

    def _validate_levels(self, levels) -> bool:
        for lvl in levels:
            try:
                p, s = float(lvl[0]), float(lvl[1])
            except (TypeError, ValueError, IndexError):
                return False
            if p <= 0 or s < 0:
                return False
        return True

    def _validate_timestamp(self, ts: datetime) -> bool:
        from datetime import timezone
        now = self.clock.now()
        if ts < datetime(2010, 1, 1, tzinfo=timezone.utc):
            return False
        if (ts - now).total_seconds() > 5:
            return False
        return True

    @staticmethod
    def _to_datetime(ts_ms) -> datetime:
        from datetime import timezone
        if ts_ms is None:
            return datetime.now(timezone.utc)
        if ts_ms > 1e12:
            ts_ms = ts_ms / 1_000_000
        return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
6.4 Adapter integration (Bybit example sketch)
python
# adapters/bybit.py (skeleton — highlights the RawMarketData translation)
class BybitAdapter(ExchangeAdapter):
    def __init__(self, exchange_id, cfg, config, clock, sink: MarketDataEngine, symbol_mapper):
        self.exchange_id = exchange_id
        self.cfg = cfg
        self.config = config
        self.clock = clock
        self.sink = sink
        self.symbol_mapper = symbol_mapper
        self.rate_limits = cfg.get("rate_limit_overrides", {})

    async def _on_ws_ticker(self, native_frame: dict) -> None:
        # Bybit public ticker frame has `topic`, `data: {symbol, bid1Price, ask1Price, lastPrice, volume24h, ts}`
        d = native_frame["data"]
        raw = RawMarketData(
            exchange_id=self.exchange_id,
            symbol_native=d["symbol"],
            kind="ticker",
            data={
                "bid": float(d["bid1Price"]),
                "ask": float(d["ask1Price"]),
                "last": float(d["lastPrice"]),
                "volume": float(d["volume24h"]),
                "timestamp_ms": int(d["ts"]),
            },
            received_at=self.clock.now(),
        )
        await self.sink.on_raw_market_data(raw)

    # ... equivalent handlers for orderbook and trades ...
Key property: BybitAdapter._on_ws_ticker extracts Bybit's fields into the common keys. Everything after sink.on_raw_market_data(raw) is exchange-agnostic. Adding a third exchange (OKX, Kraken, etc.) requires only writing a new adapter that emits RawMarketData — no changes to the Market Data Engine, Risk, Execution, or Portfolio.

7. Wiring at the Composition Root
python
# main.py
async def build_app(mode: str):
    config = ConfigManager(Path("quantflow.yaml"))
    clock = SystemClock() if mode != "replay" else SimulatedClock(...)

    event_bus = InMemoryEventBus(clock=clock)
    symbol_mapper = SymbolMapper(config)
    market_engine = MarketDataEngine(event_bus, clock, symbol_mapper)

    ADAPTER_BUILDERS: Dict[str, AdapterBuilder] = {
        "binance": lambda eid, cfg, c, clk: BinanceAdapter(
            eid, cfg, c, clk, market_engine, symbol_mapper,
        ),
        "bybit": lambda eid, cfg, c, clk: BybitAdapter(
            eid, cfg, c, clk, market_engine, symbol_mapper,
        ),
    }

    registry = ExchangeRegistry(config, clock, ADAPTER_BUILDERS)
    failures = await registry.start_all()
    if failures:
        logger.warning(f"Some exchanges failed to start: {list(failures.keys())}")

    # Subscribe adapters to streams
    for exch_cfg in config.get("exchanges", []):
        if not exch_cfg.get("enabled", True):
            continue
        eid = exch_cfg["exchange_id"]
        adapter = registry.get(eid)
        native_symbols = [
            symbol_mapper.to_native(c, eid)
            for c in symbol_mapper.supported_symbols(eid)
        ]
        await adapter.subscribe_market_data(native_symbols)

    # Risk and Execution see only exchange_id strings
    execution = PaperExecutionHandler(config, event_bus, order_books, clock, registry, symbol_mapper)
    risk = RiskEngine(config, event_bus, execution, clock)
    # ... start everything ...
8. Summary of Invariants
Invariant	Enforcement
One exchange failing does not stop others	asyncio.gather(..., return_exceptions=True) in ExchangeRegistry.start_all()
Canonical symbols only outside adapters	SymbolMapper is the sole translator; enforced by types — adapters accept native, everything else accepts canonical
No per-exchange branching in Risk/Execution	Routing is registry.get(order.exchange_id) — a single lookup
Every market data event is tagged	Payload field exchange_id (schema_version bumped to 2)
Every signal/order event is tagged	Payload field exchange_id (schema_version bumped to 2)
Adapters do minimal parsing	They only translate native WS frames into RawMarketData with a fixed key schema
Normalization/validation is written once	All in MarketDataEngine; no per-adapter copies
Config-driven symbol support	SymbolMapper._load() reads the exchanges[].symbols map
The design extends N=1 to N=k without touching Risk, Execution, Portfolio, Analytics, or the Event Bus. Adding OKX later is a new adapter file plus a type: okx entry in ADAPTER_BUILDERS and YAML.