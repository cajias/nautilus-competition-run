# Strategy Development

**Location:** `nautilus_trader.trading.strategy`

**Docs:** https://nautilustrader.io/docs/latest/concepts/strategies/

## Strategy Structure

```python
from nautilus_trader.trading import Strategy
from nautilus_trader.config import StrategyConfig

class MyStrategyConfig(StrategyConfig):
    instrument_id: str
    bar_type: str
    trade_size: float = 1.0

class MyStrategy(Strategy):
    def __init__(self, config: MyStrategyConfig):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.trade_size = Quantity.from_str(str(config.trade_size))
```

## Lifecycle Methods

```python
def on_start(self):
    """Subscribe to data, register indicators, set up timers."""
    self.register_indicator_for_bars(self.bar_type, self.ema)  # Before subscribe
    self.subscribe_bars(self.bar_type)

def on_stop(self):
    """Cancel orders, close positions, cleanup."""
    self.cancel_all_orders()

def on_reset(self):
    """Reset indicators, clear state."""
    self.ema.reset()

def on_save(self) -> dict:
    """Return state dict for persistence."""
    return {"count": self.count}

def on_load(self, state: dict):
    """Restore state from dict."""
    self.count = state.get("count", 0)
```

## Data Handlers

```python
def on_quote_tick(self, tick: QuoteTick):
    pass  # bid/ask updates

def on_trade_tick(self, tick: TradeTick):
    pass  # executed trades

def on_bar(self, bar: Bar):
    pass  # OHLCV bars

def on_order_book_deltas(self, deltas: OrderBookDelta):
    pass  # incremental book updates

def on_order_book_depth(self, depth: OrderBookDepth10):
    pass  # top 10 levels snapshot
```

## Order Handlers

```python
def on_order_filled(self, event: OrderFilled):
    self.log.info(f"Filled: {event.last_qty} @ {event.last_px}")

def on_order_rejected(self, event: OrderRejected):
    self.log.error(f"Rejected: {event.reason}")

def on_order_cancelled(self, event: OrderCancelled):
    pass

def on_order_expired(self, event: OrderExpired):
    pass
```

## Data Subscriptions

```python
# In on_start()
self.subscribe_quote_ticks(instrument_id)
self.subscribe_trade_ticks(instrument_id)
self.subscribe_bars(bar_type)
self.subscribe_order_book_deltas(instrument_id, book_type=BookType.L2_MBP, depth=10)
```

## Order Submission

```python
# Market order
order = self.order_factory.market(
    instrument_id=instrument_id,
    order_side=OrderSide.BUY,
    quantity=Quantity.from_str("1.0"),
)
self.submit_order(order)

# Limit order
order = self.order_factory.limit(
    instrument_id=instrument_id,
    order_side=OrderSide.BUY,
    quantity=Quantity.from_str("1.0"),
    price=Price.from_str("50000.00"),
    time_in_force=TimeInForce.GTC,
)

# Cancel/modify
self.cancel_order(order)
self.modify_order(order, quantity=new_qty, price=new_price)

# Close positions
self.close_position(position)
self.close_all_positions(instrument_id)
```

## Portfolio Access

```python
# Position info
position = self.portfolio.position(position_id)
positions = self.portfolio.positions_open()
net_qty = self.portfolio.net_position(instrument_id)

# PnL
unrealized = self.portfolio.unrealized_pnl(instrument_id)
realized = self.portfolio.realized_pnl(instrument_id)

# Check direction
is_long = self.portfolio.is_net_long(instrument_id)
is_short = self.portfolio.is_net_short(instrument_id)
is_flat = self.portfolio.is_flat(instrument_id)
```

## Indicator Registration

```python
def __init__(self, config):
    super().__init__(config)
    self.ema = ExponentialMovingAverage(period=20)

def on_start(self):
    # MUST register before subscribing
    self.register_indicator_for_bars(self.bar_type, self.ema)
    self.subscribe_bars(self.bar_type)

def on_bar(self, bar: Bar):
    # Indicator auto-updated before on_bar called
    if self.ema.initialized:
        value = self.ema.value
```

## Timers

```python
from datetime import timedelta

def on_start(self):
    self.clock.set_timer(
        name="check",
        interval=timedelta(seconds=60),
        callback=self.on_check,
    )

def on_check(self, event):
    self.log.info("Timer fired")

def on_stop(self):
    self.clock.cancel_timer("check")
```

## Minimal Example

```python
class EMAStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.ema_fast = ExponentialMovingAverage(12)
        self.ema_slow = ExponentialMovingAverage(26)

    def on_start(self):
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
