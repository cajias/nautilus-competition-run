---
name: nautilus-competition-operator
description: |
  Operator runbook for the nautilus-competition CLI. Use when:
  (1) scaffolding a working directory via `compete init` (or laying it
  out manually); (2) running `compete run <working-dir>` with
  `--paper-duration-minutes`, `--rounds`, `--metrics-endpoint`, or
  `--run-id`; (3) reading the output tree under
  `<working-dir>/runs/<run_id>/` (eval/, paper/, leaderboard.md,
  final_leaderboard.md); (4) triaging a team that hit
  `max_train_iterations` and produced a `FAILED` marker / `FAILED.json`;
  (5) deciding between simulated and live paper modes; (6) running the
  hermetic demo at `examples/demo_competition/`.
author: Claude Code
version: 1.0.0
date: 2026-05-07
---

# Operator runbook — `compete`

`compete run <working-dir>` orchestrates a folder of agent-controlled
teams. Per round, per team it calls the team's `train(ctx)`, gates on a
positive-gain eval window, runs paper sequentially (simulated or live),
writes a leaderboard, and announces it back into each team's workspace.
Repeat for N rounds.

## Working-directory layout

The operator hands `compete run` a single directory. It must look like:

```
<working-dir>/
├── config.yaml
├── data/catalog/                  # ParquetDataCatalog (train/test/eval/paper bars)
├── teams/
│   ├── team_alice/
│   │   ├── CLAUDE.md              # agent persona (free-form)
│   │   ├── entry.py               # def train(ctx) -> (type[Strategy], StrategyConfig)
│   │   └── incoming/              # harness drops round leaderboards here
│   └── team_bob/...
└── runs/<run_id>/                 # created by compete; see "Output tree"
```

### Scaffolding the layout

If the `compete init` subcommand is available in your install, use it:

```bash
compete init <working-dir> [--instrument BTCUSDT.BINANCE] [--teams team_alice,team_bob]
```

`compete init` creates `config.yaml`, an empty `data/catalog/`, and stub
`teams/<name>/{CLAUDE.md,entry.py}` files for every team. Drop seeded
catalog data into `data/catalog/` and you're ready for `compete run`.

If `compete init` isn't available in your build (the subcommand may be
in flight), create the layout manually using the template below.

### `config.yaml` shape

Full schema in `nautilus_competition/config.py`:

```yaml
name: demo
windows:
  - train: {start: "2024-01-01T00:00:00Z", end: "2024-02-01T00:00:00Z"}
    test:  {start: "2024-02-01T00:00:00Z", end: "2024-02-15T00:00:00Z"}
    eval:  {start: "2024-02-15T00:00:00Z", end: "2024-03-01T00:00:00Z"}
    paper: {start: "2024-03-01T00:00:00Z", end: "2024-03-15T00:00:00Z"}
paper:
  mode: simulated                 # or "live"
  duration_minutes: 4320          # 72h, only used by live mode
  starting_pot_usdt: 1000.0
instrument:
  symbol: "BTCUSDT.BINANCE"
  bar_type: "BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL"
agent:
  command: ["claude", "--print", "--output-format", "json"]
  per_train_timeout_seconds: 600
  max_train_iterations: 5
scoring:
  weights:
    sharpe: 0.4
    total_return: 0.4
    max_drawdown: 0.2
catalog:
  path: data/catalog
```

The number of rounds is implicit in `len(windows)` (no separate `rounds:`
key). Within each round, the four windows must be ordered
`train -> test -> eval -> paper` with no overlap (back-to-back boundaries
are allowed).

## `compete run` flags

```
compete run <working-dir> [--rounds N] [--paper-duration-minutes M]
                          [--run-id ID] [--metrics-endpoint URL]
```

| Flag | Purpose |
|------|---------|
| `<working-dir>` (positional) | Folder containing `config.yaml` + `teams/` + `data/catalog/`. |
| `--rounds N` | Override `config.rounds` (truncates `windows` to first `N`). |
| `--paper-duration-minutes M` | Override `config.paper.duration_minutes`. Useful for short demo runs. |
| `--run-id ID` | Pin the output dir name. Defaults to a UTC timestamp. |
| `--metrics-endpoint URL` | Push metrics to a Prometheus pushgateway. See `nautilus-competition-observability`. |

