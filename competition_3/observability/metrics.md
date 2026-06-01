# competition_3 observability metrics

## competition_3 metrics

| Metric | Labels | Source |
|--------|--------|--------|
| `nautilus_competition_inner_iterations` | `team`, `round` | emitted by each team's `entry.py` at end of round after Claude session returns |
| `nautilus_competition_paper_trades_closed` | `team`, `round` | emitted by `competition_3/scripts/score_composite.py` at score time (one push per round in `score_run()` output) |
| `nautilus_competition_composite_score` | `team`, `round`, `run` | emitted by `competition_3/scripts/score_composite.py --push` (already wired in Plan Task 6) |
