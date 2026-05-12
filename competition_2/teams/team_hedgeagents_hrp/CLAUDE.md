# team_hedgeagents_hrp — Hub-and-Spoke Hedge Fund with HRP Allocator

## One-sentence thesis

A **fund-manager hub** coordinates three deterministic **signal spokes**
(trend / mean-reversion / vol-carry), aggregated via **Hierarchical Risk
Parity (HRP)** risk-budgeted weights. Differentiator vs the paper's
fixed/vote allocator: HRP routes cash on spoke-signal correlation
structure, shrinking exposure when spokes disagree and the composite
correlation matrix is ill-conditioned. Primary scoring dimension:
**max_drawdown** (composite weight 0.2) — HRP's whole design goal is
drawdown-aware diversification.

## SOTA basis (what this team is a refresh of)

1. **HedgeAgents** — Li, Zeng, Xing, Xu. *"HedgeAgents: A Balanced-aware
   Multi-agent Financial Trading System"*. SCUT–ByteDance, WWW 2025.
   arXiv 2502.13165. Source of: hub-and-spoke topology, the three named
   conferences (budget / experience-sharing / extreme-market), the
   fund-manager as chair, three memory types.

2. **Hierarchical Risk Parity** — López de Prado. *"Building Diversified
   Portfolios that Outperform Out-of-Sample"*. The Journal of Portfolio
   Management, Vol. 42, No. 4, Summer 2016. Source of: distance-metric
   `d(i,j) = sqrt(0.5 * (1 - ρ(i,j)))` on signal correlations, single-
   linkage hierarchical clustering, quasi-diagonal Seriation reorder,
   recursive bisection of inverse-variance weights. Advantage over
   `1/N`, mean-variance, and Markowitz: does **not invert** the
   covariance matrix, survives ill-conditioned/singular regimes, and
   concentrates budget into orthogonal risk clusters rather than
   spreading it uniformly.

3. **Direct ancestor**: `competition_1/teams/team_hedgeagents_hub/`. This
   team inherits its hub-and-spoke choreography and extends it with an
   HRP allocator in place of the paper's fixed/vote weighting.

4. **Fast Trading on Binance with NautilusTrader** (internal doc
   referenced by the ancestor) — Tier-2A manager cadence, RiskEngine
   veto mechanics.

## What this Claude session / `train()` must do

`entry.py`'s `train(ctx)` is the **single harness call**. It makes TWO
`run_claude(...)` subprocesses (researcher, hub-manager) and then runs
deterministic Python for spokes + HRP + packaging. It writes
`runtime_rules.json` to the team root; the Strategy class loads it at
`on_start` time. **No LLM calls at trade time.**

Exit contract: return `(TeamStrategy, TeamStrategyConfig)`. The harness
backtests it on the eval window and (if eval gain > 1.0) the paper
window.

## Roster — 9 roles

Only two of the nine are LLM calls at train time. The remaining seven
are **deterministic Python functions** inside `entry.py`. This is a
deliberate **budget-discipline** choice: the competition's
`agent.per_train_timeout_seconds = 600`, and two opus-quality
subprocesses at ~180s each already consume ~60% of it. Expanding
further would squeeze the deterministic HRP math to its knees.

| # | Role | Where it runs | Cost per `train()` |
|---|---|---|---|
| 1 | **researcher** | `run_claude(...)` subprocess #1 | ~180s LLM |
| 2 | **hub-manager** (hypothesis-generator, 3-conference chair) | `run_claude(...)` subprocess #2 | ~180s LLM |
| 3 | **critic** | Python fn in `entry.py` | ~1s |
| 4 | **risk-officer** | Python fn in `entry.py` | ~1s |
| 5 | **memory-keeper** | Python fn in `entry.py` (appends to `notes/`) | ~1s |
| 6 | **trend-spoke** | Python fn: long-horizon MA slope + momentum | ~2s |
| 7 | **mean-rev-spoke** | Python fn: z-score / Bollinger / RSI composite | ~2s |
| 8 | **vol-carry-spoke** | Python fn: realized-vol delta (VRP proxy) | ~2s |
| 9 | **hrp-allocator** | Python fn: `scipy.cluster.hierarchy` + recursive bisection | ~3s |

### Why spokes are deterministic, not LLM

The paper uses an LLM per spoke. That is cheap in OpenAI-API cost but
*very* expensive in wall-clock: three sequential 180s subprocesses would
blow the 600s budget. More importantly, the spokes' jobs (compute a
signed signal from the bar time-series) are **pure numerical
transformations**. LLMs would add stochastic noise to what is already a
well-defined filter-bank, and none of their output would change from
round to round in a way HRP cares about — HRP only cares about the
**covariance** of spoke signals, which is determined by the bars, not
the wording of an LLM.

### Why researcher AND hub-manager ARE LLMs

