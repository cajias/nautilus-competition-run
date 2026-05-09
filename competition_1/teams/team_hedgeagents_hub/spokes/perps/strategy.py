"""
Perps spoke — synthetic-funding-proxy mean-reversion strategy.

Proxy: realized-vol regime (std of 20-bar log-returns on 5m spot closes) stands in
for elevated perp-funding environments. In high-vol windows the strategy fades
downside overshoots (z < -threshold) long-only, exiting when price reverts to or
above the rolling mean. No short positions; spot venue is long-or-flat only.

Authority: Fast Trading on Binance with NautilusTrader §2B (Tier 2B).
Reference: arXiv:2502.13165 HedgeAgents §C (hub-and-spoke isolation).
"""

from __future__ import annotations

import collections
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

import numpy as np

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.datetime import unix_nanos_to_dt
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy


@dataclass
class PerpsMeanReversionStrategyConfig(StrategyConfig):
    instrument_id: str = "BTCUSDT.BINANCE"
    bar_type: str = "BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL"

    # Budget / sizing
    target_perps: float = 1.0          # spoke request [0,1]; coordinator * w_perps
    w_perps: float = 0.25              # from budget conference
    max_position_pct: float = 0.30     # manager cap; non-binding at w=0.25
    stop_loss_pct: float = 0.015       # manager cap — 1.5 %
    max_leverage: float = 1.0          # effective leverage on spot venue

    # Signal windows
    z_window: int = 20                 # bars for rolling mean/std and realized vol
    z_entry_threshold: float = 1.8     # |z| > 1.8 on DOWNSIDE triggers long entry
    z_exit_threshold: float = 0.0      # z >= 0 → exit (mean or above → take profit)
    vol_low_threshold: float = 0.0013  # realized vol per bar (~30% ann on 5m bars)

    # Risk
    time_stop_bars: int = 12           # ~60 minutes
    sleeve_dd_suspend_pct: float = 0.10  # suspend sleeve at 10% cumulative DD


