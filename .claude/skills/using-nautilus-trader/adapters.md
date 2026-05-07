# Custom Adapters

**Docs:** https://nautilustrader.io/docs/latest/concepts/adapters/

## Adapter Components

- **InstrumentProvider** - Load instrument definitions
- **DataClient** - Market data subscriptions
- **ExecutionClient** - Order submission/management

## Custom Data Client

```python
from nautilus_trader.live.data_client import LiveMarketDataClient

class CustomDataClient(LiveMarketDataClient):
    def __init__(self, loop, client, msgbus, cache, clock, instrument_provider, config):
        super().__init__(
            loop=loop,
            client_id=ClientId("MY_EXCHANGE"),
            venue=Venue("MY_EXCHANGE"),
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
        )
        self._client = client

    async def _connect(self): pass
    async def _disconnect(self): pass
    async def _subscribe_quote_ticks(self, instrument_id): pass
    async def _subscribe_trade_ticks(self, instrument_id): pass
    async def _subscribe_bars(self, bar_type): pass
```

## Custom Execution Client

```python
from nautilus_trader.live.execution_client import LiveExecutionClient

class CustomExecClient(LiveExecutionClient):
    def __init__(self, loop, client, msgbus, cache, clock, instrument_provider, config):
        super().__init__(
            loop=loop,
            client_id=ClientId("MY_EXCHANGE"),
            venue=Venue("MY_EXCHANGE"),
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=Currency.from_str("USDT"),
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
        )

    async def _connect(self): pass
    async def _disconnect(self): pass
    async def _submit_order(self, command: SubmitOrder): pass
    async def _cancel_order(self, command: CancelOrder): pass
```

## Configuration Classes

```python
from nautilus_trader.config import LiveDataClientConfig, LiveExecClientConfig

class CustomDataClientConfig(LiveDataClientConfig):
    api_key: str
    api_secret: str
    base_url: str = "https://api.exchange.com"
    testnet: bool = False

class CustomExecClientConfig(LiveExecClientConfig):
    api_key: str
    api_secret: str
```

## Register Adapter

```python
from nautilus_trader.live.node import TradingNode

TradingNode.add_data_client_factory("MY_EXCHANGE", CustomLiveDataClientFactory)
TradingNode.add_exec_client_factory("MY_EXCHANGE", CustomLiveExecClientFactory)

config = TradingNodeConfig(
    data_clients={"MY_EXCHANGE": CustomDataClientConfig(...)},
    exec_clients={"MY_EXCHANGE": CustomExecClientConfig(...)},
)
```

## Reference Implementations

See: https://github.com/nautechsystems/nautilus_trader/tree/develop/nautilus_trader/adapters
