"""Run a fixed strategy on chronological development and untouched holdout quotes."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from quantflow.backtesting.data import read_quotes
from quantflow.backtesting.engine import BacktestEngine
from quantflow.config.manager import ConfigManager
from quantflow.strategies.momentum.strategy import SimpleMomentumStrategy


def utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


async def evaluate(args) -> dict:
    start, split, end = map(utc, (args.start, args.holdout_start, args.end))
    if not start < split < end or not math.isfinite(args.monthly_cost) or args.monthly_cost < 0:
        raise ValueError("Require start < holdout-start < end and a nonnegative monthly cost")
    if not Path(args.config).is_file():
        raise ValueError("Research configuration file does not exist")
    cfg = ConfigManager(config_path=args.config, env_dict={})
    cfg.set("backtest.close_at_end", True)
    params = cfg.get("strategies.SimpleMomentum", {})
    symbol = params.get("symbol", "BTC/USDT")
    reader = read_quotes(args.data)
    # Isolate one account denomination/symbol; do not mix quote currencies.
    reader = type(reader)([e async for e in reader.read_all(symbols=[symbol])])
    engine = BacktestEngine(cfg)
    development = await engine.run(reader, SimpleMomentumStrategy, params, start, split)
    holdout = await engine.run(reader, SimpleMomentumStrategy, params, split, end)
    months = (end-split).total_seconds() / (86400 * 30.4375)
    net = holdout.metrics["after_tax_pnl_estimate"] - months*args.monthly_cost
    warnings = ["Historical results cannot guarantee future income.",
        "Tax is a conservative quote-currency spot-VDA estimate, excluding INR conversions, USDT disposals, surcharge and withholding cash flows.",
        "Displayed liquidity is assumed available immediately; no execution latency or unseen market impact is modelled.",
        "Do not repeatedly tune parameters against this holdout."]
    eligible = (holdout.success and holdout.metrics["open_position_count"] == 0
                and net > 0 and holdout.metrics["total_trades"] >= 30 and months >= 3)
    return {"dataset": str(Path(args.data).resolve()),
        "dataset_sha256": hashlib.sha256(Path(args.data).read_bytes()).hexdigest(),
        "parameters": params, "development": asdict(development), "holdout": asdict(holdout),
        "holdout_months": months, "monthly_operating_cost": args.monthly_cost,
        "holdout_after_tax_and_operating_cost_pnl_estimate": net,
        "average_monthly_pnl_estimate": net/months,
        "eligible_for_further_paper_testing": eligible,
        "live_trading_authorized": False, "warnings": warnings}


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k.isoformat() if isinstance(k, datetime) else k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Actual top-of-book CSV")
    parser.add_argument("--config", default="config/paper.india.yaml")
    parser.add_argument("--start", required=True)
    parser.add_argument("--holdout-start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--monthly-cost", type=float, default=0.0)
    parser.add_argument("--output", default="docs/research-result.json")
    args = parser.parse_args()
    result = asyncio.run(evaluate(args))
    Path(args.output).write_text(json.dumps(json_safe(result), indent=2, default=str, allow_nan=False), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("average_monthly_pnl_estimate",
        "eligible_for_further_paper_testing", "live_trading_authorized")}))
    if not result["development"]["success"] or not result["holdout"]["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
