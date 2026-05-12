# team_kronos_feature_engineer — Foundation Model As Feature, Simple Model As Decision

## Persona / Mission

We are a **quant research lab** that treats Kronos (Shi et al., AAAI 2026, arXiv
2508.02739) as a *pretrained feature extractor*, NOT as a policy. Our
differentiating thesis against `competition_1/teams/team_kronos_forecast_committee`
(which uses Kronos to predict direction directly): **Kronos features → classical
ML head (GBM / logistic) → vol-targeted long/flat**. Motto: "foundation model as
feature; simple model as decision."

Edge rationale (per `docs/state-of-the-art/Fast Trading on Binance with
NautilusTrader…` §(v), tactical anchor, verbatim): *"Use as a feature, not the
policy. Combine with an HMM regime filter and explicit transaction-cost
modeling."* Competition_1's forecast committee honored part of that line; we
honor the other half — we let Kronos' last-layer embeddings be features and we
let a small, leakage-audited GBM be the decision.

Primary scoring dimension: **sharpe** (`config.yaml scoring.weights.sharpe =
0.4`). Secondary: total_return (0.4), max_drawdown (0.2). Vol-targeting is
chosen deliberately to drag Sharpe up at the expense of raw return when regimes
blow out.

## IMPORTANT — this team is NOT a single Claude session

Other teams in the repo (`team_tradingagents_pipeline`, `team_hedgeagents_hub`,
`team_kronos_forecast_committee`, `team_rdagent_quant_lab`) boot a full Claude
session from `train(ctx)` that then dispatches sub-agents via the `Agent` tool.
**We do NOT.**

`train(ctx)` here is **deterministic Python** with exactly ONE `run_claude(...)`
subprocess call (the `researcher` role). All other roles are pure Python
functions inside `entry.py` that read the researcher's JSON output and produce
artifacts. This keeps us inside the 600s budget (`config.agent.per_train_timeout_seconds`)
and removes orchestration failure modes.

A "role" for this team is therefore:
- ONE Python function (most roles), OR
- ONE `run_claude(...)` call (the researcher only).

Communication happens via files in the team folder (`attempts/<iter>/`,
`notes/`, `runtime_rules.json`, the persisted model file).

## Roster (8 roles)

| # | Role | Kind | Writes | Reads |
|---|---|---|---|---|
| 1 | `researcher` | `run_claude(...)` subprocess (~180s) | `attempts/<iter>/research.md` (JSON), appends to `notes/research_log.md` | `CLAUDE.md`, `_inbox/context.md`, `notes/research_log.md`, `competition_2/docs/state-of-the-art/*`, `competition_1/teams/*/reflections.md` + `notes/*` |
| 2 | `hypothesis-generator` | Python (deterministic) | `attempts/<iter>/hypothesis.json` | researcher's `research.md`, `notes/research_log.md`, `ctx.prev_gain` |
| 3 | `critic` | Python (deterministic) | `attempts/<iter>/critic.md` | hypothesis, `notes/leakage_checklist.md` |
| 4 | `risk-officer` | Python (deterministic) | `runtime_rules.json` (team root) | hypothesis, critic, `ctx.prev_round_leaderboard`, `ctx.prev_gain` |
| 5 | `memory-keeper` | Python (deterministic) | appends `notes/round_<N>_thesis.md`, updates `notes/feature_registry.md` | all `notes/*`, `ctx.prev_round_leaderboard`, `ctx.prev_gain` |
| 6 | `feature-engineer` | Python (deterministic) | `attempts/<iter>/features.parquet`, `attempts/<iter>/feature_spec.json` | train bars from `ctx.get_train_data()`, hypothesis |
| 7 | `model-builder` | Python (deterministic) | `attempts/<iter>/model.joblib` + `attempts/<iter>/model_meta.json` | features + labels |
| 8 | `validator` | Python (deterministic, CPCV) | `attempts/<iter>/validation.json` | model, held-out folds from **train window only** |

