# Indicators

**Location:** `nautilus_trader.indicators`

**Docs:** https://nautilustrader.io/docs/latest/concepts/indicators/

## Built-in Indicators

```python
# Moving Averages
from nautilus_trader.indicators.average import (
    ExponentialMovingAverage,  # EMA
    SimpleMovingAverage,       # SMA
    HullMovingAverage,         # HMA
    WilderMovingAverage,
)

# Momentum
from nautilus_trader.indicators.rsi import RelativeStrengthIndex
from nautilus_trader.indicators.macd import MovingAverageConvergenceDivergence
from nautilus_trader.indicators.stochastics import Stochastics

# Volatility
from nautilus_trader.indicators.bollinger_bands import BollingerBands
from nautilus_trader.indicators.atr import AverageTrueRange
from nautilus_trader.indicators.keltner_channel import KeltnerChannel

# Trend
from nautilus_trader.indicators.adx import AverageDirectionalIndex
from nautilus_trader.indicators.aroon import AroonOscillator

# Volume
from nautilus_trader.indicators.obv import OnBalanceVolume
from nautilus_trader.indicators.vwap import VolumeWeightedAveragePrice
```

## Registration (Auto-Update)

```python
def __init__(self, config):
    super().__init__(config)
    self.ema = ExponentialMovingAverage(period=20)
    self.rsi = RelativeStrengthIndex(period=14)

def on_start(self):
    # Register BEFORE subscribing
    self.register_indicator_for_bars(self.bar_type, self.ema)
    self.register_indicator_for_bars(self.bar_type, self.rsi)
    self.subscribe_bars(self.bar_type)

def on_bar(self, bar: Bar):
    # Indicators auto-updated before on_bar
    if self.ema.initialized and self.rsi.initialized:
        ema_val = self.ema.value
        rsi_val = self.rsi.value
```

## Manual Update

```python
def on_trade_tick(self, tick: TradeTick):
    self.ema.update_raw(float(tick.price))
    if self.ema.initialized:
        value = self.ema.value
```

## Indicator Values

```python
# Single value
ema.value
rsi.value
atr.value

# Multiple values
bb = BollingerBands(20, k=2.0)
bb.upper, bb.middle, bb.lower

macd = MovingAverageConvergenceDivergence(12, 26, 9)
macd.value      # MACD line
macd.signal     # Signal line
macd.histogram  # Histogram

stoch = Stochastics(14, 3)
stoch.value_k   # %K
stoch.value_d   # %D

adx = AverageDirectionalIndex(14)
adx.value       # ADX
adx.plus_di     # +DI
adx.minus_di    # -DI
```

## Initialization Check

```python
if indicator.initialized:
    # Safe to use .value
    pass

# For multiple indicators
if all([self.ema.initialized, self.rsi.initialized]):
    pass
```

## Custom Indicator

```python
from nautilus_trader.indicators.base.indicator import Indicator

class CustomMomentum(Indicator):
    def __init__(self, period: int):
        super().__init__([period])
        self.period = period
        self._prices: list[float] = []
        self._value: float = 0.0

    @property
    def value(self) -> float:
        return self._value

    def handle_bar(self, bar: Bar) -> None:
        self._prices.append(float(bar.close))
        if len(self._prices) > self.period:
            self._prices.pop(0)
        if len(self._prices) >= self.period:
            self._value = (self._prices[-1] - self._prices[0]) / self._prices[0]
            self._set_initialized(True)

    def _reset(self) -> None:
        self._prices.clear()
        self._value = 0.0
        self._set_initialized(False)
```

## Reset

```python
def on_reset(self):
    self.ema.reset()
    self.rsi.reset()
```
