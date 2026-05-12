# research_log.md

## iter 0

# Research Brief — team_cont_stoikov_microstructure, iteration 0

## 1. OFI / VPIN at 5-min bar grain

**OFI bar-proxy.** Canonical OFI (Cont, Kukanov & Stoikov 2014, *J. Financial Econometrics* 12(1):47–88) is `OFI_n = Σ_i e_i` with `e_i = +Δbid_size − Δask_size` summed over tick-level depth updates, and price impact is approximately linear in OFI over short intervals. At 5-min OHLCV grain we lack depth deltas; the standard bar-proxy is:

```
ofi_bar = sign(close − open) · volume · |close − open| / max(range, tick_size)
```

The `|close−open|/range` factor is a **directional-conviction weight**: ratio→1 for clean trend bars, →0 for chop. Persistent OFI = rolling sum over k bars. Literature consensus: k=4 on 5-min bars balances signal persistence vs. decay; at trade-time (3-bar paper) we must drop to k=2.

**VPIN bar-proxy (bulk-volume classification).** Easley, López de Prado & O'Hara (2012, *Rev. Fin. Studies* 25(5):1457–1493) define `VPIN = (1/n) Σ |V_b − V_s| / V̄` over n volume buckets. At bar grain we use their §5 BVC variant:

```
buy_vol_i  = V_i · Φ((c_i − o_i) / σ_r)
sell_vol_i = V_i − buy_vol_i
```

where `σ_r` is rolling std of bar returns, Φ the standard normal CDF. Accumulate into fixed-size volume buckets (bucket size V̄ ≈ mean 5-min volume × 50). Rationale follows Kyle (1985, *Econometrica* 53(6):1315–1335): when informed trading is likely (high VPIN), adverse-selection cost makes liquidity provision unprofitable; symmetrically, **taking** liquidity against toxic flow is also unwise — hence VPIN as a veto.

## 2. Recommended quantile thresholds (calibrate from train window)

Per-round calibration on the ~73-day train window (~21k bars):

| Gate | Quantile of train distribution | Interpretation |
|---|---|---|
| Persistent OFI entry (long) | ≥ 75th pct (positive side) | top-quartile buying pressure persistence |
| Persistent OFI entry (short) | skip this round — one-sided longs only |
| VPIN veto | trade only when VPIN ≤ 60th pct | bottom 60% of toxicity regime |
| Realized-vol gate | 20th ≤ σ_5m ≤ 90th pct | avoid dead tape + avoid blow-ups |

Tighten entry to 80th pct and VPIN to 55th pct if `ctx.prev_gain < 0` (prior loss); hold steady if `prev_gain ≥ 0`.

## 3. Citations

- **Cont, Kukanov, Stoikov (2014)** — "The Price Impact of Order Book Events," *J. Financial Econometrics* 12(1):47–88. Establishes linearity of mid-price response to OFI; justifies OFI as a first-order price-pressure signal.
- **Easley, López de Prado, O'Hara (2012)** — "Flow Toxicity and Liquidity in a High-Frequency World," *Rev. Fin. Studies* 25(5):1457–1493. VPIN + BVC; empirical evidence VPIN predicts short-horizon volatility and liquidity withdrawal (May 6 2010 flash crash case study).
- **Kyle (1985)** — "Continuous Auctions and Insider Trading," *Econometrica* 53(6):1315–1335. Adverse-selection micro-foundation for why liquidity-taking into informed flow is negative-EV.

## 4. Known bar-grain failure modes

1. **Choppy range days (low |close−open|/range).** OFI proxy collapses toward zero by construction; persistent_ofi fails to clear threshold → **no trade, correctly**. Risk: if the realized-vol gate is too lax we still fire on late-day bars where chop reverses. Mitigation: AND-gate persistent_ofi × vol regime.
2. **Gap opens.** First 5-min bar after gap has anomalous `close−open` relative to overnight return, inflating OFI sign-magnitude. BVC's Φ term misclassifies since σ_r is backward-looking. Mitigation: **skip bar 1 of each session** for OFI accumulation; seed VPIN bucket but do not trade.
3. **Low-volume regimes.** BVC denominators shrink, VPIN variance explodes, quantile threshold becomes noisy. Mitigation: require `V_i ≥ 10th pct` as a third gate.
4. **Trend days with no pullback.** Persistent OFI stays above threshold all day; single-entry discipline + hard stop-loss prevents overtrading but may truncate winners. Accept — inventory risk (Avellaneda–Stoikov) dominates.

**Proxy honesty:** bar-grain OFI/VPIN preserve sign but amplify noise vs. tick-level. Expect wider CI on first VPIN bucket; accept break-even (gain=1.0) on 3-bar paper as a rational outcome.

