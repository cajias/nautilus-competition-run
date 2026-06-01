# competition_3 — autoresearch-knob ablation

Sister competitions: `../competition_1/` (SOTA + foundation-model teams),
`../competition_2/` (paradigm-named teams).

## What this competition tests

Each of 6 teams uses `/autoresearch:autoresearch` (and its sub-skills
`:reason` and `:probe`) to drive trading-strategy investigation, but with a
different knob preset (breadth × depth × verification × loop discipline).
Everything else is held constant — same Sonnet model, same 10-symbol
catalog, same role agents, same passing gate. The winner has the strategy
with the highest composite `gain_factor × win_rate` summed across 5 rounds.

## Run it

```bash
# from workspace root
uv run compete run competition_3
```

After the run finishes (or while it's running, per-round):

```bash
uv run python competition_3/scripts/score_composite.py runs/<run-id>/ --push
```

This applies the composite metric, writes `leaderboard_composite.json`,
and pushes Prometheus metrics for the Grafana dashboard.

## The 6 teams

| Team | /autoresearch preset |
|------|---------------------|
| team_breadth_first | many shallow branches, light verify, single pass |
| team_depth_first | few deep branches, medium verify, single pass |
| team_adversarial | medium breadth/depth, 5-judge panel, single pass |
| team_speed_run | low breadth, shallow, minimal verify, single pass |
| team_balanced | medium across all axes — control |
| team_completeness | medium breadth/depth, "what's missing?" until 2 dry rounds |

Exact CLI args + sub-skill choices: `docs/autoresearch_knob_mapping.md`.

## Scoring

```
composite_score_round = gain_factor × win_rate
floor:                  gain ≤ 1.0 OR win_rate < 0.5 → 0
final_score = Σ composite_score_round  (over 5 rounds)
```

## Symbol universe

The catalog contains 30+ days of 5-MIN bars for 10 USDT spot pairs:
BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, POL (all `.BINANCE`).
Teams may subscribe to any subset; the harness anchors on BTCUSDT.

## Smoke before launch

```bash
uv run python competition_3/scripts/smoke_one_team.py team_balanced
```

Must succeed before committing the ~60h full run.

## Observability

Three new metrics on the existing Prometheus + pushgateway + Grafana stack:

- `nautilus_competition_inner_iterations{team, round}` — autoresearch attempts to pass gate (1–5; 5 = forfeit)
- `nautilus_competition_paper_trades_closed{team, round}` — did we hit the 20-trade target?
- `nautilus_competition_composite_score{team, round, run}` — leaderboard

See `observability/metrics.md` and `observability/grafana_panels.md`.
