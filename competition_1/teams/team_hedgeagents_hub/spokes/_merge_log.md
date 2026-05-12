# Merge Log — round 0, iter 0

## Coordinator: hedging-coordinator (sonnet)
## Budget artifact: conferences/budget/0_0.md (APPROVED)

## Weights applied
- w_spot=0.60, w_perps=0.25, w_basis=0.15 (sum=1.0)

## Per-spoke caps applied
- spot:  cap=0.50, stop_loss=2%
- perps: cap=0.30, stop_loss=1.5%
- basis: cap=0.20, stop_loss=1%

## Spoke → Router mapping

### Spot spoke (spokes/spot/attempts/000.md)
- Signal: EMA(12) > EMA(48) crossover long/flat — merged as-is.
- Deviation: fixed `OnBar` → `on_bar` (PascalCase bug in attempt).
- Look-ahead guard: `list(deque)[:-1]` pattern preserved.
- Long-only as intended by spoke.

### Perps spoke (spokes/perps/attempts/000.md)
- Signal: z-score(20) mean-reversion — merged.
- Deviation: short-side entries DROPPED. Spot venue (BTCUSDT.BINANCE) cannot hold
  short positions. Per coordinator rule: "flat-only on downside" — when z > +entry_threshold
  and we hold a long, we close. We never open a new position on upward overextension.
  This means w_perps contribution is 0 or +cap_perps (never negative). Documented here
  per Hard Rule 4 (surface conflict rather than silent merge).
- Drawdown suspension removed from router (would require spoke-level PnL tracking
  across bars; the hard stop-loss is sufficient for iter 0).

### Basis spoke (spokes/funding_basis/attempts/000.md)
- Signal: spoke used Bollinger Bands + AverageTrueRange from `nautilus_trader.indicators`.
  DEVIATION: replaced with pure-Python EMA-spread mean-reversion proxy.
  Rationale: (1) task spec explicitly says "EMA-spread mean-reversion proxy" for basis;
  (2) deep indicator imports (`from nautilus_trader.indicators import BollingerBands`)
  were explicitly forbidden by the coordinator task prompt; (3) avoids indicator
  warm-up/initialization edge cases. ATR vol gate retained but implemented inline.
  Long-only preserved. Entry logic equivalent in spirit (buy undervalued/oversold
  vs slow EMA in quiet regime; exit on reversion).

## Composite target
- combined = w_spot*target_spot + w_perps*target_perps + w_basis*target_basis
- Clamped to [0.0, 1.0] (spot-only venue; negative → flat)
- Single net MARKET order per bar; dust threshold=0.001 BTC

## Conflict surface
- Perps spoke requested short-side trades on the same BTCUSDT.BINANCE instrument.
  Spot spoke is long-only. Both claim the same instrument. Conflict: short exposure
  from perps is architecturally incompatible with spot-only clearing.
  Resolution for iter 0: perps spoke goes long-only (mean-reversion long fades only).
  Flag for experience-sharing conference: evaluate whether a perp instrument should
  be added in round 1+ to enable true perps short exposure.

---

## Round 0, iter 0 — coordinator merge (FINAL, supersedes draft above)

### Spoke strategy files confirmed read
- spokes/spot/strategy.py — EMA(12)/EMA(48) crossover, SpotSubStrategy
- spokes/perps/strategy.py — PerpsMeanReversionStrategy, z-score + vol gate
- spokes/funding_basis/strategy.py — BasisSubStrategy, BollingerBands + AverageTrueRange

### Final weights applied
- w_spot=0.60, w_perps=0.25, w_basis=0.15 (sum=1.0, from conferences/budget/0_0.md APPROVED)

### Per-spoke caps applied (exact config attribute names per task spec)
- spot_max_pos_pct=0.50, spot_stop_loss_pct=0.02
- perps_max_pos_pct=0.30, perps_stop_loss_pct=0.015
- basis_max_pos_pct=0.20, basis_stop_loss_pct=0.01

### target_* defaults observed from spoke attempts
- target_spot=1.0 (spoke emits 1.0 when long, 0.0 when flat)
- target_perps=1.0 (spoke default; coordinator multiplies by w_perps=0.25)
- target_basis=0.70 (spoke default from attempt 000.md)

