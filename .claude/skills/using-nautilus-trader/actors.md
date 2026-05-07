# Actors

**Location:** `nautilus_trader.trading.actor`

**Docs:** https://nautilustrader.io/docs/latest/concepts/actors/

## Actor vs Strategy

| Feature | Actor | Strategy |
|---------|-------|----------|
| Order submission | No | Yes |
| OrderFactory | No | Yes |
| Data subscriptions | Yes | Yes |
| Cache/Portfolio access | Yes | Yes |

**Use Actor for:** Signal generators, risk monitors, data processors, non-trading components.

## Basic Structure

```python
from nautilus_trader.trading import Actor
from nautilus_trader.config import ActorConfig

class MyActorConfig(ActorConfig):
    instrument_id: str

class MyActor(Actor):
    def __init__(self, config: MyActorConfig):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
```

## Lifecycle

```python
def on_start(self):
    self.subscribe_quote_ticks(self.instrument_id)

def on_stop(self):
    self.unsubscribe_quote_ticks(self.instrument_id)

def on_reset(self):
    self.signal_count = 0
```

## Data Handlers

```python
def on_quote_tick(self, tick: QuoteTick): pass
def on_trade_tick(self, tick: TradeTick): pass
def on_bar(self, bar: Bar): pass
def on_order_book_deltas(self, deltas): pass
def on_order_book_depth(self, depth): pass
```

## MessageBus

```python
# Publish
self.msgbus.publish(topic="signals.entry", msg=signal)

# Subscribe
def on_start(self):
    self.msgbus.subscribe(topic="signals.*", handler=self.on_signal)

def on_signal(self, signal):
    self.log.info(f"Signal: {signal}")
```

## Custom Data Publishing

```python
from nautilus_trader.core.data import DataType

class TradingSignal(Data):
    def __init__(self, value: float, ts_event: int, ts_init: int):
        super().__init__()
        self.value = value
        self.ts_event = ts_event
        self.ts_init = ts_init

# Publish
signal = TradingSignal(value=0.8, ts_event=self.clock.timestamp_ns(), ts_init=self.clock.timestamp_ns())
self.publish_data(DataType(TradingSignal), signal)

# Subscribe (in another actor/strategy)
self.subscribe_data(DataType(TradingSignal))

def on_data(self, data):
    if isinstance(data, TradingSignal):
        self.log.info(f"Signal: {data.value}")
```

## Timers

```python
from datetime import timedelta

def on_start(self):
    self.clock.set_timer(name="check", interval=timedelta(seconds=60), callback=self.on_check)

def on_check(self, event):
    self.log.info("Timer fired")

def on_stop(self):
    self.clock.cancel_timer("check")
```

## Register Actor

```python
# Backtest
engine.add_actor(MyActor(config))

# Live
TradingNodeConfig(
    actors=[MyActorConfig(instrument_id="BTCUSDT.BINANCE")],
    strategies=[...],
)
```
