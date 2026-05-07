# Cache

**Location:** `nautilus_trader.cache.cache`

**Docs:** https://nautilustrader.io/docs/latest/concepts/cache/

Access via `self.cache` in strategies/actors.

## Instruments

```python
instrument = self.cache.instrument(instrument_id)
instruments = self.cache.instruments(venue=Venue("BINANCE"))
instrument_ids = self.cache.instrument_ids()
```

## Market Data

```python
# Quote ticks
quote = self.cache.quote_tick(instrument_id)
quote.bid_price, quote.ask_price

# Trade ticks
trade = self.cache.trade_tick(instrument_id)
trade.price, trade.size

# Bars
bar = self.cache.bar(bar_type)
bar.open, bar.high, bar.low, bar.close

# Order book
book = self.cache.order_book(instrument_id)
book.best_bid_price(), book.best_ask_price()
book.spread(), book.midpoint(), book.imbalance()
```

## Orders

```python
order = self.cache.order(client_order_id)
order = self.cache.order(venue_order_id=venue_order_id)

orders = self.cache.orders()
orders = self.cache.orders_open()
orders = self.cache.orders_open(instrument_id=instrument_id)
orders = self.cache.orders_open(venue=Venue("BINANCE"))
orders = self.cache.orders_closed()
orders = self.cache.orders_emulated()

# Counts
self.cache.orders_open_count()
self.cache.orders_open_count(instrument_id=instrument_id)
```

## Positions

```python
position = self.cache.position(position_id)
positions = self.cache.positions_open()
positions = self.cache.positions_open(instrument_id=instrument_id)
positions = self.cache.positions_closed()

# Counts
self.cache.positions_open_count()
```

## Accounts

```python
account = self.cache.account_for_venue(Venue("BINANCE"))
accounts = self.cache.accounts()
```

## Custom State

```python
self.cache.add(key="my_data", value=data)
data = self.cache.get("my_data")
exists = self.cache.has("my_data")
self.cache.delete("my_data")
```

## Redis Configuration (Live)

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
```
