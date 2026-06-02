"""team_balanced — Round 4: MACD histogram cross above zero + EMA(100) trend filter.

Round-4 window: 2026-04-29->05-20.
Signal: MACD histogram crosses from <=0 to >0 (momentum turn up), price > EMA(100).
Entry: MARKET bracket. TP=4%, SL=1.5%, TIME_STOP=288 bars, COOLDOWN=48 bars.

NO @dataclass on the msgspec StrategyConfig.
"""
from __future__ import annotations

from nautilus_trader.indicators import ExponentialMovingAverage, MovingAverageConvergenceDivergence
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, OrderType
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import StrategyConfig

from competition_3.shared.team_strategy_base import TeamStrategyBase

# --- strategy parameters ---
MACD_FAST = 12
MACD_SLOW = 26
EMA_PERIOD = 100
TP_PCT = 0.040
SL_PCT = 0.015
TIME_STOP_BARS = 288
COOLDOWN_BARS = 48
TRADE_NOTIONAL_USDT = 500.0


class TeamStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType


class TeamStrategy(TeamStrategyBase):
    """Long-only MACD histogram cross above zero + EMA(100) on BTC."""

    def on_start_subscribe(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.macd = MovingAverageConvergenceDivergence(MACD_FAST, MACD_SLOW)
        self.ema = ExponentialMovingAverage(EMA_PERIOD)
        self.register_indicator_for_bars(self.config.bar_type, self.macd)
        self.register_indicator_for_bars(self.config.bar_type, self.ema)
        self._bars_seen = 0
        self._entry_bar = None
        self._cooldown_until = 0
        self._prev_hist = None
        self.subscribe_bars(self.config.bar_type)
        self.log.info(
            f"team_balanced R4: MACD({MACD_FAST},{MACD_SLOW}) hist cross>0 + EMA({EMA_PERIOD}), "
            f"TP=+{TP_PCT:.1%}/SL=-{SL_PCT:.1%}, TIME_STOP={TIME_STOP_BARS}, COOL={COOLDOWN_BARS}"
        )

    def _ready(self) -> bool:
        return self.instrument is not None and self.macd.initialized and self.ema.initialized

    def on_bar(self, bar: Bar) -> None:
        self._bars_seen += 1
        if not self._ready():
            if self.macd.initialized:
                self._prev_hist = self.macd.value
            return

        flat = self.portfolio.is_flat(self.config.instrument_id)

        # Time-stop exit
        if not flat and self._entry_bar is not None:
            if self._bars_seen - self._entry_bar >= TIME_STOP_BARS:
                self.cancel_all_orders(self.config.instrument_id)
                positions = self.cache.positions_open(instrument_id=self.config.instrument_id)
                if positions:
                    self.close_position(positions[0])
                    self._cooldown_until = self._bars_seen + COOLDOWN_BARS
            self._prev_hist = self.macd.value
            return

        # Cooldown
        if self._bars_seen < self._cooldown_until:
            self._prev_hist = self.macd.value
            return

        inflight = self.cache.orders_inflight(instrument_id=self.config.instrument_id)
        open_orders = self.cache.orders_open(instrument_id=self.config.instrument_id)
        if not flat or inflight or open_orders:
            self._prev_hist = self.macd.value
            return

        cur_hist = self.macd.value

        # MACD histogram cross above zero + price above EMA(100)
        hist_cross_up = (self._prev_hist is not None and self._prev_hist <= 0 and cur_hist > 0)
        above_ema = float(bar.close) > self.ema.value

        if hist_cross_up and above_ema:
            self._submit_bracket(bar)

        self._prev_hist = cur_hist

    def _submit_bracket(self, bar: Bar) -> None:
        px = float(bar.close)
        prec = self.instrument.price_precision
        qty_f = TRADE_NOTIONAL_USDT / px
        qty = Quantity.from_str(f"{qty_f:.{self.instrument.size_precision}f}")
        if qty.as_double() <= 0:
            return
        tp = Price.from_str(f"{px * (1 + TP_PCT):.{prec}f}")
        sl = Price.from_str(f"{px * (1 - SL_PCT):.{prec}f}")
        bracket = self.order_factory.bracket(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=qty,
            entry_order_type=OrderType.MARKET,
            tp_price=tp,
            sl_trigger_price=sl,
        )
        self.submit_order_list(bracket)

    def on_position_opened(self, event) -> None:
        self._entry_bar = self._bars_seen

    def on_position_closed(self, event) -> None:
        super().on_position_closed(event)
        self._entry_bar = None
        self._cooldown_until = self._bars_seen + COOLDOWN_BARS
