# Integrations

**Docs:** https://nautilustrader.io/docs/latest/integrations/

## Status Levels

- **stable** - Production ready
- **beta** - Functional, still testing
- **building** - Under construction

## Crypto Exchanges

### Binance (stable)

```python
from nautilus_trader.adapters.binance.config import BinanceDataClientConfig, BinanceExecClientConfig

BinanceDataClientConfig(
    api_key="...",
    api_secret="...",
    testnet=True,
    account_type="spot",  # or "usdt_future", "coin_future"
)
```

### Bybit (stable)

```python
from nautilus_trader.adapters.bybit.config import BybitDataClientConfig, BybitExecClientConfig

BybitDataClientConfig(api_key="...", api_secret="...", is_testnet=True)
```

### Interactive Brokers (beta)

```python
from nautilus_trader.adapters.interactive_brokers.config import InteractiveBrokersDataClientConfig

InteractiveBrokersDataClientConfig(ib_host="127.0.0.1", ib_port=7497, ib_client_id=1)
```

### Others

- **OKX** (stable)
- **Kraken** (stable)
- **Coinbase** (beta)
- **Bitfinex** (beta)
- **Hyperliquid** (beta)
- **BitMEX** (beta)

## Data Providers

### Databento

```python
from nautilus_trader.adapters.databento.config import DatabentoDataClientConfig
DatabentoDataClientConfig(api_key="...")
```

### Tardis

```python
from nautilus_trader.adapters.tardis.config import TardisDataClientConfig
TardisDataClientConfig(api_key="...")
```
