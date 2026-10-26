# Backtest API contract

POST `/api/v1/backtest/run` accepts the existing request schema. Initial cash
defaults to $200 and must be positive. Dates define a UTC `[start, end)` range.
Only the implemented `Simple Momentum` strategy (also `SimpleMomentum`) is
accepted. `parameters.symbol` cannot override the request's `symbol`.

The server must configure `backtest.data_path` to a local historical quote CSV.
Clients cannot choose a filesystem path. CSV columns are `timestamp,symbol,bid,
ask,bid_size,ask_size,last` with an optional `exchange`. Timestamps require a
timezone; prices/depth must be finite and valid, and per-symbol timestamps must
increase strictly. Real spreads and displayed sizes are required.

An accepted request returns `{job_id, status: "queued"}`. GET
`/api/v1/backtest/jobs/{job_id}` reports `queued`, `running`, `completed`, or
`failed`, with error and run_id. Missing configuration, unknown strategy, or
invalid dates return HTTP 422. Data parsing failures and empty requested ranges
produce failed jobs, never a successful result with fabricated returns.

Completed detail reports retain the existing shape and include actual fills,
equity points, fees, and clearly named `*_estimate` tax metrics. No dataset or
result is generated automatically. Jobs/results are in memory and lost on
restart. One backtest executes at a time; a bounded queue rejects excess jobs
with HTTP 429. Demo fixtures require explicit `demo.enabled: true` and are
identified in health metadata. They are for interface development only.

The supplied tax setting is an estimate for spot VDA disposals in account quote
currency. It is not an INR tax filing calculation; see PAPER_RESEARCH.md for
the assumptions and exclusions.
