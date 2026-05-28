# round 0 iter 0

- prev_gain: None
- lookback_bars: 200
- disagree_threshold: 0.08
- drawdown_cap: 0.2
- weights: trend=0.155 mr=0.344 vol=0.501
- notes: [active_kernel=flat realized_30bar=+0.00171] Iter 0, prev_gain=None: budget conference only (no experience-sharing or extreme-market). Researcher reports active_kernel=flat with 30-bar drift +0.17% — range regime. Bias HRP toward mean-reversion as primary signal: short HRP lookback (200 bars) to keep correlation matrix responsive, mr_period=40 z-score window, vol_period=30 short RV-delta as orthogonal diversifier, trend_period=60 to capture micro-trends rather than long-horizon drift in a flat tape. disagree_threshold lowered to 0.08 (well above 0.05 critic floor) to ensure the strategy actually trades — flat/no-trade implies gain_factor=1.0 which fails the strict eval gate. max_weight_per_spoke=0.6 caps any single-spoke dominance and forces HRP diversification across the cluster tree. drawdown_cap=0.20 protects the 0.2 composite max_drawdown weight without strangling the strategy. No spoke zeroed-out (no extreme-market trigger this iter).
