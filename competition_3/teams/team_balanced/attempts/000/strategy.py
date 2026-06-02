"""team_balanced — Round 3 strategy: BTC oversold-bounce with RSI-exit, long-only, BTC-only.

Round-3 window: 2026-04-22→05-13 (+5.49% uptrend, drops Apr22-29 then rallies May1-12).

Key improvements over Round-2:
  * MARKET entry (not LIMIT) — in this window, LIMIT at -0.2% causes adverse selection;
    those that fill are the ones that drop further. WR=0.30 with LIMIT → 0.50+ with MARKET.
  * RSI-based exit (close when RSI recovers to RSI_EXIT threshold) instead of fixed TP/SL.
    Round-2 best: RSI<30 entry + RSI>55 exit gave gain=1.004, WR=0.684.
  * EMA80 trend filter: only enter when close > EMA(80) (uptrend confirmation).
  * Fallback TP/SL bracket still placed but RSI exit fires first in recovery.

Gate: gain_train > 1.0 AND win_rate_train >= 0.5 on the 2026-04-22→05-13 window.

NO @dataclass on the msgspec StrategyConfig.
"""
from __future__ import annotations

from nautilus_trader.indicators import ExponentialMovingAverage, RelativeStrengthIndex
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import StrategyConfig

from competition_3.shared.team_strategy_base import TeamStrategyBase

# --- hardcoded strategy parameters ---
RSI_PERIOD = 14
RSI_ENTRY = 30.0           # deep-oversold long entry (RSI < this)
RSI_EXIT = 55.0            # RSI-based exit: close position when RSI recovers to this
EMA_TREND_PERIOD = 80      # enter only when close > EMA(80) — uptrend filter
TP_PCT = 0.030             # fallback bracket TP (if RSI exit doesn't fire)
SL_PCT = 0.025             # fallback bracket SL
TIME_STOP_BARS = 144       # ~12h zombie-position backstop
ENTRY_LIMIT_OFFSET = None  # None = MARKET entry (no adverse selection in uptrend)
ENTRY_TTL_BARS = 3
TRADE_NOTIONAL_USDT = 500.0


class TeamStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType


class TeamStrategy(TeamStrategyBase):
    """Long-only oversold-bounce with RSI-based exit on BTC (anchor instrument)."""

    def on_start_subscribe(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.rsi = RelativeStrengthIndex(RSI_PERIOD)
        self.register_indicator_for_bars(self.config.bar_type, self.rsi)
        self.ema = None
        if EMA_TREND_PERIOD:
            self.ema = ExponentialMovingAverage(EMA_TREND_PERIOD)
            self.register_indicator_for_bars(self.config.bar_type, self.ema)
        self._bars_seen = 0
        self._entry_bar = None
        self._pending_entry_bar = None
        self._position_open = False
        self.subscribe_bars(self.config.bar_type)
        self.log.info(
            f"team_balanced R3: RSI({RSI_PERIOD})<{RSI_ENTRY} entry, RSI>{RSI_EXIT} exit, "
            f"EMA{EMA_TREND_PERIOD} trend filter, TP=+{TP_PCT:.1%}/SL=-{SL_PCT:.1%}, "
            f"MARKET entry"
        )

    def _ready(self) -> bool:
        if not self.rsi.initialized or self.instrument is None:
            return False
        if self.ema is not None and not self.ema.initialized:
            return False
        return True

    def on_bar(self, bar: Bar) -> None:
        self._bars_seen += 1
        if not self._ready():
            return

        flat = self.portfolio.is_flat(self.config.instrument_id)

        # RSI-based exit: close when RSI recovers (overrides bracket exit)
        if not flat and self._position_open:
            if self.rsi.value >= RSI_EXIT:
                self.cancel_all_orders(self.config.instrument_id)
                positions = self.cache.positions_open(instrument_id=self.config.instrument_id)
                if positions:
                    self.close_position(positions[0])
                return

            # Time-stop: zombie position backstop
            if self._entry_bar is not None:
                if self._bars_seen - self._entry_bar >= TIME_STOP_BARS:
                    self.cancel_all_orders(self.config.instrument_id)
                    positions = self.cache.positions_open(instrument_id=self.config.instrument_id)
                    if positions:
                        self.close_position(positions[0])
                return
            return

        inflight = self.cache.orders_inflight(instrument_id=self.config.instrument_id)
        open_orders = self.cache.orders_open(instrument_id=self.config.instrument_id)

        # Expire stale limit entry
        if flat and open_orders and self._pending_entry_bar is not None:
            if self._bars_seen - self._pending_entry_bar >= ENTRY_TTL_BARS:
                self.cancel_all_orders(self.config.instrument_id)
            return

        if not flat or inflight or open_orders:
            return

        # Entry: deep oversold + uptrend filter
        if self.rsi.value >= RSI_ENTRY:
            return
        if self.ema is not None and float(bar.close) <= self.ema.value:
            return
        self._submit_entry(bar)

    def _submit_entry(self, bar: Bar) -> None:
        px = float(bar.close)
        prec = self.instrument.price_precision
        if ENTRY_LIMIT_OFFSET is None:
            entry_px = px
            entry_type = OrderType.MARKET
        else:
            entry_px = px * (1 - ENTRY_LIMIT_OFFSET)
            entry_type = OrderType.LIMIT
        qty_f = TRADE_NOTIONAL_USDT / entry_px
        qty = Quantity.from_str(f"{qty_f:.{self.instrument.size_precision}f}")
        if qty.as_double() <= 0:
            return

        # Place a simple market order (RSI exit will handle the close)
        # Use bracket with wide TP/SL as safety net only
        tp = Price.from_str(f"{entry_px * (1 + TP_PCT):.{prec}f}")
        sl = Price.from_str(f"{entry_px * (1 - SL_PCT):.{prec}f}")
        kwargs = dict(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=qty,
            entry_order_type=entry_type,
            tp_price=tp,
            sl_trigger_price=sl,
        )
        if entry_type == OrderType.LIMIT:
            kwargs["entry_price"] = Price.from_str(f"{entry_px:.{prec}f}")
            kwargs["time_in_force"] = TimeInForce.GTC
        bracket = self.order_factory.bracket(**kwargs)
        self.submit_order_list(bracket)
        self._pending_entry_bar = self._bars_seen

    def on_position_opened(self, event) -> None:
        self._entry_bar = self._bars_seen
        self._pending_entry_bar = None
        self._position_open = True

    def on_position_closed(self, event) -> None:
        super().on_position_closed(event)
        self._entry_bar = None
        self._pending_entry_bar = None
        self._position_open = False