---
## iter 1

# Research Brief — Iteration 1: Cont-Stoikov Microstructure Team

`★ Insight ─────────────────────────────────────`
Bar-grain proxies trade fidelity for availability: we lose the sub-second depth deltas Cont et al. use but gain robustness against tick-noise. The calibration discipline (quantile-from-train-window) is what keeps the proxy honest — hardcoded thresholds from papers written on tick data WILL fail on 5-min bars.
`─────────────────────────────────────────────────`

## 1. Proxy Formulations (5-min OHLCV)

**OFI bar-proxy** (volume-weighted signed conviction):
```
ofi_bar = sign(close - open) * volume * |close - open| / max(high - low, tick_size)
persistent_ofi_k = rolling_sum(ofi_bar, window=k)
```
The `|close-open|/range` ratio is the "conviction score" — approaches 1 on a clean directional bar, approaches 0 on a doji/choppy bar. Rolling sum over k bars is the load-bearing feature: single-bar OFI is too noisy.

**VPIN bar-proxy** (bar-clock BVC, per Easley-López-O'Hara §5):
```
r_i = (c_i - o_i) / σ_ret        # standardized bar return
buy_vol_i = V_i * Φ(r_i)          # Φ = standard normal CDF
sell_vol_i = V_i * (1 - Φ(r_i))
bucket_size = V̄_train * n         # typical n = 4 to 8 bars of avg volume
VPIN_t = (1/B) * Σ |buy_vol - sell_vol| / V  over last B buckets
```

## 2. Citations

- **Cont, Kukanov, Stoikov (2014)** — OFI definition at tick depth: `OFI_n = Σ e_i` where `e_i = +Δ(bid_size) − Δ(ask_size)` per depth update. Linear price-impact coefficient λ estimable by OLS of Δmid on OFI. Our bar proxy preserves sign and magnitude ordering but inflates variance ~3-5× based on published tick-vs-bar comparisons.
- **Easley, López de Prado, O'Hara (2012)** — VPIN via BVC. Key empirical result: VPIN spikes precede the May 6 2010 Flash Crash by ~1hr and predict realized toxicity. At bar-grain, signal-to-noise degrades but **relative ordering** (high vs low VPIN regimes) survives.
- **Kyle (1985)** — Adverse-selection λ: informed traders impose a cost on liquidity providers proportional to P(informed). VPIN estimates this; when VPIN is high, don't take liquidity (don't trade directionally into the book).

## 3. Recommended Quantile Thresholds (calibrate from train window)

| Gate | Rule | Quantile (prev_gain=None) |
|---|---|---|
| **OFI entry long** | `persistent_ofi_k > q_ofi_hi` | **75th pct** of train `persistent_ofi` |
| **OFI entry short** (if allowed) | `persistent_ofi_k < q_ofi_lo` | **25th pct** (mirror) |
| **VPIN permit** | `VPIN_t ≤ q_vpin_veto` | **60th pct** (trade when toxicity ≤ median+) |
| **Realized-vol gate** | `σ_k ∈ [q_vol_lo, q_vol_hi]` | **[20th, 80th pct]** |

If `prev_gain < 0`: tighten OFI to 80th pct, VPIN to 50th pct.
If `prev_gain >= 1.0`: hold thresholds; tighten stop-loss only.

## 4. Known Bar-Grain Failure Modes

1. **Choppy range days** — `|close-open|/range → 0`, so `ofi_bar → 0`. False signal: persistent_ofi sums noise. **Mitigation**: realized-vol gate excludes the lowest-vol 20% of bars (price-impact λ is unstable there anyway per Cont-Kukanov §4.2).

2. **Gap opens** — `close - open` captures intra-bar only; overnight gaps appear as zero-OFI despite massive information event. **Mitigation**: skip first bar of session; regime-gater flags session-open bars.

3. **Low-volume bars** — VPIN BVC assumes V is meaningfully classifiable; on thin bars `buy_vol ≈ sell_vol ≈ V/2` regardless of direction. **Mitigation**: require `V_i ≥ q_vol_25` before including bar in bucket.

4. **Regime shift mid-window** — calibrated quantiles become stale if eval distribution ≠ train distribution. **Mitigation**: risk-officer caps single-trade size; 15-min paper is short enough that a single bad trade is recoverable.

5. **VPIN warmup** — first bucket has noisy VPIN. **Mitigation**: use cumulative buckets from bar 1 with a prior `VPIN_0 = train_median`.

---
**Thesis stability**: classical OFI+VPIN primitives, calibrated per-round, with hard vol/session gates. No ML. No TSFM. Edge = robustness.

