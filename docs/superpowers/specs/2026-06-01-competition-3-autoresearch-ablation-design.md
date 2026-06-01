# Competition 3 — Autoresearch Ablation Design

**Status:** Draft for review
**Date:** 2026-06-01
**Author:** Raul + Claude (brainstorming session)
**Supersedes:** prior on-disk `competition_3/` scaffold (5 composition-differentiated teams) — to be discarded.

## Purpose

Competition_3 is a **controlled ablation** of the `/autoresearch:autoresearch` skill applied to live-paper crypto trading. Each of 6 teams uses the same skill with the same role agents on the same data, differing only in the autoresearch **knob preset** (breadth × depth × verification × loop-discipline). The result is a clean cell-by-cell answer to "which research configuration produces the most paper-profitable trading strategies under win-rate-aware scoring?"

This is distinct from competitions 1 and 2, which differentiated teams by qualitative architecture (agent rosters, paradigm choice, foundation models). Comparison across c1/c2 was qualitative; c3 is quantitative.

## Goals

1. Each team produces a `strategy.py` whose live-paper performance can be ranked by `gain × win_rate`.
2. Strategies must clear a generalization gate: both an in-team train-window backtest AND a harness out-of-sample test-window backtest.
3. The competition is **paradigm-agnostic and symbol-unrestricted** — teams pick their own indicators, instruments (any subset of the seeded catalog), and trading style.
4. Produce a 6-cell leaderboard showing which autoresearch knob preset dominates, with full Prometheus/Grafana observability.

## Non-Goals

- Not differentiating by foundation model (all teams use Sonnet for fairness).
- Not differentiating by agent roster (all teams have the same 4-role roster).
- Not on-demand catalog seeding — universe is pre-seeded and bounded.
- Not optimizing for sharpe or drawdown — the metric is gain × win_rate.

## Architecture

### Round lifecycle

A **round** is one full training-then-paper cycle for one team:

1. Harness calls `train(ctx)` on the team with `TrainContext` containing `get_train_data()`, `get_test_data()`, `prev_round_leaderboard`, `prev_gain`.
2. **Inner refinement loop** runs inside `train()`. Capped at **5 attempts OR 3600s**, whichever first:
    1. Researcher invokes `/autoresearch:autoresearch` with the team's knob preset. Receives an investigation report.
    2. Strategist translates the report into a candidate `strategy.py` + `runtime_rules.json`.
    3. Backtester runs the candidate on `ctx.get_train_data()`.
    4. Evaluator checks **passing criteria**: `gain_train > 1.0 AND win_rate_train ≥ 0.50`.
    5. **Pass** → break out, return strategy. **Fail** → push backtest diagnostics into next autoresearch invocation as failure context, loop.
3. **Round forfeit** if loop exhausts (5 attempts hit OR 3600s burned). Leaderboard entry: `final_score = 0`.
4. **OOS gate**: harness backtests the returned strategy on `ctx.get_test_data()`. Threshold: `gain_test > 1.0 AND win_rate_test ≥ 0.50`. Fail → no paper window, `final_score = 0`.
5. **Paper trade**: 90 min hard ceiling; strategy `self.stop()`s after **20 closed trades**.
6. **Score**: `final_score = gain_paper × win_rate_paper`. Floored to 0 if `gain_paper ≤ 1.0 OR win_rate_paper < 0.50`.

### Competition shape

- **6 teams × 5 rounds = 30 training sessions**.
- Per-team-round budget: **3600s train** + up to **90 min paper**.
- Expected wall-clock: ~30h training + ~45h paper = **~75h total** (~3 days).
- Single competition run uses the same harness CLI (`compete run competition_3`) as c1/c2 — no harness fork.

### Symbol universe

- Catalog pre-seeded with **20 USDT spot pairs** from Binance: BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, MATIC, DOT, LINK, ATOM, FIL, NEAR, ARB, OP, UNI, LTC, BCH, ETC. (Exact list adjusted at seed time per testnet availability; the seed script logs and continues on any missing symbol.)
- 30 days of 5-MIN bars per symbol, precision-rounded to each instrument's `Price` / `Quantity` precision.
- Harness `config.yaml` declares **BTCUSDT.BINANCE** as the anchor instrument (the harness API requires one). Teams subscribe to whatever subset they want from inside their strategy via `ParquetDataCatalog(ctx.config.catalog.path)` — no per-team config restriction.

## Teams — the 6 knob presets

