# Data Models

**Location:** `nautilus_trader.model`

**Docs:** https://nautilustrader.io/docs/latest/api_reference/model/

## Core Data Types

```python
from nautilus_trader.model.data import QuoteTick, TradeTick, Bar, BarType
from nautilus_trader.model.data import OrderBookDelta, OrderBookDepth10

# QuoteTick - bid/ask
tick.bid_price, tick.ask_price, tick.bid_size, tick.ask_size

# TradeTick - trades
tick.price, tick.size, tick.aggressor_side, tick.trade_id

# Bar - OHLCV
bar.open, bar.high, bar.low, bar.close, bar.volume
bar_type = BarType.from_str("BTCUSDT.BINANCE-1-MINUTE-LAST-EXTERNAL")
```

## Identifiers

```python
from nautilus_trader.model.identifiers import (
    InstrumentId, Symbol, Venue,
    TraderId, StrategyId, AccountId,
    ClientOrderId, VenueOrderId, PositionId,
)

instrument_id = InstrumentId.from_str("BTCUSDT.BINANCE")
symbol = instrument_id.symbol
venue = instrument_id.venue
```

## Value Objects

```python
from nautilus_trader.model.objects import Price, Quantity, Money, Currency

# Always use from_str() to avoid precision issues
price = Price.from_str("50000.50")
quantity = Quantity.from_str("1.5")
money = Money(10000, Currency.from_str("USDT"))

# Convert to float
float(price), float(quantity)
```

## Order Enums

```python
from nautilus_trader.model.enums import (
    OrderSide,      # BUY, SELL
    OrderType,      # MARKET, LIMIT, STOP_MARKET, STOP_LIMIT, etc.
    TimeInForce,    # GTC, IOC, FOK, DAY, GTD
    OrderStatus,    # INITIALIZED, SUBMITTED, ACCEPTED, FILLED, CANCELLED, etc.
    TriggerType,    # DEFAULT, LAST_PRICE, BID_ASK, MARK_PRICE, INDEX_PRICE
)
```

## Order Events

```python
from nautilus_trader.model.events import (
    OrderSubmitted, OrderAccepted, OrderRejected,
    OrderCancelled, OrderExpired, OrderFilled, OrderUpdated,
)

def on_order_filled(self, event: OrderFilled):
    event.client_order_id
    event.last_px      # fill price
    event.last_qty     # fill quantity
    event.commission
```

## Position Events

```python
from nautilus_trader.model.events import PositionOpened, PositionChanged, PositionClosed

def on_position_closed(self, event: PositionClosed):
    event.position_id
    event.realized_pnl
```

## Instrument Types

```python
from nautilus_trader.model.instruments import (
    CurrencyPair,      # Spot
    CryptoPerpetual,   # Perpetual futures
    CryptoFuture,      # Dated futures
    Equity,
    Option,
)

# Key properties
instrument.price_precision
instrument.size_precision
instrument.price_increment
instrument.size_increment
instrument.min_quantity
instrument.max_quantity
```

## Custom Data

```python
from nautilus_trader.model.data import Data
from nautilus_trader.core.data import DataType

class CustomSignal(Data):
    def __init__(self, value: float, ts_event: int, ts_init: int):
        super().__init__()
        self.value = value
        self.ts_event = ts_event
        self.ts_init = ts_init

# Publish
self.publish_data(DataType(CustomSignal), signal)
```

## ParquetDataCatalog

```python
from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog = ParquetDataCatalog("./catalog")

# Write
catalog.write_data(bars)

# Query
bars = catalog.bars(instrument_ids=["BTCUSDT.BINANCE"], start="2024-01-01", end="2024-12-31")
quotes = catalog.quote_ticks(instrument_ids=["BTCUSDT.BINANCE"])
```
