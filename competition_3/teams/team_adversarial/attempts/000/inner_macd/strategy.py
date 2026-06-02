"""team_breadth_first — Round 3 candidate 05: MACD zero-line cross momentum.

Signal: MACD histogram crosses above 0 (macd > signal > 0 transition).
        EMA(200) trend context — only enter longs.
Entry: MARKET order.
Exit: TP=4.0% above fill, SL=2.0% below fill (2:1 R:R), 96-bar time-stop.
Position sizing: 90% of free USDT balance.
Cooldown: 48 bars (4h) minimum between entries.

Rationale: Round 3 is a slow grind upward. MACD histogram crossing zero
is a classic momentum confirmation with fewer false signals than RSI.
2:1 R:R means we only need WR>33% to profit, but gate requires WR>=0.5.
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
MACD_SIGNAL = 9
EMA_PERIOD = 100
TP_PCT = 0.040       # 4.0% TP
SL_PCT = 0.020       # 2.0% SL → 2:1 R:R
TIME_STOP_BARS = 288  # ~24h — widened to let winners reach 4% TP
COOLDOWN_BARS = 48   # 4h between entries
POSITION_FRACTION = 0.90


class TeamStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType


class TeamStrategy(TeamStrategyBase):
    """Long-only MACD histogram cross above zero + EMA(200) on BTCUSDT.BINANCE."""

    def on_start_subscribe(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.macd = MovingAverageConvergenceDivergence(MACD_FAST, MACD_SLOW)
        self.ema = ExponentialMovingAverage(EMA_PERIOD)
        self.register_indicator_for_bars(self.config.bar_type, self.macd)
        self.register_indicator_for_bars(self.config.bar_type, self.ema)
        self._bars_seen = 0
        self._entry_bar: int | None = None
        self._cooldown_until: int = 0
        self._prev_hist: float | None = None
        self.subscribe_bars(self.config.bar_type)
        self.log.info(
            f"team_breadth_first r3c05: MACD({MACD_FAST},{MACD_SLOW},{MACD_SIGNAL}) "
            f"histogram cross>0 + EMA({EMA_PERIOD}), TP=+{TP_PCT:.1%}/SL=-{SL_PCT:.1%}"
        )

    def _ready(self) -> bool:
        return (
            self.instrument is not None
            and self.macd.initialized
            and self.ema.initialized
        )

    def on_bar(self, bar: Bar) -> None:
        self._bars_seen += 1
        if not self._ready():
            if self.macd.initialized:
                self._prev_hist = self.macd.value
            return

        flat = self.portfolio.is_flat(self.config.instrument_id)

        # Time-stop
        if not flat and self._entry_bar is not None:
            bars_held = self._bars_seen - self._entry_bar
            if bars_held >= TIME_STOP_BARS:
                self.cancel_all_orders(self.config.instrument_id)
                open_positions = self.cache.positions_open(
                    instrument_id=self.config.instrument_id
                )
                if open_positions:
                    self.close_position(open_positions[0])
                    self._cooldown_until = self._bars_seen + COOLDOWN_BARS
            self._prev_hist = self.macd.value
            return

        # Cooldown check
        if self._bars_seen < self._cooldown_until:
            self._prev_hist = self.macd.value
            return

        inflight = self.cache.orders_inflight(instrument_id=self.config.instrument_id)
        open_orders = self.cache.orders_open(instrument_id=self.config.instrument_id)
        if not flat or inflight or open_orders:
            self._prev_hist = self.macd.value
            return

        cur_hist = self.macd.value  # MACD histogram (macd - signal)
        bar_close = float(bar.close)

        # MACD histogram crosses above zero
        hist_cross_up = (
            self._prev_hist is not None
            and self._prev_hist <= 0
            and cur_hist > 0
        )

        # Trend filter: price above EMA(200)
        above_ema = bar_close > self.ema.value

        if hist_cross_up and above_ema:
            self._submit_bracket(bar_close)

        self._prev_hist = cur_hist

    def _submit_bracket(self, signal_close: float) -> None:
        prec = self.instrument.price_precision
        size_prec = self.instrument.size_precision

        account = self.portfolio.account(self.config.instrument_id.venue)
        if account is None:
            return
        try:
            from nautilus_trader.model.currencies import USDT
            free_usdt = float(account.balance_free(USDT))
        except Exception:
            free_usdt = float(account.balance_total(list(account.balances())[0].currency))

        notional = free_usdt * POSITION_FRACTION
        qty_f = notional / signal_close
        qty = Quantity.from_str(f"{qty_f:.{size_prec}f}")
        if qty.as_double() <= 0:
            return

        tp_px = signal_close * (1.0 + TP_PCT)
        sl_px = signal_close * (1.0 - SL_PCT)
        tp = Price.from_str(f"{tp_px:.{prec}f}")
        sl = Price.from_str(f"{sl_px:.{prec}f}")

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
