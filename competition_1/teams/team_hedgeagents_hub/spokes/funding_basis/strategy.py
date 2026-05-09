"""
Basis sub-strategy: carry-proxy BB mean-reversion with ATR vol gate.

Proxy: Bollinger Band lower-band touch in low-ATR (quiet) regime, exit at middle band.
Structural analog to carry: collects small mean-reversion premia in calm regimes,
identical risk profile to short-vol / positive-carry positioning.

Look-ahead guard: indicators updated from completed bar H/L/C only. No deque slicing.
Long-only, no leverage, one position at a time.
"""

from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators import BollingerBands, AverageTrueRange
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


class BasisSubStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: str = "BTCUSDT.BINANCE"
    bar_type: str = "BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL"
    # Bollinger Band parameters
    bb_period: int = 20
    bb_k: float = 2.0
    # ATR vol filter
    atr_period: int = 14
    # ATR relative threshold: if ATR/close > this, skip entry (high-vol regime)
    atr_pct_threshold: float = 0.005  # 0.5% of price — flag for tuning post-eval
    # Risk caps from budget conference (round 0, iter 0)
    max_position_pct: float = 0.20
    stop_loss_pct: float = 0.01
    # Coordinator scalar — coordinator multiplies by w_basis
    target_basis: float = 0.70


class BasisSubStrategy(Strategy):
    """
    Carry-proxy: low-vol Bollinger Band mean-reversion.

    Proxy rationale: no funding tape or cross-venue basis available.
    The carry analog is collecting small mean-reversion premia in quiet
    regimes — identical risk profile to short-vol / positive-carry.

    Entry: close <= lower_bb AND ATR/close < atr_pct_threshold (quiet regime).
    Exit:  close >= middle_bb  OR  adverse move >= stop_loss_pct.
    Direction: long-only (spot, no leverage).
    One position at a time; flatten before any new entry.
    """

    def __init__(self, config: BasisSubStrategyConfig) -> None:
        super().__init__(config)
        self._instrument_id = InstrumentId.from_str(config.instrument_id)
        self._bar_type = BarType.from_str(config.bar_type)
        self._bb = BollingerBands(config.bb_period, config.bb_k)
        self._atr = AverageTrueRange(config.atr_period)
        self._entry_price: float | None = None
        self._in_position: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self._instrument_id)
        if self.instrument is None:
            self.log.error(f"[BASIS] Instrument {self._instrument_id} not found.")
            return
        self.subscribe_bars(self._bar_type)

    def on_stop(self) -> None:
        self._flatten("on_stop")

    # ------------------------------------------------------------------
    # Bar handler — strict no look-ahead: indicators fed only completed bars
    # ------------------------------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type != self._bar_type:
            return

        self._bb.update_raw(
            bar.high.as_double(),
            bar.low.as_double(),
            bar.close.as_double(),
        )
        self._atr.update_raw(
            bar.high.as_double(),
            bar.low.as_double(),
            bar.close.as_double(),
        )

        if not self._bb.initialized or not self._atr.initialized:
            return

        close = bar.close.as_double()
        lower_bb = self._bb.lower
        middle_bb = self._bb.middle
        atr_val = self._atr.value
        atr_pct = atr_val / close if close > 0 else 999.0
        high_vol = atr_pct > self.config.atr_pct_threshold

        # --- Stop-loss check (hardest rule, evaluated before entry) ---
        if self._in_position and self._entry_price is not None:
            adverse_move = (self._entry_price - close) / self._entry_price
            if adverse_move >= self.config.stop_loss_pct:
                self._flatten("stop_loss")
                return

        # --- Exit: price reverts to middle band ---
        if self._in_position and close >= middle_bb:
            self._flatten("mean_reversion_exit")
            return

        # --- Entry: lower band touch in quiet regime, flat only ---
        if not self._in_position and not high_vol and close <= lower_bb:
            self._enter_long(close, atr_pct)

    # ------------------------------------------------------------------
    # Order helpers
    # ------------------------------------------------------------------

    def _enter_long(self, close: float, atr_pct: float) -> None:
        account = self.portfolio.account(self._instrument_id.venue)
        if account is None:
            self.log.warning("[BASIS] No account found, skipping entry.")
            return
        equity = account.balance_total(USDT)
        if equity is None:
            self.log.warning("[BASIS] No USDT balance, skipping entry.")
            return
        equity_val = equity.as_double()
        notional = equity_val * self.config.max_position_pct
        qty_raw = notional / close
        qty = round(qty_raw, 3)
        if qty <= 0:
            return
        order = self.order_factory.market(
            instrument_id=self._instrument_id,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_str(f"{qty:.3f}"),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._entry_price = close
        self._in_position = True
        self.log.info(
            f"[BASIS] ENTER LONG qty={qty:.3f} @ ~{close:.2f} "
            f"notional={notional:.2f} atr_pct={atr_pct:.4f}"
        )

    def _flatten(self, reason: str) -> None:
        if not self._in_position:
            return
        positions = self.cache.positions_open(instrument_id=self._instrument_id)
        if not positions:
            self._in_position = False
            self._entry_price = None
            return
        for pos in positions:
            close_qty = pos.quantity
            if close_qty and close_qty.as_double() > 0:
                order = self.order_factory.market(
                    instrument_id=self._instrument_id,
                    order_side=OrderSide.SELL,
                    quantity=close_qty,
                    time_in_force=TimeInForce.GTC,
                )
                self.submit_order(order)
                self.log.info(f"[BASIS] FLATTEN reason={reason} qty={close_qty}")
        self._in_position = False
        self._entry_price = None
