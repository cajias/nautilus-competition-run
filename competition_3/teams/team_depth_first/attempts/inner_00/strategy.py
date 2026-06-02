"""team_depth_first — inner_00 (Iteration 6)

Strategy: N-bar Breakout — exact team_completeness pass params as starting point.

team_completeness iter000 passed with: gain=1.000081, WR=0.5, 5 trades using:
- LR(30) slope > 0.0001
- EMA(40) price_above_ema (no margin)
- Breakout: 12 bars
- TP=2.5%, SL=1.0%
- max_hold=30 bars, cooldown=3

Depth-first refinement starting point: reproduce that pass, then improve.
This iteration: exact same as team_completeness000 to confirm reproducibility.
"""
from __future__ import annotations

from collections import deque

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId

from nautilus_trader.indicators import LinearRegression, ExponentialMovingAverage

from competition_3.shared.team_strategy_base import TeamStrategyBase

try:
    from nautilus_trader.config import StrategyConfig
except ImportError:
    from nautilus_trader.trading.config import StrategyConfig


class TeamStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    lr_period: int = 30
    ema_period: int = 40
    breakout_period: int = 12
    min_lr_slope: float = 0.0001
    cooldown_bars: int = 3
    take_profit_pct: float = 0.025
    stop_loss_pct: float = 0.010
    max_hold_bars: int = 30
    max_hold_bars: int = 40
    trade_size: float = 0.001


class TeamStrategy(TeamStrategyBase):
    def __init__(self, config: TeamStrategyConfig) -> None:
        super().__init__(config)

        self.lr = LinearRegression(config.lr_period)
        self.ema = ExponentialMovingAverage(config.ema_period)

        self._close_history: deque[float] = deque(maxlen=config.breakout_period + 1)

        self._position_side: str | None = None
        self._tp_price: float | None = None
        self._sl_price: float | None = None
        self._bars_in_trade: int = 0
        self._bars_since_last_trade: int = 0

    def on_start_subscribe(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.config.instrument_id} not found in cache")
            self.stop()
            return
        self.register_indicator_for_bars(self.config.bar_type, self.lr)
        self.register_indicator_for_bars(self.config.bar_type, self.ema)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        close_price = float(bar.close)
        self._close_history.append(close_price)

        if not (self.lr.initialized and self.ema.initialized):
            return

        if len(self._close_history) < self.config.breakout_period + 1:
            return

        lr_slope = self.lr.slope
        ema_val = self.ema.value

        # --- Manage open position ---
        if self._position_side is not None:
            self._bars_in_trade += 1

            if self._position_side == "long":
                hit_tp = close_price >= self._tp_price
                hit_sl = close_price <= self._sl_price
            else:
                hit_tp = close_price <= self._tp_price
                hit_sl = close_price >= self._sl_price

            hit_time = self._bars_in_trade >= self.config.max_hold_bars

            if hit_tp or hit_sl or hit_time:
                self._close_position()
                self._bars_since_last_trade = 0
            return

        # --- Entry logic ---
        self._bars_since_last_trade += 1
        if self._bars_since_last_trade < self.config.cooldown_bars:
            return

        lr_uptrend = lr_slope > self.config.min_lr_slope
        lr_downtrend = lr_slope < -self.config.min_lr_slope
        price_above_ema = close_price > ema_val
        price_below_ema = close_price < ema_val

        prev_closes = list(self._close_history)[:-1]
        prev_high = max(prev_closes)
        prev_low = min(prev_closes)

        long_signal = close_price > prev_high and lr_uptrend and price_above_ema
        short_signal = close_price < prev_low and lr_downtrend and price_below_ema

        if long_signal:
            self._enter_long(close_price)
            self._bars_since_last_trade = 0
        elif short_signal:
            self._enter_short(close_price)
            self._bars_since_last_trade = 0

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

    def _enter_short(self, price: float) -> None:
        qty = self.instrument.make_qty(self.config.trade_size)
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._position_side = "short"
        self._tp_price = price * (1 - self.config.take_profit_pct)
        self._sl_price = price * (1 + self.config.stop_loss_pct)
        self._bars_in_trade = 0

    def _close_position(self) -> None:
        if self._position_side == "long":
            qty = self.instrument.make_qty(self.config.trade_size)
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.SELL,
                quantity=qty,
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
        elif self._position_side == "short":
            qty = self.instrument.make_qty(self.config.trade_size)
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.BUY,
                quantity=qty,
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
        self._position_side = None
        self._tp_price = None
        self._sl_price = None
        self._bars_in_trade = 0
