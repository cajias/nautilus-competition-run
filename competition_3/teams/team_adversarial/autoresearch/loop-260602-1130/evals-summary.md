# Evals Summary — R4 autoresearch loop-260602-1130

## Run Config
- Seed: attempts/000/inner_macd/strategy.py (MACD(12,26)+EMA(100) TP=4% SL=2% TIME_STOP=96 COOLDOWN=48)
- Goal: Push gain>1.0 + WR>=0.5, adversarial target composite>1.2
- Iterations: 5

## Results Table
| Iter | Change | gain | WR | trades | composite | status |
|------|--------|------|----|--------|-----------|--------|
| 0 | baseline | 0.9926 | 0.700 | 40 | 0.6948 | FAIL |
| 1 | TIME_STOP 96→288 | 1.0019 | 0.5625 | 31 | 0.5636 | PASS |
| 2 | +SL 2%→1.5% | 1.0157 | 0.5625 | 31 | 0.5713 | PASS |
| 3 | +EMA 100→200 | 1.0035 | 0.6154 | 25 | 0.6177 | PASS |
| 4 | EMA→100, TP 4%→5% | 1.0157 | 0.5625 | 31 | 0.5713 | PASS |
| 5 | TIME_STOP disabled | 1.0008 | 0.2857 | 13 | 0.2860 | FAIL |

## Best Config
TIME_STOP=288 + SL=1.5% + TP=4% + EMA(100) + MACD(12,26,9) + COOLDOWN=48
- gain=1.0157, WR=0.5625, 31 trades, composite=0.5713
- Min gate: PASS. Adversarial gate (>1.2): NOT MET (budget exhausted)

## Key Finding
The 96-bar time-stop was the blocking issue — widening to 288 moved gain from 0.9926 to 1.0019 (crossed 1.0). The tradeoff was WR dropped from 0.70→0.5625 as some trades that previously exited at breakeven via time-stop now hit SL. Composite actually DECREASED from 0.6948 to 0.5713 because WR decline outweighed gain improvement. The adversarial composite>1.2 target was not achievable in 5 iterations on this window.
