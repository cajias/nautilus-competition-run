# competition_3 — autoresearch-driven, win-rate-weighted multi-team trading competition

Status: Design — awaiting user approval before writing-plans
Date: 2026-06-01
Author: Claude (Opus 4.7) under brainstorming skill
Predecessor competitions: competition_1 (7 teams, SOTA-derived + foundation-model), competition_2 (6 teams, paradigm-named)

## 1. Goal

Run a controlled ablation across **6 trading teams**, where every team uses the
`/autoresearch:autoresearch` skill to drive strategy investigation. Teams
differ from each other ONLY in how they configure autoresearch (breadth,
depth, verification rigor, loop discipline). The winner is the team whose
strategies — proven in backtest, then traded on Binance Spot Testnet —
maximize **composite score = gain_factor × win_rate** across paper-trading
windows.

Adapted from c1/c2, where teams differed by qualitative architecture
(agent rosters, paradigm). Here the differentiation axis is a single
controlled variable: the autoresearch knob preset.

## 2. Scoring

| Item | Value |
|------|-------|
| Per-round score | `gain_factor × win_rate` |
| Floor disqualification | gain ≤ 1.0 OR win_rate < 0.50 → score = 0 |
| `gain_factor` | `final_equity / starting_equity_1000` over paper window |
| `win_rate` | `wins / closed_trades` where `wins = positions with realized_pnl > 0` |
| Overall winner | sum of per-round scores across 5 rounds |

Scoring is implemented as a **wrapper script** (`scripts/score_composite.py`)
that reads the harness's `runs/<run-id>/leaderboard.json` plus each team's
`paper_trades.jsonl` and writes `leaderboard_composite.json`. No fork of
the `nautilus_competition` framework — the harness keeps emitting standard
`total_return` and the wrapper computes the composite.

Composite metric is also pushed to Prometheus pushgateway as
`nautilus_competition_composite_score{team, round}` for Grafana.

## 3. Round Lifecycle

Per team per round:

1. `train(ctx)` called.
2. **Inner refinement loop**, capped at **5 attempts OR 3600 s wall-clock**, whichever first:
   1. Researcher invokes `/autoresearch:autoresearch` with the team's knob preset and any prior-attempt diagnostics.
   2. Strategist translates autoresearch findings into `attempts/<iter>/strategy.py` + `runtime_rules.json`.
   3. Backtester runs **train-window backtest** on `ctx.get_train_data()`.
   4. Evaluate passing criteria: `gain_train > 1.0 AND win_rate_train ≥ 0.50`.
   5. Pass → break inner loop, return strategy. Fail → log diagnostics, loop.
3. **Forfeit** if loop exits without a passing strategy. Round leaderboard entry: `score = 0`.
4. **OOS gate**: harness backtests the returned strategy on `ctx.get_test_data()`. Same threshold: `gain_test > 1.0 AND win_rate_test ≥ 0.50`. Fail → no paper window, score = 0.
5. **Paper trade** on Binance Spot Testnet:
   - Hard ceiling: `paper.duration_minutes = 90`.
   - Strategy self-terminates via `self.stop()` once 20 closed trades accumulate.
6. **Round score** = `gain_paper × win_rate_paper`.

## 4. Team Differentiation — the 6 knob presets

All 6 teams share: same base model (Sonnet), same skill version, same catalog,
same role agents (researcher, strategist, backtester, risk-officer), same
passing criteria, same time budget.

Only the researcher's `/autoresearch` invocation differs along four axes:

| Axis | Meaning |
|------|---------|
| **Breadth** | parallel branches per question |
| **Depth** | recursion levels into follow-ups |
| **Verification** | adversarial verifier panel size |
| **Loop discipline** | termination condition |

| # | Team | Breadth | Depth | Verify | Loop | Hypothesis |
|---|------|---------|-------|--------|------|------------|
| 1 | `team_breadth_first` | many | shallow | light | first-pass | Wide net of ideas, take the best surface-level signal |
| 2 | `team_depth_first` | few | deep | medium | first-pass | One thesis, drilled deep, beats scattershot |
| 3 | `team_adversarial` | medium | medium | heavy (5) | first-pass | Aggressive refutation produces robust strategies |
| 4 | `team_speed_run` | low | shallow | minimal (1) | first-pass | Fast cheap iterations beat one careful pass |
| 5 | `team_balanced` | medium | medium | medium (3) | first-pass | Sensible defaults — control / baseline |
| 6 | `team_completeness` | medium | medium | medium | loop-until-dry (2 dry rounds) | Iterating "what's missing?" finds the edge others miss |

**Note on exact knob args:** the precise `/autoresearch` CLI argument shape
(flag names for depth, parallelism, verifier count, loop condition) must be
confirmed by reading the autoresearch skill during the writing-plans phase.
This spec pins down the *axes* and *preset intent*; the plan fills in the
exact invocation strings.

## 5. Symbol Universe

Top ~20 USDT pairs on Binance Spot Testnet, pre-seeded as
`ParquetDataCatalog` (30 days, 5-MIN bars). Teams subscribe to whatever
subset they want at strategy time — no per-team config restriction.

Working starting set, to be reconciled against testnet liquidity at
seed-time:

> BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT, DOGEUSDT,
> AVAXUSDT, MATICUSDT, DOTUSDT, LINKUSDT, ATOMUSDT, FILUSDT, NEARUSDT,
> ARBUSDT, OPUSDT, UNIUSDT, LTCUSDT, BCHUSDT, ETCUSDT.

If any symbol has no testnet liquidity or fails precision lookup at seed
time, drop and proceed with whatever subset succeeds (≥ 15 minimum).

