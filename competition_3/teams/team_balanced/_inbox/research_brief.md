# Research Brief — Round 4, Iteration 0 (team_balanced)

**Target window**: 2026-04-29T00:00:00Z -> 2026-05-20T00:00:00Z (ROUND_INDEX=4, 6048 BTC 5-min bars)
**Regime**: Moderate uptrend with EMA(200) acting as reliable support. Price sustained above
EMA(200) for most of the window. MACD histogram cross-above-zero signals capture momentum
entries reliably when combined with EMA(200) filter.

---

## Question Investigated

"This is iteration 1 (no prev_gain from a prior failing attempt, fresh round-4 context):
Across the round-4 BTC window (04-29->05-20), which short-horizon pattern has the
strongest backtest evidence and can be implemented with nautilus-trader indicators?"

---

## Autoresearch Invocation

```
Goal: Find a reliable strategy that clears the pass gate. Balance exploration
      of different approaches with refinement of promising ones.
Scope: strategy.py — consider 2-3 strategy types on iteration 1, then refine
       the most promising across remaining iterations.
Metric: composite = gain_factor × win_rate; gate: gain_train > 1.0 AND win_rate_train >= 0.5
Verify: uv run python /Users/rc/Projects/workspace/nautilus-competition-run/competition_3/teams/team_balanced/_inbox/run_train_backtest.py
Iterations: 5
```

---

## Top 3 Findings

### Finding 1: MACD histogram cross + EMA(200) is the strongest pattern for round-4 window
**Claim**: MACD(12,26) histogram crossing from <=0 to >0, filtered by price > EMA(200),
produces a composite of 0.6167 — the best of all tested approaches.
**Evidence**: Engine-verified: gain=1.002334, WR=0.6154, 25 trades, composite=0.6167, pass=true.
Compared to baseline RSI strategy: composite=0.5524 (+11.6% improvement).
MACD hist cross tested in two flavors: EMA(100) gives composite=0.5676, EMA(200) gives 0.6167.
**Confidence**: HIGH. Directly measured on confirmed round-4 window via backtest harness.

### Finding 2: EMA(200) is a more powerful trend filter than EMA(100) in this window
**Claim**: Switching from EMA(100) to EMA(200) as the trend filter improves WR from 0.5625 to
0.6154, reducing trade count from 31 to 25 (filtering out lower-quality MACD signals).
**Evidence**: EMA(100): gain=1.00911, WR=0.5625, composite=0.5676. EMA(200): gain=1.0023,
WR=0.6154, composite=0.6167. EMA(200) is stricter (price must sustain above longer MA),
removing false signals in short-lived mini-rallies.
**Confidence**: HIGH. Direct A/B test on the same engine and window.

### Finding 3: TIME_STOP=288 bars (24h) is the optimal exit mechanism — not TP
**Claim**: Most position exits in this window are via the 288-bar time-stop, not the 4% TP.
The TP threshold (3%/4%/5%) makes no difference to outcomes because price rarely reaches 4%
in 24h. The time-stop acts as the primary exit, booking partial gains or limiting losses.
**Evidence**: TP=3%, TP=4%, TP=5% all produce identical results (gain=1.002334, WR=0.6154,
25 trades). Disabling TIME_STOP (set to 9999) drops to 13 trades with WR=0.286, fails gate.
SL=1.5% is the critical tight-stop parameter — SL=1.0% over-cuts (WR=0.43, fail),
SL=2.0% allows too much loss (gain=0.997, fail).
**Confidence**: HIGH. Systematically tested all exit parameter variations.

---

## Failed Approaches Table

| Approach | gain | WR | Composite | Status |
|---|---|---|---|---|
| Baseline RSI<30+RSI>55exit MARKET, TP=2.5%/SL=2.0%, TIME_STOP=144 | 1.004 | 0.55 | 0.552 | PASS (baseline) |
| MACD value>0 + EMA(100) (not hist cross) | 0.985 | 0.45 | - | FAIL |
| MACD hist cross + EMA(100), COOL=48 | 1.009 | 0.5625 | 0.568 | PASS (inferior) |
| MACD hist cross + EMA(100), COOL=24 | 0.986 | 0.444 | - | FAIL |
| MACD hist cross + EMA(100), COOL=72 | 0.999 | 0.5625 | - | FAIL |
| MACD hist cross + EMA(200), SL=1.0% | 0.987 | 0.43 | - | FAIL |
| MACD hist cross + EMA(200), SL=2.0% | 0.997 | 0.615 | - | FAIL |
| MACD hist cross + EMA(200), TIME_STOP=576 | 1.000 | 0.40 | - | FAIL |
| MACD hist cross + EMA(200), TIME_STOP=144 | 1.003 | 0.60 | 0.602 | PASS (inferior) |
| MACD(6,13) hist cross + EMA(200) | 0.997 | 0.538 | - | FAIL |
| RSI<30+EMA(200) filter, TP=2.5%/SL=2.0% | 1.001 | 0.55 | 0.550 | PASS (inferior) |
| **MACD(12,26) hist cross + EMA(200), TP=4%/SL=1.5%/TIME_STOP=288/COOL=48** | **1.002** | **0.615** | **0.617** | **BEST PASS** |

---

## Empirically Verified Passing Strategy — RECOMMENDED CONFIG

**Backtest result (2026-04-29 to 2026-05-20 window, verified)**:
- gain_train = 1.002334 (PASS: > 1.0)
- win_rate_train = 0.6154 (PASS: >= 0.5)
- closed_trades = 25 (engine stops after 20 positions = 40 fills, but 25 trades here)
- composite = 0.6167 (best of all tested)
- pass = true

**Strategy parameters**:
- MACD_FAST = 12, MACD_SLOW = 26
- EMA_PERIOD = 200 (price must be above EMA(200) to enter)
- Signal: MACD histogram crosses from <= 0 to > 0 (momentum turn up)
- TP_PCT = 0.040 (4% take-profit — safety bracket, rarely reached)
- SL_PCT = 0.015 (1.5% stop-loss — critical, tighter or wider both fail)
- TIME_STOP_BARS = 288 (~24h zombie backstop — primary exit mechanism)
- COOLDOWN_BARS = 48 (4h between entries)
- Entry: MARKET order
- TRADE_NOTIONAL_USDT = 500.0
- Indicator: MovingAverageConvergenceDivergence(12, 26) from nautilus_trader.indicators
- Import: `from nautilus_trader.indicators import MovingAverageConvergenceDivergence, ExponentialMovingAverage`
- Note: Use `MovingAverageConvergenceDivergence` (NOT `MACD` — that name does NOT exist in nautilus_trader.indicators)

---

## Strategy Direction for Strategist

The round-4 window (04-29 to 05-20) favors a MACD momentum strategy over mean-reversion
RSI dip-buying. The key insight is: (1) MACD histogram cross-above-zero (prev_hist<=0,
cur_hist>0) combined with price > EMA(200) identifies high-quality momentum entries,
(2) EMA(200) provides a strong trend filter that raises WR to 0.615 by eliminating signals
during counter-trend moves, (3) the primary exit is the 288-bar time-stop (not TP),
so the TP threshold is irrelevant but SL=1.5% is critical. The strategist should implement
EXACTLY this pattern: MACD histogram cross + EMA(200) + MARKET bracket with TP=4%/SL=1.5%,
TIME_STOP=288, COOLDOWN=48. The strategy.py skeleton is already at
`attempts/000/strategy.py` (MACD+EMA200, verified passing). Do NOT change EMA period,
SL, or TIME_STOP without re-testing — they are all at local optima.
