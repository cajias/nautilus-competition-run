# Backtesting

**Docs:** https://nautilustrader.io/docs/latest/concepts/backtesting/

## High-Level API (BacktestNode)

```python
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import (
    BacktestRunConfig,
    BacktestEngineConfig,
    BacktestVenueConfig,
    BacktestDataConfig,
)

config = BacktestRunConfig(
    engine=BacktestEngineConfig(trader_id="BACKTESTER-001"),
    venues=[
        BacktestVenueConfig(
            name="BINANCE",
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=["10000 USDT"],
        )
    ],
    data=[
        BacktestDataConfig(
            catalog_path="./catalog",
            data_cls=QuoteTick,
            instrument_id="BTCUSDT.BINANCE",
        )
    ],
    strategies=[
        MyStrategyConfig(
            instrument_id="BTCUSDT.BINANCE",
            bar_type="BTCUSDT.BINANCE-1-MINUTE-LAST-EXTERNAL",
        )
    ],
)

node = BacktestNode(configs=[config])
results = node.run()
```

## Low-Level API (BacktestEngine)

```python
from nautilus_trader.backtest.engine import BacktestEngine

engine = BacktestEngine()

engine.add_venue(
    venue=Venue("BINANCE"),
    oms_type=OmsType.NETTING,
    account_type=AccountType.CASH,
    starting_balances=[Money(10_000, Currency.from_str("USDT"))],
)

engine.add_instrument(instrument)
engine.add_data(bars)
engine.add_strategy(MyStrategy(config))

engine.run()

# Results
fills_report = engine.trader.generate_order_fills_report()
account_report = engine.trader.generate_account_report(Venue("BINANCE"))
```

### Multiple Runs (Engine Reset)

```python
engine.run()
results1 = engine.trader.generate_order_fills_report()

engine.reset()  # Instruments and data persist
engine.add_strategy(strategy2)
engine.run()
results2 = engine.trader.generate_order_fills_report()
```

## ParquetDataCatalog

```python
from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog = ParquetDataCatalog("./catalog")

# Query data
bars = catalog.bars(instrument_ids=["BTCUSDT.BINANCE"])
quotes = catalog.quote_ticks(instrument_ids=["BTCUSDT.BINANCE"])
trades = catalog.trade_ticks(instrument_ids=["BTCUSDT.BINANCE"])
```

## Fill Models

**Location:** `nautilus_trader.backtest.models`

```python
from nautilus_trader.backtest.models import FillModel

# Conservative (realistic)
fill_model = FillModel(
    prob_fill_on_limit=0.2,  # 20% fill on touch
    prob_slippage=0.5,       # 50% slippage chance
    random_seed=42,          # Reproducibility
)

# Optimistic
fill_model = FillModel(
    prob_fill_on_limit=1.0,
    prob_slippage=0.0,
)
```

## OMS Types

- `OmsType.NETTING` - Single position per instrument (crypto)
- `OmsType.HEDGING` - Multiple positions per instrument (futures)

## Account Types

- `AccountType.CASH` - Spot trading
- `AccountType.MARGIN` - Leverage trading

## Parameter Optimization

```python
configs = []
for fast in [10, 12, 14]:
    for slow in [20, 26, 30]:
        configs.append(BacktestRunConfig(
            engine=BacktestEngineConfig(trader_id=f"TEST-{fast}-{slow}"),
            strategies=[MyStrategyConfig(fast_period=fast, slow_period=slow)],
            # ... venues, data
        ))

node = BacktestNode(configs=configs)
results = node.run()
```

## Multi-Instrument/Venue

```python
# Multiple instruments
data=[
    BacktestDataConfig(catalog_path="./catalog", data_cls=Bar, instrument_id="BTCUSDT.BINANCE"),
    BacktestDataConfig(catalog_path="./catalog", data_cls=Bar, instrument_id="ETHUSDT.BINANCE"),
]

# Multiple venues
venues=[
    BacktestVenueConfig(name="BINANCE", ...),
    BacktestVenueConfig(name="COINBASE", ...),
]
```