`config.yaml.instrument` declares `BTCUSDT` as the engine-bootstrap
instrument (the harness requires one for engine initialization). Teams
are free to subscribe to additional instruments inside their Strategy's
`on_start()`.

## 6. Harness Customizations

### Path A — wrapper, not fork (chosen)

- `config.yaml.scoring.weights: {total_return: 1.0}` — harness emits gain unchanged.
- `scripts/score_composite.py` — runs after each round (or at end of competition); reads `runs/<run-id>/leaderboard.json` + `runs/<run-id>/teams/<team>/round_<N>/paper_trades.jsonl`; writes `leaderboard_composite.json`; pushes Prometheus metrics.
- Zero modification to `nautilus_competition` framework.

### Strategy self-termination

In each team's `TeamStrategy.on_position_closed()`:

```python
def on_position_closed(self, event: PositionClosed) -> None:
    self._closed_count += 1
    if self._closed_count >= 20:
        self.log.info(f"Reached 20 closed trades; self-terminating paper window")
        self.stop()
```

Hard ceiling `paper.duration_minutes = 90` is the safety net for
under-trading strategies.

### Observability

Reuse the existing Prometheus + pushgateway + Grafana stack. Add three new
metrics:

| Metric | Purpose |
|--------|---------|
| `nautilus_competition_inner_iterations{team,round}` | autoresearch attempts to pass gate (1–5, or 5 = forfeit) |
| `nautilus_competition_paper_trades_closed{team,round}` | "did we hit the 20-trade target?" panel |
| `nautilus_competition_composite_score{team,round}` | leaderboard |

## 7. Directory Layout

```
competition_3/
├── config.yaml                       # 6 teams × 5 rounds, paper.duration_minutes=90
├── README.md                         # rules, scoring, run command
├── data/catalog/                     # 20 USDT pairs × 30 days × 5-MIN bars (gitignored)
├── scripts/
│   ├── seed_top20_catalog.py
│   ├── score_composite.py
│   └── smoke_one_team.py
├── teams/
│   ├── team_breadth_first/
│   │   ├── entry.py                  # importlib + sys.modules[name]=mod pattern
│   │   ├── CLAUDE.md                 # team-specific autoresearch knob preset
│   │   ├── .claude/agents/
│   │   │   ├── researcher.md
│   │   │   ├── strategist.md
│   │   │   ├── backtester.md
│   │   │   └── risk-officer.md
│   │   ├── attempts/                 # gitignored
│   │   └── _inbox/                   # gitignored
│   ├── team_depth_first/
│   ├── team_adversarial/
│   ├── team_speed_run/
│   ├── team_balanced/
│   └── team_completeness/
└── runs/                             # gitignored — harness writes here
```

All glob patterns in workspace `.gitignore` already use `**/` prefix from
the c1 → multi-competition refactor, so `competition_3/teams/*/attempts/`,
`competition_3/runs/`, `competition_3/data/catalog/` are auto-ignored.

## 8. Execution Sequence

Subject to writing-plans skill turning this into the actual step-by-step
implementation plan:

1. **Reconcile prior scaffolding** — task #3 from old list was `in_progress`. Check on-disk state, merge with this design's target shape.
2. **Catalog seed** — `uv run python competition_3/scripts/seed_top20_catalog.py` against testnet (~10–15 min).
3. **Smoke test** — `competition_3/scripts/smoke_one_team.py team_balanced` with `paper.duration_minutes=5, max_attempts=2`. Must produce ≥ 1 paper trade in ≤ 2 inner attempts.
4. **Pre-flight** — Prometheus/pushgateway/Grafana up; Binance testnet creds; APM lock; Claude CLI reachable; quota status.
5. **Full launch** — `uv run compete run competition_3` with observability live. Composite-score wrapper attaches.
6. **Final leaderboard** — `python competition_3/scripts/score_composite.py runs/<run-id>/` → `leaderboard_composite.json`.

**Gate before full launch:** smoke test must pass. If it doesn't, debug
before burning the ~60h full-run budget.

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| `/autoresearch` arg shape doesn't match my assumed axes | Plan phase verifies against the actual skill; presets adjusted before scaffolding |
| Some testnet USDT pairs lack liquidity | Drop at seed time; proceed with ≥ 15 |
| Inner loop exhausts 5 attempts without passing → forfeit | Acceptable; that's the signal that the team's autoresearch preset is wrong for this round's market regime |
| Win-rate from < 20 trades is noisy | Hard floor 20-trade target via strategy self-stop; paper.duration_minutes = 90 ceiling enforces upper bound on under-trading penalty |
| Claude API quota mid-run (as happened in c1) | Track quota status before launch; competition_3 totals ~60h wall-clock — schedule around reset windows |
| Strategy `self.stop()` doesn't actually halt the paper window | Verified in c1/c2 backtest; if it fails in live paper, fall back to ceiling-only |

## 10. Out of Scope

- Multi-model ablation (all teams use Sonnet — that's a different experiment, not this one).
- New harness features beyond the wrapper script.
- competition_1 or competition_2 modifications.
- Foundation-model teams (TimesFM, Kronos) — c1 covered those; this is a pure autoresearch-knob ablation.

## 11. Success Criteria

- All 6 teams complete at least 3 rounds without crashing the harness.
- At least 3 of 6 teams produce ≥ 1 paper window with ≥ 20 closed trades.
- Composite leaderboard ranks teams meaningfully (no all-zero or all-tied outcomes).
- Per-team `inner_iterations` distribution differs visibly across knob presets — i.e., the ablation has signal.
