"""Financial regression checks with hand-verifiable cash and tax arithmetic."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from quantflow.analytics.engine import AnalyticsEngine
from quantflow.api.app import create_app
from quantflow.api.dependencies import APIState, get_api_state, set_api_state
from quantflow.backtesting.data import read_quotes
from quantflow.backtesting.engine import BacktestEngine, build_backtest_pipeline
from quantflow.common.events import FillEvent, OrderEvent, SignalEvent, TickEvent
from quantflow.config.manager import ConfigManager
from quantflow.core.event_bus import InMemoryEventBus
from quantflow.execution.fill_simulator import FeeSchedule, simulate_fill
from quantflow.execution.paper import PaperExecutionHandler
from quantflow.market_data.orderbook import LocalOrderBook
from quantflow.portfolio.ledger import AccountLedger
from quantflow.replay.event_store import InMemoryEventStoreReader
from quantflow.strategies.momentum.strategy import SimpleMomentumStrategy

START = datetime(2026, 1, 1, tzinfo=UTC)
PARAMS: dict[str, Any] = {
    "symbol": "BTC/USDT",
    "period": 2,
    "threshold": 0.01,
    "order_notional": 20,
}


def config(**extra: Any) -> ConfigManager:
    return ConfigManager(
        defaults={"portfolio": {"initial_cash": 200}, "tax": {"rate": 0.312}, **extra},
        env_dict={},
    )


def tick(price: float, index: int) -> TickEvent:
    return TickEvent(
        symbol="BTC/USDT",
        exchange="historical",
        last_price=price,
        bid_price=price - 0.1,
        ask_price=price + 0.1,
        bid_size=10,
        ask_size=10,
        last_size=1,
        timestamp=START + timedelta(minutes=index),
        timestamp_received=START + timedelta(minutes=index),
    )


def fill(side: str, price: float, qty: float = 1, fee: float = 1) -> FillEvent:
    return FillEvent(
        order_id="test",
        symbol="BTC/USDT",
        side=side,
        quantity=qty,
        fill_price=price,
        commission=fee,
    )


def test_tax_reserve_does_not_offset_losing_disposal() -> None:
    ledger = AccountLedger(200, 0.312)
    ledger.apply(fill("BUY", 100))
    win = ledger.apply(fill("SELL", 110))
    assert win.metadata["closed_trade_pnl"] == 8
    assert ledger.cash == 208
    assert ledger.tax_reserve == pytest.approx(3.12)
    ledger.apply(fill("BUY", 100))
    ledger.apply(fill("SELL", 90))
    assert ledger.cash == 196
    assert ledger.taxable_gains == 10
    assert ledger.available_cash == pytest.approx(192.88)


def test_fifo_disposal_aggregates_acquisition_lots_before_tax() -> None:
    ledger = AccountLedger(1000, 0.312)
    ledger.apply(fill("BUY", 100, fee=0))
    ledger.apply(fill("BUY", 120, fee=0))
    ledger.apply(fill("SELL", 110, qty=2, fee=0))
    assert ledger.taxable_gains == 0  # one disposal, acquisition cost $220
    assert ledger.cash == 1000


def test_short_cover_and_reversal_accounting() -> None:
    ledger = AccountLedger(1000)
    ledger.apply(fill("SELL", 100, qty=2, fee=0))
    ledger.apply(fill("BUY", 90, fee=0))
    assert ledger.positions["BTC/USDT"].quantity == -1
    assert ledger.gross_realized_pnl == 10
    ledger.apply(fill("BUY", 110, qty=2, fee=0))
    assert ledger.positions["BTC/USDT"].quantity == 1
    assert ledger.positions["BTC/USDT"].average == 110
    assert ledger.gross_realized_pnl == 0


def test_multi_level_disposal_tax_is_floored_once_and_idempotent() -> None:
    ledger = AccountLedger(1000, 0.312)
    ledger.apply(fill("BUY", 100, qty=2, fee=0))
    fills = ledger.apply_order([fill("SELL", 110, fee=0), fill("SELL", 90, fee=0)])
    assert ledger.taxable_gains == 0
    assert ledger.tax_reserve == 0
    assert ledger.cash == 1000
    ledger.apply_order(fills)
    assert ledger.cash == 1000
    assert sum(bool(f.metadata["trade_complete"]) for f in fills) == 1


@pytest.mark.asyncio
async def test_entry_spread_is_reflected_immediately_and_open_marks_update() -> None:
    cfg = config()
    end = START + timedelta(hours=1)
    pipe = build_backtest_pipeline(
        cfg, InMemoryEventStoreReader(), SimpleMomentumStrategy, PARAMS, START, end
    )
    await pipe.portfolio.start()
    try:
        await pipe.event_bus.publish(tick(100, 0))
        await pipe.execution.submit_order(
            OrderEvent(
                strategy_id="test",
                symbol="BTC/USDT",
                side="BUY",
                order_type="MARKET",
                quantity=0.1,
            )
        )
        assert pipe.portfolio.get_total_equity() == pytest.approx(200 - 0.01 - 0.01001)
        await pipe.event_bus.publish(tick(110, 1))
        assert pipe.portfolio.get_total_equity() == pytest.approx(201 - 0.01 - 0.01001)
    finally:
        await pipe.portfolio.stop()


def test_ledger_recovery_preserves_lots_reserve_and_deduplication() -> None:
    ledger = AccountLedger(1000, 0.312)
    ledger.apply(fill("BUY", 100, qty=2))
    sold = fill("SELL", 110)
    ledger.apply(sold)
    restored = AccountLedger(0)
    restored.restore(ledger.snapshot())
    assert restored.snapshot() == ledger.snapshot()
    restored.apply(sold)
    assert restored.cash == ledger.cash
    restored.apply(fill("SELL", 90))
    assert restored.tax_reserve == pytest.approx(3.12)


def test_flat_fee_is_once_per_order_not_per_depth_level() -> None:
    result = simulate_fill(
        {"side": "BUY", "symbol": "BTC/USDT", "quantity": 2},
        {"asks": [[100, 1], [101, 1]]},
        FeeSchedule(taker_rate=0.001, flat_fee_per_order=2),
    )
    assert result.total_commission == pytest.approx(2.201)


@pytest.mark.asyncio
async def test_unaffordable_signal_is_rejected_and_cash_preserved() -> None:
    events = [tick(p, i) for i, p in enumerate([50000, 51000, 52000])]
    result = await BacktestEngine(config()).run(
        InMemoryEventStoreReader(events),
        SimpleMomentumStrategy,
        {**PARAMS, "quantity": 1},
        START,
        START + timedelta(hours=1),
    )
    assert result.success
    assert result.trades == []
    assert result.rejected_signals[0]["reason"] == "INSUFFICIENT_CASH"
    assert result.metrics["final_equity"] == 200
    assert result.event_count == 3


@pytest.mark.asyncio
async def test_backtest_net_returns_include_fees_tax_and_final_liquidation() -> None:
    events = [tick(p, i) for i, p in enumerate([100, 101, 103, 110, 115])]
    result = await BacktestEngine(config(backtest={"close_at_end": True})).run(
        InMemoryEventStoreReader(events),
        SimpleMomentumStrategy,
        PARAMS,
        START,
        START + timedelta(hours=1),
    )
    assert result.success, result.error
    buy, sell = result.trades
    assert buy["price"] == 103.1
    assert sell["price"] == 114.9
    assert buy["quantity"] == pytest.approx(20 / 103.1)
    gross = (114.9 - 103.1) * buy["quantity"]
    fees = buy["commission"] + sell["commission"]
    assert result.metrics["initial_cash"] == 200
    assert result.metrics["final_equity"] == pytest.approx(200 + gross - fees)
    assert result.metrics["tax_reserve_estimate"] == pytest.approx(gross * 0.312)
    assert result.metrics["after_tax_pnl_estimate"] == pytest.approx(
        gross * 0.688 - fees
    )
    assert result.metrics["open_position_count"] == 0
    assert result.equity_curve[0][1] == 200
    assert result.equity_curve[-1][1] == result.metrics["final_equity"]
    assert all(t["timestamp"] is not None for t in result.trades)


@pytest.mark.asyncio
async def test_falling_market_does_not_open_spot_short() -> None:
    result = await BacktestEngine(config()).run(
        InMemoryEventStoreReader([tick(p, i) for i, p in enumerate([100, 99, 97, 95])]),
        SimpleMomentumStrategy,
        PARAMS,
        START,
        START + timedelta(hours=1),
    )
    assert result.success
    assert result.trades == []
    assert result.metrics["final_equity"] == 200


@pytest.mark.asyncio
async def test_risk_sees_actual_fees_and_closing_loss() -> None:
    events = [tick(p, i) for i, p in enumerate([100, 101, 103, 100, 97])]
    end = START + timedelta(hours=1)
    pipe = build_backtest_pipeline(
        config(risk={"max_daily_loss": 0.01}),
        InMemoryEventStoreReader(events),
        SimpleMomentumStrategy,
        PARAMS,
        START,
        end,
    )
    await pipe.risk.start()
    await pipe.portfolio.start()
    await pipe.execution.start()
    try:
        await pipe.strategy.initialize(PARAMS, pipe.clock)
        await pipe.replay.run(START, end)
        # The budget blocks entries, but must still allow the losing exit.
        assert pipe.risk.daily_realized_pnl == pytest.approx(
            pipe.portfolio.state.realized_pnl
        )
        assert pipe.risk.daily_realized_pnl < -0.02
        assert pipe.portfolio.get_positions() == {}
        signal = SignalEvent(
            strategy_id="test", symbol="BTC/USDT", side="BUY", quantity=0.01, price=97
        )
        assert (await pipe.risk.validate_signal(signal))[0] is False
    finally:
        await pipe.strategy.stop()
        await pipe.execution.stop()
        await pipe.portfolio.stop()
        await pipe.risk.stop()


@pytest.mark.asyncio
async def test_paper_execution_never_calls_exchange_and_enforces_inventory() -> None:
    registry = MagicMock()
    registry.get.return_value.place_order = AsyncMock()
    book = LocalOrderBook("BTC/USDT")
    await book.apply_snapshot([[99, 10]], [[100, 10]], 1)
    execution = PaperExecutionHandler(
        config=config(), registry=registry, order_books={"BTC/USDT": book}
    )
    sell = OrderEvent(
        strategy_id="test",
        symbol="BTC/USDT",
        side="SELL",
        order_type="MARKET",
        quantity=1,
    )
    await execution.submit_order(sell)
    assert execution.get_order_status(sell.order_id) == "REJECTED"
    buy = sell.model_copy(update={"order_id": "buy", "side": "BUY", "quantity": 0.1})
    await execution.submit_order(buy)
    cash = execution.ledger.cash
    await execution.submit_order(buy)
    assert execution.ledger.cash == cash
    assert cash == pytest.approx(189.99)
    registry.get.assert_not_called()


@pytest.mark.asyncio
async def test_displayed_liquidity_cannot_be_reused_until_next_snapshot() -> None:
    book = LocalOrderBook("BTC/USDT")
    await book.apply_snapshot([[99, 1]], [[100, 0.1]], 1)
    execution = PaperExecutionHandler(config=config(), order_books={"BTC/USDT": book})
    first = OrderEvent(
        strategy_id="test",
        symbol="BTC/USDT",
        side="BUY",
        order_type="MARKET",
        quantity=0.1,
    )
    second = first.model_copy(update={"order_id": "second"})
    await execution.submit_order(first)
    await execution.submit_order(second)
    assert execution.get_order_status(first.order_id) == "FILLED"
    assert execution.get_order_status(second.order_id) == "REJECTED"
    assert execution.ledger.positions["BTC/USDT"].quantity == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_critical_event_failure_propagates() -> None:
    bus = InMemoryEventBus()

    async def broken(event: TickEvent) -> None:
        raise RuntimeError("accounting failed")

    await bus.subscribe(TickEvent, broken)
    with pytest.raises(RuntimeError, match="accounting failed"):
        await bus.publish(tick(100, 0))


def test_intraday_return_is_not_lost_at_midnight() -> None:
    engine = AnalyticsEngine(config(), InMemoryEventBus())
    engine.load_historical_equity(
        [
            (START, 200),
            (START + timedelta(hours=12), 220),
            (START + timedelta(days=1), 220),
        ]
    )
    assert engine.return_aggregator.mean == pytest.approx(0.1)
    assert engine.get_metrics()["total_return"] == pytest.approx(0.1)


def write_data(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["timestamp", "symbol", "bid", "ask", "bid_size", "ask_size", "last"]
        )
        for i, p in enumerate([100, 101, 103, 110, 115]):
            writer.writerow(
                [
                    (START + timedelta(minutes=i)).isoformat(),
                    "BTC/USDT",
                    p - 0.1,
                    p + 0.1,
                    10,
                    10,
                    p,
                ]
            )


def test_csv_rejects_missing_spread_and_naive_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("timestamp,symbol,last\n2026-01-01,BTC/USDT,100\n")
    with pytest.raises(ValueError, match="CSV requires"):
        read_quotes(path)
    path.write_text(
        "timestamp,symbol,bid,ask,bid_size,ask_size,last\n2026-01-01,BTC/USDT,99,101,1,1,100\n"
    )
    with pytest.raises(ValueError, match="timezone"):
        read_quotes(path)


@pytest.mark.asyncio
async def test_api_real_backtest_and_rejection_without_data(tmp_path: Path) -> None:
    state = APIState(config())
    set_api_state(state)
    app = create_app()
    request = {
        "strategy_name": "Simple Momentum",
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
        "parameters": PARAMS,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/backtest/run", json=request)
        assert response.status_code == 422
        assert state.get_backtest_runs() == []
        path = tmp_path / "quotes.csv"
        write_data(path)
        state.config.set("backtest.data_path", str(path))
        response = await client.post(
            "/api/v1/backtest/run", json={**request, "strategy_name": "invented"}
        )
        assert response.status_code == 422
        response = await client.post("/api/v1/backtest/run", json=request)
        assert response.status_code == 200, response.text
        await asyncio.gather(*state._backtest_tasks)
        job = (
            await client.get("/api/v1/backtest/jobs/" + response.json()["job_id"])
        ).json()
        assert job["status"] == "completed", job
        detail = await client.get("/api/v1/backtest/runs/" + job["run_id"])
        assert detail.status_code == 200, detail.text
        report = detail.json()
        assert report["trades"]
        assert report["metrics"]["initial_cash"] == 200
        assert report["metrics"]["total_return"] != 0.22
    await state.close()


def test_default_state_has_no_fake_performance_or_connectivity() -> None:
    state = APIState(config())
    assert state.get_trades() == []
    assert state.get_backtest_runs() == []
    assert state.get_exchanges() == []
    assert state.get_portfolio_history() == []
    assert state.get_analytics_metrics()["sharpe"] == 0


@pytest.mark.asyncio
async def test_main_application_starts_pipeline_and_no_demo_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quantflow.main import create_app as main_app
    from quantflow.main import lifespan

    monkeypatch.setenv("APP_ENV", "paper")
    app = main_app()
    async with lifespan(app):
        state = get_api_state()
        assert state.strategy_engine is not None
        assert state.analytics_engine is not None
        assert state.portfolio_engine is not None
        assert state.strategy_engine._running
        assert state.analytics_engine._running
        assert len(state.strategy_engine._strategies) == 1
        assert state.portfolio_engine.ledger.initial_cash == 200
        assert state.get_exchanges() == []
        for i, p in enumerate([100, 101, 103]):
            await state.event_bus.publish(tick(p, i))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/ready")).status_code == 200
    assert not state.strategy_engine._running
    assert not state.analytics_engine._running


@pytest.mark.asyncio
async def test_empty_historical_range_fails() -> None:
    result = await BacktestEngine(config()).run(
        InMemoryEventStoreReader(),
        SimpleMomentumStrategy,
        PARAMS,
        START,
        START + timedelta(days=1),
    )
    assert not result.success
    assert result.error is not None and "No historical events" in result.error


def test_research_cli_splits_capital_and_subtracts_operating_costs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "synthetic-software-check.csv"
    write_data(path)
    cfg = tmp_path / "paper.yaml"
    cfg.write_text(
        "portfolio:\n  initial_cash: 200\ntax:\n  rate: 0.312\n"
        "strategies:\n  SimpleMomentum:\n    period: 2\n"
        "    threshold: 0.01\n    order_notional: 20\n"
    )
    output = tmp_path / "result.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.evaluate_strategy",
            "--data",
            str(path),
            "--config",
            str(cfg),
            "--start",
            "2026-01-01",
            "--holdout-start",
            "2026-01-01T00:02:00Z",
            "--end",
            "2026-01-02",
            "--monthly-cost",
            "5",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["dataset_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report["development"]["metrics"]["initial_cash"] == 200
    assert report["holdout"]["metrics"]["initial_cash"] == 200
    assert report["holdout_after_tax_and_operating_cost_pnl_estimate"] == pytest.approx(
        report["holdout"]["metrics"]["after_tax_pnl_estimate"]
        - 5 * report["holdout_months"]
    )
    assert report["live_trading_authorized"] is False
    assert report["eligible_for_further_paper_testing"] is False