class PerpsMeanReversionStrategy(Strategy):
    """
    Realized-vol-gated long-fade mean-reversion for the perps sleeve.

    Signal logic:
      - Regime ON  : realized_vol_20 > vol_low_threshold
      - Entry BUY  : regime ON  AND  z_score < -z_entry_threshold  AND  flat
      - Exit  SELL : z_score >= z_exit_threshold  OR  hard stop  OR  time stop
      - No short entries; SELL orders close existing longs only.
    """

    def __init__(self, config: PerpsMeanReversionStrategyConfig) -> None:
        super().__init__(config)
        self._instrument_id = InstrumentId.from_str(config.instrument_id)
        self._bar_type = BarType.from_str(config.bar_type)

        self._closes: collections.deque[float] = collections.deque(
            maxlen=config.z_window + 1
        )
        self._prev_close: Optional[float] = None

        # Position tracking
        self._in_position: bool = False
        self._entry_price: float = 0.0
        self._entry_qty: float = 0.0
        self._bars_held: int = 0

        # Sleeve-level drawdown tracking
        self._sleeve_peak_equity: float = 0.0
        self._cumulative_dd_pct: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self._instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self._instrument_id} not found in cache.")
            return
        self.subscribe_bars(self._bar_type)

    def on_stop(self) -> None:
        self.unsubscribe_bars(self._bar_type)
        self._close_all_longs()

    # ------------------------------------------------------------------
    # Bar handler
    # ------------------------------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        cfg: PerpsMeanReversionStrategyConfig = self.config

        # --- 1. Update lagged-close buffer -----------------------------------
        # _prev_close holds the close of the bar that JUST completed.
        # Signals are always computed from _prev_close and the deque — never
        # from bar.close (which is the live/arriving bar, not yet confirmed).
        if self._prev_close is not None:
            self._closes.append(self._prev_close)

        self._prev_close = float(bar.close)  # store for use in NEXT on_bar call

        if len(self._closes) < cfg.z_window:
            return  # warm-up: insufficient history

        # --- 2. Compute signals from confirmed history (no look-ahead) --------
        # list(deque) produces a copy; [:-1] is not needed because the deque
        # was populated with prev_close values only (bar.close not included).
        window = list(self._closes)  # length z_window to z_window+1
        mean = float(np.mean(window))
        std = float(np.std(window))
        if std == 0.0:
            return

        log_rets = np.diff(np.log(window))
        realized_vol = float(np.std(log_rets)) if len(log_rets) > 1 else 0.0

        z = (self._prev_close - mean) / std

        # --- 3. Sleeve drawdown tracking & suspension -------------------------
        equity = float(self.portfolio.net_exposure(self._instrument_id) or 0.0)
        account = self.portfolio.account(self.instrument.venue)
        total_equity = (
            float(account.balance_total().as_double())
            if account is not None
            else 1000.0
        )

        if self._sleeve_peak_equity < total_equity:
            self._sleeve_peak_equity = total_equity

        if self._sleeve_peak_equity > 0:
            self._cumulative_dd_pct = max(
                0.0,
                (self._sleeve_peak_equity - total_equity) / self._sleeve_peak_equity,
            )

        if self._cumulative_dd_pct >= cfg.sleeve_dd_suspend_pct:
            self._close_all_longs()
            self.log.warning(
                f"Sleeve suspended: cumulative DD {self._cumulative_dd_pct:.2%} "
                f">= {cfg.sleeve_dd_suspend_pct:.2%}"
            )
            return

        # --- 4. In-position risk management -----------------------------------
        if self._in_position:
            self._bars_held += 1
            current_price = self._prev_close

            # Hard stop
            if current_price < self._entry_price * (1.0 - cfg.stop_loss_pct):
                self.log.info(
                    f"Hard stop triggered: entry={self._entry_price:.2f} "
                    f"current={current_price:.2f}"
                )
                self._close_all_longs()
                return

            # Time stop
            if self._bars_held >= cfg.time_stop_bars:
                self.log.info(f"Time stop: held {self._bars_held} bars")
                self._close_all_longs()
                return

            # Mean-reversion exit: z reverted to mean or above
            if z >= cfg.z_exit_threshold:
                self.log.info(f"Mean-reversion exit: z={z:.3f}")
                self._close_all_longs()
                return

        # --- 5. Entry: long-only fade on oversold + high-vol regime -----------
        if not self._in_position:
            if realized_vol > cfg.vol_low_threshold and z < -cfg.z_entry_threshold:
                qty = self._compute_qty(total_equity, cfg)
                if qty > 0:
                    self._submit_long(qty)
                    self.log.info(
                        f"Long fade entry: z={z:.3f} vol={realized_vol:.5f} qty={qty:.6f}"
                    )

    # ------------------------------------------------------------------
    # Order helpers
    # ------------------------------------------------------------------

    def _compute_qty(
        self, total_equity: float, cfg: PerpsMeanReversionStrategyConfig
    ) -> float:
        if self._prev_close is None or self._prev_close <= 0:
            return 0.0
        # Gross exposure = min(target * w_perps, max_position_pct) * equity
        gross_fraction = min(cfg.target_perps * cfg.w_perps, cfg.max_position_pct)
        notional = gross_fraction * total_equity
        qty = notional / self._prev_close
        # Clamp to instrument minimum quantity
        if self.instrument is not None:
            min_qty = float(self.instrument.size_increment)
            qty = max(math.floor(qty / min_qty) * min_qty, 0.0)
        return qty

    def _submit_long(self, qty: float) -> None:
        if qty <= 0:
            return
        order = self.order_factory.market(
            instrument_id=self._instrument_id,
            order_side=OrderSide.BUY,
            quantity=Quantity.from_str(f"{qty:.8f}"),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._in_position = True
        self._entry_price = self._prev_close or 0.0
        self._entry_qty = qty
        self._bars_held = 0

    def _close_all_longs(self) -> None:
        if not self._in_position:
            return
        if self.instrument is None:
            return
        qty = self._entry_qty
        if qty <= 0:
            self._in_position = False
            return
        order = self.order_factory.market(
            instrument_id=self._instrument_id,
            order_side=OrderSide.SELL,
            quantity=Quantity.from_str(f"{qty:.8f}"),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._in_position = False
        self._entry_price = 0.0
        self._entry_qty = 0.0
        self._bars_held = 0

    # ------------------------------------------------------------------
    # target_perps accessor (coordinator reads this)
    # ------------------------------------------------------------------

    @property
    def target_perps(self) -> float:
        return self.config.target_perps
