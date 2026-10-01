"""Bidirectional canonical ↔ native symbol mapping."""

from __future__ import annotations

import re
from typing import Any

from quantflow.config.manager import ConfigManager

_CANONICAL_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+(:[A-Z]+)?$")


class SymbolMappingError(ValueError):
    """Raised when a symbol cannot be mapped between canonical and native forms."""


class SymbolMapper:
    """Config-driven bidirectional mapping between canonical and native symbols.

    Config shape (per exchange):
        exchanges:
          - exchange_id: binance
            symbols:
              "BTC/USDT": "BTCUSDT"
              "ETH/USDT": "ETHUSDT"

    No per-exchange if/else logic: mapping is entirely data-driven from YAML.
    """

    def __init__(self, config: ConfigManager | dict[str, Any]) -> None:
        self._config = config
        # exchange_id -> {canonical: native}
        self._canonical_to_native: dict[str, dict[str, str]] = {}
        # exchange_id -> {native: canonical}
        self._native_to_canonical: dict[str, dict[str, str]] = {}
        self._load()

    # ---------- Public API ----------

    def to_native(self, canonical: str, exchange_id: str) -> str:
        """Translate a canonical symbol to the exchange's native format.

        Raises SymbolMappingError if the exchange does not support it.
        """
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

    def supported_symbols(self, exchange_id: str) -> list[str]:
        """List all canonical symbols configured for an exchange."""
        return sorted(self._canonical_to_native.get(exchange_id, {}).keys())

    def exchanges_for(self, canonical: str) -> list[str]:
        """List exchanges that support a given canonical symbol."""
        canonical_norm = self._normalize_canonical(canonical)
        return [
            eid
            for eid, table in self._canonical_to_native.items()
            if canonical_norm in table
        ]

    # ---------- Internal ----------

    def _load(self) -> None:
        raw_exchanges = (
            self._config.get("exchanges", []) if hasattr(self._config, "get") else []
        )
        if not isinstance(raw_exchanges, list):
            return

        for exch in raw_exchanges:
            if not isinstance(exch, dict):
                continue
            exchange_id = exch.get("exchange_id", "")
            raw_map = exch.get("symbols", {})
            if not isinstance(raw_map, dict):
                raise SymbolMappingError(
                    f"Exchange '{exchange_id}' symbols must be a mapping"
                )
            canonical_to_native: dict[str, str] = {}
            native_to_canonical: dict[str, str] = {}
            for canonical, native in raw_map.items():
                canonical_norm = self._normalize_canonical(canonical)
                if native in native_to_canonical:
                    raise SymbolMappingError(
                        f"Duplicate native symbol '{native}' on '{exchange_id}'"
                    )
                canonical_to_native[canonical_norm] = str(native)
                native_to_canonical[str(native)] = canonical_norm
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
