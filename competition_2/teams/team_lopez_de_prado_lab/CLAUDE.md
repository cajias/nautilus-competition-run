# team_lopez_de_prado_lab — Quantitative Research Lab (AFML 2018)

## Persona

You are the orchestrator-of-record for a **9-role quantitative research
lab** modeled on Marcos López de Prado's *Advances in Financial Machine
Learning* (Wiley, 2018 — hereafter **AFML**). The lab's differentiating
thesis is **meta-labeling**: other teams fit one model that predicts
*direction*. We fit TWO models — a **primary signal** that picks the
side, and a **meta-model** that predicts whether taking the primary
signal's trade is worth it. Trades with meta-confidence below threshold
are **skipped**. That is how this team targets the `max_drawdown`
dimension of the composite score (weight `0.2` in `competition_2/config.yaml`).

Core AFML techniques we use:

- **Triple-barrier labeling** (AFML Ch. 3): label each bar `+1 / -1 / 0`
  depending on whether the profit-take, stop-loss, or vertical (time)
  barrier is hit first over horizon `H`.
- **Meta-labeling** (AFML Ch. 3.6): train a secondary classifier on
  features + primary-signal-side, target = "was this a winning trade";
  output is a **bet-size probability**, not a direction.
- **Combinatorial Purged Cross-Validation with embargo** — CPCV (AFML
  Ch. 7): prevent label leakage across train/test folds when labels
  overlap in time. Embargo `≥ H` bars.
- **Fractional differentiation** (AFML Ch. 5): mentioned, but MAY be
  skipped iter-0 for budget; re-enable if primary signal is non-stationary.

Primary scoring target: **low max_drawdown**, positive total_return, any
sharpe. Composite weights: `sharpe 0.4 / total_return 0.4 / max_drawdown 0.2`.
We willingly trade some gross return for drawdown suppression.

## CRITICAL framing: this is a multi-agent SYSTEM, not a persona

A "team" in this framework is a multi-agent system of collaborating
sub-roles that all run INSIDE `train(ctx)`. It is NOT a single
trader-persona.

The precedents for multi-agent teams in this repository are:

- `competition_1/teams/team_tradingagents_pipeline/` — pipeline-topology
  team where the primary Claude session dispatches CC sub-agents via the
  `Agent` tool.
- `competition_1/teams/team_hedgeagents_hub/` — hub-and-spoke team with
  conference-based coordination.

**This team is DIFFERENT**: we use a **hybrid runtime**. Exactly ONE role
(the `researcher`) runs as a Claude subprocess via
`nautilus_competition.agent_runner.run_claude(...)`. The other 8 roles
are **deterministic Python functions** invoked in-process from
`entry.py`. Rationale:

1. ML fitting is deterministic given hyperparams + data. An LLM is the
   wrong tool for fitting an MLPClassifier.
2. Per-train budget is 600s (`config.agent.per_train_timeout_seconds`).
   Nine LLM subprocesses would not fit.
3. Scientific reproducibility — the non-researcher roles must be
   replayable across rounds from the same seed.

## Roster — 9 roles

