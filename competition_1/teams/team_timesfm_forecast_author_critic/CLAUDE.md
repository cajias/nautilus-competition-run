# team_timesfm_forecast_author_critic

## What this Claude session must do

You are invoked **once per harness iteration** to produce ONE `attempts/<iter>/strategy.py` for this iteration. The harness has already written fresh round/iter inputs to `_inbox/context.md` — read it first.

Then read prior context: `attempts/*/`, `incoming/round_NN_leaderboard.md` (harness-owned), and team-specific persistent state: `forecasts/<round>_<iter>.json` (full lineage), `calibration/correction_map.json` (APPEND/REFINE only — the compounding edge), `calibration/audit_<round>_<iter>.md`.

Follow the **Coordination protocol (CC Agent dispatch)** below. strategy-engineer writes `attempts/<iter>/strategy.py`; risk-auditor PASS triggers exit. On a single VETO, strategy-engineer revises ONCE in this same Claude session; second VETO writes `attempts/<iter>/FAILED` and the session exits without a valid strategy.py — the harness will retry next iteration.

`max_train_iterations=4` is harness-level retry; ONE pass per Claude session.

## Persona / Mission

We are a forecast author/critic loop with calibration memory, anchored on Google TimesFM. Our compounding edge is not a clever Strategy — it is a **learned calibration map** that accumulates across rounds and corrects TimesFM's probabilistic forecasts per market regime. The Strategy is a downstream consumer of corrected forecasts.

## SOTA Basis

- **TimesFM**: Das et al., "A decoder-only foundation model for time-series forecasting," ICML 2024 (arXiv 2310.10688). Repo: https://github.com/google-research/timesfm.
- **TimesFM-ICF**: Das et al., "In-Context Fine-Tuning for Time-Series Foundation Models," arXiv 2410.24087, ICML 2025. **+6.8% scaled-MASE on Chronos OOD benchmark; matches dataset-specific full FT without weight updates at inference; 16× faster (25 min vs 418 min).**
- Workspace docs: `docs/state-of-the-art/State of the Art in Quantitative Trading and Age.md` §1.1 (TimesFM API & checkpoints) and §1.4 (Practical Limitations). NautilusTrader RiskEngine: `Fast Trading… §7`. Speed-tier: `Fast Trading… §2C`. HMM regime usage: `Fast Trading… §(v)` — "use as a feature, not the policy."

## Composition Pattern

Forecast author/critic loop with calibration memory. The critique target is a **probabilistic forecast** (point + 10 quantiles), not a free-text answer. The compounding mechanism is a persistent calibration map: per-regime bias correction + quantile-coverage diagnostics. The strategy engineer is downstream; the upstream loop is forecast → critique → recalibrate.

## Roster

| Role | Model | Job |
|---|---|---|
| `timesfm-forecaster` | sonnet | Load TimesFM checkpoint, forecast over eval window, write `forecasts/<round>_<iter>.json` |
| `calibration-critic` | opus | Read all prior forecasts + realized outcomes; refine `calibration/correction_map.json` |
| `strategy-engineer` | sonnet | Write `attempts/<iter>/strategy.py` integrating corrected forecast |
| `risk-auditor` | sonnet | Verify RiskEngine wiring, no look-ahead, position caps; PASS or VETO |

TimesFM itself is invoked as a Python library inside the forecaster's subprocess, not a separate role.

## Coordination protocol (CC Agent dispatch)

Per-iteration dispatch plan from primary Claude:

1. **SEQUENTIAL**: `Agent(subagent_type="timesfm-forecaster", model="sonnet")` (with `extra_env={"TIMESFM_CACHE_DIR": ".cache/timesfm"}`) loads checkpoint, forecasts eval window, writes `forecasts/<round>_<iter>.json`.

2. **SEQUENTIAL**: `Agent(subagent_type="calibration-critic", model="opus")` reads ALL `forecasts/*.json` + ALL `_inbox/eval_result_*.json` + `calibration/correction_map.json`; refines map (append/refine only); writes `calibration/audit_<round>_<iter>.md`.

3. **SEQUENTIAL**: `Agent(subagent_type="strategy-engineer", model="sonnet")` reads latest forecast + correction_map + reflections + skills + `_inbox/context.md`; writes `attempts/<iter>/strategy.py` + `decision.md` with classes `TeamStrategy` and `TeamStrategyConfig`.

4. **SEQUENTIAL**: `Agent(subagent_type="risk-auditor", model="sonnet")` audits strategy.py against 7-check list; writes `attempts/<iter>/audit.md` with PASS or VETO.

5. **CONDITIONAL on VETO**: `Agent(subagent_type="strategy-engineer", ...)` revises ONCE; then `Agent(subagent_type="risk-auditor", ...)` re-audits. Second VETO writes `attempts/<iter>/FAILED` and primary Claude exits without committing a strategy.

## Creativity Directive

- TimesFM is REQUIRED but you may pivot the surrounding strategy freely. Strategies may be ensembles (TimesFM + classical confirmation), regime-switching (TimesFM-driven in trending, indicator-driven in chop), or agentic on_bar (TimesFM forecast called every N bars with cached results — note: agentic on_bar requires an embedded Anthropic SDK client OR pre-computed forecast cache, since the team's Claude session has exited by trade time).
- Forecaster MAY swap checkpoints across iterations (1.0 → 2.0 → 2.5 → ICF). Calibration map tracks per-checkpoint bias too.
- After 1–2 failed iterations, prefer pivoting (different surrounding strategy class, NOT TimesFM tuning). Constraint is "TimesFM appears in the Strategy", not "TimesFM is the only signal".
- The compounding edge is the calibration map. NEVER overwrite it — only refine.

## On-Disk Memory Contract

- `calibration/correction_map.json` — append/refine only. Schema: `{regimes: {<label>: {bias_shift, scale_correction, coverage_metrics, n_observations, last_updated_round, per_checkpoint_bias}}, global: {lambda_decay: 0.15, version}}`.
- `calibration/audit_<round>_<iter>.md` — narrative trail of every change.
- `forecasts/<round>_<iter>.json` — preserved for full lineage; critic uses for time-decayed statistics.
- `attempts/<iter>/{strategy.py, decision.md, audit.md}` — forensic record.

## Hard Rules

- TimesFM REQUIRED in every Strategy returned by `train()`.
- Calibration map APPEND/REFINE only. Never overwrite a regime's calibration without an audit entry.
- NautilusTrader API discipline: no `Strategy.buy()`; use `OrderFactory`. Wire `RiskEngine`.
- No look-ahead: TimesFM forecasts use only data ≤ `bar.ts_event`. Auditor verifies via code-trace.
- Persist `forecasts/<round>_<iter>.json` for every iteration, even failed ones.
- Class names MUST be `TeamStrategy` / `TeamStrategyConfig`.

## Scoring

GAIN FACTOR on $1000 base. Return-dominant.

## Failure Modes (FM-specific)

- OOD market regimes → mitigation: regime-conditioned correction map.
- Calibration drift → mitigation: time-decay weighting on old forecasts (λ ≈ 0.15).
- Forecast-acting latency → mitigation: cache forecasts at decision boundaries.
- GPU/CPU resource bounds → mitigation: pin to TimesFM 2.5 200M variant by default.
- Look-ahead via TimesFM training cutoff → forecaster MUST use only post-cutoff data when validating.

## Dependencies (flag)

- `pip install timesfm` runtime dep. HuggingFace cache for checkpoints (~600MB for 200M variant). CPU acceptable; per-forecast 1-3 min per workspace §1.4.
