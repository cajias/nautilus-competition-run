# Competition 1

First competition in this workspace. The instrument is BTCUSDT 5-MIN
bars from Binance public REST (real data, ~30-day window). Seven
multi-agent teams compete; gain factor on $1000 base wins.

## Run

From the workspace root (parent of this dir):

```bash
uv run compete run competition_1
```

## Layout

```
competition_1/
├── config.yaml                       # active harness config
├── config.yaml.production.full       # backup of the production config
├── config.yaml.test*                 # smoke-test config snapshots (1-iter, single team)
│
├── data/
│   └── catalog/                      # ParquetDataCatalog (8641 BTCUSDT 5-min bars,
│                                     #   2026-04-01..2026-05-01 UTC, real Binance data)
│
├── scripts/
│   └── seed_real_catalog.py          # one-shot seeder using BinanceRestDataSource
│                                     #   (no API key needed; public REST)
│
├── runs/                             # per-run output (gitignored)
│   └── <run_id>/
│       ├── round_NN/eval/<team>/{eval_metrics.json, train_iterations.jsonl, FAILED.json?}
│       ├── round_NN/paper/<team>/paper_metrics.json   # only if eval gain > 1.0
│       └── final_leaderboard.md
│
└── teams/                            # 7 teams, each a CC plugin (CLAUDE.md + .claude/agents/)
    ├── team_tradingagents_pipeline/         # Hierarchical pipeline (TradingAgents)
    ├── team_hedgeagents_hub/                # Hub-and-spoke + 3 conferences (HedgeAgents)
    ├── team_mountainlion_moe/               # MoE / RAG-routed experts (MountainLion)
    ├── team_fs_reasoning_split/             # Factual/subjective split + weekly reflection
    ├── team_rdagent_quant_lab/              # R→D→F + Thompson-sampling bandit + knowledge forest
    ├── team_timesfm_forecast_author_critic/ # TimesFM + per-regime calibration map
    └── team_kronos_forecast_committee/      # Kronos checkpoint ensemble + regime blender
```

## Re-seeding the catalog

```bash
cd competition_1
uv run python scripts/seed_real_catalog.py
```

Writes ~30 days of BTCUSDT 5-MIN klines to `data/catalog/`. Idempotent;
re-run to refresh against current Binance data.

## Config knobs (config.yaml)

- `paper.mode: live` — Binance Spot Testnet (creds auto-loaded from
  sibling `~/Projects/workspace/nautilus-trading/.envrc`)
- `paper.duration_minutes: 1` (smoke) or longer for real runs
- `agent.per_train_timeout_seconds: 1800` — per Claude session
- `agent.max_train_iterations: 1` (smoke) or 4 (production)
- `scoring.weights: {return: 1.0, sharpe: 0.0, max_dd: 0.0}` — pure
  dollar-gain ranking

Edit and re-run; the config snapshots `config.yaml.test*` and
`config.yaml.production.full` are reference variants.

## Smoke-test history (notable runs in `runs/`)

- `ready_smoke_v3b_*` — first end-to-end successful smoke at 1800s with
  real Binance data. 4/7 teams completed eval; `team_mountainlion_moe`
  cleared gain > 1.0 and exercised the live paper-stage code path. The
  other 3 teams hit Claude Code subscription quota (403). All other
  failure modes (entry.py dataclass NoneType, seeder precision, etc.)
  fixed in earlier commits.

See workspace `README.md` for cross-competition execution-model docs.