**The researcher is the ONLY LLM call.** `hypothesis-generator`, `critic`,
`risk-officer`, and `memory-keeper` are simple deterministic functions that
*read* the researcher's JSON and apply rules. This is intentional — they would
be LLM calls in a bigger-budget shape, but we cannot afford 4 more Claude
subprocesses inside a 600s budget and still fit model fitting.

## Invocation order (inside `train(ctx)`)

```
 0.  memory-keeper.consult_prior_rounds(ctx)  → prior_context.md
 1.  researcher()  (run_claude, ~180s timeout)  → attempts/<iter>/research.md
 2.  hypothesis-generator(research, prior_context, ctx.prev_gain)  → hypothesis.json
 3.  critic(hypothesis)  → critic.md  (may demote features; never hard-fail)
 4.  feature-engineer(train_bars, hypothesis, critic)  → features.parquet
 5.  model-builder(features, labels)  → model.joblib
 6.  validator(model, train_folds [CPCV])  → validation.json
 7.  risk-officer(validation, ctx.prev_round_leaderboard, critic)  → runtime_rules.json
 8.  memory-keeper.append_round_thesis(...)  → notes/round_<N>_thesis.md
 9.  return (TeamStrategy, TeamStrategyConfig(... model_path=..., rules_path=...))
```

Step 0 runs FIRST so the researcher prompt can be conditioned on past
round retrospectives. Step 8 runs LAST so the thesis entry includes everything
we actually committed to this round.

## Researcher contract (role #1 — the one LLM call)

### Budget

~180s on a 600s global budget. Leaves ~400s for feature engineering, model
fitting, CPCV validation, and strategy assembly.

### System-prompt priorities

The researcher's prompt explicitly ranks its sources:

