"""
RouterStrategy — team_hedgeagents_hub, round 0 / iter 3.

Hub-and-spoke merger of two inline sub-signals (perps DROPPED per iter-2 PIVOT_DECISION):

  - spot:   regime_switching_ema_atr_gated                        w=0.72  cap=0.55
             EMA(12)/EMA(48) golden-cross long entry, only in trending regime
             (atr_pct >= 0.0018). Slow-EMA slope gate retained. Counter-trend exit
             (close < fast_ema), death-cross exit, 288-bar timeout.
             target_spot=0.50 internal fraction.

  - perps:  DROPPED per iter-2 PIVOT_DECISION.                    w=0.00  cap=0.00
             _perps_on_bar is an inert no-op. Placeholder retained for forensic
             continuity and one-line re-instatement if a real perp instrument is added.

  - basis:  BollingerBands(20,2) + ATR(14) LOW-vol gate           w=0.28  cap=0.22
             + EMA-spread filter (ema_fast < ema_slow, one-sided).
             Entry on close <= lower BB in LOW-vol quiet regime.
             Exit: bb_mid revert → gain_target 1.008x → 12-bar timeout.
             Python-level 1% stop included as belt-and-suspenders signal layer;
             RiskEngine stop_loss_pct=0.010 is the hard veto.
             Internal max_position_pct=0.20 (2pp below RiskEngine cap of 0.22).
             target_basis=0.70 internal fraction.

Budget weights from conferences/budget/0_3.md (APPROVED, round 0 iter 3).
Binding PIVOT_DECISION from conferences/extreme_market/0_2.md.

Architecture: per-spoke handlers each submit independent MarketOrders.
Each spoke tracks its own position qty.
All indicators registered via register_indicator_for_bars for automatic
Nautilus-driven updates — no manual handle_bar() calls inside handlers.

References:
  HedgeAgents, Li et al., WWW 2025 — arXiv:2502.13165 §B (no look-ahead), §C (hub-and-spoke)
  Fast Trading on Binance with NautilusTrader — §2, §7.7 (multi-subaccount pattern)
  conferences/budget/0_3.md — APPROVED (w_spot=0.72, w_perps=0.00, w_basis=0.28)
  conferences/extreme_market/0_2.md — PIVOT_DECISION (drop_spoke=perps, spot class upgrade,
    revert_basis_overrides)
  spokes/_merge_log.md — full deviation log (round 0 iter 3 entry)
"""

from __future__ import annotations

