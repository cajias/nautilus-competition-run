# competition_3 — Competition-Level Rules

Inherited by every team session under `competition_3/teams/*`. Per-team
strategy details live in each team's own `CLAUDE.md`.

## The game

6 teams. Each team uses `/autoresearch:autoresearch` (and its sub-skills `:reason` and `:probe`) with a different configuration preset (breadth × depth × verification × loop). All other inputs are equal: same model (Sonnet), same catalog, same role agents.

Goal: produce a strategy that wins the **most paper trades** AND **makes
the most money**, summed as `composite_score = gain_factor × win_rate`
per round, summed across 5 rounds.

## Multi-asset universe

The catalog at `data/catalog/` contains 5-MIN bars for 10 USDT spot pairs:
BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, MATIC (all suffixed
`.BINANCE`). Trade any subset.

The harness `config.yaml` declares `BTCUSDT.BINANCE` as the engine-bootstrap
instrument. Teams may subscribe to additional pairs at runtime by loading
`ParquetDataCatalog(ctx.config.catalog.path)` inside their strategy.

## Round = "iterate until backtest passes, then paper trade"

Inside `train(ctx)`:
1. Researcher invokes `/autoresearch` (or `:reason` / `:probe` sub-skills) with the team's preset.
2. Strategist writes `attempts/<iter>/strategy.py` from autoresearch findings.
3. Backtester runs train-window backtest on `ctx.get_train_data()`.
4. **Passing criteria**: `gain_train > 1.0 AND win_rate_train >= 0.5`.
   - Pass → return strategy. Fail → loop back to step 1 with diagnostics.
5. Inner loop cap: **5 attempts OR 3600 s**, whichever first. Exceeding either = forfeit.

After `train()` returns:
6. Harness backtests on `ctx.get_test_data()` (OOS gate, same threshold).
7. Paper trade on Binance testnet — `paper.duration_minutes = 90` ceiling;
   strategy `self.stop()` after 20 closed trades.

## Scoring

Per round: `composite_score = gain_factor × win_rate`, with floor:
- `gain_factor <= 1.0` OR `win_rate < 0.5` → `composite_score = 0`.

Final ranking: sum of per-round `composite_score` across all 5 rounds.

Implemented by `scripts/score_composite.py` post-harness. Harness scoring
key remains `total_return: 1.0` — wrapper applies the composite.

## Role agents (all 6 teams)

- `researcher.md` — drives `/autoresearch` (and sub-skills `:reason` / `:probe`) with the team's preset; produces research findings used by the strategist.
- `strategist.md` — translates findings into `attempts/<iter>/strategy.py` +
  `runtime_rules.json`.
- `backtester.md` — runs train-window backtest, evaluates passing criteria,
  emits diagnostics on failure.
- `risk-officer.md` — enforces `runtime_rules.json` constraints (position
  size, stop loss, max drawdown).

## Autoresearch knob mapping

Each team's specific invocation knobs (which sub-skill, which flags, which
prompt wording) are pinned in `docs/autoresearch_knob_mapping.md`. Do NOT
deviate from your team's mapping — it is the controlled variable that makes
the competition a clean ablation matrix.
