# Live Trading

**Docs:** https://nautilustrader.io/docs/latest/concepts/live/

## TradingNode Setup

```python
from nautilus_trader.live.node import TradingNode
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.adapters.binance.config import (
    BinanceDataClientConfig,
    BinanceExecClientConfig,
)

config = TradingNodeConfig(
    trader_id="TRADER-001",
    data_clients={
        "BINANCE": BinanceDataClientConfig(
            api_key=os.getenv("BINANCE_API_KEY"),
            api_secret=os.getenv("BINANCE_API_SECRET"),
            testnet=True,  # Use testnet first
        ),
    },
    exec_clients={
        "BINANCE": BinanceExecClientConfig(
            api_key=os.getenv("BINANCE_API_KEY"),
            api_secret=os.getenv("BINANCE_API_SECRET"),
            testnet=True,
        ),
    },
    strategies=[MyStrategyConfig(instrument_id="BTCUSDT.BINANCE")],
)

node = TradingNode(config=config)
node.build()
node.start()
```

## Redis Cache (Production)

```python
from nautilus_trader.config import CacheConfig, DatabaseConfig

cache_config = CacheConfig(
    database=DatabaseConfig(
        host="localhost",
        port=6379,
        password=os.getenv("REDIS_PASSWORD"),
    ),
    flush_on_start=False,
)

config = TradingNodeConfig(
    cache=cache_config,
    # ...
)
```

## Risk Configuration

```python
from nautilus_trader.config import RiskEngineConfig

risk_config = RiskEngineConfig(
    bypass=False,  # NEVER bypass in production
    max_order_submit_rate=100,
    max_order_modify_rate=50,
    max_notionals={"BTCUSDT.BINANCE": 50000.0},
)

config = TradingNodeConfig(risk_engine=risk_config, ...)
```

## Logging

```python
from nautilus_trader.config import LoggingConfig

logging_config = LoggingConfig(
    log_level="INFO",
    log_level_file="DEBUG",
    log_directory="logs",
    log_file_format="json",
)
```

## Graceful Shutdown

```python
import signal

def signal_handler(sig, frame):
    node.stop()
    node.dispose()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

## Multi-Venue

```python
config = TradingNodeConfig(
    data_clients={
        "BINANCE": BinanceDataClientConfig(...),
        "BYBIT": BybitDataClientConfig(...),
    },
    exec_clients={
        "BINANCE": BinanceExecClientConfig(...),
        "BYBIT": BybitExecClientConfig(...),
    },
)
```

## Paper Trading (Testnet)

```python
# Binance testnet
BinanceDataClientConfig(testnet=True)
BinanceExecClientConfig(testnet=True)

# Bybit testnet
BybitDataClientConfig(is_testnet=True)
BybitExecClientConfig(is_testnet=True)
```

## Execution Reconciliation

On startup, `LiveExecutionEngine` reconciles state with venue:
- With cached state: generates missing events
- Without cache: rebuilds from venue reports

## Production Checklist

- Extensive backtesting completed
- Paper trading validated
- Risk limits configured (`bypass=False`)
- Graceful shutdown handling
- Logging configured
- Credentials secured (env vars)
- Monitoring/alerts set up
