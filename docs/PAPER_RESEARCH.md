# What was repaired and how to evaluate the engine

QuantFlow now supports cash-spot **paper research**. It does not establish a
profitable strategy, connect a real account, or promise monthly income. The
sample momentum strategy remains an unvalidated hypothesis. With $200, profits
of $400–$500 per month would still require extraordinary returns; repairs do not
change that arithmetic.

## Current behavior

- Paper execution cannot submit an order to an exchange adapter.
- Cash, inventory, fees and tax reserves share one fill ledger. An order that
  cannot be funded is rejected, including directly submitted paper orders.
- The strategy uses a $20 order budget by default, sells only actual holdings,
  and tracks partial fills. There is no simulated leverage or spot shorting.
- Risk sees actual fee-adjusted realized PnL. Loss/exposure limits block new
  entries while allowing risk-reducing sales. The daily loss setting measures
  realized losses and fees; it does not cap unrealized losses or market gaps.
- Portfolio equity uses current marks, includes spread costs immediately, and
  starts performance measurement before the first entry fee. Reports include
  the final mark. Research can close positions at the end, charging exit fees
  and reserving estimated disposal tax. Insufficient depth may leave holdings;
  a report with open holdings is ineligible for the paper-testing gate.
- Daily returns preserve intraday gains and include inactive days. Sharpe uses
  a daily equivalent of the configured annual risk-free rate; Sortino uses RMS
  downside relative to that target. Closed-order statistics include entry/exit
  fees and zero-PnL closes. Multiple depth fills do not inflate the trade count.
- Backtest API jobs execute the real engine against the configured dataset.
  Missing data and unknown strategies produce errors. Default accounts have no
  fabricated exchange connections, trades, equity history, or performance.
- Critical callback failures propagate. Financial events are processed in
  subscription order. Dashboard messages use bounded client queues so network
  sends do not block financial updates.
- Repeated in-memory reads reuse a sorted dataset, sweep limits apply before
  materializing the parameter grid, and the artificial 10 ms sleep is removed.
- Optional database snapshots preserve lots, commissions, reserves and fill
  IDs. Recovery fails if a legacy snapshot lacks this ledger, rather than
  inventing a cost basis. Paper application accounts and API jobs are otherwise
  in memory and reset on restart; they are not real exchange balances.

## Start the paper application

From `F:\QuantFlow`:

```powershell
rtk proxy .venv\Scripts\python.exe -m uvicorn quantflow.main:app --host 127.0.0.1 --port 8000
```

It loads `config/paper.india.yaml` by default. `QUANTFLOW_CONFIG_PATH` selects a
different configuration file. The supplied file uses $200 initial cash, $20
orders, $40 exposure limits, a $4 realized daily loss limit, 365 daily periods
per year, and an illustrative 31.2% tax reserve rate.

`market_data.source: none` means no automatic feed. `/ready` reports pipeline
readiness separately from `market_feed_available` and
`historical_data_configured`. To inspect synthetic streaming behavior, explicitly
set `market_data.source: demo`. Demo prices cannot validate profitability.
`demo.enabled` separately enables legacy account fixtures for UI development;
leave it false for research. Health metadata identifies these choices.

`APP_ENV=live` refuses startup. This build deliberately has no real-money order
submission path. Merely configuring exchange credentials cannot enable it.

The default fee schedule is an assumption: 0.1% taker fee, with no flat charge.
Set `execution.paper.fees.default.taker` and `.flat` to the actual account's
costs before interpreting results. A flat fee is charged once per order, not
once per book level. Fee rates must be finite and nonnegative.

## Historical data and evaluation

No genuine historical dataset was present in the repository or supplied during
this repair. No claim about real historical profits has therefore been made.

The CSV reader requires real timestamped quotes:

```text
timestamp,symbol,bid,ask,bid_size,ask_size,last
```

An optional `exchange` column identifies the venue. Timestamps need an explicit
timezone and must increase strictly per symbol. Quotes require finite positive
prices, nonnegative sizes, and bid <= ask. A candle close is not a historical
bid/ask quote. The engine does not fabricate depth from candles. Use a data
vendor or an exchange export that provides the necessary observations, and
preserve its source and sampling frequency alongside the file.

After saving the dataset, run fixed parameters over separate chronological
development and holdout periods. For example, with data covering these dates:

```powershell
rtk proxy .venv\Scripts\python.exe -m scripts.evaluate_strategy --data data/quotes.csv --start 2025-01-01 --holdout-start 2025-10-01 --end 2026-04-01 --monthly-cost 5 --output docs/research-result.json
```

