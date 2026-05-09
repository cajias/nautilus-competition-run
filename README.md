# nautilus-competition-run

Workspace hosting one or more NautilusTrader trading competitions.
The competition runner (`compete` CLI) lives in the sibling project
`~/Projects/workspace/nautilus-competition/` and is installed editably
into this workspace's `.venv/`.

## Layout

```
nautilus-competition-run/
├── README.md                    # this file
├── apm.yml, apm.lock.yaml       # APM project config (CC plugin from cajias/nautilus-competition)
├── docs/state-of-the-art/       # shared SOTA research material
├── .claude/
│   ├── skills/                  # vendored CC plugin skills (auto-loaded)
│   └── commands/                # vendored slash commands wrapping `compete` CLI
├── .env.local.template          # Binance testnet creds template (live-paper mode only)
├── .envrc                       # workspace env-var defaults (non-secret)
├── .cache/                      # shared HF / model checkpoint cache (gitignored)
├── .venv/                       # uv-managed Python venv (gitignored)
├── apm_modules/                 # APM dependency cache (gitignored)
│
├── competition_1/               # COMPETITION #1 — see competition_1/README.md
│   ├── config.yaml              # rounds, instrument, scoring, agent budgets
│   ├── data/catalog/            # per-competition ParquetDataCatalog
│   ├── scripts/                 # per-competition seeders/utilities
│   ├── runs/                    # per-competition run artifacts (gitignored)
│   └── teams/                   # 7 multi-agent teams competing in this competition
│
└── competition_2/  (future)     # add more competitions as sibling dirs
```

Each `competition_N/` is a self-contained working dir for the harness:
its own config, its own catalog, its own teams, its own runs. Adding a
new competition is just `mkdir competition_2 && ...`.

## Running a competition

From the workspace root:

```bash
uv run compete run competition_1
```

The harness reads `competition_1/config.yaml`, walks `competition_1/teams/`,
and per round per team calls each team's `entry.py:train(ctx)` up to
`max_train_iterations` times (default 4). Each `train()` invokes
`claude --print` ONCE in the team folder; the Claude session reads
`CLAUDE.md` + dispatches role agents via the CC Agent tool, producing
one strategy artifact. The harness backtests each strategy on the eval
window; surviving strategies (`gain_factor > 1.0`) advance to paper.

## Per-team execution model

- Harness invokes `team.entry.train(ctx)` directly.
- `train(ctx)` writes `_inbox/context.md`, then calls
  `nautilus_competition.agent_runner.run_claude(...)` to spawn ONE Claude
  session.
- The Claude session reads `CLAUDE.md` + `.claude/agents/<role>.md`
  profiles and dispatches role agents via the CC Agent tool per the
  team's "Coordination protocol (CC Agent dispatch)" section.
- Sub-agents write artifacts to disk; primary Claude exits when
  `attempts/<iter>/strategy.py` (or team variant) is produced.
- `train()` then loads that artifact and returns `(StrategyClass,
  StrategyConfig)` to the harness.

## Cross-round persistence

Each team's folder is long-lived. Compounding state (forest, calibration
map, blender weights, RAG triples, spoke memory, reflections) survives
between rounds via disk persistence. Inside a Claude session, agents
Read prior state and append/refine; the next session sees those updates.

## Scoring

Gain factor on $1000. `final_equity / starting_equity`. Highest gain
wins. Sharpe and max-drawdown are stability metrics teams may use
internally; the harness scoring is return-dominant per `config.yaml`.

## Adding a new competition

```bash
mkdir competition_2
# Author competition_2/config.yaml (use competition_1/config.yaml as template)
# Seed competition_2/data/catalog/ with the new instrument/window
# Author competition_2/teams/<team_name>/CLAUDE.md + entry.py + .claude/agents/...
# Or copy a team folder from competition_1/teams/ as a starting point

uv run compete run competition_2
```

`.gitignore` patterns are `**/`-prefixed so they apply to all
`competition_*/` dirs without modification.
