# Architecture

**Docs:** https://nautilustrader.io/docs/latest/concepts/architecture/

## Core Components

```
NautilusKernel (orchestration)
    ├── MessageBus (pub/sub communication)
    ├── Cache (instruments, market data, orders, positions)
    ├── Portfolio (accounts, balances, PnL)
    ├── DataEngine (data routing)
    ├── ExecutionEngine (order routing)
    └── RiskEngine (pre-trade checks)
```

## Data Flow

```
Market Data -> DataClient -> DataEngine -> Cache -> MessageBus -> Strategies
```

## Order Flow

```
Strategy -> RiskEngine -> ExecutionEngine -> ExecutionClient -> Venue
```

## System Nodes

- **BacktestEngine** - Historical data replay, simulated execution
- **TradingNode** - Live/paper trading with real venues

## Key Principle

Same strategy code works in backtest and live - no reimplementation.

## Package Structure

```
nautilus_trader/
├── adapters/      # Venue integrations (Binance, Bybit, IB)
├── backtest/      # BacktestEngine, BacktestNode
├── cache/         # Cache system
├── config/        # Configuration objects
├── data/          # DataEngine
├── execution/     # ExecutionEngine
├── indicators/    # Technical indicators
├── live/          # TradingNode
├── model/         # Data models, orders, instruments
├── persistence/   # ParquetDataCatalog
├── portfolio/     # Portfolio management
├── risk/          # RiskEngine
└── trading/       # Strategy, Actor
```

## MessageBus Topics

```python
"data.quotes.*"      # Quote ticks
"data.trades.*"      # Trade ticks
"data.bars.*"        # Bars
"events.order.*"     # Order events
"events.position.*"  # Position events
```

## Component Lifecycle

```
INITIALIZED -> STARTING -> RUNNING -> STOPPING -> STOPPED
```

Strategy hooks: `on_start()`, `on_stop()`, `on_reset()`, `on_save()`, `on_load()`
