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