Dates are UTC and the end boundary is exclusive. The $5 operating cost is an
example; replace it with actual monthly hosting, data, power and other costs.
The runner records the dataset SHA-256, configuration, both runs, commissions,
estimated tax, remaining holdings, net result after operating costs, and average
monthly net PnL. It starts each period with fresh capital and no prior positions.
It does not tune parameters or reinvest development-period profits into the
holdout. Freezing parameters before examining the holdout is essential.

The report's `eligible_for_further_paper_testing` flag requires a successful
holdout of at least three months, at least 30 closing orders, no open holdings,
and positive estimated net PnL after operating costs. These are screening
conditions, not statistical proof or authorization for live trading. Reusing
the holdout to select parameters invalidates its status as unseen data.

For dashboard runs, set `backtest.data_path` to the same local file. The API
contract is documented in [BACKTEST_API_CONTRACT.md](BACKTEST_API_CONTRACT.md).
Jobs are bounded and run one at a time. Results are actual fills, not seeded
returns. Infinite profit factor is represented as JSON null.

## Tax estimate limits

The 31.2% example combines a 30% rate with 4% cess on that tax, without surcharge.
The Income Tax Department describes the rate in its
[ITR-2 FAQ](https://www.incometax.gov.in/iec/foportal/help/FileITR-2Online-FAQ?mobile-app=1)
and disposal/deduction restrictions in its
[VDA guidance](https://www.incometaxindia.gov.in/documents/20117/42998/Taxation-of-Virtual-Digital-Asset-VDA_2026-01-06_06-43-57_cfe04a_en.pdf/153706c8-7b5c-77d4-fc56-624c50ece1b0?t=1774007412959&version=1.0).
Confirm the treatment applicable to your tax year and actual instruments.

The research model uses FIFO acquisition prices and excludes commissions from
tax deductions. It floors each disposal's negative taxable gain at zero;
losses on separate disposals do not reduce reserves on winning disposals.
Trading fees still reduce cash and economic profit. Reserved tax remains in
account cash but is unavailable to fund new purchases.

Example: buy at $100 and sell at $110, then buy at $100 and sell at $90, paying
$1 for each of the four fills. Starting with $200 leaves $196 cash, with a
$3.12 reserve on the winning disposal and $192.88 available after that reserve.
Multiplying the overall trading loss by one tax rate would miss this effect.

This is a **quote-currency estimate**, not a filing calculation. It does not
model transaction-specific INR conversion, disposal of USDT used for purchases,
other income, surcharge, instrument-specific derivative treatment, withholding
thresholds or withholding cash-flow timing. USDT is not guaranteed to equal USD.
An INR transaction ledger and the relevant professional tax treatment are
required before interpreting a report as actual after-tax income.

## Validation and remaining boundaries

Final local validation on 26 October 2026: **230 backend tests passed**, with
two PostgreSQL/Redis service checks skipped because those services were not
configured. The new ledger/data/runner/regression files pass the full Ruff rule
set. Modified Python files also pass the fatal-error, unused-name and import
checks. The research CLI is exercised as a subprocess using a clearly synthetic
fixture, including chronological splitting and operating-cost subtraction.

Repository-wide CI is not fully green: full Ruff also scans the bundled
`alpha-skills` tree and reports thousands of issues, and strict Mypy reports
legacy test annotations plus optional Redis/CCXT typing issues. These findings
are separate from the passing runtime tests and have not been hidden by changing
the repository's lint or type-check configuration. Live PostgreSQL/Redis,
production Docker operation and external exchange integration remain unverified.

The final local flat-price replay diagnostic processed 10,000 input ticks in
about 0.24 seconds (roughly 41,500 ticks/sec). This skips unchanged financial
snapshots while flat and includes no database, external feed or browser clients.
It is an indicative local measurement, not a production latency guarantee.

`tests/test_paper_financial_integrity.py` includes hand-calculated checks for
unaffordable orders, tax loss asymmetry, FIFO lots, partial depth fills,
immediate spreads, mark updates, fees, final liquidation, recovery,
nonexistent strategies, real API jobs and application startup.

The original audit evidence remains in `audit-engine-results.json`. Re-running
`python -m scripts.audit_engine` writes a separate `repair-engine-results.json`
so the original evidence is preserved. Both use fabricated prices strictly as
software diagnostics, not performance estimates.

When using database persistence, apply migration `002_ledger_state` via
`python -m alembic upgrade head` before startup. Old snapshots must be reconciled
from original fills; no automatic guess of fees or tax lots is attempted.

The simulator assumes displayed depth is available immediately, charges taker
fees, and models no execution latency, future queue position, exchange minimum
lot rules or hidden market impact. It rejects unfilled limits rather than
maintaining an exchange-like matching queue. Partially filled pending remnants
are not automatically retried. Durable live execution, exchange reconciliation,
current market-data collection and production capacity checks remain separate
work. Profitability remains unproven until genuine data and subsequent real-feed
paper operation provide convincing evidence after these limitations and costs.
