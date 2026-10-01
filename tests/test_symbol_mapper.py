"""Tests for SymbolMapper: bidirectional round-trip, normalization, error handling."""

from __future__ import annotations

import pytest

from quantflow.config.manager import ConfigManager
from quantflow.market_data.symbol_mapper import SymbolMapper, SymbolMappingError


@pytest.fixture
def config_dict() -> dict:
    return {
        "exchanges": [
            {
                "exchange_id": "binance",
                "type": "binance",
                "symbols": {
                    "BTC/USDT": "BTCUSDT",
                    "ETH/USDT": "ETHUSDT",
                    "SOL/USDT": "SOLUSDT",
                    "XRP/USDT": "XRPUSDT",
                    "ADA/USDT": "ADAUSDT",
                    "BTC/USDT:PERP": "BTCUSDT_PERP",
                },
            },
            {
                "exchange_id": "bybit",
                "type": "bybit",
                "symbols": {
                    "BTC/USDT": "BTCUSDT",
                    "ETH/USDT": "ETHUSDT",
                    "SOL/USDT": "SOLUSDT",
                    "XRP/USDT": "XRPUSDT",
                    "ADA/USDT": "ADAUSDT",
                    "BTC/USDT:PERP": "BTC-PERP",
                },
            },
        ]
    }


def test_symbol_mapper_roundtrip_5_pairs(config_dict: dict) -> None:
    """Symbol mapper round-trips canonical -> Binance format and

    canonical -> Bybit format for >= 5 pairs.
    """
    cfg = ConfigManager(defaults=config_dict)
    mapper = SymbolMapper(cfg)

    pairs = [
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "XRP/USDT",
        "ADA/USDT",
        "BTC/USDT:PERP",
    ]

    # Binance round-trip
    for pair in pairs:
        native = mapper.to_native(pair, "binance")
        canonical = mapper.to_canonical(native, "binance")
        assert canonical == pair

    # Bybit round-trip
    for pair in pairs:
        native = mapper.to_native(pair, "bybit")
        canonical = mapper.to_canonical(native, "bybit")
        assert canonical == pair


def test_symbol_mapper_helpers(config_dict: dict) -> None:
    """Verify is_supported, supported_symbols, and exchanges_for."""
    mapper = SymbolMapper(config_dict)

    assert mapper.is_supported("BTC/USDT", "binance") is True
    assert mapper.is_supported("DOGE/USDT", "binance") is False
    assert mapper.is_supported("invalid_symbol", "binance") is False

    supported = mapper.supported_symbols("binance")
    assert "BTC/USDT" in supported
    assert "ADA/USDT" in supported
    assert len(supported) == 6

    exchanges = mapper.exchanges_for("BTC/USDT")
    assert set(exchanges) == {"binance", "bybit"}


def test_symbol_mapper_errors() -> None:
    """Test invalid symbols, unknown exchanges, and duplicate native mappings."""
    cfg = ConfigManager(
        defaults={
            "exchanges": [
                {
                    "exchange_id": "binance",
                    "type": "binance",
                    "symbols": {"BTC/USDT": "BTCUSDT"},
                }
            ]
        }
    )
    mapper = SymbolMapper(cfg)

    # Invalid canonical symbol regex
    with pytest.raises(SymbolMappingError):
        mapper.to_native("invalid-symbol", "binance")

    with pytest.raises(SymbolMappingError):
        mapper.to_native("", "binance")

    # Unconfigured exchange
    with pytest.raises(SymbolMappingError):
        mapper.to_native("BTC/USDT", "unknown_exchange")

    with pytest.raises(SymbolMappingError):
        mapper.to_canonical("BTCUSDT", "unknown_exchange")

    # Unmapped symbol
    with pytest.raises(SymbolMappingError):
        mapper.to_native("ETH/USDT", "binance")

    with pytest.raises(SymbolMappingError):
        mapper.to_canonical("ETHUSDT", "binance")

    # Duplicate native symbol in config
    dup_config = {
        "exchanges": [
            {
                "exchange_id": "binance",
                "type": "binance",
                "symbols": {
                    "BTC/USDT": "BTCUSDT",
                    "BTC/USD": "BTCUSDT",  # Duplicate native
                },
            }
        ]
    }
    with pytest.raises(SymbolMappingError):
        SymbolMapper(dup_config)
