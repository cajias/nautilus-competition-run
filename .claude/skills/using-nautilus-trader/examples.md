# Examples

**Official examples:** https://github.com/nautechsystems/nautilus_trader/tree/develop/examples

## EMA Crossover Strategy

```python
class EMACrossConfig(StrategyConfig):
    instrument_id: str
    bar_type: str
    fast_period: int = 10
    slow_period: int = 20
    trade_size: float = 1.0

class EMACrossStrategy(Strategy):
    def __init__(self, config: EMACrossConfig):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.trade_size = Quantity.from_str(str(config.trade_size))
        self.ema_fast = ExponentialMovingAverage(config.fast_period)
        self.ema_slow = ExponentialMovingAverage(config.slow_period)
        self.prev_fast = self.prev_slow = None

    def on_start(self):
        self.register_indicator_for_bars(self.bar_type, self.ema_fast)
        self.register_indicator_for_bars(self.bar_type, self.ema_slow)
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar):
        if not (self.ema_fast.initialized and self.ema_slow.initialized):
            return

        fast, slow = self.ema_fast.value, self.ema_slow.value

        if self.prev_fast and self.prev_slow:
            # Bullish crossover
            if self.prev_fast <= self.prev_slow and fast > slow:
                if not self.portfolio.is_net_long(self.instrument_id):
                    self.close_all_positions(self.instrument_id)
                    order = self.order_factory.market(
                        instrument_id=self.instrument_id,
                        order_side=OrderSide.BUY,
                        quantity=self.trade_size,
                    )
                    self.submit_order(order)
            # Bearish crossover
            elif self.prev_fast >= self.prev_slow and fast < slow:
                self.close_all_positions(self.instrument_id)

        self.prev_fast, self.prev_slow = fast, slow

    def on_stop(self):
        self.close_all_positions(self.instrument_id)
```

## Backtest Setup

```python
from nautilus_trader.backtest.node import BacktestNode
from nautilus_trader.config import BacktestRunConfig, BacktestEngineConfig, BacktestVenueConfig, BacktestDataConfig

config = BacktestRunConfig(
    engine=BacktestEngineConfig(trader_id="BACKTESTER-001"),
    venues=[BacktestVenueConfig(
        name="BINANCE",
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        starting_balances=["100000 USDT"],
    )],
    data=[BacktestDataConfig(
        catalog_path="./catalog",
        data_cls=Bar,
        instrument_id="BTCUSDT.BINANCE",
    )],
    strategies=[EMACrossConfig(
        instrument_id="BTCUSDT.BINANCE",
        bar_type="BTCUSDT.BINANCE-1-MINUTE-LAST-EXTERNAL",
    )],
)

node = BacktestNode(configs=[config])
results = node.run()
```

## Live Trading Setup

```python
from nautilus_trader.live.node import TradingNode
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.adapters.binance.config import BinanceDataClientConfig, BinanceExecClientConfig

config = TradingNodeConfig(
    trader_id="TRADER-001",
    data_clients={"BINANCE": BinanceDataClientConfig(
        api_key=os.getenv("BINANCE_API_KEY"),
        api_secret=os.getenv("BINANCE_API_SECRET"),
        testnet=True,
    )},
    exec_clients={"BINANCE": BinanceExecClientConfig(
        api_key=os.getenv("BINANCE_API_KEY"),
        api_secret=os.getenv("BINANCE_API_SECRET"),
        testnet=True,
    )},
    strategies=[EMACrossConfig(instrument_id="BTCUSDT.BINANCE", ...)],
)

node = TradingNode(config=config)
node.build()
node.start()
```

## Signal Actor Pattern

```python
class TradingSignal(Data):
    def __init__(self, instrument_id, direction, strength, ts_event, ts_init):
        super().__init__()
        self.instrument_id = instrument_id
        self.direction = direction  # 1=long, -1=short
        self.strength = strength
        self.ts_event = ts_event
        self.ts_init = ts_init

class SignalGenerator(Actor):
    def on_bar(self, bar: Bar):
        signal = TradingSignal(...)
        self.publish_data(DataType(TradingSignal), signal)

class SignalFollower(Strategy):
    def on_start(self):
        self.subscribe_data(DataType(TradingSignal))

    def on_data(self, data):
        if isinstance(data, TradingSignal):
            if data.direction == 1 and data.strength > 0.5:
                # Go long
                pass
```
