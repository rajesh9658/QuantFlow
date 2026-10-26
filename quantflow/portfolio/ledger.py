"""Shared fill accounting and configurable spot-VDA tax reserve estimates.

Tax estimates use FIFO acquisition prices, exclude fee deductions, and never
offset losing disposals against winning disposals. They are research estimates
in the account quote currency, not an INR tax return or derivative tax model.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

from quantflow.common.events import FillEvent


@dataclass
class LedgerPosition:
    quantity: float = 0.0
    average: float = 0.0
    opening_fees: float = 0.0


class AccountLedger:
    def __init__(self, cash: float, tax_rate: float = 0.0) -> None:
        if not math.isfinite(cash) or cash < 0 or not 0 <= tax_rate <= 1:
            raise ValueError("Invalid initial cash or tax rate")
        self.initial_cash = self.cash = cash
        self.tax_rate = tax_rate
        self.tax_reserve = 0.0
        self.taxable_gains = 0.0
        self.total_fees = 0.0
        self.gross_realized_pnl = 0.0
        self.positions: dict[str, LedgerPosition] = {}
        self.lots: dict[str, deque[list[float]]] = {}
        self.fills: dict[str, FillEvent] = {}

    @property
    def available_cash(self) -> float:
        return max(0.0, self.cash - self.tax_reserve)

    def apply(self, fill: FillEvent) -> FillEvent:
        if fill.fill_id in self.fills:
            return self.fills[fill.fill_id]
        qty, px, fee = fill.quantity, fill.fill_price, fill.commission
        if (fill.side not in {"BUY", "SELL"} or not all(map(math.isfinite, (qty, px, fee)))
                or qty <= 0 or px <= 0 or fee < 0):
            raise ValueError("Invalid fill")
        pos = self.positions.setdefault(fill.symbol, LedgerPosition())
        old = pos.quantity
        delta = qty if fill.side == "BUY" else -qty
        closed = min(abs(old), qty) if old * delta < 0 else 0.0
        gross = closed * (px - pos.average) * (1 if old > 0 else -1)
        allocated_entry_fee = pos.opening_fees * closed / abs(old) if closed else 0.0
        closing_fee = fee * closed / qty
        net_closed = gross - allocated_entry_fee - closing_fee
        new = old + delta
        remaining_entry_fee = pos.opening_fees - allocated_entry_fee
        if old * delta >= 0:
            pos.average = (abs(old)*pos.average + qty*px) / abs(new)
            pos.opening_fees += fee
        elif old * new > 0:
            pos.opening_fees = remaining_entry_fee
        elif abs(new) > 1e-12:
            pos.average = px
            pos.opening_fees = fee - closing_fee
        else:
            pos.average = pos.opening_fees = 0.0
        pos.quantity = new if abs(new) > 1e-12 else 0.0
        self.cash += (-qty*px if delta > 0 else qty*px) - fee
        self.total_fees += fee
        self.gross_realized_pnl += gross

        # FIFO tax gain is aggregated per disposal, before clipping its loss.
        lots = self.lots.setdefault(fill.symbol, deque())
        taxable = 0.0
        if fill.side == "BUY" and old >= 0:
            lots.append([qty, px])
        elif fill.side == "SELL" and old > 0:
            remaining, gain = min(qty, old), 0.0
            while remaining > 1e-12 and lots:
                amount, cost = lots[0]
                used = min(amount, remaining)
                gain += used * (px-cost)
                lots[0][0] -= used
                remaining -= used
                if lots[0][0] <= 1e-12:
                    lots.popleft()
            taxable = max(0.0, gain)
            self.taxable_gains += taxable
            self.tax_reserve += taxable*self.tax_rate

        enriched = fill.model_copy(update={"realized_pnl": gross-fee,
            "metadata": {**fill.metadata, "accounted": True,
                "closed_quantity": closed, "closed_trade_pnl": net_closed,
                "gross_realized_pnl": gross, "taxable_gain": taxable,
                "tax_gain_before_floor": gain if fill.side == "SELL" and old > 0 else 0.0,
                "tax_reserve": self.tax_reserve}})
        self.fills[fill.fill_id] = enriched
        return enriched

    def apply_order(self, fills: list[FillEvent]) -> list[FillEvent]:
        """Aggregate tax gain across depth fills from one disposal before flooring."""
        if not fills:
            return []
        if all(f.fill_id in self.fills for f in fills):
            return [self.fills[f.fill_id] for f in fills]
        if any(f.fill_id in self.fills for f in fills):
            raise ValueError("Cannot apply a partially duplicated order batch")
        previous_taxable = self.taxable_gains
        accounted = [self.apply(fill) for fill in fills]
        net_closed = sum(f.metadata["closed_trade_pnl"] for f in accounted)
        if fills[0].side == "SELL":
            taxable = max(0.0, sum(f.metadata["tax_gain_before_floor"] for f in accounted))
            excess = self.taxable_gains - previous_taxable - taxable
            self.taxable_gains -= excess
            self.tax_reserve -= excess*self.tax_rate
            for i, fill in enumerate(accounted):
                updated = fill.model_copy(update={"metadata": {**fill.metadata,
                    "taxable_gain": taxable if i == len(accounted)-1 else 0.0,
                    "tax_reserve": self.tax_reserve}})
                self.fills[fill.fill_id] = updated
                accounted[i] = updated
        for i, fill in enumerate(accounted):
            updated = fill.model_copy(update={"metadata": {**fill.metadata,
                "trade_complete": i == len(accounted)-1,
                "closed_trade_pnl": net_closed if i == len(accounted)-1 else fill.metadata["closed_trade_pnl"]}})
            self.fills[fill.fill_id] = updated
            accounted[i] = updated
        return accounted

    def snapshot(self) -> dict[str, Any]:
        return {"version": 1, "initial_cash": self.initial_cash, "cash": self.cash,
            "tax_rate": self.tax_rate, "tax_reserve": self.tax_reserve,
            "taxable_gains": self.taxable_gains, "total_fees": self.total_fees,
            "gross_realized_pnl": self.gross_realized_pnl,
            "positions": {s: asdict(p) for s, p in self.positions.items()},
            "lots": {s: list(lots) for s, lots in self.lots.items()},
            "fills": {i: f.model_dump(mode="json") for i, f in self.fills.items()}}

    def restore(self, snapshot: dict[str, Any]) -> None:
        if snapshot.get("version") != 1:
            raise ValueError("Unsupported ledger snapshot")
        for key in ("initial_cash", "cash", "tax_rate", "tax_reserve", "taxable_gains",
                    "total_fees", "gross_realized_pnl"):
            setattr(self, key, float(snapshot[key]))
        self.positions = {s: LedgerPosition(**p) for s, p in snapshot["positions"].items()}
        self.lots = {s: deque([list(lot) for lot in lots]) for s, lots in snapshot["lots"].items()}
        self.fills = {i: FillEvent.model_validate(f) for i, f in snapshot["fills"].items()}
