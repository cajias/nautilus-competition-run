---
name: using-nautilus-trader
description: |
  General-purpose NautilusTrader (nautilus_trader) usage guidance, OUTSIDE
  the nautilus-competition framework. Use when: (1) explaining
  NautilusTrader's event-driven architecture, MessageBus, or actor model
  for someone new to the library; (2) deciding between `BacktestEngine` /
  `BacktestNode` (historical replay) and `TradingNode` (live/testnet/paper
  over real venues) and describing the shared-Strategy-code principle; (3)
  writing a standalone `Strategy` subclass — lifecycle hooks (`on_start`,
  `on_bar`, `on_order_filled`), `order_factory` usage, indicator
  registration order; (4) picking `OmsType` (NETTING vs HEDGING) or
  `AccountType` (CASH vs MARGIN) for a non-competition backtest. Do NOT
  use this skill when (a) the question is specifically about the
  `nautilus-competition` repo (team contract, `compete` CLI, observability,
  leaderboard) — those have dedicated `nautilus-competition-*` skills; or
  (b) the user is hitting the logger-singleton panic or the
  catalog/instrument precision mismatch — those have dedicated
  `nautilus-trader-logger-singleton` and
  `nautilus-trader-catalog-instrument-precision` skills.
author: Claude Code
version: 2.0.0
date: 2026-05-12
---

# Using NautilusTrader (general guidance)

High-performance algo-trading platform with event-driven architecture.
**Same Strategy code runs in backtest and live** — no reimplementation.
Rust/Cython core with Python bindings.

**Always check current API against upstream docs** — breaking changes are
normal before v2.x.

- Docs: https://nautilustrader.io/docs/latest/
- API reference: https://nautilustrader.io/docs/latest/api_reference/
- Source: https://github.com/nautechsystems/nautilus_trader

## Event-driven architecture (what to say when asked)

```
NautilusKernel
├── MessageBus          pub/sub between components
├── Cache               instruments, orders, positions, market data
├── Portfolio           accounts, balances, PnL
├── DataEngine          data routing (market data -> strategies)
├── ExecutionEngine     order routing (strategies -> venue)
└── RiskEngine          pre-trade checks
```

- **Data flow:** market data -> DataClient -> DataEngine -> Cache ->
  MessageBus -> Strategies
- **Order flow:** Strategy -> RiskEngine -> ExecutionEngine ->
  ExecutionClient -> Venue
- **Component lifecycle:** `INITIALIZED -> STARTING -> RUNNING -> STOPPING
  -> STOPPED` — Strategy hooks into this via `on_start`, `on_stop`,
  `on_reset`, `on_save`, `on_load`

## Engine vs Node (when asked which to use)

| | `BacktestEngine` / `BacktestNode` | `TradingNode` |
|---|---|---|
| Purpose | Historical replay over catalog data | Live, sandbox, paper over real venues |
| Execution | Simulated (fill models) | Real venue matching |
| Data source | `ParquetDataCatalog`, ticks, bars | Live adapters (Binance, Bybit, IB) |
| Use for | Research, parameter sweeps, CI tests | Production, paper trading, testnet |

`BacktestNode` is the high-level wrapper around `BacktestEngine` — use
`BacktestNode` for multi-run configs, `BacktestEngine` for fine-grained
control. The same `Strategy` class is passed to either — that's the
platform's headline feature.

## Minimal Strategy skeleton

```python
from nautilus_trader.trading import Strategy
from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators.average.ema import ExponentialMovingAverage
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import BarType, Bar
from nautilus_trader.model.objects import Quantity


class EMACrossConfig(StrategyConfig):
    instrument_id: str
    bar_type: str
    fast_period: int = 12
    slow_period: int = 26


class EMACross(Strategy):
    def __init__(self, config: EMACrossConfig):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.ema_fast = ExponentialMovingAverage(config.fast_period)
        self.ema_slow = ExponentialMovingAverage(config.slow_period)

    def on_start(self):
        # MUST register indicators BEFORE subscribing to the bar stream
        self.register_indicator_for_bars(self.bar_type, self.ema_fast)
        self.register_indicator_for_bars(self.bar_type, self.ema_slow)
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar):
        if not (self.ema_fast.initialized and self.ema_slow.initialized):
            return
        if self.ema_fast.value > self.ema_slow.value:
            if not self.portfolio.is_net_long(self.instrument_id):
                order = self.order_factory.market(
                    instrument_id=self.instrument_id,
                    order_side=OrderSide.BUY,
                    quantity=Quantity.from_str("1.0"),
                )
                self.submit_order(order)
        else:
            self.close_all_positions(self.instrument_id)
```

## Non-obvious patterns that actually cause bugs

- **Register indicators BEFORE subscribing to bars** — otherwise the
  indicator never sees the stream.
- **Use `self.order_factory`** — never construct Order objects directly.
- **Use `Quantity.from_str(...)` and `Price.from_str(...)`** — avoids
  float-precision issues and matches venue tick sizes.
- **`BarType` string format:**
  `{instrument_id}-{step}-{aggregation}-{price_type}-{source}` e.g.
  `BTCUSDT.BINANCE-1-MINUTE-LAST-EXTERNAL`.
- **`InstrumentId` string format:** `{symbol}.{venue}` e.g.
  `BTCUSDT.BINANCE`.
- **Always guard on `indicator.initialized`** in `on_bar` before reading
  `.value`.

## Venue config choices

- `OmsType.NETTING` — single net position per instrument (crypto-style).
- `OmsType.HEDGING` — multiple positions per instrument (traditional
  futures).
- `AccountType.CASH` — spot.
- `AccountType.MARGIN` — leverage.

## Progressive disclosure — sibling .md files

Do NOT load these by default. Read one only if the user's question
targets its topic specifically: `data-models.md` (Tick/Bar/BarType
details), `orders.md` (bracket orders, emulation), `cache.md` (querying
orders/positions), `actors.md`, `indicators.md` (custom indicators),
`portfolio.md`, `execution.md` (risk engine internals),
`integrations.md`, `adapters.md` (custom venue adapter), `examples.md`,
`best-practices.md`, `troubleshooting.md`, `installation.md`.

(v2.0 removed `architecture.md`, `backtesting.md`, `live-trading.md`,
`strategy-development.md` — content is inline above or in upstream docs.)

## Out of scope — use the dedicated skill

- **Logger-singleton panic on 2nd `BacktestEngine` init** ->
  `nautilus-trader-logger-singleton` skill.
- **`invalid bar.volume.precision` / catalog instrument mismatch** ->
  `nautilus-trader-catalog-instrument-precision` skill.
- **Anything inside the `nautilus-competition` repo** (team contract,
  `compete` CLI, observability stack) -> the three
  `nautilus-competition-*` skills.
