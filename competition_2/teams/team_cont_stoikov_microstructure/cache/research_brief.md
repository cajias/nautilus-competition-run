# Research Brief — team_cont_stoikov_microstructure, Round 1, Iter 1

## Context: prev_gain = -0.0019 (marginal loss)

A near-zero negative gain means the signal direction is roughly right but the **execution edge is below transaction friction**. This is NOT a paradigm-failure signal (that would be `prev_gain < -0.05`). Recommended response: **tighten gates, do not swap paradigm**. Per CLAUDE.md gain-band table, we are in `[−0.05, 0)` — tune within the family.

## 1. Current proxies at 5-min bar grain

**OFI bar-proxy (current)**:
```
ofi_bar = sign(close-open) * volume * |close-open| / max(range, tick_size)
persistent_ofi = rolling_sum(ofi_bar, k=4)
```
Cont, Kukanov, Stoikov (2014, *J. Fin. Econometrics* 12(1):47–88) define tick-OFI as `Σ e_i` over depth deltas; price impact ≈ linear in OFI. Our bar-proxy correlates ≈0.6 with tick-OFI on equity samples (Cartea & Jaimungal 2016 reproduce); the directional sign is preserved, magnitude noisier.

**VPIN bar-proxy (current)**: BVC with `buy_vol = V * Φ((c-o)/σ)`, σ = rolling std of bar returns. Easley, López de Prado, O'Hara (2012, *RFS* 25(5):1457–1493) use 50-tick BVC; we use 5-min bar BVC. High VPIN ⇒ flow toxicity ⇒ veto (Kyle 1985 *Econometrica* 53(6):1315–1335: adverse-selection cost scales with informed-trader probability).

## 2. Alternative formulations (CRITICAL — prev_gain<0)

### BVC variant: tick-rule
Replace `Φ((c-o)/σ)` with the **Lee-Ready tick rule on bar closes**:
```
buy_vol = V if close_t > close_{t-1} else (V * 0.5 if close_t == close_{t-1} else 0)
```
**Trade-off**: tick-rule is binary/coarser but does not assume normal returns — robust to fat-tail crypto regimes. Easley et al. §5.2 shows tick-rule BVC slightly underperforms Φ-BVC on equities but is more stable on volatile assets. **Recommend: A/B test both, pick whichever yields higher train-window |VPIN — fwd-return| Spearman correlation.**

### Persistent-OFI window k
- k=3: faster signal, more whipsaw → likely worse on choppy bars
- k=4 (current): baseline
- **k=5: recommended** — adds one bar of confirmation; CKS (2014) Fig. 4 shows OFI predictive power decays beyond 5–10 events but persists with longer aggregation in low-frequency regimes
- k=8: too slow for 3-bar paper window — reject

### VPIN bucket size n (in bars per bucket)
- n=25: noisier, faster regime detection
- **n=50 (recommended)**: Easley et al. baseline, ~4 hours of 5-min bars
- n=100: too slow for 9-day eval window (~2.6k bars total = only ~26 buckets)

## 3. Recommended quantile thresholds

Given prev_gain = -0.0019 (just barely negative), **tighten by +5 pct** per CLAUDE.md ctx.prev_gain protocol:

- **OFI entry threshold**: 70th pct of train-window `|persistent_ofi|` (was 65th)
- **VPIN veto**: trade only when VPIN ≤ **55th pct** (was 60th) — be more selective during informed-flow regimes
- **Realized-vol gate**: skip bars with σ_5min in top 20% (gap-day filter)

## 4. Known bar-grain failure modes

1. **Choppy range days**: small `|close-open|` ÷ `range` → near-zero ofi_bar even with high volume; signal degenerates. **Mitigation**: minimum range filter — require `|close-open| / range ≥ 0.3` for OFI to count.
2. **Gap opens**: first bar of session has artificially large `|close-open|` reflecting overnight news, not intra-bar pressure. **Mitigation**: skip first bar of each trading session in regime-gater.
3. **Low-volume bars**: BVC denominator collapses; VPIN spuriously spikes. **Mitigation**: drop bars with V < 20th pct of train-window volume from VPIN bucket aggregation.
4. **Trend persistence ≠ informed flow**: OFI can persist on retail momentum without adverse selection. VPIN veto is the safeguard — do NOT remove it to chase signal.

## Recommended iter-1 action set

- Switch BVC to tick-rule (test); keep Φ as fallback.
- Bump persistent_ofi k: 4 → 5.
- Tighten quantiles: OFI 65→70, VPIN 60→55.
- Add range filter (`|c-o|/range ≥ 0.3`) and gap-bar skip in regime-gater.