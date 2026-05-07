# nautilus-competition-run

Workspace for the 7-team NautilusTrader trading competition. The competition runner lives in the sibling project `~/Projects/workspace/nautilus-competition/`.

## Layout

```
nautilus-competition-run/
├── config.yaml                 # rounds, instrument, scoring, agent budgets
├── data/catalog/               # ParquetDataCatalog (operator-seeded)
├── .cache/                     # shared HF / model checkpoint cache
├── .env.local.template         # Binance testnet creds (live-paper mode only)
└── teams/
    ├── team_tradingagents_pipeline/         # Hierarchical pipeline (TradingAgents)
    ├── team_hedgeagents_hub/                # Hub-and-spoke + 3 conferences (HedgeAgents)
    ├── team_mountainlion_moe/               # MoE / RAG-routed experts (MountainLion)
    ├── team_fs_reasoning_split/             # Factual/subjective split + weekly reflection (FS-ReasoningAgent + Singhi)
    ├── team_rdagent_quant_lab/              # R→D→F + Thompson-sampling bandit + knowledge forest (RD-Agent(Q))
    ├── team_timesfm_forecast_author_critic/ # TimesFM forecast + per-regime calibration map
    └── team_kronos_forecast_committee/      # Kronos checkpoint ensemble + regime-conditioned blender
```

## Running the competition

```bash
cd ~/Projects/workspace/nautilus-competition
uv run compete run /Users/rc/Projects/workspace/nautilus-competition-run
```

The harness reads `config.yaml`, walks `teams/`, and per round per team calls each team's `entry.py:train(ctx)` up to `max_train_iterations` times (default 4). Each `train()` invokes `claude --print` ONCE in the team folder; the Claude session reads `CLAUDE.md` + dispatches role agents via the CC Agent tool, producing one strategy artifact. The harness backtests each strategy on the eval window; surviving strategies (`gain_factor > 1.0`) advance to paper.

## Per-team execution model

- Harness invokes `team.entry.train(ctx)` directly.
- `train(ctx)` writes `_inbox/context.md`, then calls `nautilus_competition.agent_runner.run_claude(...)` to spawn ONE Claude session.
- The Claude session reads `CLAUDE.md` + `.claude/agents/<role>.md` profiles and dispatches role agents via the CC Agent tool per the team's "Coordination protocol (CC Agent dispatch)" section.
- Sub-agents write artifacts to disk; primary Claude exits when `attempts/<iter>/strategy.py` (or team variant) is produced.
- `train()` then loads that artifact and returns `(StrategyClass, StrategyConfig)` to the harness.

## Cross-round persistence

Each team's folder is long-lived. Compounding state (forest, calibration map, blender weights, RAG triples, spoke memory, reflections) survives between rounds via disk persistence. Inside a Claude session, agents Read prior state and append/refine; the next session sees those updates.

## Scoring

Gain factor on $1000. `final_equity / starting_equity`. Highest gain wins. Sharpe and max-drawdown are stability metrics teams may use internally; the harness scoring is return-dominant per `config.yaml`.
