"""Re-export SymbolMapper in core for spec compatibility."""

from quantflow.market_data.symbol_mapper import SymbolMapper, SymbolMappingError

__all__ = ["SymbolMapper", "SymbolMappingError"]