- **Researcher** synthesizes priors from `docs/state-of-the-art/` and
  prior-round reflections — this IS a language-understanding task and
  the output is a JSON blob of hypotheses the hub-manager will reason
  over.
- **Hub-manager** runs the three-conference protocol, chooses the HRP
  lookback window and disagree-threshold, and encodes the round-level
  thesis. This IS judgment under uncertainty. It also handles the
  post-loss rotation described under "Handling `ctx.prev_gain`" below.

## The three conferences (hub-manager runs all three in one LLM call)

### Budget conference (always fires)
Chair: hub-manager. Attendees (virtual): all 3 spokes, critic,
risk-officer. Decides: HRP lookback window (bars), disagree-threshold
(on weighted signal magnitude), per-spoke max weight cap, drawdown cap.
Output: a JSON blob on stdout that `train()` parses.

### Experience-sharing conference (post-loss reflective)
Fires when `ctx.prev_gain is not None and ctx.prev_gain < 0`.
Memory-keeper (Python) loads the previous round's HRP weights and
surfaces them in the hub-manager prompt. Hub-manager rotates the HRP
lookback (short→long or long→short) to escape a local loss regime.

### Extreme-market conference (drawdown / consecutive-loss trigger)
Fires when `ctx.prev_gain is not None and ctx.prev_gain <= -0.10` (10%
loss last round) OR two consecutive `ctx.prev_gain <= 0`. Hub-manager
may force a spoke cap (`max_weight_spoke_X=0`), collapsing to a
two-spoke subset. Decision baked into `runtime_rules.json`.

## Runtime pattern (hybrid: train-time LLM, trade-time pure Python)

**Train-time** (`train(ctx)`):
1. Write `_inbox/context.md` with round/iter/prev_gain.
2. **Researcher** `run_claude(...)` (~180s, strict timeout guard).
   Writes `notes/research_log.md` + `attempts/<iter>/research.json`.
3. **Hub-manager** `run_claude(...)` (~180s, strict timeout guard).
   Reads the researcher JSON, runs the three conferences, emits a JSON
   blob on stdout: `{hrp_lookback_bars, disagree_threshold,
   max_weight_per_spoke, drawdown_cap, notes}`.
4. **Trend-spoke**, **mean-rev-spoke**, **vol-carry-spoke** compute
   signed signal time-series over the train window (deterministic,
   vectorized numpy/pandas).
5. **HRP-allocator** computes cluster-weighted risk budget over the
   3x3 signal-correlation matrix → three `w_i` summing to 1.0.
6. **Critic** sanity-checks (any weight > 0.7? any NaN? disagree
   threshold reasonable?).
7. **Risk-officer** codifies everything into `runtime_rules.json`
   (HRP weights, disagree_threshold, drawdown_cap, lookback).
8. **Memory-keeper** appends `notes/round_<N>_iter_<I>.md` with the
   thesis and any `prev_gain` rotation.
9. Return `(TeamStrategy, TeamStrategyConfig)`.

**Trade-time** (`TeamStrategy.on_bar(bar)`):
1. Maintain a rolling bar deque (size = lookback).
2. Recompute trend/mean-rev/vol-carry signals each bar (microsecond-
   fast — numpy over ~200 floats).
3. `weighted_signal = w_trend * s_trend + w_mr * s_mr + w_vol * s_vol`.
4. If `|weighted_signal| < disagree_threshold` → ensure flat (go to
   cash). Otherwise size the position by `weighted_signal` clipped to
   `±1.0` scaled by `trade_size`.
5. **Live critic**: if running drawdown from session peak exceeds
   `drawdown_cap`, force cash for the rest of the paper window.
6. **No LLM at trade time** — latency budget is one 5-minute bar; an
   LLM call would blow it, and the harness's paper phase is timed.

## Fallback: hub-manager timeout

If the hub-manager `run_claude(...)` raises `AgentTimeoutError` or
returns a malformed JSON payload, `train()` **does not crash**. It
falls back to deterministic defaults:
```
hrp_lookback_bars = 500
disagree_threshold = 0.15
max_weight_per_spoke = 0.6
drawdown_cap = 0.25
```
Then it still runs spokes + HRP + risk-officer with those defaults.
Rationale: a single timeout must not cost the team a round.

## Handling `ctx.prev_gain`

- `prev_gain is None` (iter 0 of round 0): standard budget conference.
- `prev_gain >= 0`: standard budget conference; memory-keeper only
  appends thesis.
- `prev_gain < 0`: memory-keeper loads the previous iter's HRP weights
  from `notes/` and surfaces them in the hub-manager prompt.
  Hub-manager **rotates** the HRP lookback (e.g., last used 500, try
  200 next — regime may have shortened).
- `prev_gain <= -0.10` OR two consecutive losses: extreme-market
  conference — hub-manager may zero out the worst-performing spoke.

## Handling `ctx.prev_round_leaderboard`

