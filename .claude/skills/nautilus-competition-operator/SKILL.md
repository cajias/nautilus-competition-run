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
version: 1.3.0
date: 2026-05-26
---

# Operator runbook — `compete`

`compete run <working-dir>` orchestrates a folder of agent-controlled
teams. Per round, per team it calls the team's `train(ctx)`, gates on a
positive-gain eval window (see Promotion Rules below for the exact
threshold and failure semantics), runs paper sequentially (simulated or
live), writes a leaderboard, and announces it back into each team's
workspace. Repeat for N rounds.

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

### Live-paper pre-flight

Before invoking `compete run --paper-mode live` on a fresh host, run
these three one-liners. They cover the failure modes that account for
nearly every first-time live-paper abort. Full triage matrix in skill
`nautilus-competition-live-paper-troubleshooting`.

```bash
# 1. Credential presence (no values logged — paths + booleans only)
python -c 'from nautilus_competition._env import load_competition_env, describe_credential_sources; load_competition_env(); print(describe_credential_sources())'

# 2. CA bundle resolves to a real file (rustls fails opaquely without one)
python -c 'import os; p=os.environ.get("SSL_CERT_FILE"); print("SSL_CERT_FILE:", p, "exists:", bool(p) and os.path.isfile(p))'

# 3. Post-mortem after a failed run
compete status <working-dir>/runs/<run_id>
```

If a run aborts before placing orders, see skill
`nautilus-competition-live-paper-troubleshooting` for the symptom ->
root-cause matrix. The two most common buckets are
`HttpClientBuildError("builder error")` (CA bundle) and
`MissingBinanceCredentialsError` (env vars missing or shell exporting
a stale path).

## Promotion Rules (Eval → Paper Gate)

A team advances to paper when ANY training iteration produces a strategy
whose `eval gain_factor > 1.0` (final equity strictly greater than
starting equity on the eval bars). Breakeven (`1.0`) and losses
(`< 1.0`) do NOT advance. The check lives in `orchestrator.py` (around
the `if ev.gain_factor > 1.0:` branch); `gain_factor =
final_equity / starting_equity` over the eval window.

The orchestrator loops up to `config.agent.max_train_iterations` times.
As soon as one iteration crosses the threshold, that iteration's
strategy is promoted to paper and the round ends for that team. If the
budget exhausts without any iteration crossing 1.0, the harness writes
`FAILED.json` with `cause: "max_iterations_exhausted"`,
`last_gain_factor`, and the per-iteration `gain_factor` history. The
team's `paper/<team>/` directory is pre-created but stays empty, and the
team's composite for the round is `0.0`.

### Reading the leaderboard during failure scenarios

`+0.0000` for every team in `leaderboard.md`, combined with a
`FAILED.json` under each `eval/<team>/`, means the gate worked
correctly — no team produced a profitable eval-window strategy. This is
not a code bug; it is a real signal that no team cleared the bar.
Verify with:

```bash
for f in runs/<id>/round_NN/eval/*/FAILED.json; do
  team=$(basename $(dirname $f))
  gf=$(jq -r .last_gain_factor $f)
  echo "$team gain=$gf"
done
```

A scoreboard of `+0.0000` with empty `paper/<team>/` directories is
indistinguishable at a glance from teams that paper-traded and broke
even — always cross-check `FAILED.json` presence before drawing
conclusions.

### All-teams-fail triage

When every team fails the gate, work through these causes in order:

1. **`max_train_iterations` is too small.** The default is `5`. For
   stress runs or harder eval windows, bump to `8`–`10` in
   `config.yaml` and re-run.
2. **The eval-window market regime is genuinely difficult.** A flat or
   adversarial regime can defeat a healthy roster. Try a different
   eval-window date range and re-run before blaming the teams.
3. **Team strategies are mis-specified for the asset.** If teams were
   scaffolded against a different instrument or timeframe, regenerate
   them with priors that match the current `instrument` /
   `bar_type`.
4. **Check regime balance**: Read `runs/<run-id>/round_<N>/regime_check.json`.
   If `warning_triggered: true`, the eval window's regime diverges
   sharply from the train window — teams may have trained on a
   different market state than they were evaluated on. This is a known
   cause of all-teams-fail.

Do NOT respond by raising or removing the `> 1.0` threshold. That
hides the failure rather than fixing it; a team that breaks even on
eval has not earned paper.

## Regime-Balance Check

The framework computes a buy-and-hold (B&H) baseline over both train
and eval windows and emits a warning if the magnitudes diverge by more
than `regime_check_threshold` (default 0.15).

Outputs:
- Stdout: `[regime-warning] Round N: train B&H=... eval B&H=... Δ=...`
- Log: `regime-mismatch round=N train_bh=... eval_bh=... delta=...`
- Artifact: `runs/<run-id>/round_<N>/regime_check.json`
- Leaderboard: "Eval Window B&H Baseline" section with optional warning callout

Tuning: increase `regime_check_threshold` in config.yaml if your
instrument's natural volatility produces frequent false-positive
warnings.

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

### Live-paper run-level aborts (separate from team `FAILED`)

When the run itself aborts before any team trades — i.e., the live
`TradingNode` never builds — the failure surfaces as a Python
exception, not a `FAILED.json`. Common root-cause buckets:

| Exception | Bucket |
|---|---|
| `MissingBinanceCredentialsError` | One of `BINANCE_TESTNET_API_KEY` / `_API_SECRET` / `_ED25519_KEY_PATH` is unset after env loading. Fail-fast guard in `paper_phase._run_live`. |
| `HttpClientBuildError("builder error")` | rustls couldn't find / read the system CA bundle. `SSL_CERT_FILE` unset or pointing at a non-existent file. |

Both are diagnosed in skill
`nautilus-competition-live-paper-troubleshooting`. Run the pre-flight
one-liners above before re-invoking `compete run --paper-mode live`.

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