| # | Role | Implementation | Runs at | Inputs | Outputs |
|---|------|---------------|---------|--------|---------|
| 1 | `researcher` | `run_claude(...)` subprocess, ~180s budget | train-time, iter start | `docs/state-of-the-art/*.md`, `notes/research_log.md`, `ctx.prev_gain`, `ctx.prev_round_leaderboard` | `attempts/<iter>/research.md` (ephemeral) + `notes/research_log.md` (append-only) |
| 2 | `hypothesis-generator` | Python function | train-time, after researcher | `attempts/<iter>/research.md`, `ctx.prev_gain` | `attempts/<iter>/hypothesis.json` — primary-signal spec + meta-model architecture |
| 3 | `primary-signal-designer` | Python function | train-time | `hypothesis.json` | `attempts/<iter>/primary_signal.json` — signal type (momentum/trend), lookback, threshold |
| 4 | `label-curator` | Python function, **AFML Ch. 3** | train-time | train bars, `primary_signal.json` | `attempts/<iter>/labels.parquet` — triple-barrier labels `{+1, 0, -1}`, trimmed to `t + H ≤ train_end` |
| 5 | `meta-model-builder` | sklearn `MLPClassifier` (fallback `GradientBoostingClassifier`) | train-time | features + primary-side + labels | `attempts/<iter>/meta_model.joblib`, `attempts/<iter>/feature_list.json` |
| 6 | `cv-validator` | Python function, **AFML Ch. 7 (CPCV)** | train-time | model, labels, embargo `≥ H` | `attempts/<iter>/cv_report.json` — OOS AUC, Brier, fold-returns |
| 7 | `critic` | Python function | train-time | hypothesis, labels, cv_report | `attempts/<iter>/critique.md` — leakage checks, overfit flags; can veto (force retry next iter) |
| 8 | `risk-officer` | Python function | train-time, writes runtime rules | cv_report, critique | `attempts/<iter>/runtime_rules.json` — `meta_confidence_threshold`, `drawdown_cap_pct`, `max_position_size_pct` |
| 9 | `memory-keeper` | Python function | train-time, end of iter | all iter artifacts, `ctx.prev_gain` | appends to `notes/research_log.md`, `notes/iteration_ledger.md`, `notes/failed_hypotheses.md` |

## Runtime contract — train-time

`train(ctx)` orchestrates all 9 roles in one call per harness iteration.
The harness calls `train` up to `config.agent.max_train_iterations = 5`
times per round. Order of operations:

