"""team_depth_first — inner_00 (Iteration 2)

Strategy: RSI Dip-Buy with tight EMA trend filter + ATR volatility gate.

Changes from iter1: tighten RSI threshold to 25 (deeper dip), add ATR(14)
minimum filter to avoid entering during flat/compression periods.

Signal logic:
- EMA(50) for trend direction filter (price > EMA = bullish bias)
- RSI(14) for mean-reversion entry (below 25 = deeply oversold)
- ATR(14) > min_atr_pct of price (volatility confirmation)
- Entry: market BUY when RSI < 25 AND close > EMA AND ATR > min threshold
- Exit: TP=2.5%, SL=1.5%, time-stop=24 bars (2hr)

Fee awareness: TP=2.5% >> 0.2% round-trip fee (12.5x ratio).
"""
from __future__ import annotations

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId

from nautilus_trader.indicators import RelativeStrengthIndex, ExponentialMovingAverage, AverageTrueRange

from competition_3.shared.team_strategy_base import TeamStrategyBase

try:
    from nautilus_trader.config import StrategyConfig
except ImportError:
    from nautilus_trader.trading.config import StrategyConfig


class TeamStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    rsi_period: int = 14
    ema_period: int = 50
    atr_period: int = 14
    rsi_oversold: float = 25.0       # tighter: deeply oversold only
    min_atr_pct: float = 0.003       # ATR must be > 0.3% of price (volatility gate)
    take_profit_pct: float = 0.025   # 2.5%
    stop_loss_pct: float = 0.015     # 1.5%
    max_hold_bars: int = 24          # time-stop: 24 x 5min = 2 hours
    cooldown_bars: int = 3
    trade_size: float = 0.001


class TeamStrategy(TeamStrategyBase):
    def __init__(self, config: TeamStrategyConfig) -> None:
        super().__init__(config)

        self.rsi = RelativeStrengthIndex(config.rsi_period)
        self.ema = ExponentialMovingAverage(config.ema_period)
        self.atr = AverageTrueRange(config.atr_period)

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
        self.register_indicator_for_bars(self.config.bar_type, self.rsi)
        self.register_indicator_for_bars(self.config.bar_type, self.ema)
        self.register_indicator_for_bars(self.config.bar_type, self.atr)
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if not (self.rsi.initialized and self.ema.initialized and self.atr.initialized):
            return

        close_price = float(bar.close)
        rsi_val = self.rsi.value
        ema_val = self.ema.value
        atr_val = self.atr.value

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

        # Dip-buy: RSI deeply oversold AND price above EMA (uptrend bias) AND ATR volatile
        rsi_dip = rsi_val < self.config.rsi_oversold
        price_in_uptrend = close_price > ema_val
        atr_active = atr_val > close_price * self.config.min_atr_pct

        if rsi_dip and price_in_uptrend and atr_active:
            self._enter_long(close_price)
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
        self._position_side = None
        self._tp_price = None
        self._sl_price = None
        self._bars_in_trade = 0
