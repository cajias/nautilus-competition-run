# Evals Summary — loop-260602-1058

## Metric Progression
- Iter 0 (baseline RSI/round-2): composite=0.499 → FAIL
- Iter 1 (MACD+EMA200): composite=0.6691 → PASS
- Iter 3 (MACD+EMA100): composite=0.7121 → PASS ← BEST

## Kept: 2/5 | Discarded: 3/5 (TP/SL variant, EMA sweep losers, MACD fast params)

## Top 3 Most Effective Changes
1. Switching RSI mean-reversion → MACD histogram momentum (+34.5% composite)
2. EMA(200) → EMA(100) (+6.4% composite: 0.6691 → 0.7121)
3. MACD(12,26,9) is optimal; faster MACD(8,21) and shorter cooldown both degrade metrics

## Key Finding
EMA period is the critical lever for this round-3 slow-grind window. EMA=100 (500 min = 8.3h)
better fits the medium-term trend structure than EMA=200. TP/SL backstops (4%/2%) never fire —
the time-stop at 96 bars is the actual exit mechanism alongside reaching TP naturally.

## Recommendation
Use attempts/r3_macd_iter3/strategy.py as the production strategy for round 3.
Config: MACD(12,26,9)+EMA(100), TP=4%, SL=2%, cooldown=48bars, position=90%.
Verified: gain=1.017303, WR=0.70, trades=40, PASS, composite=0.7121.