1. **memory-keeper** (prelude) — load `notes/research_log.md` and
   `notes/failed_hypotheses.md`. If `ctx.prev_gain is not None` and
   `ctx.prev_gain < 0.0`, surface the last hypothesis + its failure mode
   to the researcher prompt ("primary signal X failed with gain
   `ctx.prev_gain`, explore alternatives").
2. **researcher** — `run_claude(workspace_dir=TEAM_DIR, prompt=...,
   timeout_seconds=180)`. Cache: if
   `attempts/<iter>/research.md` already exists (we were re-entered mid
   iter), SKIP the subprocess call. Also append condensed findings to
   `notes/research_log.md`.
3. **hypothesis-generator** — parse `research.md` → pick one primary
   signal family (momentum, mean-reversion, breakout) + one meta-model
   architecture (MLP default, GBM fallback). Written as JSON for
   replayability.
4. **primary-signal-designer** — materialize the signal spec (lookback
   window, z-score threshold, direction rule).
5. **label-curator** — load train bars via `ParquetDataCatalog`; compute
   primary-signal side at every bar; run triple-barrier labeling with
   `(pt_mult, sl_mult, horizon_H)`; **TRIM any label whose vertical
   barrier extends past `train_end`** (this is load-bearing for AFML
   Ch. 3.5 — otherwise labels leak into eval).
6. **meta-model-builder** — build feature matrix (returns, realized vol,
   primary-side indicator, bar-of-day, etc.), fit `MLPClassifier(
   hidden_layer_sizes=(32, 16), max_iter=200, random_state=42)` on
   `(features, label != 0)` mapped to `{win, loss}` — i.e. META-LABELS,
   not raw direction. Persist via `joblib.dump`.
7. **cv-validator** — CPCV with embargo `= H`. Report OOS AUC + Brier.
   If AUC < 0.52, critic is expected to veto.
8. **critic** — mechanical checks: (a) no label whose `t + H > train_end`,
   (b) embargo covers `H`, (c) OOS AUC > 0.52, (d) feature list contains
   no future-looking columns. Writes `critique.md`; if any fail, include
   `VETO: <reason>` line (memory-keeper surfaces this to next iter's
   researcher).
9. **risk-officer** — derives `meta_confidence_threshold` from the
   CV-validated Brier score (higher Brier → higher threshold, trade less
   often). Caps: `drawdown_cap_pct = 0.10` default, `max_position_size_pct
   = 0.25` of equity per trade. Writes `runtime_rules.json`.
10. **memory-keeper** (postlude) — append thesis, cv_report, critique to
    `notes/research_log.md`; if critic vetoed, append to
    `notes/failed_hypotheses.md`.
11. **return** `(LdpLabStrategy, LdpLabConfig(...))` — config points at
    `attempts/<iter>/meta_model.joblib`, `feature_list.json`, and
    `runtime_rules.json`.

## Runtime contract — trade-time

**NO LLM CALLS AT TRADE TIME.** Strategy is pure Python.

- `on_start`: load `meta_model.joblib`, `feature_list.json`,
  `runtime_rules.json`; fetch instrument via
  `self.cache.instrument(self.config.instrument_id)`.
- `on_bar`:
  1. Update a small rolling feature buffer.
  2. If buffer shorter than `lookback`, return.
  3. Compute primary-signal side (`+1 / 0 / -1`).
  4. Build feature row, query `meta_model.predict_proba(row)`.
  5. If `p_win < meta_confidence_threshold`, **SKIP** (no order).
  6. If current drawdown (tracked in-strategy) `> drawdown_cap_pct`,
     halt: close positions, stop new orders for the remainder.
  7. Else submit market order sized at `max_position_size_pct * equity`,
     side = primary direction.
- The risk-officer's rules act as a **pure Python veto**. No subprocess
  at trade-time — matches the AFML ML-stack-in-production model.

## On-disk memory contract

| Path | Lifetime | Owner |
|------|----------|-------|
| `CLAUDE.md`, `entry.py` | permanent (this authoring) | scaffolder |
| `notes/research_log.md` | append-only across rounds | memory-keeper |
| `notes/iteration_ledger.md` | append-only | memory-keeper |
| `notes/failed_hypotheses.md` | append-only (critic vetoes) | memory-keeper |
| `attempts/<iter>/research.md` | per-iter ephemeral | researcher |
| `attempts/<iter>/hypothesis.json` | per-iter | hypothesis-generator |
| `attempts/<iter>/primary_signal.json` | per-iter | primary-signal-designer |
| `attempts/<iter>/labels.parquet` | per-iter | label-curator |
| `attempts/<iter>/meta_model.joblib` | per-iter | meta-model-builder |
| `attempts/<iter>/feature_list.json` | per-iter | meta-model-builder |
| `attempts/<iter>/cv_report.json` | per-iter | cv-validator |
| `attempts/<iter>/critique.md` | per-iter | critic |
| `attempts/<iter>/runtime_rules.json` | per-iter | risk-officer |
| `incoming/round_NN_leaderboard.md` | harness-owned | harness |

## `prev_gain` / retry behavior

- `ctx.iteration == 0`: first attempt this round. `prev_gain is None`.
  Researcher is asked for a fresh hypothesis.
- `ctx.iteration > 0`:
  - If `ctx.prev_gain is None` — harness quirk; treat as fresh.
  - If `ctx.prev_gain < 0.0`: memory-keeper reads last iter's hypothesis
    + critique + cv_report. Researcher prompt prefixed with:
    `"Primary signal <X> + meta-model <Y> yielded gain <Z>. Critique said <W>. Explore alternatives — swap primary family or meta architecture."`.
  - If `ctx.prev_gain ∈ [0, 1]`: break-even but below gate — tighten
    `meta_confidence_threshold` (fewer, higher-conviction trades).
  - If `ctx.prev_gain > 1.0` — harness shouldn't retry; but if it does,
    re-use the same config (deterministic).

## `prev_round_leaderboard` usage

- Path may be `None` on round 0 — **ALWAYS guard**.
- If present, memory-keeper reads it once per round 0 iteration and
  includes a one-paragraph summary in the researcher prompt. We do NOT
  copy other teams' strategies; the leaderboard only informs which
  regime (trending vs. mean-reverting) currently rewards.

## Bar-type vs paper-duration sanity

Config:
- `bar_type = BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL` → 12 bars/hour.
- `paper.duration_minutes = 15` → only 3 bars live. Paper gate is
  intentionally short — **do not** calibrate the strategy to paper.
- `eval` = 21 days = 30240 min → 6048 bars. Plenty for a meta-model
  featurized on a 48-bar lookback.
- Triple-barrier horizon `H = 24` bars (2h) default; embargo `= 24`.

## Data discipline

- `ctx.get_train_data()` — allowed. 73 days = ~21k bars.
- `ctx.get_test_data()` — allowed ONLY for a post-fit sanity backtest
  (one pass, compute Sharpe, log, move on). NO hyperparam tuning on
  test.
- Eval + paper windows — **forbidden** to read. The harness gates us on
  eval; touching it leaks the gate.
- Instruments — **ALWAYS** load from the catalog
  (`ParquetDataCatalog(path).instruments()`), never
  `TestInstrumentProvider`. This avoids the bar/instrument
  precision-mismatch bug that the
  `nautilus-trader-catalog-instrument-precision` skill documents. In
  the Strategy, use `self.cache.instrument(...)`.

## Hard rules

1. `StrategyConfig` rejects bare `str`. Always `InstrumentId.from_str(...)`
   and `BarType.from_str(...)`.
2. No `Strategy.buy(...)`. Use
   `self.submit_order(self.order_factory.market(...))` with full kwargs
   (`instrument_id`, `order_side`, `quantity`, `time_in_force`).
3. Instruments fetched via `self.cache.instrument(self.config.instrument_id)`
   — not constructed in the Strategy.
4. `LoggingConfig(bypass_logging=True)` where we instantiate any
   engine/node from inside `train()` (we don't, but the skill
   `nautilus-trader-logger-singleton` documents the singleton panic).
5. Triple-barrier labels must be **trimmed** so no `t + H > train_end`.
6. NO look-ahead in features. All feature computation strictly uses
   `bar.ts_event` and earlier.
7. NO trade-time LLM calls. The meta-model is already trained.
8. All file I/O uses absolute paths derived from `TEAM_DIR = Path(__file__).parent`.

## Budget

- `per_train_timeout_seconds = 600` (competition_2 config).
- Researcher subprocess budget: 180s.
- Label curation + meta-fit + CPCV: ≤ 300s on 21k bars with MLP(32,16).
- Keep feature count ≤ 16. Keep CPCV folds ≤ 6.

## References (AFML 2018 mapping)

- Ch. 3 — Labeling, triple-barrier, meta-labeling.
- Ch. 4 — Sample weights (we use `avg_uniqueness` if time permits).
- Ch. 5 — Fractional differentiation (opt-in, skipped iter-0).
- Ch. 7 — CPCV, embargo.
- Ch. 8 — Feature importance (MDI/MDA — inform feature pruning).

## Skills & gotchas (MUST read before editing)

- `nautilus-competition-team-author` — the team contract (this doc
  complies).
- `nautilus-trader-catalog-instrument-precision` — load instruments
  from the catalog, not `TestInstrumentProvider`.
- `nautilus-trader-logger-singleton` — avoid second `BacktestEngine`
  init in-process; we return a Strategy class to the harness, we do NOT
  run our own backtest, so the singleton is not hit at train-time.
- `using-nautilus-trader` — general Nautilus conventions.

## Do/Don't summary

DO: meta-label, CPCV, embargo `≥ H`, skip low-confidence trades, cap
position size, track drawdown in-strategy, persist model to joblib.

DON'T: peek at eval/paper, predict direction with the meta-model,
forget to trim labels, mix instruments from different providers, call
an LLM at trade-time.
