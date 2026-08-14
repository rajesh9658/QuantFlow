# QuantFlow

QuantFlow is an event-driven quantitative trading, backtesting, and execution framework built in Python 3.12.

## Package Management

This project uses **`uv`** as its Python package manager.

### Installation & Setup

```bash
uv sync --all-extras --dev
```

### Development Commands

```bash
# Run linting
uv run ruff check .

# Run formatting check
uv run black --check .

# Run type checking
uv run mypy quantflow tests

# Run tests
uv run pytest
```
