# round 0 iter 2

- prev_gain: -0.00013471726000002793
- lookback_bars: 350
- disagree_threshold: 0.07
- drawdown_cap: 0.2
- weights: trend=0.367 mr=0.159 vol=0.474
- notes: Iter 2. prev_gain=-1.35e-4 (flat micro-loss). Ledger: iter 0 (lookback=500, thr=0.15) -> -4.19e-5; iter 1 (lookback=200, thr=0.10) -> small loss. Persistent under-trading (composite never clears gate), not risk overshoot. Experience-sharing fires; extreme-market does NOT (|loss| << 10pct, no second consecutive >=1pct loss). Pivots: (1) bisect HRP lookback 200/500 -> 350 (neither extreme cleared the gate); (2) drop disagree_threshold 0.10 -> 0.07 (still above 0.05 critic floor) to admit medium-conviction composites; (3) keep trend_period=60, mr_period=20, vol_period=30 from iter 1's orthogonality tuning -- horizons remain well-separated for HRP cluster diversification; (4) hold drawdown_cap=0.20 (team over-indexes on composite max_drawdown weight, our edge); (5) hold max_weight_per_spoke=0.6 -- no extreme-market trigger so no spoke veto. Researcher JSON absent at attempts/002/research.json; proceeded on budget + experience-sharing conferences only. File write to attempts/002/hub_manager.json blocked by harness sandbox (same as iter 1); stdout is authoritative per CLAUDE.md contract.