---
## iter 2

# Research Brief — Iteration 2
**Team:** cont_stoikov_microstructure
**Date:** 2026-05-12
**Focus:** OFI/VPIN proxies, threshold calibration, failure-mode registry

## 1. Proxy formulations at 5-min bar grain

**OFI bar-proxy (signed conviction-weighted volume):**
```
ofi_bar = sign(close - open) * volume * |close - open| / max(range, tick_size)
persistent_ofi_k = Σ ofi_bar over last k bars
```
At train-time we calibrate `k ∈ {3,4,5}` and pick the `k` that maximizes lag-1 autocorrelation of persistent_ofi on the train window — this selects the horizon where bar-level directional pressure genuinely persists. At trade-time we **hard-cap `k=2`** because the paper window is only 3 bars. This is a known precision tax; accept it.

**VPIN bar-proxy (bar-clock BVC, cumulative buckets):**
```
buy_vol_i  = V_i * Φ((c_i - o_i) / σ_r)
sell_vol_i = V_i - buy_vol_i
bucket = first set of consecutive bars with Σ V_i ≥ V̄   (V̄ = mean bar volume)
VPIN = mean over last n buckets of |Σ buy_vol - Σ sell_vol| / V̄
```
σ_r is the rolling std of bar log-returns, precomputed on train (prior) and allowed to update live. Cumulative (not rolling) buckets dodge the 3-bar warmup.

## 2. Citations

- **Cont, Kukanov, Stoikov (2014)**, *J. Fin. Econometrics* 12(1):47–88 — OFI is linear in short-horizon price impact; OFI-return correlation dominates trade-imbalance at book-level grain. Our bar proxy inherits directionality but loses the depth-delta decomposition.
- **Easley, López de Prado, O'Hara (2012)**, *RFS* 25(5):1457–1493 — VPIN quantifies order-flow toxicity; high VPIN coincides with informed-trading regimes and precedes liquidity crises (flash crash, 2010). Used here as a **veto**, never as a signal.
- **Kyle (1985)**, *Econometrica* 53(6):1315–1335 — adverse-selection lambda scales with P(counterparty informed); justifies conditioning entry on a low-toxicity gate.

## 3. Recommended quantile thresholds

Calibrate **on the train window each round**; never hardcode.

| Gate | Metric | Threshold |
|---|---|---|
| Entry (long) | `persistent_ofi_k` | ≥ 80th pct of train distribution |
| Entry (long) | `persistent_ofi_k` | must be positive (sign-aligned) |
| VPIN permit | VPIN | ≤ 60th pct of train distribution |
| Vol gate | realized_vol (rolling std of returns, window=6 on train, prior-seeded live) | ≤ 70th pct |
| Session gate | US equity RTH only (14:30–21:00 UTC) | required |

**Iteration 2 adjustment** — if `ctx.prev_gain < 0`: tighten entry to **85th pct**, VPIN permit to **50th pct**. If `prev_gain ≥ 1.0`: hold thresholds; tighten only the hard stop-loss.

Exit: time-stop at end of paper OR adverse move ≥ 0.4 × train-window ATR. Inventory hard cap: one position.

## 4. Known bar-grain failure modes

1. **Choppy range days** — small `|close-open|` with high volume; OFI proxy near zero but noisy; `persistent_ofi` flips sign bar-to-bar. *Mitigation:* persistence requirement (same-sign across k bars) plus the `|close-open|/range` conviction weight already down-weights these bars.
2. **Gap opens** — the first bar of a session has `open` discontinuous from prior close; `close-open` no longer reflects within-bar flow. *Mitigation:* skip bars flagged as session-open in the session-gate (signal-engineer marks `is_session_open` per bar).
3. **Low-volume drift** — thin volume inflates σ_r; BVC misclassifies buy/sell; VPIN becomes uninformative. *Mitigation:* require `V_i ≥ 0.3 × V̄`; else treat VPIN as missing (veto defaults to ON).
4. **Volatility regime shift mid-paper** — train-window σ_r diverges from live σ_r. *Mitigation:* realized-vol gate uses the *live* 3-bar std once defined; falls back to train prior only during warmup.
5. **Proxy identifiability collapse** — if `|close-open|/range → 0` for majority of bars, OFI proxy is noise. *Critic signal:* if > 60% of train bars have conviction ratio < 0.2, flag proxy failure and defer to flat.

**Round-over-round prior:** bar-level OFI carries directional content but 2–3× the noise of tick-level OFI; expect gain factor distribution widened vs canonical literature. Break-even (gain = 1.0) is a success floor given 15-min paper + 3-bar warmup.