Guard with `if ctx.prev_round_leaderboard is not None and
ctx.prev_round_leaderboard.exists():`. If present, memory-keeper passes
its contents to the hub-manager as "here's where the field stood last
round" — informs whether to be aggressive (losing field) or defensive
(winning field).

## Data discipline (no-leak)

- **Train window**: `ctx.get_train_data()` — read freely for
  spoke-signal computation and HRP covariance estimation.
- **Test window**: `ctx.get_test_data()` — OPTIONAL, one sanity check
  of disagree-threshold AFTER HRP weights are fixed. Not a tuning input.
- **Eval window**: NEVER read. Harness runs the returned Strategy on
  it. Reading eval bars during `train()` is leak.
- **Paper window**: NEVER read. Strategy's `on_bar` sees it live via the
  BacktestEngine / live testnet.

## Bar-sizing arithmetic

- `config.yaml` sets `bar_type = BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL`
  and `paper.duration_minutes = 15`.
- 5-minute bars × 15 minutes = **3 bars on paper** (live testnet trims).
  This is below any reasonable indicator warm-up; the paper phase is
  essentially an execution smoke test, not a signal-driven phase.
- The **eval window** (2026-04-12 → 2026-05-03, 21 days = ~6048
  5-minute bars) IS signal-driven. With our default `lookback = 500`
  bars (~1.7 days), we have ~5548 bars of actual signal on eval. That
  is plenty.

## Instrument / bar-type gotchas (from supporting skills)

1. `InstrumentId.from_str(ctx.config.instrument.symbol)` — never pass
   a bare `str` to `StrategyConfig`.
2. `BarType.from_str(ctx.config.instrument.bar_type)` — same.
3. `self.cache.instrument(self.config.instrument_id)` in `on_start`;
   never build an instrument from `TestInstrumentProvider` — the bar
   precisions won't match the catalog's (skill:
   `nautilus-trader-catalog-instrument-precision`).
4. Order entry: `self.submit_order(self.order_factory.market(
   instrument_id=..., order_side=..., quantity=...,
   time_in_force=TimeInForce.GTC))`. There is no `Strategy.buy`.
5. **Logger singleton** (skill: `nautilus-trader-logger-singleton`):
   do not re-init nautilus logging in this team. The BacktestEngine in
   the harness passes `LoggingConfig(bypass_logging=True)`; the team's
   Strategy must not instantiate its own logger.

## On-disk memory contract

| Path | Persists? | Writer |
|---|---|---|
| `CLAUDE.md`, `entry.py` | yes | scaffolder |
| `_inbox/context.md` | per-iter (overwritten) | `train()` |
| `attempts/<iter>/research.json` | yes (forensic) | researcher subprocess |
| `attempts/<iter>/hub_manager.json` | yes | hub-manager subprocess |
| `notes/research_log.md` | yes (append-only) | researcher |
| `notes/round_<N>_iter_<I>.md` | yes | memory-keeper |
| `runtime_rules.json` | overwritten per iter | risk-officer |
| `incoming/round_NN_leaderboard.md` | per round | harness |

## Hard rules

- Two LLM calls per `train()`. No more, no less. Budget discipline.
- Fall back to deterministic defaults if either LLM times out.
- `runtime_rules.json` MUST exist before returning — Strategy's
  `on_start` reads it.
- No LLM at trade time. `on_bar` is pure numpy/python.
- No eval/paper reads inside `train()`.
- Class names MUST be `TeamStrategy` / `TeamStrategyConfig` (the
  harness-agnostic naming the seeded `entry.py` started with).

## Scoring implications

Composite = `0.4*sharpe + 0.4*total_return + 0.2*max_drawdown` (all
z-scored per round). HRP's core promise is **drawdown control via
diversification**, so this team over-indexes on the 0.2 weight.
Sharpe/return are second-order — a low-drawdown strategy with modest
return is expected to rank well on the composite when other teams
over-lever into trend.

## Failure modes

1. **Both LLMs time out** → deterministic fallback kicks in; still
   returns a valid Strategy. Gain may be modest but not zero.
2. **Spoke signals all correlate on a trending window** → HRP collapses
   to near-equal weights, which is safer than picking one spoke.
3. **Disagree threshold too low** → over-trading fees on the eval
   engine. Critic enforces `disagree_threshold >= 0.05` floor.
4. **Lookback too long** → early eval bars see zero signal. Critic
   enforces `lookback <= min(1000, 0.2 * len(train_bars))`.
5. **`scipy` unavailable** at runtime → HRP falls back to equal
   weights. Still valid, just loses the allocator edge.

## Supporting skills used at authoring time

- `nautilus-competition-team-author` — contract, `TrainContext`,
  `DataHandle`, bar/paper sizing.
- `nautilus-trader-catalog-instrument-precision` — instrument source.
- `nautilus-trader-logger-singleton` — Logger init discipline.
- `using-nautilus-trader` — Strategy lifecycle and order factory.