`--metrics-endpoint` may also be supplied via the
`COMPETE_METRICS_ENDPOINT` environment variable — useful for direnv /
dev shells. Precedence is **flag → env var → unset (no metrics)**.

## Output tree

```
<working-dir>/runs/<run_id>/
├── round_01/
│   ├── eval/<team>/
│   │   ├── eval_metrics.json            # last successful iteration
│   │   ├── train_iterations.jsonl       # one line per train() call
│   │   └── FAILED                       # written iff max_train_iterations exhausted
│   ├── paper/<team>/
│   │   └── paper_metrics.json
│   └── leaderboard.md
├── round_02/...
└── final_leaderboard.md
```

Additionally, after each round finishes, the harness copies that round's
leaderboard into every team's workspace:

```
<working-dir>/teams/<team>/incoming/round_<NN>_leaderboard.md
```

This is the announcement channel — each team sees the round result
before its next `train()` call (also surfaced via
`ctx.prev_round_leaderboard`).

## Simulated vs live paper modes

Selected by `config.paper.mode`.

- **`simulated`** — `BacktestEngine` on `windows[r].paper` (a fourth
  window disjoint from train/test/eval). Deterministic; **no Binance
  credentials needed**. This is the demo + test mode.
- **`live`** — single-strategy `TradingNode` against Binance Spot
  Testnet. Credentials loaded via
  `nautilus_competition._env.load_competition_env()` +
  `nautilus_competition._env.ensure_ed25519_key_path()`. The harness
  runs for `config.paper.duration_minutes` (after any
  `--paper-duration-minutes` override) and stops the node via a
  `threading.Timer`. Then metrics are extracted via
  `nautilus_competition._metrics.metrics_from_engine`.

Both branches end at the same `paper_metrics.json` shape.

## Triage — reading `FAILED` / `FAILED.json`

When a team exhausts `max_train_iterations` without ever returning a
strategy whose eval-gain factor exceeds `1.0`, the harness writes
`runs/<run_id>/round_NN/eval/<team>/FAILED` (zero-byte sentinel) and may
also emit a `FAILED.json` with structured triage details:

```json
{
  "team": "team_alice",
  "round": 1,
  "iterations": 5,
  "last_gain_factor": 0.94,
  "last_error": "ValueError: bar_type mismatch in DemoConfig",
  "history": [
    {"iteration": 0, "gain_factor": 0.82, "error": null},
    {"iteration": 1, "gain_factor": 0.79, "error": null},
    {"iteration": 4, "gain_factor": null, "error": "TimeoutError: ..."}
  ]
}
```

`train_iterations.jsonl` next to it has one line per `train()` call with
the full prompt / agent output (when `agent_runner.run_claude` was
used). Read it for the per-iteration rationale.

A failed team's row in `leaderboard.md` shows the FAILED status and is
ranked at the bottom; the team still gets the leaderboard announcement
in `incoming/`, so it can adapt next round.

## Running the hermetic demo

A self-contained fixture lives at `examples/demo_competition/` (one
team, deterministic buy-and-hold, pre-baked synthetic uptrend catalog).
It needs no Claude or Binance credentials:

```bash
compete run examples/demo_competition --paper-duration-minutes 1
```

Expected artefacts:

```
examples/demo_competition/runs/<run_id>/round_01/eval/team_demo/eval_metrics.json
examples/demo_competition/runs/<run_id>/round_01/paper/team_demo/paper_metrics.json
examples/demo_competition/runs/<run_id>/round_01/leaderboard.md
examples/demo_competition/runs/<run_id>/final_leaderboard.md
examples/demo_competition/teams/team_demo/incoming/round_01_leaderboard.md
```

Use this fixture as the canonical end-to-end smoke test before any
substantive harness change.

## References

- `docs/competition.md` — the canonical operator runbook.
- `docs/team-contract.md` — the per-team contract (skill:
  `nautilus-competition-team-author`).
- `docs/observability.md` — metrics + dashboard (skill:
  `nautilus-competition-observability`).
- `nautilus_competition/config.py` — full `CompetitionConfig` schema.