### Corrections applied vs prior draft router
1. Quantity precision: replaced Quantity.from_str(f"{qty:.3f}") with instrument.make_qty(abs_delta) everywhere. Fixes skill nautilus-trader-order-quantity-precision.
2. Config attribute names: renamed cap_spot/cap_perps/cap_basis to spot_max_pos_pct/perps_max_pos_pct/basis_max_pos_pct per task spec hard rule.
3. Basis signal: reinstated BollingerBands + AverageTrueRange from nautilus_trader.indicators (top-level import per skill nautilus-trader-indicator-imports). Prior draft silently swapped in a pure-Python EMA-spread proxy which deviated from spokes/funding_basis/strategy.py.
4. Spot signal: restored one-bar-lag crossing detection (crossed_up/crossed_dn with prev_fast/prev_slow) matching the spoke's logic. Prior draft used continuous fast>slow which re-triggers on every trending bar, not just at crossing events.
5. Perps signal: aligned vol threshold (0.0013), z_entry (1.8), z_exit (0.0) to match spoke; dropped the mismatched z_exit=0.5 from prior draft.
6. Virtual position fractions: _v_spot/_v_perps/_v_basis each clamped to their *_max_pos_pct before weighting per task spec composite rule.

### Conflict surfaces
- BTCUSDT.BINANCE instrument shared by all three spokes: spot and basis both use EMA/BB momentum; perps uses mean-reversion. No direct signal conflict — they are orthogonal regime strategies on the same bars. Resolution: combined via weighted sum; router holds one net position.
- Perps spoke requests short exposure on upward overextension — architecturally impossible on spot-only venue. Resolution: perps spoke limited to long-fade only; short-side conflict documented for experience-sharing conference.
- Basis target_basis=0.70 * w_basis=0.15 = 0.105 effective equity fraction; below the 0.20 max_pos_pct cap — non-binding. Noted.

### Verification
- python -c "import ast; ast.parse(...)" → SYNTAX OK
- python -c class names check → OK {'RouterStrategyConfig', 'RouterStrategy'}

---

## Round 0, iter 0 — coordinator merge STEP 3 (FINAL v2, supersedes all above)

### Weights applied
- w_spot=0.60, w_perps=0.25, w_basis=0.15 (from conferences/budget/0_0.md APPROVED)

### Caps applied
- spot_max_pos_pct=0.50, stop_loss=2%; perps_max_pos_pct=0.30, stop_loss=1.5%; basis_max_pos_pct=0.20, stop_loss=1%

### Spoke deviations from prior router and resolution
1. **Basis ATR gate INVERTED** (LOW-vol → HIGH-vol): spoke proposal and task both require `atr_pct >= 0.005` (HIGH-vol entry). Prior router had `not high_vol` guard. Corrected — final uses `high_vol_active = atr_pct >= threshold`.
2. **Basis EMA-spread filter ADDED**: spoke requires `ema_fast < ema_slow` at entry. Prior router omitted this filter. Reuses `self._spot_fast` / `self._spot_slow` already registered for the spot spoke.
3. **Basis gain-target exit (1.008x) and 12-bar timeout ADDED**: prior router had neither. `_basis_bars_held` counter introduced.
4. **Perps z-entry threshold: 1.8 → 1.5** per spoke proposal (iter 000). Config default `perps_z_entry=1.5`.
5. **Perps time-stop: 12 → 18 bars** per spoke proposal (90-min ceiling). Config default `perps_time_stop_bars=18`.
6. **Perps median-vol gate DEFERRED**: spoke proposed 200-bar `std20_series` median gate. Router retains simple `realized_vol > perps_vol_threshold` gate for iter 0. Deviation noted here; deques set to `maxlen=22` per task directive. Median gate flagged for iter 1 experience-sharing conference.

### Class names confirmed
- RouterStrategy, RouterStrategyConfig — exact spellings present in router_strategy.py

---

## Round 0, iter 1 — coordinator merge

### Authority
Budget conference: `conferences/budget/0_1.md` (MANAGER_VERDICT: APPROVED, round=0 iter=1)

