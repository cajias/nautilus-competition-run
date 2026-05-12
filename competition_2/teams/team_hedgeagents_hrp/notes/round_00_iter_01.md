# round 0 iter 1

- prev_gain: -4.193959999998498e-05
- lookback_bars: 300
- disagree_threshold: 0.12
- drawdown_cap: 0.2
- weights: trend=0.445 mr=0.164 vol=0.391
- notes: Round 0 iter 1. prev_gain=-4.19e-05 (effectively zero — strategy likely never tripped disagree_threshold=0.15 on the 3-bar paper window, or traded flat). Budget conference + experience-sharing conference fire; extreme-market does NOT (prev_gain > -0.10, no loss streak). Per CLAUDE.md rule, rotated lookback from iter-0 value 500 → 300 to keep ~1d of 5-min coverage and maintain HRP correlation stability. Relaxed disagree_threshold 0.15 → 0.12 (well above 0.05 floor) so composite signal becomes actionable more often; iter-0 setting was likely too restrictive. trend_period scaled 100 → 80; mr/vol dropped 30 → 25 symmetrically. max_weight_per_spoke=0.6 unchanged — iter-0 weights (0.186/0.343/0.471) were already well-diversified. drawdown_cap=0.20 unchanged, aligned with composite's 0.2 max_drawdown weight. NOTE: researcher's attempts/001/research.json is missing (subprocess likely timed out again) — operating on iter-0 memory-keeper notes only. If iter-2 still near-zero after rotation, extreme-market conference should zero the weakest spoke.
