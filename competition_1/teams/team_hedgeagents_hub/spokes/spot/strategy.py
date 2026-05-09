"""
Spot sub-strategy: EMA(12) / EMA(48) crossover momentum on 5-min BTCUSDT bars.
Long/flat only. No look-ahead (on_bar fires on completed bar).
Complies with: Fast Trading... §2C, AI Agents... §B.
"""

from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


class SpotSubStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    # Sizing — within manager cap max_position_pct=0.50
    position_pct: float = 0.40
    # Stop — within manager cap stop_loss_pct=0.02
    stop_loss_pct: float = 0.018
    # EMA windows
    fast_period: int = 12   # ~1h on 5-min bars
    slow_period: int = 48   # ~4h on 5-min bars
    # Stale-long protection: exit after 24h of holding
    max_bars_in_position: int = 288
    # Target allocation scalar: coordinator multiplies by w_spot
    target_spot: float = 0.0


class SpotSubStrategy(Strategy):
    """
    EMA-crossover momentum strategy for BTCUSDT spot.

    Entry:  fast EMA(12) crosses above slow EMA(48) — buy.
    Exit:   fast EMA crosses below slow EMA — flatten.
    Stop:   hard stop at entry_price * (1 - stop_loss_pct).
    Guard:  max_bars_in_position exit to avoid stale longs.

    target_spot attribute (0.0 or 1.0) signals current allocation intent
    to the coordinator.
    """

    def __init__(self, config: SpotSubStrategyConfig) -> None:
        super().__init__(config)
        self._fast_ema = ExponentialMovingAverage(config.fast_period)
        self._slow_ema = ExponentialMovingAverage(config.slow_period)
        # One-bar lagged values for crossing detection (no look-ahead)
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None
        # Position tracking
        self._position_qty: float = 0.0
        self._entry_price: float | None = None
        self._bars_in_position: int = 0
        # Public scalar for coordinator
        self.target_spot: float = 0.0

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        self.register_indicator_for_bars(self.config.bar_type, self._fast_ema)
        self.register_indicator_for_bars(self.config.bar_type, self._slow_ema)
        self.subscribe_bars(self.config.bar_type)

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        self.close_all_positions(self.config.instrument_id)

    def on_bar(self, bar: Bar) -> None:
        # Indicators update on each bar automatically after registration.
        # Gate: both must be initialised before we act.
        if not (self._fast_ema.initialized and self._slow_ema.initialized):
            return

        fast = self._fast_ema.value
        slow = self._slow_ema.value
        close = float(bar.close)

        # Detect crossings using one-bar lag; skip if no prior values yet.
        if self._prev_fast is not None and self._prev_slow is not None:
            crossed_up = (self._prev_fast <= self._prev_slow) and (fast > slow)
            crossed_dn = (self._prev_fast >= self._prev_slow) and (fast < slow)

            # --- Stop-loss check (before signal evaluation) ---
            if self._position_qty > 0.0 and self._entry_price is not None:
                if close <= self._entry_price * (1.0 - self.config.stop_loss_pct):
                    self._flatten()
                    self._save_lags(fast, slow)
                    return

            # --- Max-duration guard ---
            if self._position_qty > 0.0:
                self._bars_in_position += 1
                if self._bars_in_position >= self.config.max_bars_in_position:
                    self._flatten()
                    self._save_lags(fast, slow)
                    return

            # --- Signal-driven entry / exit ---
            if crossed_up and self._position_qty == 0.0:
                self._enter_long(close)
            elif crossed_dn and self._position_qty > 0.0:
                self._flatten()

        self._save_lags(fast, slow)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save_lags(self, fast: float, slow: float) -> None:
        self._prev_fast = fast
        self._prev_slow = slow

    def _get_equity(self) -> float:
        venue = self.config.instrument_id.venue
        try:
            account = self.portfolio.account(venue)
            return float(account.balance_total(USDT).as_double())
        except Exception:
            return 1000.0  # fallback to starting equity

    def _enter_long(self, price: float) -> None:
        equity = self._get_equity()
        notional = equity * self.config.position_pct
        btc_qty = notional / price
        btc_qty = max(round(btc_qty, 3), 0.001)
        qty = Quantity.from_str(f"{btc_qty:.3f}")
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._entry_price = price
        self._position_qty = btc_qty
        self._bars_in_position = 0
        self.target_spot = 1.0

    def _flatten(self) -> None:
        self.close_all_positions(self.config.instrument_id)
        self._position_qty = 0.0
        self._entry_price = None
        self._bars_in_position = 0
        self.target_spot = 0.0
