# round 0 iter 3

- prev_gain: -0.00033678913000001476
- lookback_bars: 100
- disagree_threshold: 0.05
- drawdown_cap: 0.25
- weights: trend=0.183 mr=0.346 vol=0.470
- notes: Iter 3 (4th consecutive sub-bp loss, prev_gain=-3.4e-4). Three losses in a row triggers extreme-market conference per CLAUDE.md (>=2 consecutive prev_gain<=0), but losses are sub-bp << -10% so no spoke zero-out. Diagnosis: range regime confirmed; allocator pathology — vol_carry hoarded 71.7% in iter 2 while mean_rev (the structural winner in range) was stranded at 10.3%. Triple-fix per researcher: (a) max_weight_per_spoke 0.6→0.45 to forcibly break vol_carry monopoly and route budget to mean-rev cluster; (b) hrp_lookback_bars 150→100 to track BTC 5-min reversion half-life and rotate lookback after 4 losses (experience-sharing conference); (c) shorten all spoke periods (trend 50→30, mr 60→30, vol 60→30) so mean-rev z-score variance dominates HRP inverse-variance bisection arithmetic, which currently mistakes vol_carry's smoothness for low risk. Keep disagree_threshold at 0.05 floor and drawdown_cap=0.25. Contingency: if iter 4 still loses, force vol_carry zero-out (true extreme-market spoke cap).
