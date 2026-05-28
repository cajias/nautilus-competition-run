# round 0 iter 1

- prev_gain: -0.0011468422399999456
- lookback_bars: 300
- disagree_threshold: 0.1
- drawdown_cap: 0.25
- weights: trend=0.392 mr=0.094 vol=0.514
- notes: Iter1 budget conference + experience-sharing rotation. prev_gain=-0.0011 (sub-edge loss; range regime confirmed by 4 prior flat losses). Root cause: disagree_threshold=0.15 kept us flat, fee bleed on the few crossings dominated. Pivot: lookback 500->300 (regime shorter than assumed), threshold 0.15->0.10 so signals actually clear the gate, max_weight 0.6->0.65 to let HRP route more cash to mean-rev. trend_period set to schema max 200 (researcher wanted 200-300); mr_period clipped to 60 (researcher wanted 80-120 but schema cap is 60); vol_period=60 matches researcher's short(60) leg. drawdown_cap 0.25 retained as the 0.2-composite-leg protector. Loss<10%, no extreme-market trigger fired.
