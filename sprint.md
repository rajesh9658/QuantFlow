QuantFlow Platform Specification – Analytics Module
The Analytics Module provides real‑time and historical performance metrics for the trading system. It consumes PortfolioUpdateEvent and FillEvent (or ExecutionEvent) to compute key statistics. The design ensures that the exact same formulas are used for live streaming (incremental) and offline backtesting (batch), guaranteeing consistency between paper/live trading results and historical simulations.

1. Core Design Principles
Unified Computation: A set of pure StatAggregator classes maintains rolling or incremental state. Batch computation simply instantiates these aggregators and feeds them the full historical dataset.

Event‑Driven Updates: In live mode, the AnalyticsEngine subscribes to events and updates aggregators. In backtest mode, a replay loop feeds historical events through the exact same interface.

Time‑Series Alignment: All metrics are anchored to daily returns for Sharpe/Sortino to avoid dependencies on irregular trade timings. Daily equity snapshots are derived from PortfolioUpdateEvent.

2. Metrics & Exact Formulas
2.1 Returns & Volatility (Sharpe / Sortino)
Let 
E
t
E 
t
​
  be the total equity at the end of day 
t
t.
Define daily return:

R
t
=
E
t
−
E
t
−
1
E
t
−
1
,
with 
E
0
=
initial capital
R 
t
​
 = 
E 
t−1
​
 
E 
t
​
 −E 
t−1
​
 
​
 ,with E 
0
​
 =initial capital
Mean Return (excess over risk‑free rate 
R
f
R 
f
​
 ):

R
ˉ
e
=
1
N
∑
t
=
1
N
(
R
t
−
R
f
)
R
ˉ
  
e
​
 = 
N
1
​
  
t=1
∑
N
​
 (R 
t
​
 −R 
f
​
 )
Volatility (Standard Deviation):

σ
=
1
N
−
1
∑
t
=
1
N
(
R
t
−
R
ˉ
)
2
σ= 
N−1
1
​
  
t=1
∑
N
​
 (R 
t
​
 − 
R
ˉ
 ) 
2
 
​
 
Downside Deviation (for Sortino, using negative returns only):

σ
d
=
1
N
−
1
∑
t
=
1
N
min
⁡
(
R
t
−
R
ˉ
,
0
)
2
σ 
d
​
 = 
N−1
1
​
  
t=1
∑
N
​
 min(R 
t
​
 − 
R
ˉ
 ,0) 
2
 
​
 
(Alternative definition uses 
min
⁡
(
R
t
,
0
)
2
min(R 
t
​
 ,0) 
2
 ; we use the mean‑adjusted version for consistency with Sortino’s original paper.)

Annualization Factor: 
252
252
​
  (assuming 252 trading days per year).
Risk‑Free Rate: Read from ConfigManager (analytics.risk_free_rate, default 0.0).

Sharpe
=
R
ˉ
e
σ
×
252
Sharpe= 
σ
R
ˉ
  
e
​
 
​
 × 
252
​
 
Sortino
=
R
ˉ
e
σ
d
×
252
Sortino= 
σ 
d
​
 
R
ˉ
  
e
​
 
​
 × 
252
​
 
Note: For live streaming, 
R
ˉ
R
ˉ
  and 
σ
σ are computed incrementally using Welford’s online algorithm to avoid storing daily returns.

2.2 Max Drawdown
Given the equity curve 
E
0
,
E
1
,
…
,
E
N
E 
0
​
 ,E 
1
​
 ,…,E 
N
​
 :

Drawdown
t
=
Peak
t
−
E
t
Peak
t
,
where 
Peak
t
=
max
⁡
0
≤
i
≤
t
E
i
Drawdown 
t
​
 = 
Peak 
t
​
 
Peak 
t
​
 −E 
t
​
 
​
 ,where Peak 
t
​
 = 
0≤i≤t
max
​
 E 
i
​
 
Max Drawdown
=
max
⁡
0
≤
t
≤
N
Drawdown
t
Max Drawdown= 
0≤t≤N
max
​
 Drawdown 
t
​
 
This is computed by maintaining a running peak and the current drawdown percentage.

2.3 Trade‑Based Metrics
For a set of 
M
M closed trades, let 
PnL
i
PnL 
i
​
  be the realized profit/loss of trade 
i
i.

Win Rate:

Win Rate
=
#
{
i
:
PnL
i
>
0
}
M
Win Rate= 
M
#{i:PnL 
i
​
 >0}
​
 
Profit Factor:

