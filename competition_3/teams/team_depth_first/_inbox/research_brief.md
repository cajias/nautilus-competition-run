# Research Brief — team_depth_first, Round 3, Iteration 0

## Question Investigated

Round-3 train window (slow grind upward, Apr 22 - May 13, 2026): The RSI mean-reversion
strategy that won Round 2 fails on Round 3 (gain=0.999, WR=0.5, FAIL). What MACD momentum
configuration maximizes composite = gain_factor × win_rate on the round-3 window?
Specifically: given MACD(12,26)>0 + EMA trend filter is the proven thesis, which EMA period
and which MACD fast/slow parameters produce the highest composite above the gate?

## Autoresearch Invocation Run

```
/autoresearch
Goal: Identify the single most promising strategy type from the diagnostics,
      then refine it across as many iterations as the budget allows.
      Prefer deep refinement of one approach over exploring new approaches.
Scope: strategy.py — refine indicator periods, signal thresholds, and position
       sizing for the approach chosen on iteration 1. Do NOT switch strategy type
       mid-run unless the backtester confirms zero chance of passing.
Metric: composite = gain_factor × win_rate; gate: gain_train > 1.0 AND win_rate_train >= 0.5;
        secondary: maximize composite margin above gate (not just barely pass)
Verify: uv run python backtest.py --strategy attempts/<iter>/strategy.py
Iterations: 5
--evals --evals-interval 2
```

## Top 3 Findings

### Finding 1: MACD(12,26,9) histogram cross above zero + EMA(100) is the winning config
**Claim**: MACD histogram crosses from ≤0 to >0, with price above EMA(100), MARKET entry,
TP=4%/SL=2% backstops, cooldown=48 bars, produces gain=1.017303, WR=0.70, 40 trades (PASS).
Composite = 1.017303 × 0.70 = **0.7121** — the best verified result.
**Evidence**: Directly verified with `uv run python backtest.py --strategy attempts/r3_macd_iter3/strategy.py`
→ `{"gain": 1.017303, "win_rate": 0.7, "num_trades": 40, "pass": true}`
**Confidence**: HIGH — live backtest on round-3 train window.

### Finding 2: EMA(100) beats EMA(200) significantly; EMA(50) fails
**Claim**: EMA period is the critical lever for round-3's slow-grind structure.
EMA(100) = 500 minutes = 8.3 hours captures the dominant intraday trend without being
either too lagging (EMA200) or too reactive (EMA50).
**Evidence** (all verified on round-3 window):
- EMA=50: gain=0.976, WR=0.50 → FAIL
- EMA=100: gain=1.017, WR=0.70 → PASS, composite=**0.7121** (BEST)
- EMA=150: gain=1.029, WR=0.65 → PASS, composite=0.6688
- EMA=200: gain=1.029, WR=0.65 → PASS, composite=0.6691
**Confidence**: HIGH — full EMA sweep, reproducible.

### Finding 3: MACD(12,26,9) is optimal; faster periods and shorter cooldown degrade metrics
**Claim**: MACD(8,21,9) with EMA(100) fails (gain=0.999, WR=0.50). Cooldown=24 bars
(vs 48) also fails (gain=0.988, WR=0.55). The standard MACD(12,26,9) with 48-bar cooldown
is the optimal parameterization for this window. TP/SL backstops (4%/2%) effectively never
fire — the 96-bar time-stop is the actual exit mechanism (plus TP hit on strong moves).
**Evidence**: r3_macd_iter4b (MACD 8,21,9): `{"gain": 0.999435, "win_rate": 0.5, "pass": false}`;
r3_macd_iter5b (cooldown=24): `{"gain": 0.987532, "win_rate": 0.55, "pass": false}`
**Confidence**: HIGH — both verified on round-3 window.

## Strategy Direction for Strategist

Use `attempts/r3_macd_iter3/strategy.py` as the production strategy for round 3. The winning
config is: **MACD(12,26,9) histogram cross above zero (prev_hist ≤ 0, curr_hist > 0) with
price above EMA(100), MARKET entry, TP=4.0%, SL=2.0% (backstops — rarely fire), 96-bar
time-stop, 48-bar cooldown, 90% position fraction.** This delivers gain=1.017, WR=0.70,
40 trades, composite=0.7121 — the strongest verified result in the round-3 slow-grind regime.
Do NOT use RSI mean-reversion (fails at gain=0.999). Do NOT tighten EMA below 100 (EMA=50
fails). Do NOT shorten cooldown below 48 bars. The EMA(100) filter is the key differentiator:
it improves WR from 0.65 to 0.70 versus EMA(200) by better fitting the intraday 8.3-hour
trend structure of the round-3 window. Note: prior rounds had OOS scoring 0 with MACD momentum;
strategist should be aware of potential overfit but the train gate is confirmed passing with
healthy margin (composite 42% above the WR=0.5 floor).

## Best Strategy File

`/Users/rc/Projects/workspace/nautilus-competition-run/competition_3/teams/team_depth_first/attempts/r3_macd_iter3/strategy.py`

Verified: `{"gain": 1.017303, "win_rate": 0.7, "num_trades": 40, "pass": true}`
Composite: 1.017303 × 0.70 = **0.7121**

## Iteration Log

| iter | config | gain | WR | trades | pass | composite |
|---|---|---|---|---|---|---|
| baseline | RSI dip-buy (Round 2) on Round 3 window | 0.999 | 0.50 | 39 | FAIL | 0 |
| r3_iter1 | MACD(12,26,9)+EMA(200) TP=4% SL=2% | 1.029 | 0.65 | 40 | PASS | 0.6691 |
| r3_iter2 | MACD(12,26,9)+EMA(200) TP=5% SL=2.5% | 1.029 | 0.65 | 40 | PASS | 0.6691 (no change) |
| r3_iter3 | MACD(12,26,9)+EMA(100) TP=4% SL=2% | 1.017 | 0.70 | 40 | PASS | **0.7121** ← BEST |
| r3_iter4 | MACD(12,26,9)+EMA(50) TP=4% SL=2% | 0.976 | 0.50 | 40 | FAIL | 0 |
| r3_iter5 | MACD(12,26,9)+EMA(150) TP=4% SL=2% | 1.029 | 0.65 | 40 | PASS | 0.6688 |
| r3_iter4b | MACD(8,21,9)+EMA(100) TP=4% SL=2% | 0.999 | 0.50 | 40 | FAIL | 0 |
| r3_iter5b | MACD(12,26,9)+EMA(100) cooldown=24 | 0.988 | 0.55 | 40 | FAIL | 0 |
