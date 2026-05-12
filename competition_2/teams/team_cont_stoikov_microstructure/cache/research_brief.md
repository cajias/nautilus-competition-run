# Research Brief — team_cont_stoikov_microstructure, Iteration 4

## 1. Bar-Grain Proxy Formulations (current best practice)

**OFI bar-proxy.** Cont, Kukanov & Stoikov (2014, *J. Financial Econometrics* 12(1):47–88) define tick-level OFI as the signed sum of best-bid/ask depth deltas: `OFI_n = Σ e_i`, with approximately linear price impact. At 5-min OHLCV grain we approximate:

```
ofi_bar = sign(close - open) * volume * |close - open| / max(range, tick_size)
persistent_ofi = rolling_sum(ofi_bar, k)
```

The `|close-open|/range` ratio is the **directional conviction weight** — it suppresses choppy bars where open and close are near equal despite high intrabar range. For the 15-min paper window, use **k=2** (not train-time k=4) so the signal is defined by bar 2. Empirically the sign of bar-proxy OFI correlates ~0.55–0.65 with next-bar return sign on equity index futures at 5-min; the magnitude decays faster than canonical tick OFI.

**VPIN bar-proxy.** Easley, López de Prado & O'Hara (2012, *Rev. Fin. Studies* 25(5):1457–1493) define `VPIN = (1/n) Σ |V_b - V_s| / V̄` with buy/sell volumes split by Bulk Volume Classification: `V_buy = V * Φ((c-o)/σ)`, `σ` being the rolling std of bar returns. Use a **cumulative volume-bucket accumulator** (not fixed-window) so VPIN is defined from bar 1 with wider CI. Bucket size: `V̄ * n` where `V̄` is train-window mean bar volume and n ∈ {20, 30, 50}. n=30 is the iter-3 default; consider 20 if prev_gain < 1.

## 2. Theoretical anchors

- **Cont-Kukanov-Stoikov (2014)** — OFI as price-pressure signal; linear impact coefficient. Justifies using *signed persistent OFI* as the directional trigger.
- **Easley-López de Prado-O'Hara (2012)** — VPIN as flow-toxicity measure; high VPIN ⇒ adverse selection risk ⇒ stand aside. Justifies VPIN as a **veto, not a signal**.
- **Kyle (1985)** *Econometrica* 53(6):1315–1335 — liquidity pricing scales with P(informed counterparty). Provides the adverse-selection backbone for why a VPIN veto is not just empirical curve-fitting but a rational response to expected inventory loss.

## 3. Recommended quantile thresholds (train-window calibrated)

All thresholds calibrated **from train-window distributions each round**, never hardcoded:

| Gate | Threshold | Rationale |
|---|---|---|
| `persistent_ofi_long` | 80th pct of train `persistent_ofi` | Top-quintile directional pressure |
| `persistent_ofi_short` | 20th pct (symmetric) | Mirror for shorts if enabled |
| `vpin_permit` | ≤ 60th pct | Trade only in low-toxicity regimes |
| `realized_vol_cap` | ≤ 75th pct of rolling 12-bar std | Avoid vol-blowout bars |
| `session_gate` | exclude first/last 15 min | Open/close microstructure distortions |

If `ctx.prev_gain < 0`, tighten OFI entry quantile to **85th pct** and VPIN permit to **50th pct** (Memory rule from cross_round: two consecutive losses triggers proxy re-examination).

## 4. Known bar-grain failure modes

1. **Choppy range days.** High `range` but small `|close-open|` makes OFI noise-dominated. **Mitigation:** the conviction ratio `|c-o|/range` already suppresses these; add a hard filter `|c-o|/range > 0.3` before counting a bar toward `persistent_ofi`.
2. **Gap opens.** Overnight gap inflates bar 1's `|close-open|` without genuine intrabar flow; OFI proxy will spuriously fire. **Mitigation:** skip entries on the first bar after a session break; require `k ≥ 2` persistent bars *within-session*.
3. **Low-volume drift bars.** Strong directional close with tiny volume — common in pre/post-session. OFI magnitude is volume-scaled so this is partially self-correcting, but add `volume > 25th pct` floor.
4. **BVC sign inversion on mean-reverting regimes.** VPIN assumes directional persistence; on strong mean-reversion days VPIN underestimates toxicity. **Mitigation:** augment VPIN with a realized-vol cap (above) so we don't solely rely on VPIN to flag regime change.
5. **3-bar warmup.** Paper window = 3 bars. `persistent_ofi` with k=2 is valid by bar 2; VPIN cumulative is valid by bar 1 but wide CI. **If no clean signal fires, do nothing** — break-even beats a forced trade.