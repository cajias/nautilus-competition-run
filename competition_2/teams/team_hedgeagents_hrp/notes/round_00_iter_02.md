# round 0 iter 2

- prev_gain: -9.849765000002897e-05
- lookback_bars: 150
- disagree_threshold: 0.05
- drawdown_cap: 0.25
- weights: trend=0.179 mr=0.103 vol=0.717
- notes: Iter 2 budget conference: prev_gain=-9.85e-05 (sub-1bp, range regime confirmed across iters 0-1). Rotate lookback 300->150 to track BTC 5-min mean-reversion horizon. Floor disagree_threshold at 0.05 so mean-rev signals actually clear the gate (prior threshold was over-suppressing trades). mr_period=60 (schema cap) maximizes signal variance so HRP cluster-bisection naturally lifts mean-rev weight away from last iter's 9.4%. trend_period=50 keeps trend as a short regime-flip detector, not a primary engine. vol_period=60 retains 60v240 RV ratio but expects HRP to demote from last iter's 51.4% as trend-vol correlation tightens in low-vol. drawdown_cap=0.25 retained as free insurance on the 0.2 composite leg. NO experience-sharing rotation beyond lookback (loss is sub-bp); NO extreme-market trigger (loss << -10% threshold, no consecutive >=10% losses); NO spoke zero-out — let HRP rebalance organically once mean-rev variance dominates the orthogonal-cluster budget. max_weight_per_spoke=0.6 retained (no need to shrink toward 0.4 since not in extreme regime).
