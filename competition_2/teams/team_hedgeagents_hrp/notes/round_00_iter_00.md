# round 0 iter 0

- prev_gain: None
- lookback_bars: 500
- disagree_threshold: 0.15
- drawdown_cap: 0.2
- weights: trend=0.186 mr=0.343 vol=0.471
- notes: Iter 0 cold start. prev_gain=None, no leaderboard, no researcher JSON. Budget conference only (experience-sharing and extreme-market sit out without prior loss signal). lookback=500 5min-bars (~1.7d) keeps the 3x3 spoke-signal correlation matrix well-conditioned while leaving ~5548 signal bars on the 21-day eval window. max_weight_per_spoke=0.6 prevents mono-spoke collapse but lets HRP express conviction when one cluster dominates. drawdown_cap=0.20 tight to over-index the composite's 0.2 max_drawdown weight (HRPs whole point is drawdown-aware diversification). disagree_threshold=0.15 well above the 0.05 critic floor to suppress trade-fee bleed on weak composites. Spoke periods 100/30/30 give orthogonal horizons (8.3h trend slope, 2.5h mean-rev z-score, 2.5h realized-vol delta) so HRPs distance metric can actually cluster them rather than collapsing to near-equal weights.