All teams share:
- Base model: **Claude Sonnet (Sonnet 4.6)** per role — the ablation is research process, not model strength.
- Role agents: **researcher**, **strategist**, **backtester**, **risk-officer**.
- Catalog: full 20-pair pool.
- Inner-loop cap: 5 attempts.
- Passing criteria + OOS gate: identical.

Teams differ **only in the researcher's invocation of `/autoresearch:autoresearch`**:

| # | Team | Breadth | Depth | Verification | Loop discipline | Hypothesis |
|---|---|---|---|---|---|---|
| 1 | `team_breadth_first` | high (many parallel branches) | shallow (1–2 levels) | light (1 verifier) | first-pass | Wide surface scan finds the best surface idea. |
| 2 | `team_depth_first` | low (1–2 branches) | deep (4–5 levels) | medium (3 verifiers) | first-pass | One drilled thesis beats scattershot. |
| 3 | `team_adversarial` | medium (3 branches) | medium (3 levels) | heavy (5 verifiers, refute-by-default) | first-pass | Aggressive refutation produces robust strategies. |
| 4 | `team_speed_run` | low (1 branch) | shallow (1 level) | minimal (no verifier) | first-pass | Fast cheap iterations beat one careful pass. |
| 5 | `team_balanced` | medium (3) | medium (3) | medium (3) | first-pass | Sensible defaults — the control / baseline. |
| 6 | `team_completeness` | medium (3) | medium (3) | medium (3) | loop-until-dry (2 dry rounds) | Iterating "what's missing?" until convergence finds the edge others miss. |

**The exact `/autoresearch:autoresearch` argument syntax** for each preset is pinned during the writing-plans phase after reading the skill source. The design fixes the *axes*; the plan fixes the *flags*.

### Per-team folder layout

```
teams/team_<name>/
├── entry.py                          # Standard train() pattern (importlib + sys.modules[spec.name] = mod)
├── CLAUDE.md                         # Team-specific instructions, references the knob preset
├── .claude/agents/
│   ├── researcher.md                 # Drives /autoresearch with this team's preset
│   ├── strategist.md                 # Translates findings → strategy.py + runtime_rules.json
│   ├── backtester.md                 # Runs in-loop train backtest, returns diagnostics
│   └── risk-officer.md               # Enforces runtime_rules.json at trade-time (live Python critic)
└── attempts/, _inbox/                # Gitignored via existing **/teams/*/{attempts,_inbox}/ patterns
```

## Scoring & harness customizations

### Composite score

`final_score = gain × win_rate`, floored to 0 if `gain ≤ 1.0 OR win_rate < 0.50`.

This isn't a built-in harness metric. Integration **uses a post-hoc wrapper, not a harness fork**:

- `config.yaml` keeps `scoring.weights: {total_return: 1.0}` so the harness still emits per-team gain to `runs/<run-id>/leaderboard.json`.
- `competition_3/scripts/score_composite.py` runs after each round (and again at competition end). It reads:
    - `runs/<run-id>/leaderboard.json` (per-team gain).
    - `runs/<run-id>/teams/<team>/round_<N>/paper_trades.jsonl` (per-team paper trades).
- For each `PositionClosed` event with `realized_pnl > 0`, count a win. `win_rate = wins / closed_trades`.
- Compute `final_score`, apply the floor, write `runs/<run-id>/leaderboard_composite.json`.
- Push three Prometheus metrics to pushgateway:
    - `nautilus_composite_score{team, round}` — composite final score per team-round.
    - `nautilus_competition_inner_iterations{team, round}` — 1–5 (or 5 = forfeit).
    - `nautilus_competition_paper_trades_closed{team, round}` — drives the "hit the 20-trade target?" Grafana panel.

Zero harness fork debt. Future framework bumps require no merge work.

### Adaptive paper-window termination

Strategy-level: each team's `TeamStrategy.on_position_closed()` increments a counter; at 20, calls `self.stop()`. Harness honors strategy-initiated stop (verified in c1/c2). `paper.duration_minutes = 90` is the hard safety net for under-trading strategies.

### Observability

Reuse the existing Prometheus + pushgateway + Grafana stack (`:9091` and `:3000`). Add a new Grafana dashboard `competition_3_leaderboard.json` showing:
- 6-team composite score per round.
- Inner-iterations histogram per team.
- Paper-trade count vs the 20-trade target.

## Execution plan

### File / directory layout (target)

