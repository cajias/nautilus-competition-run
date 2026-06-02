"""team_depth_first — iter_013 (BEST ROUND 2 CANDIDATE)

Strategy: RSI(14)<30 dip-buy + EMA(80) trend filter + RSI exit at 55.

Depth-first refinement result — round 2 train window (Apr 15 - May 6, 2026).

DISCOVERY:
- Baseline 000 (RSI<30 LIMIT entry): gain=1.001247, WR=0.40 → FAIL
- RSI recovery exit (iter_012): gain=1.002128, WR=0.50 → PASS
- RSI recovery exit + SL widened to 3.5%: gain=1.003369, WR=0.60 → PASS
- RSI recovery exit + EMA80 filter: gain=1.004285, WR=0.684 → BEST

KEY INSIGHT:
EMA(80) = 400 minutes = 6.67 hours. This period captures the medium-term
trend in the Apr 15 - May 6 BTC window. Requiring price above EMA(80) filters
out dip entries during deeper corrections, selecting only pullbacks within
the primary uptrend. Result: WR jumps from 0.60 to 0.684.

Parameters (confirmed by sweep):
- rsi_period=14, rsi_oversold=30.0 (standard)
- ema_period=80 (KEY: medium-term trend filter)
- rsi_exit=55 (exit when RSI recovers to neutral/bullish zone)
- take_profit_pct=8% (backstop only — RSI exit fires first)
- stop_loss_pct=4% (backstop only — RSI exit fires first)
- max_hold_bars=288 (24h backstop)
- cooldown_bars=3

TRAIN RESULT: gain=1.004285, win_rate=0.684211, num_trades=38(19closed), pass=True
COMPOSITE: 1.004285 × 0.684 = 0.6869 (well above gate of 0.5)
"""
from __future__ import annotations

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId

from nautilus_trader.indicators import RelativeStrengthIndex, ExponentialMovingAverage

from competition_3.shared.team_strategy_base import TeamStrategyBase

try:
    from nautilus_trader.config import StrategyConfig
except ImportError:
    from nautilus_trader.trading.config import StrategyConfig


class TeamStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    rsi_period: int = 14
    rsi_oversold: float = 30.0          # RSI entry threshold
    rsi_exit: float = 55.0             # RSI recovery exit level
    ema_period: int = 80               # trend filter (6.67h on 5-min bars)
    take_profit_pct: float = 0.080     # 8% backstop TP
    stop_loss_pct: float = 0.040       # 4% backstop SL
    max_hold_bars: int = 288           # 24h time-stop backstop
    cooldown_bars: int = 3
    trade_size: float = 0.001


class TeamStrategy(TeamStrategyBase):
    def __init__(self, config: TeamStrategyConfig) -> None:
        super().__init__(config)
        self.rsi = RelativeStrengthIndex(config.rsi_period)
        self.ema = ExponentialMovingAverage(config.ema_period)

        self._position_side: str | None = None
        self._tp_price: float | None = None
        self._sl_price: float | None = None
        self._bars_in_trade: int = 0
        self._cooldown_remaining: int = 0

    def on_start_subscribe(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.config.instrument_id} not found in cache")
            self.stop()
            return
        self.register_indicator_for_bars(self.config.bar_type, self.rsi)
        self.register_indicator_for_bars(self.config.bar_type, self.ema)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if not (self.rsi.initialized and self.ema.initialized):
            return

        close = float(bar.close)
        curr_rsi = self.rsi.value

        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

        if self._position_side is not None:
            self._bars_in_trade += 1
            # Primary exit: RSI recovery to neutral/bullish
            rsi_recovered = curr_rsi >= self.config.rsi_exit
            # Backstop exits
            hit_tp = close >= self._tp_price
            hit_sl = close <= self._sl_price
            hit_time = self._bars_in_trade >= self.config.max_hold_bars

            if rsi_recovered or hit_tp or hit_sl or hit_time:
                self._close_position()
            return

        # Entry: RSI oversold + price above EMA80 (in uptrend)
        if (self._cooldown_remaining <= 0
                and curr_rsi < self.config.rsi_oversold
                and close > self.ema.value):
            self._enter_long(close)

    def _enter_long(self, price: float) -> None:
        qty = self.instrument.make_qty(self.config.trade_size)
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._position_side = "long"
        self._tp_price = price * (1 + self.config.take_profit_pct)
        self._sl_price = price * (1 - self.config.stop_loss_pct)
        self._bars_in_trade = 0

    def _close_position(self) -> None:
        qty = self.instrument.make_qty(self.config.trade_size)
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._position_side = None
        self._tp_price = None
        self._sl_price = None
        self._bars_in_trade = 0
        self._cooldown_remaining = self.config.cooldown_bars
