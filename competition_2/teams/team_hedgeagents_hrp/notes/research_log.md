# research_log.md

- iter 0: regime=mixed | Round 0 iter 0 cold start with no prev_gain and no leaderboard — assume a mixed regime over the 21-day eval window (BTC 5-min on 2026-04-12→2026-05-03 typically straddles trend-day and chop-day cluste

- iter 1: regime=mixed | Iter 0 returned prev_gain ≈ -3.6e-5 — essentially flat, meaning the strategy effectively never traded (disagree_threshold=0.15 was too restrictive on a mixed regime where the 3-spoke composite rarely 

- iter 2: regime=range | Two consecutive marginal-zero gains (-3.6e-5, -4.3e-5) signal a flat-strategy failure mode, not a paradigm failure: signals are too quiet to clear the disagree-threshold, so the strategy never trades.

- iter 3: regime=range | Iter 3: 4 consecutive micro-flat losses (~10^-5) on BTC 5-min eval diagnose RANGE regime, not paradigm failure — composite signals stay below gate, fee bleed on rare crossings dominates. Pivot: lookba

- iter 4: regime=range | Iter4 LAST-SHOT pivot: 5 consecutive losses confirm iter3's range thesis was correct but parameters too conservative — strategy now trades (loss grew from 1e-5 to 2e-4) but mean-rev fires at sub-edge 

- iter 0: regime=mixed | Iter 0 thesis: HRP routes the 0.4 sharpe + 0.4 return + 0.2 drawdown composite by treating trend / mean-rev / vol-carry as three signal columns and clustering them on the correlation distance d=sqrt(0

- iter 1: regime=range | Iter1 thesis: prev_gain ≈ -0.0011 (sub-edge loss) is the same diagnostic signature as prior cross-round 'range' iterations — disagree_threshold=0.15 keeps strategy mostly flat, fee bleed on the few cr

- iter 2: regime=range | Iter 2 thesis (paradigm-tighten, not paradigm-swap given losses are sub-1bp): the prior two iterations bled fees on a range-bound train window. The fix is a triple cut: (a) disagree_threshold floor 0.

- iter 3: regime=range | Iter 3 (4th consecutive sub-bp loss, prev_gain=-3.4e-4): regime is confirmed RANGE, paradigm is correct (HRP + mean-rev tilt) but allocator pathology is misallocating to the smoothest-but-flattest spo

- iter 4: regime=range | Iter 4 (LAST of 5-iter budget; prev_gain=-3.23e-05 = essentially flat, 10x improvement from iter 3's -3.37e-04 confirming the triple-fix paradigm direction is correct). The microscopic residual loss i

- iter 0: regime=range | Iter 0 active_kernel=flat (drift +0.17% over 30 bars) — Strategy will not trade this iteration. To pivot in iter 1: lower disagree_threshold to 0.08 and shorten HRP lookback to 200 bars so mean-revers