1. **`competition_2/docs/state-of-the-art/`** (if it exists in the current
   working directory's repo) — the competition's authoritative SOTA curation.
2. **`competition_1/teams/*/reflections.md`** and `competition_1/teams/*/notes/*`
   — what *other* teams learned in prior competitions. Concrete > abstract.
3. **External `arXiv` / papers** — Kronos (2508.02739) itself, HAR-RV (Corsi
   2009), realized-skew (Amaya et al. 2015), vol-weighted momentum (Moskowitz
   et al. 2012). Used to justify feature choices.

### Output contract (researcher → disk)

Researcher writes `attempts/<iter>/research.md` containing a fenced JSON block
with this shape:

```json
{
  "feature_shortlist": [
    {"name": "har_rv_22", "rationale": "...", "expected_sign": "neg", "paper_ref": "Corsi 2009"},
    {"name": "kronos_last_hidden_mean", "rationale": "...", "expected_sign": "unsure", "paper_ref": "arXiv 2508.02739"},
    ...
  ],
  "model_head": "lightgbm" | "logistic" | "gbm_sklearn",
  "label_horizon_bars": 12,
  "label_def": "sign(close[t+h] - close[t])",
  "regime_gate": {"realized_vol_annualized_max": 1.8},
  "vol_target_annualized": 0.20,
  "drawdown_cap_pct": 0.15,
  "position_size_cap_pct": 0.60,
  "prior_hypothesis_failed": true | false,
  "notes_for_next_round": "..."
}
```

`entry.py` parses this block. If the parse fails (invalid JSON, missing fields)
the `hypothesis-generator` falls back to a **hardcoded default** hypothesis
documented in `notes/fallback_hypothesis.json` so the round still ships.

### Cache / persistence

- Ephemeral: `attempts/<iter>/research.md` (full Claude output, forensic).
- Persistent: the actionable findings get appended to `notes/research_log.md`
  by `memory-keeper` so future rounds don't re-ask the same questions.

## Retry behaviour (`ctx.prev_gain` on iteration > 0)

`train(ctx)` is called with `ctx.iteration == 0` on the first try; retries pass
`ctx.prev_gain = last_eval_gain_factor - 1.0`.

- `ctx.prev_gain is None` → iter 0; researcher runs normal prompt.
- `ctx.prev_gain is not None and ctx.prev_gain < 0`:
  - `memory-keeper` reads last round's `notes/round_<N>_thesis.md` and the
    most recent `attempts/*/hypothesis.json`.
  - Researcher's prompt gets an appended "prior hypothesis failed
    (gain=<value>); the feature set was <X>, the regime gate was <Y>. Propose a
    materially different shortlist — e.g., swap HAR-RV for realized-bipower, or
    relax the regime gate, or move from GBM to logistic." Goal: force
    exploration, not parameter nudging.
- `ctx.prev_gain is not None and ctx.prev_gain >= 0`:
  - Very unusual (the harness only retries on failure), but guard anyway.
  - Researcher's prompt is unchanged; deterministic Python re-runs with the
    same hypothesis to confirm reproducibility.

## Runtime contract — two phases

### Phase A: train-time (inside `train(ctx)`, 600s budget)

Per "Invocation order" above. End result:

1. `attempts/<iter>/model.joblib` persisted on disk.
2. `runtime_rules.json` at team root with fields:
   ```json
   {
     "drawdown_cap_pct": 0.15,
     "position_size_cap_pct": 0.60,
     "vol_target_annualized": 0.20,
     "regime_gate": {"realized_vol_annualized_max": 1.8},
     "label_horizon_bars": 12,
     "prediction_threshold_long": 0.55,
     "prediction_threshold_flat": 0.50
   }
   ```
3. Return `(TeamStrategy, TeamConfig(instrument_id=..., bar_type=...,
   model_path=..., rules_path=...))`.

### Phase B: trade-time (`Strategy.on_bar`, live paper, 3 bars)

**No LLM calls at trade-time.** The "live critic" is pure Python reading
`runtime_rules.json`.

1. `on_start` — load `model.joblib` and `runtime_rules.json`. Fetch instrument
   via `self.cache.instrument(self.config.instrument_id)`.
2. On every bar:
   a. Maintain a rolling buffer of closes / highs / lows / volumes.
   b. Compute live features (same spec as train-time: HAR-RV, realized-skew,
      vol-weighted momentum residual, plus Kronos embedding IF the model was
      loaded successfully; otherwise fall back to the 3 classical features).
   c. Get `p_long = model.predict_proba(X)[0,1]`.
   d. Apply live critic (from `runtime_rules.json`):
      - If `realized_vol > regime_gate.realized_vol_annualized_max`: skip (flat).
      - If `p_long < prediction_threshold_flat`: flat.
      - Else: size = `vol_target_annualized / max(realized_vol, epsilon)`,
        capped at `position_size_cap_pct`.
   e. If current position differs from target, submit a single market order.

The trade-time critic is **rules, not thinking** — this is what "crystallize"
means here. The thinking happened at train-time; trade-time just evaluates the
rule set.

## On-disk memory contract

| Path | Persists across rounds? | Owner |
|---|---|---|
| `CLAUDE.md` | yes | scaffolder (this file) |
| `entry.py` | yes | scaffolder |
| `_inbox/context.md` | per-iteration (overwritten) | `entry.py` |
| `attempts/<iter>/research.md` | yes (forensic, ephemeral for round) | researcher |
| `attempts/<iter>/hypothesis.json` | yes | hypothesis-generator |
| `attempts/<iter>/critic.md` | yes | critic |
| `attempts/<iter>/features.parquet` | yes | feature-engineer |
| `attempts/<iter>/model.joblib` | yes — Strategy loads from here | model-builder |
| `attempts/<iter>/validation.json` | yes | validator |
| `runtime_rules.json` (team root) | per-iter (overwritten) — Strategy reads | risk-officer |
| `notes/research_log.md` | yes | memory-keeper |
| `notes/round_<N>_thesis.md` | yes (append-only) | memory-keeper |
| `notes/feature_registry.md` | yes | memory-keeper |
| `notes/fallback_hypothesis.json` | yes (scaffolder-seeded) | scaffolder |
| `incoming/round_NN_leaderboard.md` | yes | harness |

## Feature engineering — concrete spec

Three "always-on" classical features (must work without Kronos):

1. **HAR-RV** (Corsi 2009): realized variance over 1, 5, 22 bar windows; a
   recent realized-vol regressor that's well-known to trade off Sharpe and
   turnover.
2. **Realized skew** (Amaya et al. 2015): third central moment of log returns
   over a rolling window; weak but stable edge.
3. **Vol-weighted momentum residual** (Moskowitz 2012 + de-meaning by rolling
   realized vol): classical TSMOM with vol normalization.

One optional feature (activates only if Kronos weights load in < 30s):

4. **Kronos last-hidden mean** (arXiv 2508.02739): mean-pool of the last
   transformer layer over a fixed lookback. Used as a dense feature, never
   decoded to a forecast.

If `feature_shortlist` includes `kronos_*` fields but Kronos load fails or
exceeds the 30s budget, the `feature-engineer` drops them silently and
continues with the three classical features. The model is retrained on
whatever features actually loaded — no skipped rounds.

## Leakage discipline (critic's main job)

The `critic` applies a hard checklist:

- All rolling windows are strictly trailing (`.shift(1)` applied).
- Labels are computed from `close[t+h]` but features are computed up to
  `close[t]`.
- CPCV folds have embargo ≥ `label_horizon_bars` on each side.
- Train window ONLY is used for fitting. `ctx.get_test_data()` is used for a
  single out-of-sample sanity check before returning — never for model
  selection.
- `eval` / `paper` windows are NEVER opened in `train()`. Reading them is a
  disqualifying leak.

Critic output is advisory (it annotates `critic.md`) and can demote features
but never blocks the round. A true blocker would fail-closed and miss the
iteration; instead we narrow the feature set and keep going.

## Top gotchas (must-not-regress)

1. `StrategyConfig` rejects bare `str` — use `InstrumentId.from_str(...)` and
   `BarType.from_str(...)` when constructing `TeamConfig`.
2. No `Strategy.buy` — use
   `self.submit_order(self.order_factory.market(instrument_id=..., order_side=OrderSide.BUY, quantity=self.instrument.make_qty(size), time_in_force=TimeInForce.GTC))`.
3. Instrument fetch: `self.cache.instrument(self.config.instrument_id)` in
   `on_start`. Never construct (skill:
   `nautilus-trader-catalog-instrument-precision`).
4. Logger singleton across engines: the harness handles this via
   `BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True))`; our
   Strategy must NOT re-init logging (skill:
   `nautilus-trader-logger-singleton`).
5. OOS leakage: never call anything that could open `eval` or `paper` windows
   — disqualifying.
6. Kronos download > 500MB at runtime is a hard no. Feature engineer must
   time-budget the Kronos load (30s cap) and fall back cleanly.
7. Bar-count warm-up: `paper.duration_minutes = 15` in `config.yaml` with a
   5-minute bar → only **3 bars** at paper. Indicators must warm up from
   lookback state loaded at `on_start` (the model + rolling buffer init from
   train-tail bars); we cannot rely on warming up during paper.

## Budget knobs (global, `config.yaml`)

- `agent.per_train_timeout_seconds = 600`
- `agent.max_train_iterations = 5`
- Researcher subprocess internal budget: `~180s` (leaves ~420s headroom).

## Supporting skills

- `nautilus-competition-team-author` — per-team contract.
- `nautilus-trader-catalog-instrument-precision` — bar / instrument precision.
- `nautilus-trader-logger-singleton` — re-init panic avoidance.
- `using-nautilus-trader` — Strategy lifecycle hooks.
