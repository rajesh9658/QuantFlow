"""Test suite for database models, repositories, and persistence."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config

from quantflow.common.events import FillEvent, OrderEvent
from quantflow.database.models import (
    LogLevel,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalDirection,
)
from quantflow.database.repository import (
    ErrorLogRepository,
    ExecutionRepository,
    LogRepository,
    MetricRepository,
    OrderBookRepository,
    OrderRepository,
    PartitionRepository,
    PortfolioRepository,
    PositionRepository,
    SignalRepository,
    StrategyRepository,
    TickerRepository,
)
from quantflow.database.session import DatabaseManager
from quantflow.execution.paper import PaperExecutionHandler
from quantflow.market_data.orderbook import LocalOrderBook
from quantflow.portfolio.engine import PortfolioEngine


@pytest.fixture
async def db_manager() -> AsyncGenerator[DatabaseManager, None]:
    """Create an in-memory SQLite database manager for test execution."""
    manager = DatabaseManager(database_url="sqlite+aiosqlite:///:memory:")
    await manager.create_all()
    yield manager
    await manager.close()


# ── 1. Migration Tests ───────────────────────────────────────────


def test_alembic_migrations_apply_and_downgrade_cleanly(
    tmp_path: Path,
) -> None:
    """Verify migrations apply head, downgrade to base, and upgrade again."""
    db_file = tmp_path / "test_migration.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    # 1. Upgrade to head
    upgrade(alembic_cfg, "head")

    # 2. Downgrade to base
    downgrade(alembic_cfg, "base")

    # 3. Upgrade to head again
    upgrade(alembic_cfg, "head")


# ── 2. Strategy Repository Tests ─────────────────────────────────


async def test_strategy_repository_crud(db_manager: DatabaseManager) -> None:
    """Test Strategy CRUD operations."""
    async with db_manager.session() as session:
        repo = StrategyRepository(session)

        # Create
        strat = await repo.create_or_update(
            name="mean_reversion_v1",
            version="1.0.0",
            config={"window": 20, "threshold": 2.0},
            active=True,
        )
        assert strat.id is not None
        assert strat.name == "mean_reversion_v1"

    # Query & Update
    async with db_manager.session() as session:
        repo = StrategyRepository(session)
        fetched = await repo.get_by_name("mean_reversion_v1")
        assert fetched is not None
        assert fetched.version == "1.0.0"
        assert fetched.config["window"] == 20

        # Update
        updated = await repo.create_or_update(
            name="mean_reversion_v1",
            version="1.1.0",
            config={"window": 30},
            active=True,
        )
        assert updated.version == "1.1.0"
        assert updated.config["window"] == 30

        active_list = await repo.list_active()
        assert len(active_list) == 1
        assert active_list[0].name == "mean_reversion_v1"


# ── 3. Order & Execution Repository Tests ────────────────────────


async def test_order_and_execution_repository_crud(
    db_manager: DatabaseManager,
) -> None:
    """Test Order and Execution repository operations."""
    order_id = uuid.uuid4()
    fill_id_1 = uuid.uuid4()
    fill_id_2 = uuid.uuid4()

    async with db_manager.session() as session:
        strat_repo = StrategyRepository(session)
        await strat_repo.create_or_update("trend_v1", "1.0.0")

        order_repo = OrderRepository(session)
        order = await order_repo.create(
            order_id=order_id,
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=2.0,
            strategy_name="trend_v1",
            limit_price=50000.0,
            status=OrderStatus.PENDING,
        )
        assert order.order_id == order_id
        assert order.status == OrderStatus.PENDING

    # Add executions (fills)
    async with db_manager.session() as session:
        exec_repo = ExecutionRepository(session)
        f1 = await exec_repo.create(
            fill_id=fill_id_1,
            order_id=order_id,
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            price=50000.0,
            quantity=1.0,
            commission=2.0,
        )
        f2 = await exec_repo.create(
            fill_id=fill_id_2,
            order_id=order_id,
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            price=50010.0,
            quantity=1.0,
            commission=2.0,
        )
        assert f1.fill_id == fill_id_1
        assert f2.fill_id == fill_id_2

        order_repo = OrderRepository(session)
        updated_order = await order_repo.update_status(
            order_id=order_id,
            status=OrderStatus.FILLED,
            filled_quantity=2.0,
            avg_price=50005.0,
        )
        assert updated_order is not None
        assert updated_order.status == OrderStatus.FILLED
        assert updated_order.filled_quantity == 2.0
        assert updated_order.avg_price == 50005.0

    # Query fills for order
    async with db_manager.session() as session:
        exec_repo = ExecutionRepository(session)
        order_fills = await exec_repo.get_fills_for_order(order_id)
        assert len(order_fills) == 2
        assert {f.fill_id for f in order_fills} == {fill_id_1, fill_id_2}


# ── 4. Position & Portfolio Repository Tests ─────────────────────


async def test_position_and_portfolio_repository_crud(
    db_manager: DatabaseManager,
) -> None:
    """Test Position and Portfolio snapshot persistence and recovery."""
    async with db_manager.session() as session:
        port_repo = PortfolioRepository(session)
        pos_repo = PositionRepository(session)

        # Upsert portfolio
        port = await port_repo.upsert(
            portfolio_id="quantflow_main",
            cash=80000.0,
            total_equity=130000.0,
            total_exposure=50000.0,
            realized_pnl=5000.0,
            unrealized_pnl=2000.0,
        )
        assert port.cash == 80000.0
        assert port.total_equity == 130000.0

        # Upsert positions
        p_btc = await pos_repo.upsert(
            portfolio_id="quantflow_main",
            symbol="BTC/USDT",
            quantity=1.0,
            avg_entry_price=50000.0,
            unrealized_pnl=2000.0,
            realized_pnl=5000.0,
        )
        p_eth = await pos_repo.upsert(
            portfolio_id="quantflow_main",
            symbol="ETH/USDT",
            quantity=-10.0,
            avg_entry_price=3000.0,
            unrealized_pnl=0.0,
        )
        assert p_btc.quantity == 1.0
        assert p_eth.quantity == -10.0

    # Verify retrieval
    async with db_manager.session() as session:
        port_repo = PortfolioRepository(session)
        pos_repo = PositionRepository(session)

        saved_port = await port_repo.get("quantflow_main")
        assert saved_port is not None
        assert saved_port.cash == 80000.0
        assert saved_port.realized_pnl == 5000.0

        all_pos = await pos_repo.get_all("quantflow_main")
        assert len(all_pos) == 2
        symbols = {p.symbol for p in all_pos}
        assert symbols == {"BTC/USDT", "ETH/USDT"}

        # Delete closed position
        deleted = await pos_repo.delete("quantflow_main", "ETH/USDT")
        assert deleted is True

        remaining = await pos_repo.get_all("quantflow_main")
        assert len(remaining) == 1
        assert remaining[0].symbol == "BTC/USDT"


# ── 5. Multi-Day Partitioned Ticker Inserts & Range Queries ───────


async def test_partitioned_ticker_multi_day_inserts(
    db_manager: DatabaseManager,
) -> None:
    """Test inserting tick records across a simulated multi-day range and querying."""
    base_time = datetime(2026, 8, 20, 0, 0, 0, tzinfo=UTC)
    ticks_data = []

    # Generate ticks spanning 5 days
    for day in range(5):
        day_time = base_time + timedelta(days=day)
        for hour in range(0, 24, 6):
            t_time = day_time + timedelta(hours=hour)
            ticks_data.append(
                {
                    "symbol": "BTC/USDT",
                    "bid": 50000.0 + (day * 100) + hour,
                    "ask": 50001.0 + (day * 100) + hour,
                    "last": 50000.5 + (day * 100) + hour,
                    "volume": 10.0,
                    "timestamp_exchange": t_time,
                    "received_at": t_time + timedelta(milliseconds=5),
                    "source": "binance",
                    "metadata": {"day_index": day},
                }
            )

    async with db_manager.session() as session:
        repo = TickerRepository(session)
        created_ticks = await repo.create_batch(ticks_data)
        assert len(created_ticks) == 20

    # Query range across Day 1 to Day 3
    query_start = base_time + timedelta(days=1)
    query_end = base_time + timedelta(days=3, hours=12)

    async with db_manager.session() as session:
        repo = TickerRepository(session)
        range_ticks = await repo.get_range("BTC/USDT", query_start, query_end)
        assert len(range_ticks) > 0
        for tick in range_ticks:
            ts = (
                tick.timestamp_exchange
                if tick.timestamp_exchange.tzinfo
                else tick.timestamp_exchange.replace(tzinfo=UTC)
            )
            assert query_start <= ts <= query_end

        latest = await repo.get_latest("BTC/USDT")
        assert latest is not None
        latest_ts = (
            latest.timestamp_exchange
            if latest.timestamp_exchange.tzinfo
            else latest.timestamp_exchange.replace(tzinfo=UTC)
        )
        assert latest_ts == base_time + timedelta(days=4, hours=18)


# ── 6. OrderBook Repository Tests ────────────────────────────────


async def test_orderbook_repository_crud(db_manager: DatabaseManager) -> None:
    """Test OrderBook snapshot persistence and query."""
    now_ts = datetime.now(UTC)
    bids = [[50000.0, 1.5], [49990.0, 3.0]]
    asks = [[50010.0, 2.0], [50020.0, 4.5]]

    async with db_manager.session() as session:
        repo = OrderBookRepository(session)
        ob = await repo.create(
            symbol="BTC/USDT",
            bids=bids,
            asks=asks,
            timestamp_exchange=now_ts,
            source="binance",
            last_update_id=1234567,
        )
        assert ob.id is not None
        assert ob.symbol == "BTC/USDT"

    async with db_manager.session() as session:
        repo = OrderBookRepository(session)
        latest_ob = await repo.get_latest("BTC/USDT")
        assert latest_ob is not None
        assert latest_ob.bids == bids
        assert latest_ob.asks == asks
        assert latest_ob.last_update_id == 1234567


# ── 7. Signal & Metric Repository Tests ──────────────────────────


async def test_signal_and_metric_repository_crud(
    db_manager: DatabaseManager,
) -> None:
    """Test Signal and Metric repositories."""
    event_id = uuid.uuid4()
    now_ts = datetime.now(UTC)

    async with db_manager.session() as session:
        strat_repo = StrategyRepository(session)
        await strat_repo.create_or_update("alpha_v1", "1.0")

        sig_repo = SignalRepository(session)
        sig = await sig_repo.create(
            event_id=event_id,
            strategy_name="alpha_v1",
            symbol="ETH/USDT",
            direction=SignalDirection.BUY,
            confidence=0.85,
            timestamp_exchange=now_ts,
            metadata={"indicator": "rsi", "value": 28.5},
        )
        assert sig.event_id == event_id
        assert sig.direction == SignalDirection.BUY

        metric_repo = MetricRepository(session)
        m1 = await metric_repo.record("sharpe_ratio", 2.15, timestamp=now_ts)
        m2 = await metric_repo.record(
            "sharpe_ratio", 2.25, timestamp=now_ts + timedelta(seconds=10)
        )
        assert m1.id is not None
        assert m2.id is not None

    async with db_manager.session() as session:
        sig_repo = SignalRepository(session)
        fetched_sig = await sig_repo.get_by_event_id(event_id)
        assert fetched_sig is not None
        assert fetched_sig.strategy_name == "alpha_v1"

        metric_repo = MetricRepository(session)
        series = await metric_repo.get_series("sharpe_ratio")
        assert len(series) == 2
        assert [float(m.metric_value) for m in series] == [2.15, 2.25]


# ── 8. Log, ErrorLog, & Partition Metadata Tests ─────────────────


async def test_log_error_and_partition_metadata(
    db_manager: DatabaseManager,
) -> None:
    """Test operational logs, error logs, and partition metadata tracking."""
    corr_id = uuid.uuid4()

    async with db_manager.session() as session:
        log_repo = LogRepository(session)
        err_repo = ErrorLogRepository(session)
        part_repo = PartitionRepository(session)

        # Log
        l_entry = await log_repo.log(
            level=LogLevel.INFO,
            logger_name="test_logger",
            message="System initialized successfully",
            correlation_id=corr_id,
            metadata={"status": "ready"},
        )
        assert l_entry.id is not None

        # Error
        e_entry = await err_repo.record_error(
            component="order_router",
            error_message="Exchange connection timeout",
            error_code="TIMEOUT_504",
            correlation_id=corr_id,
        )
        assert e_entry.id is not None

        # Partition Metadata
        start = datetime(2026, 8, 23, tzinfo=UTC)
        end = datetime(2026, 8, 24, tzinfo=UTC)
        p_meta = await part_repo.record_partition(
            table_name="tickers",
            partition_name="tickers_y2026m08d23",
            start_date=start,
            end_date=end,
        )
        assert p_meta.partition_name == "tickers_y2026m08d23"

    async with db_manager.session() as session:
        part_repo = PartitionRepository(session)
        parts = await part_repo.list_partitions("tickers")
        assert len(parts) == 1
        assert parts[0].partition_name == "tickers_y2026m08d23"


# ── 9. Execution Engine DB Persistence Integration ───────────────


async def test_paper_execution_engine_db_persistence(
    db_manager: DatabaseManager,
) -> None:
    """Verify PaperExecutionHandler persists Orders and Executions to DB."""
    # Create Strategy in DB for foreign key constraint
    async with db_manager.session() as session:
        strat_repo = StrategyRepository(session)
        await strat_repo.create_or_update("stat_arb", "1.0.0")

    book = LocalOrderBook("BTC/USDT")
    await book.apply_snapshot(
        bids=[[50000.0, 2.0], [49900.0, 5.0]],
        asks=[[50010.0, 1.5], [50020.0, 3.0]],
        update_id=1,
    )

    handler = PaperExecutionHandler(
        order_books={"BTC/USDT": book},
        session_factory=db_manager.session_factory,
    )
    await handler.start()

    order = OrderEvent(
        strategy_id="stat_arb",
        symbol="BTC/USDT",
        side="BUY",
        order_type="MARKET",
        quantity=1.0,
    )

    await handler.submit_order(order)
    assert handler.get_order_status(order.order_id) == "FILLED"

    # Verify persisted Order and Executions in DB
    async with db_manager.session() as session:
        order_repo = OrderRepository(session)
        exec_repo = ExecutionRepository(session)

        db_order = await order_repo.get_by_order_id(order.order_id)
        assert db_order is not None
        assert db_order.status == OrderStatus.FILLED
        assert db_order.filled_quantity == 1.0
        assert db_order.avg_price == 50010.0

        db_fills = await exec_repo.get_fills_for_order(order.order_id)
        assert len(db_fills) == 1
        assert db_fills[0].price == 50010.0
        assert db_fills[0].quantity == 1.0


# ── 10. Portfolio Engine DB Persistence Integration ──────────────


async def test_portfolio_engine_db_persistence_and_recovery(
    db_manager: DatabaseManager,
) -> None:
    """Verify PortfolioEngine persists state changes and recovers state."""
    engine = PortfolioEngine(
        initial_cash=100000.0,
        session_factory=db_manager.session_factory,
        portfolio_id="quantflow_main",
    )
    await engine.start()

    # Apply BUY fill
    fill_1 = FillEvent(
        order_id="ord-1",
        symbol="BTC/USDT",
        side="BUY",
        quantity=1.0,
        fill_price=50000.0,
        commission=10.0,
    )
    await engine.handle_fill(fill_1)

    # Cash: 100000 - 50000 - 10 = 49990.0
    assert engine.get_cash() == 49990.0
    assert engine.get_positions() == {"BTC/USDT": 1.0}

    # Verify database state immediately after fill
    async with db_manager.session() as session:
        port_repo = PortfolioRepository(session)
        pos_repo = PositionRepository(session)

        saved_port = await port_repo.get("quantflow_main")
        assert saved_port is not None
        assert saved_port.cash == 49990.0

        saved_pos = await pos_repo.get("quantflow_main", "BTC/USDT")
        assert saved_pos is not None
        assert saved_pos.quantity == 1.0
        assert saved_pos.avg_entry_price == 50000.0

    # Simulate new PortfolioEngine instance starting up (Recovery)
    recovered_engine = PortfolioEngine(
        initial_cash=0.0,  # Will be overridden by DB
        session_factory=db_manager.session_factory,
        portfolio_id="quantflow_main",
    )
    await recovered_engine.start()

    assert recovered_engine.get_cash() == 49990.0
    assert recovered_engine.get_positions() == {"BTC/USDT": 1.0}
    pos_state = recovered_engine.get_position("BTC/USDT")
    assert pos_state is not None
    assert pos_state.avg_entry_price == 50000.0

    # Close position on recovered engine
    fill_2 = FillEvent(
        order_id="ord-2",
        symbol="BTC/USDT",
        side="SELL",
        quantity=1.0,
        fill_price=55000.0,
        commission=10.0,
    )
    await recovered_engine.handle_fill(fill_2)

    # Realized PnL = 5000.0, Cash = 49990 + 55000 - 10 = 104980.0
    assert recovered_engine.get_cash() == 104980.0
    assert recovered_engine.get_positions() == {}

    # Verify DB position is deleted and portfolio updated
    async with db_manager.session() as session:
        port_repo = PortfolioRepository(session)
        pos_repo = PositionRepository(session)

        saved_port = await port_repo.get("quantflow_main")
        assert saved_port is not None
        assert saved_port.cash == 104980.0
        assert saved_port.realized_pnl == 5000.0

        db_positions = await pos_repo.get_all("quantflow_main")
        assert len(db_positions) == 0