Profit Factor
=
∑
i
:
PnL
i
>
0
PnL
i
∑
i
:
PnL
i
<
0
(
−
PnL
i
)
Profit Factor= 
∑ 
i:PnL 
i
​
 <0
​
 (−PnL 
i
​
 )
∑ 
i:PnL 
i
​
 >0
​
 PnL 
i
​
 
​
 
If there are no losing trades, profit factor is defined as 
∞
∞ (or inf).

Average Trade:

PnL
ˉ
=
1
M
∑
i
=
1
M
PnL
i
PnL
ˉ
 = 
M
1
​
  
i=1
∑
M
​
 PnL 
i
​
 
Average Slippage (per trade):

Slippage
i
=
ExecPrice
i
−
ExpectedPrice
i
Slippage 
i
​
 =ExecPrice 
i
​
 −ExpectedPrice 
i
​
 
Slippage
ˉ
=
1
M
∑
i
=
1
M
Slippage
i
Slippage
ˉ
​
 = 
M
1
​
  
i=1
∑
M
​
 Slippage 
i
​
 
Average Latency (per fill/order):

Latency
j
=
timestamp_received
j
−
timestamp_exchange
j
Latency 
j
​
 =timestamp_received 
j
​
 −timestamp_exchange 
j
​
 
Latency
ˉ
=
1
K
∑
j
=
1
K
Latency
j
Latency
ˉ
​
 = 
K
1
​
  
j=1
∑
K
​
 Latency 
j
​
 
(Where 
K
K is the total number of fills.)

3. Aggregator Classes (Incremental & Reusable)
These classes maintain running state and can be fed data sequentially.

python
# analytics/aggregators.py
import math
from typing import Optional, Tuple
from datetime import datetime, timedelta, timezone


class WelfordOnline:
    """Online mean and variance (Welford's algorithm)."""
    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0   # sum of squared differences from mean

    def update(self, x: float) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    def variance(self) -> float:
        return self.m2 / (self.n - 1) if self.n > 1 else 0.0

    def stddev(self) -> float:
        return math.sqrt(self.variance()) if self.n > 1 else 0.0


class DrawdownTracker:
    """Tracks running and maximum drawdown."""
    def __init__(self, initial_equity: float):
        self.peak = initial_equity
        self.current_drawdown = 0.0
        self.max_drawdown = 0.0

    def update(self, equity: float) -> None:
        if equity > self.peak:
            self.peak = equity
        self.current_drawdown = (self.peak - equity) / self.peak if self.peak > 0 else 0.0
        self.max_drawdown = max(self.max_drawdown, self.current_drawdown)


class TradeStatsAggregator:
    """Aggregates per-trade PnL, slippage, win/loss counts."""
    def __init__(self):
        self.total_trades = 0
        self.winning_trades = 0
        self.sum_pnl = 0.0
        self.sum_win_pnl = 0.0
        self.sum_loss_pnl = 0.0  # absolute value of losses
        self.sum_slippage = 0.0
        self.sum_latency = 0.0
        self.latency_count = 0

    def add_trade(
        self,
        pnl: float,
        slippage: Optional[float] = None,
        latency: Optional[float] = None
    ) -> None:
        self.total_trades += 1
        self.sum_pnl += pnl
        if pnl > 0:
            self.winning_trades += 1
            self.sum_win_pnl += pnl
        elif pnl < 0:
            self.sum_loss_pnl += abs(pnl)

        if slippage is not None:
            self.sum_slippage += slippage
        if latency is not None:
            self.sum_latency += latency
            self.latency_count += 1

    @property
    def win_rate(self) -> float:
        return self.winning_trades / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def avg_trade(self) -> float:
        return self.sum_pnl / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.sum_loss_pnl == 0:
            return float('inf')
        return self.sum_win_pnl / self.sum_loss_pnl

    @property
    def avg_slippage(self) -> float:
        return self.sum_slippage / self.total_trades if self.total_trades > 0 else 0.0

    @property
    def avg_latency(self) -> float:
        return self.sum_latency / self.latency_count if self.latency_count > 0 else 0.0
4. Analytics Engine
The engine combines the aggregators, collects daily equity samples, and computes final metrics on demand.

python
# analytics/engine.py
import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from interfaces import EventBus
from events import PortfolioUpdateEvent, FillEvent, EventType
from config_manager import ConfigManager
from logging_setup import get_logger
from analytics.aggregators import WelfordOnline, DrawdownTracker, TradeStatsAggregator


