"""Offline audit reproductions. Run from repo root: python -m scripts.audit_engine.

Uses fabricated prices solely to check engine behavior, never to estimate returns.
Does not read .env, call an exchange, or submit live orders.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from quantflow.analytics.engine import AnalyticsEngine
from quantflow.backtesting.engine import BacktestEngine, build_backtest_pipeline
from quantflow.common.events import PortfolioUpdateEvent, TickEvent
from quantflow.config.manager import ConfigManager
from quantflow.core.event_bus import InMemoryEventBus
from quantflow.replay.event_store import InMemoryEventStoreReader
from quantflow.strategies.momentum.strategy import SimpleMomentumStrategy


def ticks(prices: list[float]) -> list[TickEvent]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [TickEvent(event_id=f"audit_{i}", symbol="BTC/USDT", exchange="binance",
                      last_price=p, bid_price=p-1, ask_price=p+1,
                      bid_size=10, ask_size=10, last_size=1,
                      timestamp=start+timedelta(seconds=i),
                      timestamp_received=start+timedelta(seconds=i))
            for i, p in enumerate(prices)]


async def main() -> None:
    logging.basicConfig(level=logging.CRITICAL)
    report = {}
    cfg = ConfigManager(defaults={"portfolio": {"initial_cash": 200}}, env_dict={})
    data = ticks([50000,50100,50200,50300,50500,50800,50600,50400,50200,50000,49800])
    params = {"symbol": "BTC/USDT", "period": 5, "threshold": .01}
    start, end = data[0].timestamp, data[-1].timestamp+timedelta(seconds=1)
    result = await BacktestEngine(cfg).run(InMemoryEventStoreReader(data), SimpleMomentumStrategy,
                                         {**params, "quantity": 1.0}, start, end)
    report["unaffordable_backtest"] = {"success": result.success, "signals": len(result.signals),
        "fills": result.trades, "rejected": result.rejected_signals,
        "metrics": result.metrics, "equity_curve": result.equity_curve}

    pipeline = build_backtest_pipeline(cfg, InMemoryEventStoreReader(data), SimpleMomentumStrategy, params, start, end)
    await pipeline.portfolio.start()
    await pipeline.risk.start()
    await pipeline.execution.start()
    snapshots = []
    async def snapshot(event):
        snapshots.append({"cash": event.cash, "equity": event.total_value})
    await pipeline.event_bus.subscribe(PortfolioUpdateEvent, snapshot)
    await pipeline.strategy.initialize(params, pipeline.clock)
    await pipeline.replay.run(start, end)
    before_mark = pipeline.portfolio.get_total_equity()
    for p in [pipeline.portfolio]:
        await p.stop()
    await pipeline.execution.stop()
    await pipeline.risk.stop()
    report["cash_and_risk"] = {"snapshots": snapshots, "final_equity": before_mark,
        "portfolio_realized_pnl": pipeline.portfolio.get_realized_pnl(),
        "risk_daily_pnl": pipeline.risk.daily_realized_pnl,
        "risk_positions": pipeline.risk.positions, "portfolio_positions": pipeline.portfolio.get_positions()}

    # A last tick after entry should change open-position equity.
    rising = ticks([50000,50100,50200,50300,50500,50800,52000])
    pipe = build_backtest_pipeline(cfg, InMemoryEventStoreReader(rising), SimpleMomentumStrategy, params,
                                  rising[0].timestamp, rising[-1].timestamp+timedelta(seconds=1))
    await pipe.portfolio.start()
    await pipe.execution.start()
    await pipe.risk.start()
    await pipe.strategy.initialize(params, pipe.clock)
    await pipe.replay.run(rising[0].timestamp, rising[-1].timestamp+timedelta(seconds=1))
    report["stale_valuation"] = {"equity_before_explicit_mark": pipe.portfolio.get_total_equity()}
    await pipe.portfolio.update_mark_price("BTC/USDT", 52000)
    report["stale_valuation"]["equity_after_explicit_mark"] = pipe.portfolio.get_total_equity()
    await pipe.execution.stop()
    await pipe.risk.stop()
    await pipe.portfolio.stop()

    bus = InMemoryEventBus()
    async def broken(event):
        raise RuntimeError("audit handler failed")
    await bus.subscribe(TickEvent, broken)
    try:
        await bus.publish(data[0])
        report["subscriber_failure"] = "publish returned normally despite handler RuntimeError"
    except RuntimeError:
        report["subscriber_failure"] = "handler RuntimeError propagated to caller"

    for slow in [False, True]:
        bus = InMemoryEventBus()
        async def handler(event):
            if slow:
                await asyncio.sleep(.01)
        await bus.subscribe(TickEvent, handler)
        t0 = perf_counter()
        for _ in range(50):
            await bus.publish(data[0])
        report[f"publish_50_slow_{slow}_seconds"] = perf_counter()-t0

    analytics = AnalyticsEngine(cfg, InMemoryEventBus())
    analytics.load_historical_equity([(start, 200), (start+timedelta(hours=12), 220),
                                     (start+timedelta(days=1), 220)])
    report["daily_return"] = {"expected": .10, "observed_mean": analytics.return_aggregator.mean}

    # Throughput with no signals isolates replay/book/dispatch overhead.
    many = ticks([50000.0]*10000)
    t0 = perf_counter()
    run = await BacktestEngine(cfg).run(InMemoryEventStoreReader(many), SimpleMomentumStrategy,
        params, many[0].timestamp, many[-1].timestamp+timedelta(seconds=1))
    elapsed = perf_counter()-t0
    report["replay_benchmark"] = {"input_ticks": len(many), "wall_seconds": elapsed,
        "ticks_per_second": len(many)/elapsed, "reported_event_count": run.event_count,
        "success": run.success}

    import httpx

    from quantflow.api.dependencies import get_api_state
    from quantflow.main import create_app, lifespan
    # Replace config and environment only during isolated paper startup.
    with patch.dict("os.environ", {"APP_ENV": "development", "QUANTFLOW_EVENT_BUS_TYPE": "in_memory"}), \
            patch("quantflow.main.ConfigManager", return_value=cfg):
        app = create_app()
        async with lifespan(app):
            state = get_api_state()
            await asyncio.sleep(.05)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://audit") as client:
                response = await client.get("/health")
            try:
                state.submit_backtest_job({"strategy_name": "AUDIT_NONEXISTENT_STRATEGY", "parameters": {}})
                unknown_error = None
            except ValueError as exc:
                unknown_error = str(exc)
            report["startup"] = {"health_status": response.status_code,
                "health_body": response.json(),
                "analytics_running": state.analytics_engine._running,
                "strategy_engine_running": state.strategy_engine._running,
                "strategy_count": len(state.strategy_engine._strategies),
                "exchanges_reported": state.get_exchanges(),
                "nonexistent_strategy_error": unknown_error,
                "backtest_runs": state.get_backtest_runs()}

    out = Path("docs/repair-engine-results.json")
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    asyncio.run(main())