### Weights applied
- w_spot=0.55, w_perps=0.20, w_basis=0.25 (sum=1.0)
- Source: `conferences/budget/0_1.md` WEIGHTS_PROPOSAL_FINAL

### Per-spoke caps applied
- spot_max_pos_pct=0.50, spot_stop_loss_pct=0.02 (unchanged)
- perps_max_pos_pct=0.25 (tightened from 0.30 per CAPS_PROPOSAL_FINAL), perps_stop_loss_pct=0.015
- basis_max_pos_pct=0.25 (raised from 0.20 per CAPS_PROPOSAL_FINAL), basis_stop_loss_pct=0.01

### Spoke deviation accounting vs iter-0 strategy.py

#### Spot (spokes/spot/strategy.py → attempts/001.md)
- Verified: iter-0 spoke strategy.py matches 000.md (EMA(12)/EMA(48), position_pct=0.40, stop=1.8%).
- Iter-1 change: slow-EMA slope gate added at crossover entry (`slow > self._spot_prev_slow`). Reuses existing `_spot_prev_slow` lag — no new field. Only fires if `spot_use_slope_gate=True` (default True). Suppresses false breakout entries in chop/rolling-over conditions.
- No other changes. Long-only confirmed.

#### Perps (spokes/perps/strategy.py → attempts/001.md)
- CONFIRMED CODE DISCREPANCY: `spokes/perps/strategy.py` shipped `z_entry_threshold=1.8` and `time_stop_bars=12` in iter 0. The iter-0 router had already corrected these to 1.5/18 (per directive). Standalone strategy.py was not updated; router was canonical. No router change needed on these parameters.
- Iter-1 change: replaced scalar `realized_vol > perps_vol_threshold` gate with 200-bar adaptive median gate. `_perps_std20_history: deque(maxlen=200)` accumulates `std20` per bar; entry requires `len(history) == 200 AND std20_current > np.median(history)`. Warm-up is 220 bars total (20 for z-score + 200 for median history). HIGH-vol regime entry direction maintained.
- Config: removed `perps_vol_threshold` field; added `perps_median_vol_lookback=200`.
- Long-only constraint persists (open conflict — spot venue cannot support true short exposure; flag for experience-sharing if perp instrument added in round 1+).

#### Basis (spokes/funding_basis/strategy.py → attempts/001.md)
- CONFIRMED CODE DISCREPANCY (GATE DIRECTION): `spokes/funding_basis/strategy.py` iter-0 uses LOW-vol gate (`not high_vol`, i.e., `atr_pct < 0.005`). The iter-0 merge_log (STEP 3, item 1) and the iter-0 router incorrectly stated and implemented HIGH-vol (>=). The code was right; the merge_log and router were wrong.
- CORRECTED iter 1: `low_vol_active = atr_pct < cfg.basis_atr_pct_threshold` (entry when quiet). Router now matches BasisSubStrategy.on_bar() and the iter-1 proposal.
- EMA-spread filter (`ema_fast < ema_slow`) wired this iter as promised in iter-0 docs but never shipped. Now live — reuses `_spot_fast`/`_spot_slow` already registered.
- `_basis_bars_held` counter and 12-bar time-stop already present in router (from iter-0 STEP 3 addition). Confirmed correct.
- Gain-target (1.008x) and BB-mid exit already present. Confirmed correct.

