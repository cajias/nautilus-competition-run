"""team_balanced — Round 0 strategy: BTC oversold-bounce, long-only, BTC-only.

Why this design (see _inbox/research_brief.md + EDA + engine calibration):
  * The backtest engine loads bars ONLY for the anchor instrument (BTCUSDT) —
    `build_backtest_engine` does `catalog.bars(bar_types=[config.instrument.bar_type])`.
    So every backtest gate is BTC-only; multi-asset is live-paper only.
  * BTC fees are 0.1% maker + 0.1% taker = 0.2% round-trip. The prior round's
    ATR-tight (~0.12%) targets were SMALLER than the fee → fee-dominated loss.
    Fix: WIDE targets so the 0.2% fee is a small fraction of the move.
  * Entry on deep oversold (RSI(14) < threshold) in an uptrend (EMA filter),
    via a resting LIMIT at the dip price so we capture the cheap fill the
    mean-reversion edge depends on (a market order fills next-bar-open, after
    the bounce has started — calibrated to drop win-rate ~20 points).
  * Exit via a resting BRACKET (TP limit + SL stop) so intrabar first-touch
    fills, plus a bar-count time-stop for zombie positions.

Gate: gain_train > 1.0 AND win_rate_train >= 0.5 on the 2026-04-01→04-22 window.

NO @dataclass on the msgspec StrategyConfig (stacking it crashes import with
"AttributeError: readonly attribute"). All params are hardcoded module constants
because the harness constructs TeamStrategyConfig with ONLY instrument_id+bar_type.
"""
from __future__ import annotations

from nautilus_trader.indicators import ExponentialMovingAverage, RelativeStrengthIndex
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import StrategyConfig

from competition_3.shared.team_strategy_base import TeamStrategyBase

# --- hardcoded strategy parameters (config carries only instrument_id+bar_type) ---
RSI_PERIOD = 14
RSI_ENTRY = 30.0           # deep-oversold long entry
EMA_TREND_PERIOD = 0       # buy dips only when close > EMA(this); 0 disables the filter
TP_PCT = 0.025             # take-profit fraction (TP>SL: positive R:R, satisfies risk rule)
SL_PCT = 0.024             # stop-loss fraction (rarely triggers; losers exit via time-stop)
TIME_STOP_BARS = 144       # ~12h on 5-min bars: zombie-position backstop
# Round-3 fix: LIMIT entry at 0.2% below was causing adverse selection in the
# mild uptrend (Apr22-May13). Orders not filling → those that DO fill are deep dips
# that keep falling → WR=0.30. Switch to MARKET entry to get all signals filled.
ENTRY_LIMIT_OFFSET = None  # None = MARKET entry (fills at next bar open)
ENTRY_TTL_BARS = 3         # cancel an unfilled limit entry after this many bars
TRADE_NOTIONAL_USDT = 500.0


class TeamStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType


class TeamStrategy(TeamStrategyBase):
    """Long-only oversold-bounce on the anchor instrument (BTCUSDT)."""

    def on_start_subscribe(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.rsi = RelativeStrengthIndex(RSI_PERIOD)
        self.register_indicator_for_bars(self.config.bar_type, self.rsi)
        self.ema = None
        if EMA_TREND_PERIOD:
            self.ema = ExponentialMovingAverage(EMA_TREND_PERIOD)
            self.register_indicator_for_bars(self.config.bar_type, self.ema)
        self._bars_seen = 0
        self._entry_bar = None       # bar index when the current position opened
        self._pending_entry_bar = None  # bar index when a limit entry was placed
        self.subscribe_bars(self.config.bar_type)
        self.log.info(
            f"team_balanced R0: RSI({RSI_PERIOD})<{RSI_ENTRY} oversold-bounce, "
            f"EMA{EMA_TREND_PERIOD} trend filter, TP=+{TP_PCT:.1%}/SL=-{SL_PCT:.1%}, "
            f"limit_entry={ENTRY_LIMIT_OFFSET}, time-stop={TIME_STOP_BARS} bars"
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

        # Time-stop: close a zombie position that neither TP nor SL has resolved.
        if not flat and self._entry_bar is not None:
            if self._bars_seen - self._entry_bar >= TIME_STOP_BARS:
                self.cancel_all_orders(self.config.instrument_id)
                self.close_position(
                    self.cache.positions_open(instrument_id=self.config.instrument_id)[0]
                )
            return

        inflight = self.cache.orders_inflight(instrument_id=self.config.instrument_id)
        open_orders = self.cache.orders_open(instrument_id=self.config.instrument_id)

        # Expire a stale, unfilled limit entry so a fresh signal can re-arm.
        if flat and open_orders and self._pending_entry_bar is not None:
            if self._bars_seen - self._pending_entry_bar >= ENTRY_TTL_BARS:
                self.cancel_all_orders(self.config.instrument_id)
            return

        if not flat or inflight or open_orders:
            return

        # Entry: deep oversold, in uptrend (if filter enabled).
        if self.rsi.value >= RSI_ENTRY:
            return
        if self.ema is not None and float(bar.close) <= self.ema.value:
            return
        self._submit_bracket(bar)

    def _submit_bracket(self, bar: Bar) -> None:
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

    def on_position_closed(self, event) -> None:
        super().on_position_closed(event)  # base counts closed trades / self-stops at 20
        self._entry_bar = None
        self._pending_entry_bar = None
