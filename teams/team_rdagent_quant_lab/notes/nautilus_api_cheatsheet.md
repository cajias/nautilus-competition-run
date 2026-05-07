# nautilus_api_cheatsheet

Quick reference for `implementation-agent` (Co-STEER). The full docs live at `docs.nautilustrader.io`.

## Strategy class skeleton

```python
from decimal import Decimal
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy


class TeamStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal = Decimal("0.001")


class TeamStrategy(Strategy):
    def __init__(self, config: TeamStrategyConfig) -> None:
        super().__init__(config)
        self.instrument = None

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.stop()
            return
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        # ... your logic
        pass
```

## Submitting orders

- **NEVER** call `Strategy.buy(...)` — that method does not exist.
- Use:
  ```python
  order = self.order_factory.market(
      instrument_id=self.config.instrument_id,
      order_side=OrderSide.BUY,        # or OrderSide.SELL
      quantity=self.instrument.make_qty(self.config.trade_size),
      time_in_force=TimeInForce.GTC,
  )
  self.submit_order(order)
  ```

## ID types

- `InstrumentId.from_str("BTCUSDT.BINANCE")` — never raw string into config.
- `BarType.from_str("BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL")` — never raw string.

## Indicators

- Subclass `nautilus_trader.indicators.base.indicator.Indicator` for custom indicators.
- Built-ins: `ExponentialMovingAverage`, `MovingAverageConvergenceDivergence`, `RelativeStrengthIndex`, `BollingerBands`, `AverageTrueRange`, etc.
- Register via `self.register_indicator_for_bars(self.config.bar_type, indicator_instance)` in `on_start`.
- Gate logic on `indicator.initialized` before reading values.

## RiskEngine

- Configure `RiskEngineConfig(max_notional_per_order=Decimal("..."), max_order_submit_rate="...")` at engine setup; not directly inside the Strategy.
- The harness wires this; you express risk caps via Strategy logic (position cap, leverage cap) and let RiskEngine reject if you exceed.

## Catalog and instrument precision

- Load instrument FROM the catalog: bar precision must match instrument `size_precision`.
- Skill: `nautilus-trader-catalog-instrument-precision` covers the common pitfall.
