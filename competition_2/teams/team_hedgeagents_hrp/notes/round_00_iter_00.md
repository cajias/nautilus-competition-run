# round 0 iter 0

- prev_gain: None
- lookback_bars: 500
- disagree_threshold: 0.15
- drawdown_cap: 0.2
- weights: trend=0.186 mr=0.343 vol=0.471
- notes: Iter 0 round 0: prev_gain=None, no prev_round_leaderboard, researcher research.json MISSING (subprocess likely timed out) so no external priors - falling back to HRP-thesis-aligned defaults. Budget conference only. Lookback 500 bars ~=1.7d of 5-min bars gives HRP ~10x coverage on 21-day eval. max_weight_per_spoke=0.6 prevents mono-spoke collapse and preserves HRP diversification. drawdown_cap=0.20 is tight, directly supporting the composite's 0.2 max_drawdown weight which is this team's edge. disagree_threshold=0.15 well above the 0.05 critic floor; below it composite routes to cash. trend_period=100 (~8h) medium-horizon; mr_period=30 (~2.5h) Bollinger/z-score window; vol_period=30 matches mr for realized-vol delta symmetry.