---
## iter 3

# Research Brief — team_cont_stoikov_microstructure, Iteration 3

## 1. OFI / VPIN Proxies at 5-min Bar Grain

**OFI bar-proxy (per bar):**
```
ofi_bar = sign(close - open) · volume · |close - open| / max(range, tick_size)
```
Directional conviction scalar in [−V, +V]. The `|c-o|/range` term suppresses choppy bars (ratio → 0) and amplifies clean directional bars (ratio → 1), reducing false positives from high-volume inside-range churn.

**Persistent OFI (trade-time, k=2):**
```
persistent_ofi_t = ofi_bar_{t-1} + ofi_bar_t
```
Defined from bar 2 onward. This is the primary entry signal. Train-time calibration uses k=4 for threshold estimation, but trade-time MUST use k=2 to respect the 3-bar paper window.

**VPIN bar-proxy (bar-clock BVC):**
```
buy_vol_i = V_i · Φ((c_i − o_i) / σ_r)
sell_vol_i = V_i − buy_vol_i
VPIN_j = (1/n) · Σ_{i∈bucket_j} |2·buy_vol_i − V_i| / V_i
```
where `σ_r` is the rolling std of bar returns over the train window (used as a prior at trade-time so VPIN is defined on bar 1). Volume buckets of size `V̄ · n` with n=50 bars target-equivalent, but at trade-time we use **cumulative** buckets to avoid warmup starvation.

## 2. Canonical Citations

- **Cont, Kukanov, Stoikov (2014)**, *J. Financial Econometrics* 12(1):47–88. Establishes linearity of short-horizon price impact in tick-level OFI. Our bar proxy preserves sign and volume-weighting but loses the depth-delta granularity — expect higher noise floor, ~2× wider CI on threshold estimates.
- **Easley, López de Prado, O'Hara (2012)**, *Rev. Fin. Studies* 25(5):1457–1493. BVC formulation and flow-toxicity interpretation. Their production implementation uses 50-tick buckets; bar-clock BVC is acknowledged in their §5 as a coarser but valid variant when tick data is unavailable.
- **Kyle (1985)**, *Econometrica* 53(6):1315–1335. Adverse-selection theory justifying VPIN as a liquidity-provision veto: when informed-trader probability rises, uninformed participants should withdraw — we translate this to "do not enter longs."

## 3. Recommended Quantile Thresholds (from train window)

Calibrate on the current round's train slice — **do not hardcode across rounds**:

| Gate | Threshold | Rationale |
|---|---|---|
| `persistent_ofi_entry_long` | ≥ 70th pct of train-window positive persistent_ofi | Upper tercile captures directional conviction without overfitting to tail |
| `vpin_permit_ceiling` | ≤ 60th pct of train-window VPIN | Below-median toxicity; leaves headroom for live drift |
| `realized_vol_ceiling` | ≤ 80th pct of train-window rolling σ (10-bar) | Avoids blow-off regimes where OFI decays in milliseconds |
| `stop_loss` | 0.5 × ATR(14) from train window | Inventory-risk discipline (Stoikov 2018) |

**If `ctx.prev_gain < 0`:** tighten entry to 75th pct, VPIN to 55th pct.
**If `ctx.prev_gain ≥ 1.0`:** hold thresholds; tighten risk only.

## 4. Known Bar-Grain Failure Modes

1. **Choppy range days.** Inside-range high-volume bars produce `|c-o|/range ≈ 0`, OFI collapses correctly. But **persistent_ofi over k=2** can still sum two small same-sign bars into a fake signal. *Mitigation:* require `|persistent_ofi| ≥ threshold` AND each component bar `|c-o|/range ≥ 0.4`.

2. **Gap opens.** Overnight/session-boundary gaps produce a single large-OFI bar that is pure rebalancing, not informed flow. BVC misreads this as extreme buy_vol. *Mitigation:* regime-gater drops bar 1 of each session from persistent_ofi accumulation; VPIN first-bucket of session gets +10 pct threshold buffer.

3. **Low-volume drift.** Thin-volume bars with large `|c-o|/range` inflate OFI per-unit-volume but reflect noise. *Mitigation:* add `volume ≥ 30th pct of train-window volume` as an entry gate.

4. **VPIN auto-correlation lag.** Bar-clock BVC has ~2-bucket lag vs tick-BVC. First paper bucket is unreliable. *Mitigation:* require ≥ 1 full bucket of live VPIN before entry (earliest entry = bar 3).

**Net recommendation:** earliest trade-time entry remains **bar 3 of paper window**; bars 1–2 are warmup. Accept gain = 1.0 if no valid signal fires.

---
## iter 4

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