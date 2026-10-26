# QuantFlow engine audit — 26 October 2026

The current project does not establish a profitable trading strategy. Its dashboard includes fabricated results, its application startup leaves essential engines inactive, and its backtests allow trades far beyond available capital. With US$200, a reliable US$400–$500 monthly withdrawal after Indian taxes is not a realistic planning assumption.

This was an inspection and execution audit, not a repair of the trading engine. Only this report, an offline reproduction script, and its results were added. No exchange connections or live orders were used. Existing .env credentials were not read. The reproduction script explicitly isolates configuration for its paper application startup.

## Executed checks

| Check | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest --durations=15` | 209 passed, 2 skipped, 18.96 seconds |
| Skipped integration checks | PostgreSQL and Redis host configuration absent |
| Dashboard `npm run test` | 14 passed across 6 files; 69.74 seconds |
| Dashboard `npm run build` | Passed; 791.15 kB JS bundle, 220.56 kB gzip; Vite size warning |
| Isolated main application lifespan and GET `/health` | HTTP 200 while strategy engine and analytics were inactive |
| Offline fabricated-price backtests and event-bus probes | Completed; results in `audit-engine-results.json` |

Passing component tests does not establish correct application wiring, realistic capital constraints, valid performance statistics, or a trading edge. No historical market database was queried, so this audit makes no historical profitability claim.

## Critical findings, in repair order

### 1. Dashboard backtests report invented performance

`quantflow/api/dependencies.py:516`, `APIState.submit_backtest_job`, immediately marks a job completed and inserts fixed results: 22% return, Sharpe 1.72, 58% win rate, and 88 trades. It never invokes `BacktestEngine`. The initial state also seeds trades, exchange connectivity, and a backtest with a 28% return.

Reproduction: submitting `AUDIT_NONEXISTENT_STRATEGY` directly to the API state method produced those successful results with empty trades and equity history. Dashboard statistics cannot currently be used as evidence of profits or exchange connectivity.

Repair: connect the job path to the real backtest engine and an identified historical dataset; reject unknown strategies. Keep explicitly labelled demo fixtures out of actual account views. Strategy toggles and config edits also need real engine integration: `update_risk_config` currently updates `_risk_config`, whereas risk checks read `RiskEngine.config`.

### 2. Main application does not start its trading pipeline

`quantflow/main.py:72` constructs registry, market data, plugins, paper execution, analytics, strategy engine, and scheduler. Only portfolio and risk receive `.start()` calls. No strategies are discovered or registered, registry startup is absent, and execution and analytics are not started. The non-live feed emits synthetic prices.

Reproduction: isolated startup returned health HTTP 200 with `strategy_engine_running=false`, `analytics_running=false`, and zero registered strategies. API state nevertheless reported Binance and Bybit connected using fixture values.

Repair: establish explicit lifecycle ordering, configuration loading, subscription wiring, and reverse shutdown for all required components. Add one application-level integration check that takes a known market event through strategy, risk, execution, portfolio, and analytics. Make readiness reflect actual component state.

### 3. A $200 account can buy one whole BTC

`quantflow/strategies/momentum/strategy.py:120` hardcodes quantity `1.0`. Risk checks omit buying-power and inventory validation. The paper executor fills against depth without checking account cash or spot inventory. Defaults permit effectively unlimited notional exposure unless configured.

Reproduction using a $50,801 fabricated ask: the $200 account bought 1 BTC, paid $50.801 commission, and cash fell to **-$50,651.801**. A subsequent sell ended the account at **-$902.60**. Both orders were accepted with no rejected signals.

Repair: size orders from available capital including fees; enforce spot cash and sell inventory; validate exchange minimum notional, precision, and lot sizes. Reserve buying power for pending orders. Margin trading requires an explicit margin model with borrowing costs and liquidation rules; negative cash alone is not such a model.

### 4. Loss protection does not see the reproduced loss

`quantflow/risk/engine.py`, `_handle_fill`, adds to daily loss only when the incoming fill carries nonzero `realized_pnl`. Simulated fills contain zero. Portfolio accounting independently calculates realized loss, but `_handle_portfolio` does not synchronize realized PnL into the risk daily loss ledger.

Reproduction: portfolio realized PnL was **-$1,002**, while risk daily PnL remained **$0**. Commissions further reduced equity. This undermines daily loss limits and the loss-based circuit breaker.

Repair: use one authoritative realized PnL ledger, apply commissions consistently, define daily reset/timezone behavior, and feed risk from that ledger. Verify loss limits with actual closing fills, rather than fixtures that inject their own PnL.

### 5. Equity and performance statistics are unreliable

- Portfolio subscribes to fills, not ongoing market marks. In the backtest, a final move to $52,000 left open-position equity at **$148.199**; an explicit mark changed it to **$1,348.199**. Final valuations can be stale when there is no closing trade.
- `quantflow/analytics/engine.py:119` initializes starting equity from the first portfolio update, after entry fees/spread in the reproduction. It used $148.199 instead of the actual $200 starting capital. This distorted the reported return to about -709%, versus the actual fabricated account change of -551.3%.
- The saved intraday equity curve contained only the first point, excluding the final loss. It is not a complete chart of the run.
- `analytics/engine.py:129` and the batch equivalent overwrite `last_equity` on intraday updates before computing a new-day return. A hand-built $200 -> $220 intraday -> $220 next-day sequence returned **0%** average daily return instead of **10%**.
- Trade analytics excludes zero-PnL closes and uses gross reconstructed closing PnL without commissions. This can overstate win rate and profit factor.
- In `backtesting/engine.py:206`, short-cover enrichment subtracts closing quantity from a negative position, increasing the short instead of reducing it. A separate capture ledger uses the opposite sign. Reversals also need verification. This is a source-inspection finding, not a reproduced short-trade result.
- Captured trade timestamps were null in the audit output; event counting reports signals plus fills, not replayed inputs. A successful 10,000-tick no-trade run reported zero events.

Repair: initialize equity before trading; mark holdings on market events and at the evaluation boundary; record the final valuation; calculate returns on consistent time bars, including inactive days. Use one ledger for fills, reversals, fees, and realized PnL across portfolio, risk, reports, and analytics. Use a crypto-appropriate sampling/calendar convention consistently.

### 6. Paper execution can call an exchange adapter

`quantflow/execution/paper.py:104` calls `registry.get(...).place_order(order)` before simulating a fill when a registry is provided. Adapter errors are caught and processing continues into simulated fills. This source path contradicts the expectation that paper execution is isolated from exchange order placement. It was not invoked against any real adapter during the audit.

Repair: give paper execution no access to exchange order submission; make live execution a separate implementation. Validate go-live attestation contents and signature: current startup only checks file existence and a nonempty signing-key environment variable.

## Slow paths and scalability findings

| Location | Evidence and consequence | Change to consider |
|---|---|---|
| `core/event_bus.py:92` | Publish awaits all callbacks. A 50-event probe took ~0.002 seconds with an immediate callback versus ~1.18 seconds with one callback sleeping 10 ms; Windows timer overhead is included. One slow subscriber delays the producer. | Keep ordered critical state processing; isolate telemetry/UI with bounded queues and measured timeouts. Do not blindly run financial events without ordering. |
| `api/websocket.py:94` | Broadcast awaits each client send sequentially; the bridge is awaited by the event bus. Slow client/network can delay market processing. Source-inspected, not measured with real browsers. | Per-client bounded outbound buffers, stale ticker coalescing, disconnect persistently slow clients. Preserve critical notifications. |
| `portfolio/engine.py:456` and `execution/paper.py:116` | Locks remain held across database work and nested event publication. Portfolio persistence queries and upserts positions on every update. Database/UI latency can serialize fills. Source-inspected; live database latency unmeasured. | Separate atomic state mutation from persistence and UI delivery with ordered, durable work and defined failure behavior. |
| `replay/event_store.py:126` | In-memory reads sort the entire dataset for every range, including repeated parameter/fold runs. | Pre-sort immutable datasets and index timestamps for range lookup. |
| `replay/event_store.py:166` | PostgreSQL reader stores a batch-size option but collects queried events into a list and sorts them. Large histories risk high memory use and delayed first event. | Stream ordered batches and merge event streams; index time/symbol query paths. Measure database plans on representative data. |
| `backtesting/optimizer.py:158` | Entire Cartesian grid is built before applying the limit; default worker count leads to sequential runs. Process-pool failure falls back to sequential execution. | Limit lazily, validate picklable worker inputs, expose fallback and timings, cache shared immutable data. |
| `backtesting/engine.py:390` | Every run adds a real 10 ms sleep despite awaiting event publication. At 10,000 parameter runs this alone has a 100-second nominal floor, potentially higher under Windows timer scheduling. | Replace with explicit completion semantics and verify deterministic draining. |
| Dashboard build | Single JS asset ~791 kB, 221 kB gzip. | Split routes/heavy charts to improve initial loading. This is separate from execution latency. |

The offline flat-price benchmark replayed **10,000 ticks in ~0.84 seconds (~11,900 ticks/sec)**. This includes in-memory book updates, strategy callbacks, and replay, with no signals, database, Redis, network, or dashboard clients. Two audit runs were approximately 0.82 and 0.84 seconds. These are local observations, not production capacity or latency guarantees. Correctness is more urgent than optimizing this number.

`core/event_bus.py:94` also gathers callback exceptions and discards the returned exceptions. A callback raising `RuntimeError` still allowed `publish()` to return normally. Backtests can consequently report success despite internal handler failures. Critical accounting/risk failures should fail the run or halt trading with an observable error; noncritical telemetry needs a separate error policy.

## $400–$500 per month from $200 in India

Before any costs or tax, monthly profits of $400–$500 require **200%–250% returns** on $200 while preserving the starting principal. The project offers no evidence supporting this.

For transfers subject to Indian virtual digital asset taxation, the Income Tax Department's [ITR-2 FAQ](https://www.incometax.gov.in/iec/foportal/help/FileITR-2Online-FAQ) describes a 30% rate plus applicable surcharge and 4% cess. At 30% plus cess, without surcharge, that is 31.2%. Its [VDA provision](https://www.incometaxindia.gov.in/w/section-115bbh-3?p_l_back_url=%2Fsearch%3Fq%3DSection%2B115bbh&p_l_back_url_title=Search) also specifies restrictions on deductions and loss set-off. Verify the rules applicable to the assessment year and instrument before using them for filing. A crypto derivative is not automatically treated like a spot VDA transfer.

A simplified illustration assuming all net trading profit is taxable at 31.2%, with no losing-trade tax asymmetry, would require **$581.40–$726.74 of monthly pretax profit**, or **290.7%–363.4% of starting capital**. Actual taxes can be less favorable because losing trades do not necessarily offset taxable winning transfers. Transaction withholding, exchange charges, spread, slippage, conversions, withdrawals, funding/borrowing if applicable, and hosting can further constrain available cash. Withholding is a tax credit/cash-flow issue, not automatically an extra permanent tax to add to the final bill.

For scale only, these hypothetical returns are after trading expenses but before the illustrative 31.2% tax:

| Hypothetical monthly return | Pretax profit on $200 | After illustrative tax | Capital mathematically needed for $400–$500 net/month |
|---|---:|---:|---:|
| 1% | $2 | $1.38 | $58,140–$72,674 |
| 2% | $4 | $2.75 | $29,070–$36,337 |
| 5% | $10 | $6.88 | $11,628–$14,535 |

These are arithmetic scenarios, not expected returns, recommended capital deposits, or guaranteed income. Even 5% every month is an aggressive assumption. Fixed infrastructure costs and tax asymmetry are excluded from this table. The [SEC's day-trading risk guidance](https://www.sec.gov/files/investor/pubs/daytips.htm) explains that leverage magnifies losses and many traders fail to become profitable. Increasing leverage is not a reliable solution to the capital/income mismatch.

## What would establish credible profitability evidence

First repair startup, fake reporting, cash/inventory enforcement, PnL/risk propagation, valuations, and metric calculations. Then obtain identified historical market data with clean timestamps, realistic spreads/depth, fees, and exchange rules. Separate training and validation chronologically; freeze strategy parameters before evaluating a genuinely untouched holdout. Parameter searching must not reuse that holdout to select winners.

Compare net performance against cash and buy-and-hold, account for open positions at the final boundary, and report costs, drawdown, worst month, trade count, capital utilization, and losing periods. Stress execution delays, wider spreads, fee changes, missing data, reconnects, and adverse market regimes. Compute tax-aware cash flows from the transaction ledger rather than multiplying aggregate PnL by one tax rate. Follow with sustained paper operation using real market inputs and reconciliation of each expected and simulated fill.

The $200 can serve as a development budget. It is not sufficient evidence or capital for depending on $400–$500 of monthly trading income. Current conclusion: **profitability unproven; simulated results presently unreliable; live deployment premature.**

## Reproduce

From the repository root, using the required wrapper:

```powershell
rtk proxy .venv\Scripts\python.exe -m scripts.audit_engine
```

This overwrites `docs/audit-engine-results.json` with a fresh local diagnostic run. Synthetic prices test implementation behavior only; the observed losses and gains are not a prediction of market performance. The script inspects some private state to document the existing implementation and should be revisited after repairs.
