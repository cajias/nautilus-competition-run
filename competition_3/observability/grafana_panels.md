# competition_3 Grafana panels

Datasource UID: `prometheus` (matches existing competition dashboards in
`apm_modules/cajias/nautilus-competition/observability/grafana/dashboards/`).

Import these panels into a new "competition_3 Ablation" dashboard, or add to
an existing one. Each panel below is described with title, type, and PromQL.

---

## Panel 1 — Inner iterations to pass

**Type:** barchart  
**Title:** Inner iterations to pass

```promql
nautilus_competition_inner_iterations{team=~"$team"}
```

**Legend:** `{{team}} round {{round}}`  
**Description:** Number of inner researcher→strategist→backtester attempts
before a passing strategy was found (or 5 if forfeited). Lower = faster
convergence. Useful to compare autoresearch depth presets.

---

## Panel 2 — Paper trades closed

**Type:** barchart  
**Title:** Paper trades closed

```promql
nautilus_competition_paper_trades_closed{team=~"$team"}
```

**Legend:** `{{team}} round {{round}}`  
**Description:** Count of `PositionClosed` events from the paper-trade phase
per team per round. Indicates strategy activity — strategies that never close
a position score 0 on win_rate.

---

## Panel 3 — Composite leaderboard

**Type:** table  
**Title:** Composite leaderboard

```promql
sum by (team) (nautilus_competition_composite_score{run=~"$run"})
```

**Transform:** Sort descending by `Value`.  
**Legend:** `{{team}}`  
**Description:** Total composite score (`gain_factor × win_rate`) summed
across all rounds for the selected run. Higher = better overall ablation
performance.

---

## Template variables (suggested)

| Variable | Query |
|----------|-------|
| `$team` | `label_values(nautilus_competition_composite_score, team)` |
| `$run` | `label_values(nautilus_competition_composite_score, run)` |

---

## Notes

- Datasource UID is the literal string `prometheus`, NOT `${DS_PROMETHEUS}`.
  The grafana-dashboard-datasource-uid-mismatch skill documents why the
  existing dashboards hard-code this string.
- `nautilus_competition_inner_iterations` is pushed by each team's `entry.py`
  after the Claude session returns (job=`competition_3`).
- `nautilus_competition_paper_trades_closed` is pushed by
  `competition_3/scripts/score_composite.py --push`.
- `nautilus_competition_composite_score` is pushed by
  `competition_3/scripts/score_composite.py --push`.
- All three metrics are pushed to pushgateway at `http://localhost:9091`.
