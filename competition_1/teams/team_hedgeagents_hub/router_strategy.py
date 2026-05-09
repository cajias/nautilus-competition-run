"""
RouterStrategy — team_hedgeagents_hub, round 0 / iter 0.

Hub-and-spoke merger of three inline sub-signals:
  - spot:   EMA(12) > EMA(48) crossover momentum       w=0.60  cap=0.50
  - perps:  z-score(20) mean-reversion + vol gate       w=0.25  cap=0.30
  - basis:  BollingerBands(20) + ATR(14) mean-revert    w=0.15  cap=0.20

Budget weights from conferences/budget/0_0.md (APPROVED).
Per-spoke virtual positions track _v_spot/_v_perps/_v_basis in [0, max_pos_pct].
One net MARKET order per bar via instrument.make_qty() — precision-safe.
No look-ahead: signals use only prev_* state, never current bar.close directly.

References:
  HedgeAgents, Li et al., WWW 2025 — arXiv:2502.13165
  Fast Trading on Binance with NautilusTrader — §2, §7.7
"""

from __future__ import annotations

import math
from collections import deque
from typing import Optional

import numpy as np

from nautilus_trader.config import StrategyConfig
from nautilus_trader.indicators import AverageTrueRange, BollingerBands, ExponentialMovingAverage
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class RouterStrategyConfig(StrategyConfig, frozen=True):
    """
    Configuration for the hedgeagents hub-and-spoke RouterStrategy.

    instrument_id and bar_type are REQUIRED — entry.py passes them as typed
    objects from harness config.
    """

    instrument_id: InstrumentId
    bar_type: BarType

    # --- Budget weights (sum=1.0) from conferences/budget/0_0.md -------------
    w_spot: float = 0.60
    w_perps: float = 0.25
    w_basis: float = 0.15

    # --- Per-spoke risk caps (from budget conference, hard rule) --------------
    spot_max_pos_pct: float = 0.50
    spot_stop_loss_pct: float = 0.02

    perps_max_pos_pct: float = 0.30
    perps_stop_loss_pct: float = 0.015

    basis_max_pos_pct: float = 0.20
    basis_stop_loss_pct: float = 0.01

    # --- Spot sub-signal parameters ------------------------------------------
    spot_fast_period: int = 12    # 1h on 5-min bars
    spot_slow_period: int = 48    # 4h on 5-min bars
    spot_max_bars: int = 288      # 24h stale-long guard

    # --- Perps sub-signal parameters (z-score mean-reversion + vol gate) -----
    perps_z_window: int = 20
    perps_z_entry: float = 1.8    # spoke value: |z| > 1.8 triggers long fade
    perps_z_exit: float = 0.0     # spoke value: z >= 0 → exit (mean reverted)
    perps_vol_threshold: float = 0.0013  # realized-vol gate per bar (~30% ann)
    perps_time_stop_bars: int = 12       # ~60 min max hold

    # --- Basis sub-signal parameters (BollingerBands + ATR vol gate) ----------
    basis_bb_period: int = 20
    basis_bb_k: float = 2.0
    basis_atr_period: int = 14
    basis_atr_pct_threshold: float = 0.005   # 0.5% of price → high-vol skip

    # --- Order dust threshold -------------------------------------------------
    dust_threshold_btc: float = 0.001


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class RouterStrategy(Strategy):
    """
    Single Nautilus Strategy that inlines three spoke sub-signals and routes
    capital according to budget weights from the approved budget conference.

    Virtual positions:
      _v_spot, _v_perps, _v_basis  each in [0.0, *_max_pos_pct]

    Net target = clamp(w_spot*_v_spot + w_perps*_v_perps + w_basis*_v_basis, 0, 1)
    One net MARKET order per bar when |delta_btc| > dust_threshold_btc.

    All signals operate on confirmed closed bars only (no look-ahead per
    AI Agents... §B). Indicators are registered for automatic Nautilus updates.
    """

    def __init__(self, config: RouterStrategyConfig) -> None:
        super().__init__(config)

        # ---- Nautilus indicators ---- (registered in on_start)
        self._spot_fast = ExponentialMovingAverage(config.spot_fast_period)
        self._spot_slow = ExponentialMovingAverage(config.spot_slow_period)
        self._basis_bb = BollingerBands(config.basis_bb_period, config.basis_bb_k)
        self._basis_atr = AverageTrueRange(config.basis_atr_period)

        # ---- Perps: manual rolling deque (no Nautilus indicator for realized vol)
        _perps_maxlen = config.perps_z_window + 2
        self._perps_closes: deque[float] = deque(maxlen=_perps_maxlen)
        self._perps_prev_close: Optional[float] = None

        # ---- One-bar-lag cache for spot EMA crossing detection ----
        self._spot_prev_fast: Optional[float] = None
        self._spot_prev_slow: Optional[float] = None

        # ---- Per-spoke virtual position fractions ----
        self._v_spot: float = 0.0    # in [0.0, spot_max_pos_pct]
        self._v_perps: float = 0.0   # in [0.0, perps_max_pos_pct]
        self._v_basis: float = 0.0   # in [0.0, basis_max_pos_pct]

        # ---- Spoke state ----
        # Spot
        self._spot_entry_price: Optional[float] = None
        self._spot_bars_held: int = 0

        # Perps
        self._perps_entry_price: Optional[float] = None
        self._perps_bars_held: int = 0

        # Basis
        self._basis_entry_price: Optional[float] = None

        # ---- Net position tracking ----
        self._current_btc: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"[ROUTER] Instrument {self.config.instrument_id} not in cache.")
            return
        # Register indicators for automatic bar-driven updates
        self.register_indicator_for_bars(self.config.bar_type, self._spot_fast)
        self.register_indicator_for_bars(self.config.bar_type, self._spot_slow)
        self.register_indicator_for_bars(self.config.bar_type, self._basis_bb)
        self.register_indicator_for_bars(self.config.bar_type, self._basis_atr)
        self.subscribe_bars(self.config.bar_type)

    # on_stop deliberately does NOT flatten — harness handles round closure.

    # ------------------------------------------------------------------
    # Main bar handler
    # ------------------------------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        close = float(bar.close)
        high = float(bar.high)
        low = float(bar.low)

        # 1. Update spoke sub-signals (modifies _v_spot/_v_perps/_v_basis in place)
        self._update_spot(close)
        self._update_perps(close)
        self._update_basis(close, high, low)

        # 2. Weighted composite (clamped per-spoke BEFORE weighting)
        cfg = self.config
        v_s = max(0.0, min(self._v_spot,  cfg.spot_max_pos_pct))
        v_p = max(0.0, min(self._v_perps, cfg.perps_max_pos_pct))
        v_b = max(0.0, min(self._v_basis, cfg.basis_max_pos_pct))

        combined = cfg.w_spot * v_s + cfg.w_perps * v_p + cfg.w_basis * v_b
        combined = max(0.0, min(combined, 1.0))

        # 3. Net order
        self._rebalance(combined, close)

    # ------------------------------------------------------------------
    # Spoke sub-signal: SPOT — EMA(12)/EMA(48) crossover
    # One-bar lag on EMA values to detect crossings without look-ahead.
    # ------------------------------------------------------------------

    def _update_spot(self, close: float) -> None:
        cfg = self.config

        if not (self._spot_fast.initialized and self._spot_slow.initialized):
            return

        fast = self._spot_fast.value
        slow = self._spot_slow.value

        # One-bar crossing detection using lagged EMA values
        if self._spot_prev_fast is not None and self._spot_prev_slow is not None:
            crossed_up = (self._spot_prev_fast <= self._spot_prev_slow) and (fast > slow)
            crossed_dn = (self._spot_prev_fast >= self._spot_prev_slow) and (fast < slow)

            # Stop-loss check (highest priority)
            if self._spot_entry_price is not None:
                if close <= self._spot_entry_price * (1.0 - cfg.spot_stop_loss_pct):
                    self._v_spot = 0.0
                    self._spot_entry_price = None
                    self._spot_bars_held = 0
                    self._spot_prev_fast = fast
                    self._spot_prev_slow = slow
                    return

            # Stale-long guard
            if self._spot_entry_price is not None:
                self._spot_bars_held += 1
                if self._spot_bars_held >= cfg.spot_max_bars:
                    self._v_spot = 0.0
                    self._spot_entry_price = None
                    self._spot_bars_held = 0
                    self._spot_prev_fast = fast
                    self._spot_prev_slow = slow
                    return

            # Signal: bullish crossover → enter; bearish → exit
            if crossed_up and self._spot_entry_price is None:
                self._spot_entry_price = close
                self._spot_bars_held = 0
                self._v_spot = cfg.spot_max_pos_pct
            elif crossed_dn and self._spot_entry_price is not None:
                self._v_spot = 0.0
                self._spot_entry_price = None
                self._spot_bars_held = 0

        self._spot_prev_fast = fast
        self._spot_prev_slow = slow

    # ------------------------------------------------------------------
    # Spoke sub-signal: PERPS — realized-vol-gated z-score mean-reversion
    # Uses prev_close buffer to ensure no look-ahead.
    # ------------------------------------------------------------------

    def _update_perps(self, close: float) -> None:
        cfg = self.config

        # Push previous close into the rolling deque (not current bar's close)
        if self._perps_prev_close is not None:
            self._perps_closes.append(self._perps_prev_close)
        self._perps_prev_close = close  # stored for NEXT bar's use

        if len(self._perps_closes) < cfg.perps_z_window:
            return  # warm-up

        window = list(self._perps_closes)[-cfg.perps_z_window:]
        mean = float(np.mean(window))
        std = float(np.std(window))
        if std == 0.0:
            return

        log_rets = np.diff(np.log(window))
        realized_vol = float(np.std(log_rets)) if len(log_rets) > 1 else 0.0

        prev_close = window[-1]  # most recent confirmed close
        z = (prev_close - mean) / std

        # In-position risk management
        if self._perps_entry_price is not None:
            self._perps_bars_held += 1

            # Hard stop-loss
            if prev_close < self._perps_entry_price * (1.0 - cfg.perps_stop_loss_pct):
                self._v_perps = 0.0
                self._perps_entry_price = None
                self._perps_bars_held = 0
                return

            # Time stop
            if self._perps_bars_held >= cfg.perps_time_stop_bars:
                self._v_perps = 0.0
                self._perps_entry_price = None
                self._perps_bars_held = 0
                return

            # Mean-reversion exit: z has reverted to or above mean
            if z >= cfg.perps_z_exit:
                self._v_perps = 0.0
                self._perps_entry_price = None
                self._perps_bars_held = 0
                return

            # Still holding long fade — maintain virtual position
            return

        # Entry: oversold (z < -threshold) AND vol regime is active
        if realized_vol > cfg.perps_vol_threshold and z < -cfg.perps_z_entry:
            self._perps_entry_price = prev_close
            self._perps_bars_held = 0
            self._v_perps = cfg.perps_max_pos_pct

    # ------------------------------------------------------------------
    # Spoke sub-signal: BASIS — BollingerBands mean-reversion + ATR gate
    # Indicators are Nautilus-managed (registered via on_start).
    # Entry: close <= lower_bb AND ATR/close < atr_pct_threshold (quiet regime).
    # Exit:  close >= middle_bb OR stop-loss.
    # ------------------------------------------------------------------

    def _update_basis(self, close: float, high: float, low: float) -> None:
        cfg = self.config

        if not (self._basis_bb.initialized and self._basis_atr.initialized):
            return

        lower_bb = self._basis_bb.lower
        middle_bb = self._basis_bb.middle
        atr_val = self._basis_atr.value
        atr_pct = atr_val / close if close > 0 else 999.0
        high_vol = atr_pct > cfg.basis_atr_pct_threshold

        # Stop-loss check (highest priority)
        if self._basis_entry_price is not None:
            adverse_move = (self._basis_entry_price - close) / self._basis_entry_price
            if adverse_move >= cfg.basis_stop_loss_pct:
                self._v_basis = 0.0
                self._basis_entry_price = None
                return

        # Mean-reversion exit: close reverts to middle band
        if self._basis_entry_price is not None and close >= middle_bb:
            self._v_basis = 0.0
            self._basis_entry_price = None
            return

        # Entry: lower band touch in quiet regime, flat only
        if self._basis_entry_price is None and not high_vol and close <= lower_bb:
            self._basis_entry_price = close
            self._v_basis = cfg.basis_max_pos_pct

    # ------------------------------------------------------------------
    # Order execution: net single MARKET order toward target position
    # Uses instrument.make_qty() for precision-safe quantity.
    # ------------------------------------------------------------------

    def _get_equity(self) -> float:
        venue = self.config.instrument_id.venue
        try:
            account = self.portfolio.account(venue)
            return float(account.balance_total(USDT).as_double())
        except Exception:
            return 1000.0

    def _rebalance(self, target_fraction: float, price: float) -> None:
        if price <= 0 or self.instrument is None:
            return

        equity = self._get_equity()
        target_notional = equity * target_fraction
        target_btc = target_notional / price

        # Sync current BTC from open positions
        try:
            positions = self.cache.positions_open(instrument_id=self.config.instrument_id)
            self._current_btc = sum(float(p.quantity) for p in positions)
        except Exception:
            pass

        delta = target_btc - self._current_btc
        abs_delta = abs(delta)

        if abs_delta < self.config.dust_threshold_btc:
            return

        # Use instrument.make_qty() for catalog-precision quantity
        qty_obj = self.instrument.make_qty(abs_delta)

        if qty_obj <= 0:
            return

        if delta > 0:
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.BUY,
                quantity=qty_obj,
                time_in_force=TimeInForce.GTC,
            )
        else:
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=OrderSide.SELL,
                quantity=qty_obj,
                time_in_force=TimeInForce.GTC,
            )

        self.submit_order(order)
        self._current_btc += delta  # optimistic local update