```
competition_3/
├── config.yaml                       # 6 teams × 5 rounds, paper.duration_minutes=90, instrument=BTCUSDT.BINANCE (anchor)
├── README.md                         # competition rules, scoring, run command
├── CLAUDE.md                         # competition-level rules (inherited by all team sessions)
├── data/catalog/                     # 20 USDT pairs × 30 days × 5-MIN bars, gitignored
├── scripts/
│   ├── seed_top20_catalog.py         # fetches top-20 testnet pairs, precision-rounded
│   ├── score_composite.py            # post-harness wrapper: gain × win-rate + push to Prometheus
│   └── smoke_one_team.py             # 1-team 1-round 5-min-paper sanity check
├── teams/
│   ├── team_breadth_first/           # (entry.py, CLAUDE.md, .claude/agents/{researcher,strategist,backtester,risk-officer}.md)
│   ├── team_depth_first/
│   ├── team_adversarial/
│   ├── team_speed_run/
│   ├── team_balanced/
│   └── team_completeness/
└── runs/                             # gitignored, harness writes per-run artifacts here
```

### Execution sequence (post-spec-approval)

1. **Discard prior scaffold** — remove existing 5 team folders (solo_researcher, researcher_critic, researcher_memory_risk, parallel_ensemble, regime_adaptive); reset `CLAUDE.md` and `README.md`.
2. **Scaffold** new structure — directory tree + 6 team folders, all 6 `entry.py` copies (identical pattern), 6 differentiated `CLAUDE.md` files, 6 sets of role agents.
3. **Catalog seed** — `uv run python competition_3/scripts/seed_top20_catalog.py` against testnet (~10–15 min, logs missing symbols and continues).
4. **Smoke test** — `competition_3/scripts/smoke_one_team.py team_balanced` with `paper.duration_minutes=5, max_attempts=2` to validate end-to-end before committing the ~75h full-run budget.
5. **Pre-flight checklist** — Prometheus/pushgateway/Grafana running; Binance testnet creds loaded; APM lock matches; `claude` CLI reachable; API quota status verified.
6. **Full launch** — `uv run compete run competition_3` with observability live. Composite-score wrapper polls leaderboard.json and pushes metrics as rounds close.
7. **Final leaderboard** — `python competition_3/scripts/score_composite.py runs/<run-id>/` emits `leaderboard_composite.json` ranking teams by `gain × win-rate`.

### Smoke-test gate

Smoke test must complete cleanly:
- Passing strategy produced in ≤ 2 inner attempts.
- OOS gate passes.
- ≥ 1 paper trade closes within 5 min.
- `nautilus_composite_score` appears in pushgateway.

If any of those fail, debug before burning the full-run budget.

## Risks & open items

- **`/autoresearch:autoresearch` argument syntax** — the design fixes axes; exact flag names are read from the skill source during writing-plans. If the skill exposes fewer knobs than expected (e.g., no breadth flag), team presets collapse to fewer real dimensions and the ablation gets weaker. Mitigation: writing-plans phase audits the skill first.
- **Win-rate noise at 20 trades** — for a true 50%-hit-rate strategy, 20 trades has σ ≈ 0.11 on the measured rate. Two teams 0.10 apart may not be statistically distinguishable. Acceptable for ranking, not for declaring a "winner by 1pt".
- **API quota** — prior competition run was interrupted by quota. ~30h of Sonnet sessions risks recurrence. Mitigation: smoke test first, monitor quota during run, abort cleanly if hit.
- **Testnet symbol availability** — not all 20 listed symbols have testnet liquidity. The seed script logs and continues; effective universe may shrink. Mitigation: log final universe to `competition_3/data/catalog/UNIVERSE.md` after seeding.
- **Round forfeits inflating the floor** — if a team forfeits 4 of 5 rounds, its sample size shrinks and composite score becomes noisy. Acceptable: forfeit IS a signal that the knob preset is wrong for the search space.

## What this design DOES NOT do

- Does not modify the harness source (`nautilus_competition/*`).
- Does not change other competitions (c1, c2 are untouched).
- Does not introduce on-demand catalog seeding.
- Does not vary model tiers across teams (all Sonnet).
- Does not change the shared `.claude/` skills install at repo root.
- Does not change the existing observability stack — it adds metrics on top.

## Approval

Sections 1 (architecture + lifecycle), 2 (6 knob presets), 3 (scoring + harness customizations), and 4 (directory layout + execution plan) of the brainstorming session were approved verbally by Raul on 2026-06-01. This document captures that approval in writing.