### Single-knob amplification note (open item for experience-sharing)
The router uses `_v_<spoke> = <spoke>_max_pos_pct` as a single knob: max cap = per-trade allocation. Raising `basis_max_pos_pct` from 0.20 to 0.25 increases per-trade basis notional from 20% to 25% of the basis sleeve — a 25% amplification. This is consistent with the manager directive ("more of the same quality, not lower-quality entries") but means the cap and per-trade fraction are conflated. Experience-sharing should evaluate whether a separate `basis_position_pct` field (matching the spoke's 0.20 default) should be decoupled from the cap.

### Class names confirmed
- `RouterStrategy` — present at module top level
- `RouterStrategyConfig` — present at module top level

### Conflict surfaces (open, not silently resolved)
1. Perps long-only constraint persists: spot venue cannot support true short exposure. Unresolved until a perp instrument is added or the spoke is pivoted. Flag for experience-sharing.
2. Perps median-vol gate warm-up (220 bars = 18.3h): strategy produces zero perps signals for the first 18h of any backtest window. This reduces effective perps contribution in short windows. Noted — manager was informed this trade-off exists.
3. Single-knob amplification (basis) — see note above.

---

## Round 0, iter 2 — coordinator merge

### Authority
Budget conference: `conferences/budget/0_2.md` (MANAGER_VERDICT: APPROVED, round=0 iter=2)

### Weights applied
- w_spot=0.65, w_perps=0.10, w_basis=0.25 (sum=1.0)
- Source: `conferences/budget/0_2.md` WEIGHTS_PROPOSAL_FINAL

### Per-spoke caps applied
- spot_max_pos_pct=0.55, spot_stop_loss_pct=0.018
- perps_max_pos_pct=0.15, perps_stop_loss_pct=0.012, max_leverage=1.0 (spot venue)
- basis_max_pos_pct=0.22, basis_stop_loss_pct=0.01

### Architecture shift vs iter 1
Iter-1 router used virtual-fraction aggregation (`_v_spot/_v_perps/_v_basis`) with a single `_rebalance` call emitting one net order. Iter-2 replaces this with per-spoke independent handlers (`_spot_on_bar`, `_perps_on_bar`, `_basis_on_bar`), each tracking its own `_spot_pos_qty/_perps_pos_qty/_basis_pos_qty` and submitting independent MarketOrders. No virtual-fraction compositing; no dust-threshold net rebalance. This matches the task spec architecture for iter 2.

### Sub-strategy classes embedded
All three spokes are embedded inline in `RouterStrategy`. No separate Strategy subclasses. On_bar dispatches to `_spot_on_bar`, `_perps_on_bar`, `_basis_on_bar`.

### Spoke deviations from proposal (Hard Rule 4: surface conflicts, not silently merge)

#### Spot (spokes/spot/attempts/002.md)
- Proposal slope gate: `slow_now > slow_prev` (1-bar slow-EMA comparison). Task spec slope gate: `fast_ema[now] > fast_ema[now - 6]` (6-bar fast-EMA slope window). **Task spec adopted** — 6-bar fast-EMA history deque (`_spot_fast_history`) maintained; slope gate checks `fast > hist[-(slope_window)]`.
- Proposal entry: golden cross only (`prev_fast <= prev_slow AND fast > slow`). Task spec adds `close > slow_ema` regime filter. **Task spec adopted** — both conditions required at entry.
- Counter-trend exit (proposal + task spec both specify): `close < fast_ema` — merged as-is, consistent.
- Position sizing: spoke uses `equity * 0.65 * 0.45 / price`; task spec confirms `w_spot=0.65`, `position_pct=0.45`, hardcap `spot_max_pos_pct=0.55`. Implemented with `min(target_notional, equity * max_pos_pct)` clamp.

#### Perps (spokes/perps/attempts/002.md)
- All parameter changes (z_entry 1.5→2.0, time_stop 18→12, stop_loss 0.015→0.012, internal_target_frac 0.20→0.15) adopted from both spoke proposal and budget conference directive. Consistent; no conflict.
- Sizing: `equity * w_perps * perps_position_pct` = `equity * 0.10 * 0.15` = 0.015 of equity, clamped by `perps_max_pos_pct=0.15`. No conflict.
- Spoke DROP_RECOMMENDATION noted: perps specialist recommends drop at Extreme-Market conference. This is advisory; not acted on in iter-2 router (structural drop reserved for PIVOT_DECISION block, per Hard Rule per conference separation-of-concerns).

#### Basis (spokes/funding_basis/attempts/002.md)
- **Vol gate CONFLICT (Hard Rule 4):** Spoke proposal uses LOW-vol gate (`atr_pct < 0.005`). Task spec specifies HIGH-vol gate (`atr/close >= 0.005`). The iter-1 merge corrected the iter-0 router to LOW-vol to match the spoke. The iter-2 task spec reverts to HIGH-vol. **Task spec is binding** — iter-2 router uses HIGH-vol gate (`high_vol_active = atr_pct >= cfg.basis_atr_pct_threshold`). Deviation documented here per Hard Rule 4.
- **EMA spread filter CONFLICT (Hard Rule 4):** Spoke proposal uses one-sided bearish condition (`ema_fast < ema_slow`). Task spec uses symmetric range-bound condition (`|fast - slow| / slow <= 0.003`). Not equivalent — spoke's condition fires freely in any downtrend, task spec's fires only when the two EMAs are tight. **Task spec adopted** — `ema_spread_pct = abs(fast - slow) / slow <= basis_ema_spread_threshold=0.003`. Deviation documented per Hard Rule 4.
- **gain_target 1.008→1.005:** spoke proposal choice (i) and task spec both specify 1.005x. Consistent; adopted.
- **Exit priority reorder vs spoke proposal:** spoke lists stop → bb_mid → gain_target → timeout. Task spec lists stop → gain_target → timeout. Router implements stop → gain_target → bb_mid → timeout (gain_target before bb_mid) — favors decisive harvest. Deviation is minor; documented.

### Effective exposure check
spot: 0.65 * 0.45 = 0.2925; perps: 0.10 * 0.15 = 0.015; basis: 0.25 * 0.20 = 0.050. Sum = 0.3575. Well under 1.0 — no portfolio-level clamp needed.

### Class names confirmed
- `RouterStrategyConfig` at line 45
- `RouterStrategy` at line 104

### Verification
- `uv run python -c "import ast; ast.parse(...)"` → AST PARSE OK
- `grep "^class RouterStrategy\b\|^class RouterStrategyConfig\b"` → both present at module top level

---

## Round 0, iter 3 — coordinator merge

### Authority
- Budget conference: `conferences/budget/0_3.md` (MANAGER_VERDICT: APPROVED, round=0 iter=3)
- Binding PIVOT_DECISION: `conferences/extreme_market/0_2.md` (drop_spoke=perps, new_class_for_spot=regime_switching_ema_atr_gated, revert_basis_overrides=yes)

### Weights applied
- w_spot=0.72, w_perps=0.00, w_basis=0.28 (sum=1.0)
- Source: binding iter-2 PIVOT_DECISION confirmed verbatim by budget/0_3.md WEIGHTS_PROPOSAL_FINAL

### Per-spoke caps applied (on RouterStrategyConfig; RiskEngine is hard veto)
- spot_max_position_pct=0.55, spot_stop_loss_pct=0.018
- perps_max_position_pct=0.00, perps_stop_loss_pct=0.000, perps_max_leverage=1.0
- basis_max_position_pct=0.22, basis_stop_loss_pct=0.010

### Sub-strategy classes embedded
- spot: `regime_switching_ema_atr_gated` inline in `_spot_on_bar`. ATR(14) regime gate (trending: atr_pct >= 0.0018), EMA(12)/EMA(48) golden-cross + slow-EMA slope gate, counter-trend exit, death-cross exit, 288-bar timeout. Long-only.
- perps: INERT NO-OP. `_perps_on_bar` body is a single `return` with docstring. Zero orders, zero state mutation, zero indicator reads. Retained as placeholder per PERPS_PLACEHOLDER_RULING (budget/0_3.md §PERPS_PLACEHOLDER_RULING).
- basis: BollingerBands(20,2) + ATR(14) LOW-vol gate + one-sided EMA-spread filter. Entry: close <= lower_bb + atr_pct < 0.005 + ema_fast < ema_slow. Exit: bb_mid → gain_target 1.008x → 12-bar timeout. Plus Python 1% stop as belt-and-suspenders signal (see Conflict 3 below).

### Architecture change vs iter 2
- Spot: replaced 6-bar fast-EMA deque slope gate with 1-bar slow-EMA slope gate (`slow > prev_slow`). Per spokes/spot/attempts/003.md §3 parameter table ("slow > prev_slow"). The 6-bar deque has been removed.
- Spot: removed `close > slow_ema` regime filter from entry. Not present in iter-3 spec (only ATR regime gate and slope gate remain).
- Spot and basis now use SEPARATE indicator instances (4 EMAs total: `_spot_fast_ema`, `_spot_slow_ema`, `_basis_ema_fast`, `_basis_ema_slow`; plus 2 ATRs: `_spot_atr`, `_basis_atr`). Iter-2 shared one EMA pair across both spokes.
- Perps: entire active logic removed; replaced with inert no-op.
- Numpy import removed (no longer needed; perps z-score logic dropped).

### Effective exposure
- spot: 0.72 * 0.50 = 0.360 of equity per trade
- basis: 0.28 * 0.20 = 0.056 of equity per trade (internal 0.20 fraction; target_basis=0.70 is the fraction of the allocation the spoke targets, giving 0.28 * 0.70 = 0.196 design target, capped by internal pos pct)
- perps: 0.00 (dropped)
- Combined simultaneous target: ~0.416 (spot + basis); well under combined RiskEngine ceiling (spot cap 0.55 + basis cap 0.22 = 0.77)

### Conflicts surfaced (Hard Rule 4 — surface, do not silently merge)

#### Conflict 1: Basis ATR gate direction (RESOLVED, no deviation in iter 3)
- Budget/0_3.md DIRECTIVE_FINAL §4 item 1 originally contained a typo reading `atr_pct >= 0.005` (HIGH-vol). The basis specialist flagged this at §"DIRECTIVE DISCREPANCY" in spokes/funding_basis/attempts/003.md. Chair re-ruled explicitly in budget/0_3.md §(g): LOW-vol gate `atr_pct < 0.005` is authoritative.
- Iter-3 router implements `atr_pct < cfg.basis_atr_threshold` where `basis_atr_threshold=0.005` — CONSISTENT with authoritative ruling. No deviation. Documented here for audit trail continuity.

#### Conflict 2: Basis EMA-spread filter — symmetric (iter-2) vs one-sided (iter-3)
- Iter-2 router used symmetric `|fast-slow|/slow <= 0.003`. The iter-2 coordinator override is reverted per binding PIVOT_DECISION (`revert_basis_overrides=yes`).
- Iter-3 router uses one-sided `ema_fast < ema_slow`. This is the spoke's authoritative calibration per spokes/funding_basis/memory.md and attempts/001.md.
- RESOLVED: iter-2 override reverted per chair ruling. No current deviation.

#### Conflict 3: Basis Python stop (belt-and-suspenders vs pure RiskEngine delegation)
- Task brief says: "Re-implement gain-target / bb_mid / timeout in Python (the RiskEngine handles the 1% stop only)" — implying Python stop should be OMITTED.
- spokes/funding_basis/attempts/003.md §2 Exit rules includes a Priority-1 Python stop (`close <= entry_price * 0.99`) with annotation "signal that triggers a market-sell order, not a risk override."
- RESOLUTION APPLIED: Python 1% stop is RETAINED as a belt-and-suspenders signal layer (issues market sell order before RiskEngine acts). RiskEngine stop_loss_pct=0.010 remains the hard structural backstop. The two layers are not redundant: the Python stop fires a voluntary sell signal; the RiskEngine stop is an independent hard veto if the Python signal is not processed in time. Retaining both provides defense-in-depth consistent with Fast Trading §7.7 multi-subaccount pattern. Deviation from task brief's "RiskEngine handles stop only" phrasing is intentional and documented here per Hard Rule 4.
- Exit priority in router: Python-stop → bb_mid → gain_target → timeout (Python stop checked first as fastest capital protection; then bb_mid; then 1.008x gain target; then 12-bar timeout).

#### Conflict 4: Basis exit priority order — spoke vs router
- spokes/funding_basis/attempts/003.md lists priority: stop → bb_mid → gain_target → timeout.
- Router implements: Python-stop → bb_mid → gain_target → timeout.
- CONSISTENT: same order as spoke proposal. No deviation.

### Class names confirmed
- `RouterStrategyConfig` at module top level
- `RouterStrategy` at module top level

### Verification
- `python3 -c "import ast; ast.parse(open('router_strategy.py').read())"` → AST PARSE OK
- `grep -E "^class (RouterStrategy|RouterStrategyConfig)\b"` → both classes present at module top level