from typing import Optional

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
    Configuration for the hedgeagents hub-and-spoke RouterStrategy (iter 3).

    instrument_id and bar_type are REQUIRED — entry.py passes them as typed
    objects from harness config. No defaults for these two fields.

    Budget weights and per-spoke caps sourced from:
      conferences/budget/0_3.md (APPROVED, round 0 iter 3)
      conferences/extreme_market/0_2.md (binding PIVOT_DECISION)

    Per-spoke caps are surfaced here so downstream RiskEngine wiring can
    read them directly from the config. The actual enforcement lives in
    entry.py / RiskEngineConfig — NOT in on_bar Python branches.
    """

    instrument_id: InstrumentId
    bar_type: BarType

    # --- Equity fallback (used when portfolio account balance unavailable) ---
    starting_equity: float = 1000.0

    # --- Budget weights (sum=1.0) from conferences/budget/0_3.md ------------
    w_spot: float = 0.72
    w_perps: float = 0.00   # DROPPED per iter-2 PIVOT_DECISION
    w_basis: float = 0.28

    # Weight sum validation (informational; enforced by design)
    # 0.72 + 0.00 + 0.28 = 1.00 — CONFORMING

    # --- Per-spoke risk caps (from budget conference; RiskEngine is hard veto) ---
    spot_max_position_pct: float = 0.55
    spot_stop_loss_pct: float = 0.018

    perps_max_position_pct: float = 0.00   # defense-in-depth for the dropped spoke
    perps_stop_loss_pct: float = 0.000
    perps_max_leverage: float = 1.0

    basis_max_position_pct: float = 0.22
    basis_stop_loss_pct: float = 0.010

    # --- Spot sub-signal parameters (regime_switching_ema_atr_gated) ---------
    spot_fast_period: int = 12      # ~1h on 5-min bars
    spot_slow_period: int = 48      # ~4h on 5-min bars
    spot_atr_period: int = 14       # Wilder ATR(14)
    spot_atr_threshold: float = 0.0018   # trending regime gate (>= enters)
    spot_target_pct: float = 0.50   # internal fraction: w_spot * target_spot = 0.36
    spot_max_bars: int = 288        # 24h stale-long guard (5-min bars)

    # --- Basis sub-signal parameters -----------------------------------------
    basis_bb_period: int = 20
    basis_bb_k: float = 2.0
    basis_atr_period: int = 14
    basis_atr_threshold: float = 0.005  # LOW-vol gate: entry when atr_pct < 0.005
    basis_ema_fast_period: int = 12
    basis_ema_slow_period: int = 48
    basis_gain_target: float = 1.008    # 1.008x entry price (restored from iter-1)
    basis_max_bars: int = 12            # 60-min timeout (12 × 5-min bars)
    basis_internal_pos_pct: float = 0.20  # internal cap; 2pp below RiskEngine cap 0.22
    basis_target_pct: float = 0.70      # internal fraction: w_basis * target_basis = 0.196


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class RouterStrategy(Strategy):
    """
    Single Nautilus Strategy that inlines two active spoke sub-signals
    (perps spoke dropped per iter-2 PIVOT_DECISION, retained as inert placeholder).

    Each active spoke handler (_spot_on_bar, _basis_on_bar) manages its own
    position state and submits independent MarketOrders. _perps_on_bar is an
    inert no-op that immediately returns.

    Spoke sizing (effective equity fractions when both simultaneously long):
        spot:  w_spot * target_spot  = 0.72 * 0.50 = 0.360
        basis: w_basis * target_basis = 0.28 * 0.70 = 0.196
        perps: 0.00 (dropped)
        Total target: ~0.556 — bounded by RiskEngine caps
          spot cap: 0.55, basis cap: 0.22, combined ceiling: 0.458

    All signals use confirmed closed bars only (no look-ahead, AI Agents §B).
    Indicators registered via register_indicator_for_bars — Nautilus drives updates
    automatically. No manual handle_bar() calls inside spoke handlers.
    """

    def __init__(self, config: RouterStrategyConfig) -> None:
        super().__init__(config)

        cfg = config

        # ---- Spot indicators (registered in on_start) ----
        # Separate instances from basis indicators (both 12/48 but independent objects)
        self._spot_fast_ema = ExponentialMovingAverage(cfg.spot_fast_period)
        self._spot_slow_ema = ExponentialMovingAverage(cfg.spot_slow_period)
        self._spot_atr = AverageTrueRange(cfg.spot_atr_period)

        # ---- Spot: lag scalars for crossover and slope gate (written end-of-bar) ----
        self._spot_prev_fast: Optional[float] = None
        self._spot_prev_slow: Optional[float] = None

        # ---- Spot: position state ----
        self._spot_pos_qty: float = 0.0
        self._spot_entry_price: Optional[float] = None
        self._spot_bars_held: int = 0

        # ---- Basis indicators (registered in on_start) ----
        # Separate EMA instances from spot — both 12/48 but driven independently
        self._basis_bb = BollingerBands(cfg.basis_bb_period, cfg.basis_bb_k)
        self._basis_atr = AverageTrueRange(cfg.basis_atr_period)
        self._basis_ema_fast = ExponentialMovingAverage(cfg.basis_ema_fast_period)
        self._basis_ema_slow = ExponentialMovingAverage(cfg.basis_ema_slow_period)

        # ---- Basis: position state ----
        self._basis_pos_qty: float = 0.0
        self._basis_entry_price: Optional[float] = None
        self._basis_bars_held: int = 0

        # ---- Instrument (set in on_start) ----
        self.instrument = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(
                f"[ROUTER] Instrument {self.config.instrument_id} not in cache."
            )
            return

        bar_type = self.config.bar_type

        # Spot indicators — Nautilus feeds these automatically on each closed bar
        self.register_indicator_for_bars(bar_type, self._spot_fast_ema)
        self.register_indicator_for_bars(bar_type, self._spot_slow_ema)
        self.register_indicator_for_bars(bar_type, self._spot_atr)

        # Basis indicators — separate registrations from spot
        self.register_indicator_for_bars(bar_type, self._basis_bb)
        self.register_indicator_for_bars(bar_type, self._basis_atr)
        self.register_indicator_for_bars(bar_type, self._basis_ema_fast)
        self.register_indicator_for_bars(bar_type, self._basis_ema_slow)

        self.subscribe_bars(bar_type)

    # on_stop intentionally does not flatten — harness owns round closure.

    # ------------------------------------------------------------------
    # Main bar handler
    # ------------------------------------------------------------------

    def on_bar(self, bar: Bar) -> None:
        if self.instrument is None:
            return

        # Dispatch to per-spoke handlers. Each handler manages its own warm-up.
        self._spot_on_bar(bar)
        self._perps_on_bar(bar)   # inert no-op — see method docstring
        self._basis_on_bar(bar)

        # Update spot lag scalars AFTER all spoke logic has run (no look-ahead).
        # Written at END of bar so they reflect the just-closed bar values,
        # available as "previous bar" lags on the NEXT on_bar call.
        if self._spot_fast_ema.initialized:
            self._spot_prev_fast = self._spot_fast_ema.value
        if self._spot_slow_ema.initialized:
            self._spot_prev_slow = self._spot_slow_ema.value

    # ------------------------------------------------------------------
    # Spoke handler: SPOT
    # Class: regime_switching_ema_atr_gated
    # Authorized by conferences/extreme_market/0_2.md PIVOT_DECISION
    #   (new_class_for_spot: regime_switching_ema_atr_gated).
    #
    # Regime gate (computed on completed bars, no look-ahead, AI Agents §B):
    #   atr_pct = ATR(14) / close
    #   Trending regime: atr_pct >= 0.0018 → entry admitted on golden cross
    #   Chop regime: atr_pct < 0.0018 → NO new entries; exits/stops continue
    #
    # EMA pair: EMA(12) fast / EMA(48) slow
    # Entry: golden cross (prev_fast <= prev_slow AND fast > slow)
    #        + slow-EMA slope gate (slow > prev_slow)
    #        + in trending regime
    # Exits (regime-independent):
    #   counter-trend: close < fast_ema
    #   death-cross: prev_fast >= prev_slow AND fast < slow
    #   timeout: 288 bars (24h on 5-min bars)
    # Stop-loss: delegated entirely to RiskEngine (stop_loss_pct=0.018)
    # Long-only. Position qty tracked in _spot_pos_qty.
    # ------------------------------------------------------------------

    def _spot_on_bar(self, bar: Bar) -> None:
        # Guard: all spot indicators must be initialized before any trade logic.
        if (
            not self._spot_fast_ema.initialized
            or not self._spot_slow_ema.initialized
            or not self._spot_atr.initialized
        ):
            return

        cfg = self.config
        close = bar.close.as_double()
        fast = self._spot_fast_ema.value   # reflects just-closed bar (Nautilus-registered)
        slow = self._spot_slow_ema.value   # reflects just-closed bar
        atr_val = self._spot_atr.value     # ATR(14) — last 14 closed bars including current
        atr_pct = atr_val / close if close > 0 else 0.0

        # Regime classification (ATR window = last 14 closed bars; current bar IS included
        # because Nautilus EXTERNAL bar events fire only after bar is fully closed).
        # Assertion: no future bar is accessed. Compliant with arXiv:2502.13165 §B.
        trending_regime = atr_pct >= cfg.spot_atr_threshold  # >= 0.0018

        # Lag scalars from previous on_bar call — written at END of previous bar.
        prev_fast = self._spot_prev_fast
        prev_slow = self._spot_prev_slow

        # --- In-position management (exits fire regardless of current regime) ---
        if self._spot_pos_qty > 0.0:
            self._spot_bars_held += 1

            # Stop-loss: fully delegated to RiskEngine (stop_loss_pct=0.018).
            # Do NOT re-implement here — RiskEngine is the hard veto (CLAUDE.md Hard Rules §1).

            # Priority 1: counter-trend exit — close breaks below fast EMA
            if close < fast:
                self._spot_exit(close, "spot_counter_trend")
                return

            # Priority 2: death-cross exit (uses lagged values to avoid look-ahead)
            if (
                prev_fast is not None
                and prev_slow is not None
                and prev_fast >= prev_slow
                and fast < slow
            ):
                self._spot_exit(close, "spot_death_cross")
                return

            # Priority 3: stale-long timeout (288 bars = 24h on 5-min bars)
            if self._spot_bars_held >= cfg.spot_max_bars:
                self._spot_exit(close, "spot_timeout")
                return

            return  # still holding

        # --- Entry logic (flat only, trending regime only) ---
        if self._spot_pos_qty == 0.0 and trending_regime:
            if prev_fast is None or prev_slow is None:
                return

            # Golden cross: previous bar had fast <= slow; this bar fast > slow
            golden_cross = (prev_fast <= prev_slow and fast > slow)

            # Slope gate: slow EMA must be rising (1-bar comparison; arXiv:2502.13165 §B)
            slope_ok = (prev_slow is not None and slow > prev_slow)

            if golden_cross and slope_ok:
                self._spot_enter(close)

    def _spot_enter(self, price: float) -> None:
        cfg = self.config
        equity = self._get_equity()
        # Effective notional: equity * w_spot * target_spot = equity * 0.72 * 0.50
        target_notional = equity * cfg.w_spot * cfg.spot_target_pct
        # RiskEngine hard cap: max_position_pct=0.55 — additional safety clamp
        capped_notional = min(target_notional, equity * cfg.spot_max_position_pct)
        qty_raw = capped_notional / price
        qty = self.instrument.make_qty(qty_raw)  # MANDATORY — never Quantity.from_str()
        if float(qty) <= 0:
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._spot_pos_qty = float(qty)
        self._spot_entry_price = price
        self._spot_bars_held = 0

    def _spot_exit(self, price: float, reason: str) -> None:
        if self._spot_pos_qty <= 0.0:
            return
        qty = self.instrument.make_qty(self._spot_pos_qty)
        if float(qty) <= 0:
            self._spot_pos_qty = 0.0
            self._spot_entry_price = None
            self._spot_bars_held = 0
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._spot_pos_qty = 0.0
        self._spot_entry_price = None
        self._spot_bars_held = 0

    # ------------------------------------------------------------------
    # Spoke handler: PERPS — INERT NO-OP
    #
    # DROPPED per iter-2 PIVOT_DECISION (conferences/extreme_market/0_2.md).
    # drop_spoke=perps; w_perps=0.00; perps_max_position_pct=0.00.
    #
    # Placeholder retained for:
    #   (a) forensic continuity — on_bar dispatch contract preserved
    #   (b) one-line re-instatement if a real perp instrument is added in
    #       a future round
    #
    # CONTRACT: This method MUST emit zero orders, touch zero state, and
    # compute nothing. It returns immediately. Any non-return code path
    # in this method is a protocol violation.
    # ------------------------------------------------------------------

    def _perps_on_bar(self, bar: Bar) -> None:
        """
        Perps spoke dropped at iter-2 extreme-market conference.
        Placeholder retained for forensic continuity and re-instatement
        if a real perp instrument is added. No-op.
        """
        return  # DROPPED per iter-2 PIVOT_DECISION; placeholder for forensic continuity.

    # ------------------------------------------------------------------
    # Spoke handler: BASIS
    # BollingerBands(20,2) + ATR(14) LOW-vol gate + EMA-spread filter.
    #
    # Entry gate (authoritative per chair re-ruling, budget/0_3.md §(g)):
    #   LOW-vol: atr_pct < 0.005  (NOT high-vol; override reverted per PIVOT_DECISION)
    #   EMA-spread: ema_fast < ema_slow  (one-sided; symmetric override reverted)
    #   Lower-BB touch: close <= bb_lower
    #
    # Exit priority (Python-level; RiskEngine 1% stop is the hard backstop):
    #   1. bb_mid revert: close >= bb_middle
    #   2. gain target: close >= entry_price * 1.008  (restored from 1.005 override)
    #   3. timeout: 12 bars (60 min on 5-min bars)
    #
    # Python stop (close <= entry_price * 0.99): retained as belt-and-suspenders
    # signal layer (issues market sell). RiskEngine stop_loss_pct=0.010 is the
    # structural backstop and hard veto (CLAUDE.md Hard Rules §1).
    # See merge_log Round 0 iter 3 for conflict surface documentation.
    #
    # Internal sizing: equity * w_basis * basis_internal_pos_pct = equity * 0.28 * 0.20
    # RiskEngine cap: max_position_pct=0.22 (2pp above internal cap = headroom buffer)
    # Long-only. Position qty tracked in _basis_pos_qty.
    # ------------------------------------------------------------------

    def _basis_on_bar(self, bar: Bar) -> None:
        # Guard: all basis indicators must be initialized.
        if (
            not self._basis_bb.initialized
            or not self._basis_atr.initialized
            or not self._basis_ema_fast.initialized
            or not self._basis_ema_slow.initialized
        ):
            return

        cfg = self.config
        close = bar.close.as_double()
        atr_val = self._basis_atr.value
        atr_pct = atr_val / close if close > 0 else 999.0

        lower_bb = self._basis_bb.lower
        middle_bb = self._basis_bb.middle
        ema_fast = self._basis_ema_fast.value
        ema_slow = self._basis_ema_slow.value

        # --- In-position management ---
        if self._basis_pos_qty > 0.0:
            self._basis_bars_held += 1

            # Python-level 1% stop (belt-and-suspenders signal layer).
            # RiskEngine stop_loss_pct=0.010 is the hard veto and structural backstop.
            if (
                self._basis_entry_price is not None
                and close <= self._basis_entry_price * (1.0 - 0.01)
            ):
                self._basis_exit(close, "basis_stop_loss")
                return

            # Priority 1: mean-reversion target — basis converged to BB midline
            if close >= middle_bb:
                self._basis_exit(close, "basis_bb_mid")
                return

            # Priority 2: gain-target take-profit — 1.008x entry price (restored from 1.005)
            if (
                self._basis_entry_price is not None
                and close >= self._basis_entry_price * cfg.basis_gain_target
            ):
                self._basis_exit(close, "basis_gain_target")
                return

            # Priority 3: time-stop — structural divergence assumed after 60 min
            if self._basis_bars_held >= cfg.basis_max_bars:
                self._basis_exit(close, "basis_timeout")
                return

            return  # still holding

        # --- Entry logic (flat only) ---
        # LOW-vol gate: atr_pct < 0.005 (authoritative; HIGH-vol override reverted)
        low_vol_active = atr_pct < cfg.basis_atr_threshold
        # One-sided EMA filter: fast below slow (bearish/ranging; symmetric override reverted)
        ema_filter_ok = ema_fast < ema_slow
        # Lower-band touch: basis widening signal
        lower_band_touch = close <= lower_bb

        if (
            self._basis_pos_qty == 0.0
            and lower_band_touch
            and low_vol_active
            and ema_filter_ok
        ):
            self._basis_enter(close)

    def _basis_enter(self, price: float) -> None:
        cfg = self.config
        equity = self._get_equity()
        # Effective notional: equity * w_basis * internal_pos_pct = equity * 0.28 * 0.20
        target_notional = equity * cfg.w_basis * cfg.basis_internal_pos_pct
        # RiskEngine cap: max_position_pct=0.22 — safety clamp
        capped_notional = min(target_notional, equity * cfg.basis_max_position_pct)
        qty_raw = capped_notional / price
        qty = self.instrument.make_qty(qty_raw)  # MANDATORY — never Quantity.from_str()
        if float(qty) <= 0:
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._basis_pos_qty = float(qty)
        self._basis_entry_price = price
        self._basis_bars_held = 0

    def _basis_exit(self, price: float, reason: str) -> None:
        if self._basis_pos_qty <= 0.0:
            return
        qty = self.instrument.make_qty(self._basis_pos_qty)
        if float(qty) <= 0:
            self._basis_pos_qty = 0.0
            self._basis_entry_price = None
            self._basis_bars_held = 0
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._basis_pos_qty = 0.0
        self._basis_entry_price = None
        self._basis_bars_held = 0

    # ------------------------------------------------------------------
    # Equity helper: portfolio account balance with fallback.
    # ------------------------------------------------------------------

    def _get_equity(self) -> float:
        venue = self.config.instrument_id.venue
        try:
            account = self.portfolio.account(venue)
            return float(account.balance_total(USDT).as_double())
        except Exception:
            return self.config.starting_equity
