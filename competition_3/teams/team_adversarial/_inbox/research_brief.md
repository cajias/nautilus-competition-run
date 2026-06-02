# Research Brief — Round 4, Iteration 0 (team_adversarial)

## Question Investigated

"The MACD momentum strategy hits WR=0.70 but gain=0.9926 on R4 train (2026-04-29 to 2026-05-20, BTCUSDT.BINANCE 5-MIN bars) because wins are too small — the 96-bar time-stop cuts winners before the 4% TP. What is the smallest change to win-size/exit-logic that pushes gain>1.0 while keeping WR>=0.5?"

## Autoresearch Invocation

```
/autoresearch
Goal: Find a strategy that not only clears the minimum gate (gain > 1.0,
      win_rate >= 0.5) but also achieves composite >= 1.2. Treat the minimum
      gate as necessary but not sufficient. After each candidate clears the
      minimum, run a stricter check: composite must exceed 1.2, else treat
      as a soft fail and continue iterating.
Scope: strategy.py — any modification, but prefer modifications that increase
       composite headroom rather than just barely clearing the gate. Start from
       the MACD(12,26)+EMA(100) momentum seed. Vary: TIME_STOP_BARS (192, 288,
       disabled), SL_PCT (1.0%, 1.5%), EMA_PERIOD (50, 100, 200), TP_PCT (3%, 4%, 5%).
Metric: primary: composite = gain_factor x win_rate; hard gate: gain > 1.0 AND
        win_rate >= 0.5; adversarial gate: composite > 1.2 (soft — loop continues
        if not met, but accept if iteration budget exhausted)
Verify: uv run python backtest.py --strategy attempts/000/inner_macd/strategy.py
Iterations: 5
--evals
```

## Top 3 Findings

### Finding 1: TIME_STOP is the gate-crossing knob — 96 to 288 fixes gain<1.0
**Claim:** Widening TIME_STOP_BARS from 96 to 288 moves gain from 0.9926 to 1.0019, crossing the hard gate.
**Evidence:** Iter1 direct measurement — same seed, only TIME_STOP changed; gain=0.9926 to 1.0019, 40 to 31 trades. The 96-bar stop was prematurely exiting winners before the 4% TP.
**Confidence:** HIGH (direct A/B, single change)

### Finding 2: Tighter SL (1.5%) adds marginal gain headroom without hurting WR
**Claim:** SL 2.0% to 1.5% with TIME_STOP=288 improves gain to 1.0157 with no WR change (still 0.5625, 31 trades).
**Evidence:** Iter2 measurement — gain 1.0019 to 1.0157, WR unchanged. The tighter stop cuts each losing trade's loss by 0.5% of position, adding roughly +0.014 gain across the 31-trade sample.
**Confidence:** HIGH

### Finding 3: Composite is LOWER than the baseline — WR decline from 0.70 to 0.5625 outweighs gain improvement
**Claim:** The adversarial composite (gain x WR) target of >1.2 is not achievable via parameter sweeps on this window. Best composite achieved: 0.5713 vs. baseline 0.6948.
**Evidence:** Baseline (TIME_STOP=96) had WR=0.70 because the 96-bar stop was functioning as a breakeven exit for many flat trades — they exited near 0% P&L rather than turning into SL hits. Widening the stop allows those trades to reverse into losses, dropping WR from 0.70 to 0.5625. Disabling the stop entirely (iter5) collapsed WR to 0.286. The 96-bar stop was therefore not purely hurting wins — it was also protecting against reversals on stalled momentum trades.
**Confidence:** HIGH — confirmed across 5 parameter combinations

## Strategy Direction for Strategist

Use the **iter2 configuration**: MACD(12,26,9) histogram-cross-above-zero + EMA(100) trend filter (price > EMA), TP=4%, SL=1.5%, TIME_STOP=288 bars (~24h), COOLDOWN=48 bars (4h), POSITION_FRACTION=0.90. This is the best parameter set found in 5 iterations: **gain=1.0157, WR=0.5625, 31 trades — minimum gate PASS**. The adversarial composite>1.2 target was not met (best composite=0.5713); per the team_adversarial preset rules this is a budget-exhaustion acceptance. The current state of `attempts/000/inner_macd/strategy.py` already has these exact parameters applied — the strategist should copy this file to the round's strategy path directly without modification. Robustness note: this 31-trade WR=0.5625 sample is more OOS-robust than any thin-trade-count WR=1.0 overfit — every small-sample train pass in this competition has died OOS, so the 31-trade distribution is the preferred submit even though composite is below 1.2.
