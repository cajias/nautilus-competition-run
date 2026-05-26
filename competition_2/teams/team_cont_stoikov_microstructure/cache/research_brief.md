# Research Brief — Iteration 4: OFI/VPIN at 5-Min Bar Grain

## 1. Proxy Formulations (current)

**OFI bar-proxy** (Cont-Kukanov-Stoikov 2014 §3, adapted):
```
ofi_bar = sign(close - open) * volume * |close - open| / max(range, tick_size)
persistent_ofi = Σ_{i=t-k+1}^{t} ofi_bar_i,  k=4 (train), k=2 (trade-time)
```
The `|close-open|/range` factor is the **directional conviction ratio** — 1.0 on a clean trend bar, → 0 on a doji. This approximates the tick-level OFI sum `Σ e_i = Σ(+Δbid_size − Δask_size)` from CKS by assuming bar volume distributes proportionally to net side pressure. Fidelity is highest on directional bars, lowest on inside-bar rotations.

**VPIN bar-proxy** (Easley-López de Prado-O'Hara 2012, eq. 4 with bar-clock BVC):
```
buy_vol_i  = V_i * Φ((c_i - o_i) / σ_r)
sell_vol_i = V_i - buy_vol_i
VPIN_t     = (1/n) * Σ |2*buy_vol - V| / V    over n volume buckets of size V̄
```
σ_r = rolling std of bar log-returns (train-window prior used at trade-time bar 1). Cumulative volume bucketing — not fixed window — so VPIN is defined from bar 1.

## 2. Citations (load-bearing)

- **Cont, Kukanov, Stoikov (2014)** *J. Fin. Econometrics* 12(1):47–88. OFI is approximately **linear** in mid-price returns at sub-second grain; β ≈ depth-normalized. At 5-min grain we expect linearity to degrade and noise variance to dominate — hence we use **persistent OFI** (rolling sum) to denoise, not raw bar OFI.
- **Easley, López de Prado, O'Hara (2012)** *Rev. Fin. Studies* 25(5):1457–1493. VPIN ≥ 80th percentile predicts the May 2010 Flash Crash 1 hour ahead. Mechanism: BVC-imbalance proxies the probability counterparties are informed (Kyle's λ regime).
- **Kyle (1985)** *Econometrica* 53(6):1315–1335. Provides the adverse-selection scaffolding: liquidity providers price-in P(informed). VPIN operationalizes this; OFI persistence captures the *direction* informed flow is leaning.

## 3. Recommended Thresholds (iter 4 — tighten if prev_gain < 1.0)

Calibrate from train-window quantiles (NOT hardcoded):

| Gate | Quantile | Direction |
|---|---|---|
| **OFI long entry** | persistent_ofi ≥ Q(0.75) of train | strong positive pressure |
| **OFI short entry** | persistent_ofi ≤ Q(0.25) of train | (skip if longs-only) |
| **VPIN veto** | VPIN ≤ Q(0.60) of train | only trade when toxicity is below median+ |
| **Realized-vol gate** | σ_bar within [Q(0.20), Q(0.85)] | avoid both dead and panic regimes |

If `prev_gain < 1.0` twice running: tighten OFI to Q(0.80) and VPIN to Q(0.50). If `prev_gain ≥ 1.0`: hold thresholds, narrow the realized-vol band by 5 pct.

## 4. Known Bar-Grain Failure Modes

1. **Choppy range days** — large `range` with small `|close-open|` collapses OFI proxy to ≈0, masking real informed flow that ticked back and forth. Mitigation: the `max(range, tick_size)` denominator at least bounds the weight; secondary mitigation = realized-vol upper gate vetos these regimes.
2. **Gap opens** — `open` of bar 1 includes overnight gap, inflating `|close-open|` and producing a spurious OFI spike. Mitigation: regime-gater ignores the first bar of any session boundary; for BTCUSDT 24/7 this is less acute but still relevant on UTC midnight rolls.
3. **VPIN BVC σ instability on tiny windows** — at 3-bar paper window σ_r is undefined; we use the **train-window σ as prior** until ≥3 live bars accumulate.
4. **Volume spikes from liquidations** — inflate VPIN imbalance regardless of true informed flow. Mitigation: VPIN veto is conservative-side here (high VPIN = no trade), so this fails *safe*.
5. **Proxy drift** — bar-OFI correlation with true tick-OFI degrades in low-volume regimes. If iter 4 underperforms, hypothesis-generator should propose a **trade-imbalance variant** using `(taker_buy_vol - taker_sell_vol)` if the catalog exposes it; otherwise stick with directional-conviction weighting.

**Trade-time discipline:** OFI-first warmup (bar 1: no trade), VPIN cumulative (live from bar 1), no rolling window > 3 in the live path.