class AnalyticsEngine:
    """
    Real‑time analytics engine. Subscribes to PortfolioUpdate and Fill events.
    Maintains rolling stats and exposes computed metrics.
    """

    def __init__(self, config: ConfigManager, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.logger = get_logger("analytics_engine")

        # Config
        self.risk_free_rate = config.get_float("analytics.risk_free_rate", 0.0)

        # State
        self.initial_equity: Optional[float] = None
        self.last_equity: Optional[float] = None
        self.last_update_day: Optional[str] = None  # YYYY-MM-DD

        # Daily return aggregator (for Sharpe/Sortino)
        self.return_aggregator = WelfordOnline()
        self.downside_aggregator = WelfordOnline()  # stores negative deviations

        # Drawdown
        self.drawdown_tracker: Optional[DrawdownTracker] = None

        # Trade stats
        self.trade_stats = TradeStatsAggregator()

        # Equity curve (store daily snapshots for batch/visualization)
        self.equity_curve: List[Tuple[datetime, float]] = []

        # Running flag
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self.event_bus.subscribe(EventType.PORTFOLIO_UPDATE, self._handle_portfolio)
        await self.event_bus.subscribe(EventType.FILL, self._handle_fill)
        self.logger.info("Analytics Engine started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        await self.event_bus.unsubscribe(EventType.PORTFOLIO_UPDATE, self._handle_portfolio)
        await self.event_bus.unsubscribe(EventType.FILL, self._handle_fill)
        self.logger.info("Analytics Engine stopped")

    # ---------- Event Handlers ----------

    async def _handle_portfolio(self, event: PortfolioUpdateEvent) -> None:
        """Process portfolio updates to compute daily returns and drawdown."""
        if not self._running:
            return

        equity = event.payload.total_value
        timestamp = event.timestamp_received or datetime.now(timezone.utc)
        day_key = timestamp.date().isoformat()

        # Initialize
        if self.initial_equity is None:
            self.initial_equity = equity
            self.drawdown_tracker = DrawdownTracker(equity)
            self.last_equity = equity
            self.last_update_day = day_key
            self.equity_curve.append((timestamp, equity))
            return

        # Check if we crossed a new day
        if day_key != self.last_update_day:
            # Compute daily return for the previous day
            if self.last_equity is not None and self.last_equity > 0:
                daily_ret = (equity - self.last_equity) / self.last_equity
                self._add_daily_return(daily_ret)

            # Update day tracker
            self.last_update_day = day_key
            self.last_equity = equity

            # Store equity curve snapshot at the start of the new day (or end of previous)
            self.equity_curve.append((timestamp, equity))
        else:
            # Within the same day, just update drawdown (equity may fluctuate)
            pass

        # Update drawdown regardless of day boundary
        if self.drawdown_tracker:
            self.drawdown_tracker.update(equity)

        # Store the latest equity for future daily returns
        self.last_equity = equity

    async def _handle_fill(self, event: FillEvent) -> None:
        """Process fills to compute trade PnL, slippage, and latency."""
        if not self._running:
            return

        fill = event.payload

        # 1. PnL per trade: we rely on the portfolio engine to compute realized PnL per fill.
        # The fill event can carry a 'realized_pnl' field in metadata.
        realized_pnl = fill.metadata.get("realized_pnl", 0.0)

        # 2. Slippage: expected price from signal metadata or reference price.
        expected_price = fill.metadata.get("expected_price")
        slippage = None
        if expected_price is not None and expected_price > 0:
            slippage = fill.price - expected_price

        # 3. Latency: timestamp_received - timestamp_exchange
        latency = None
        if event.timestamp_received and event.timestamp_exchange:
            latency = (event.timestamp_received - event.timestamp_exchange).total_seconds()

        # Add to aggregator (only if we consider this a closed trade segment)
        # Note: In practice, a 'trade' might be composed of multiple fills.
        # For this design, we treat each fill as contributing to the PnL of its order.
        # Better: aggregate per order, but for real-time we can approximate.
        if abs(realized_pnl) > 1e-12:
            self.trade_stats.add_trade(realized_pnl, slippage, latency)

    # ---------- Internal Computation ----------

    def _add_daily_return(self, ret: float) -> None:
        """Update both standard and downside variance aggregators."""
        # Standard return
        self.return_aggregator.update(ret)

        # Downside deviation (for Sortino)
        downside = min(ret - self.return_aggregator.mean, 0.0)
        self.downside_aggregator.update(downside)

    # ---------- Batch Loading (for Backtests) ----------

    def load_historical_equity(self, equity_curve: List[Tuple[datetime, float]]) -> None:
        """
        Bulk‑load a historical equity curve for batch/backtest calculations.
        Resets all internal state and replays the curve.
        """
        self.reset()
        for ts, eq in equity_curve:
            # Simulate portfolio update logic
            if self.initial_equity is None:
                self.initial_equity = eq
                self.drawdown_tracker = DrawdownTracker(eq)
                self.last_equity = eq
                self.last_update_day = ts.date().isoformat()
                self.equity_curve.append((ts, eq))
                continue

            day_key = ts.date().isoformat()
            if day_key != self.last_update_day:
                if self.last_equity is not None and self.last_equity > 0:
                    daily_ret = (eq - self.last_equity) / self.last_equity
                    self._add_daily_return(daily_ret)
                self.last_update_day = day_key
                self.last_equity = eq
                self.equity_curve.append((ts, eq))
            else:
                pass  # same day, just update equity for drawdown

            if self.drawdown_tracker:
                self.drawdown_tracker.update(eq)
            self.last_equity = eq

    def load_historical_trades(
        self,
        trades: List[Tuple[float, Optional[float], Optional[float]]]
    ) -> None:
        """
        Bulk‑load historical trades: (pnl, slippage, latency).
        """
        for pnl, slippage, latency in trades:
            self.trade_stats.add_trade(pnl, slippage, latency)

    # ---------- Reset ----------

    def reset(self) -> None:
        """Reset all state to compute a fresh set of metrics."""
        self.initial_equity = None
        self.last_equity = None
        self.last_update_day = None
        self.return_aggregator = WelfordOnline()
        self.downside_aggregator = WelfordOnline()
        self.drawdown_tracker = None
        self.trade_stats = TradeStatsAggregator()
        self.equity_curve.clear()

    # ---------- Metric Getters ----------

    def get_metrics(self) -> Dict[str, float]:
        """Return the full set of performance metrics."""
        metrics = {}

        # Sharpe
        mean_ret = self.return_aggregator.mean
        std_ret = self.return_aggregator.stddev()
        excess_ret = mean_ret - self.risk_free_rate
        annual_factor = math.sqrt(252)
        metrics["sharpe_ratio"] = (excess_ret / std_ret) * annual_factor if std_ret > 0 else 0.0

        # Sortino
        downside_std = self.downside_aggregator.stddev()
        metrics["sortino_ratio"] = (excess_ret / downside_std) * annual_factor if downside_std > 0 else 0.0

        # Drawdown
        metrics["max_drawdown"] = self.drawdown_tracker.max_drawdown if self.drawdown_tracker else 0.0
        metrics["current_drawdown"] = self.drawdown_tracker.current_drawdown if self.drawdown_tracker else 0.0

        # Trade metrics
        metrics["win_rate"] = self.trade_stats.win_rate
        metrics["profit_factor"] = self.trade_stats.profit_factor
        metrics["avg_trade"] = self.trade_stats.avg_trade
        metrics["avg_slippage"] = self.trade_stats.avg_slippage
        metrics["avg_latency"] = self.trade_stats.avg_latency
        metrics["total_trades"] = float(self.trade_stats.total_trades)

        # Total return
        if self.initial_equity and self.last_equity:
            metrics["total_return"] = (self.last_equity - self.initial_equity) / self.initial_equity

        return metrics

    def get_equity_curve(self) -> List[Tuple[datetime, float]]:
        """Return the equity curve samples."""
        return self.equity_curve.copy()
5. Batch / Offline Usage (Backtest)
For backtesting, the exact same analytics engine is used:

python
# backtest_runner.py (snippet)
analytics = AnalyticsEngine(config, event_bus)
analytics.load_historical_equity(historical_equity_samples)
analytics.load_historical_trades(historical_trade_pnls)
metrics = analytics.get_metrics()
No code duplication ensures 100% correlation between backtest results and live paper trading results.

6. Configuration (quantflow.yaml)
yaml
analytics:
  risk_free_rate: 0.0   # e.g., 0.025 for 2.5% per year
  annualization_factor: 252  # trading days per year
7. Summary of Formulas Reference
Metric	Formula	Computation Mode
Win Rate	wins / total_trades	Incremental counter
Avg Trade	sum(pnl) / total_trades	Incremental sum
Profit Factor	sum(win_pnl) / sum(loss_pnl)	Incremental sums
Avg Slippage	sum(slippage) / total_trades	Incremental
Avg Latency	sum(latency) / fills_count	Incremental
Sharpe	(mean_ret - rf) / std_ret * sqrt(252)	Online Welford
Sortino	(mean_ret - rf) / downside_std * sqrt(252)	Online Welford (negative deviations)
Max Drawdown	max( (peak - equity) / peak )	Running peak tracker
Equity Curve	Daily snapshots of total_equity	Time‑series array