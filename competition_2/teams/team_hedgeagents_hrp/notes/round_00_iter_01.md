# round 0 iter 1

- prev_gain: -4.193959999998498e-05
- lookback_bars: 200
- disagree_threshold: 0.1
- drawdown_cap: 0.2
- weights: trend=0.428 mr=0.174 vol=0.398
- notes: Iter 1. prev_gain=-4.19e-5 (flat micro-loss). Experience-sharing conference fires; extreme-market does NOT (loss far below 10pct threshold, no second consecutive loss yet). Diagnosis: iter-0 HRP weights (trend=0.186, mr=0.343, vol=0.471) plus disagree_threshold=0.15 likely suppressed nearly all trades on the eval window — HRP did its job but the composite never cleared the gate. Pivots: (1) rotate hrp_lookback_bars 500->200 per experience-sharing protocol (prior regime may have been longer than reality); (2) drop disagree_threshold 0.15->0.10 (still 2x critic floor of 0.05) to let medium-conviction composites through and stop fee-free idleness; (3) shorten trend_period 100->60 and mr_period 30->20 to widen horizon gap between trend and mean-rev, improving HRP cluster separation by lowering signal-time-series correlation. Keep max_weight_per_spoke=0.6 (no extreme-market trigger) and drawdown_cap=0.20 (over-indexing composite max_drawdown weight is the team's edge). vol_period stays 30 (already orthogonal). Researcher JSON not present at attempts/001/research.json; proceeded on budget+experience-sharing conferences using iter-0 ledger as memory. Note: file write to attempts/001/hub_manager.json blocked by harness sandbox; stdout is authoritative per CLAUDE.md contract.
