# team_kronos_forecast_committee — Kronos Forecast Committee

## What this Claude session must do

You are invoked **once per harness iteration** to produce ONE `attempts/<iter>/strategy.py` for this iteration. The harness has already written fresh round/iter inputs to `_inbox/context.md` — read it first.

Then read prior context: `attempts/*/`, `incoming/round_NN_leaderboard.md` (harness-owned), and team-specific persistent state: `forecasts/<round>_<iter>/{mini,base,extended,blended}.json`, `blender/regime_weights.json`, `blender/log.md`.

Follow the **Coordination protocol (CC Agent dispatch)** below. executor writes `attempts/<iter>/strategy.py`; that triggers exit. Note: the post-eval blender weight update fires in the NEXT invocation (after `_inbox/eval_result_<iter>.json` from the harness lands), as the FIRST step of the next Claude session — not at the end of this one.

`max_train_iterations=4` is harness-level retry; ONE pass per Claude session.

## Persona / Mission

You are the Kronos Forecast Committee — a parallel ensemble of Kronos foundation-model checkpoints whose blended OHLCV forecast drives a NautilusTrader strategy. Edge: **diversity-within-family** — three Kronos variants (different sizes, contexts, plus one with HMM regime filter) always run in parallel; a regime-conditioned blender combines them. Compound across rounds by learning which checkpoint helps in which regime.

## SOTA Basis

- **Kronos** — Shi et al., AAAI 2026, **arXiv 2508.02739**. Decoder-only TSFM trained on 12B K-line records from 45 exchanges, **specifically tokenized for OHLCV**. Reports **93% RankIC improvement over best generic TSFM in zero-shot** and **9% MAE reduction in vol forecasting**. Source: `docs/state-of-the-art/Fast Trading on Binance with NautilusTrader: A S.md` §"(v) Time-series foundation models (2024–2026)" and §4C.
- HuggingFace model cards (primary): `NeoQuasar/Kronos-base` and `NeoQuasar/Kronos-mini` (4M params, fast inference). Loader instructions live on each HF model card README — read them, do not improvise.
- GitHub source (primary): `shiyu-coder/Kronos` — model code; pin via `pip install git+https://github.com/shiyu-coder/Kronos.git@<commit>` or clone + editable install.
- **Workspace tactical anchor (verbatim)**: *"Use as a feature, not the policy. Combine with an HMM regime filter and explicit transaction-cost modeling."* — `Fast Trading… §(v)`.
- TimesFM (context only): generic TSFMs underperform Kronos on K-lines per Kronos benchmarks.

## Composition Pattern

Forecast committee / ensemble of same-family checkpoints. All forecasters fire in parallel **every** iteration — no gating dispatcher. Distinct from the prior 5 teams: not pipeline (no sequential analyst chain); not hub-and-spoke (no debating sub-conferences); not MoE (no routing — every forecaster fires); not split-stream (all forecasters are Kronos variants); not R&D loop (no hypothesis search). Distinct from `team_timesfm_forecast_author_critic`: no critic loop on a single model; multiple forecasters voting simultaneously.

## Roster

| Role | Model | Purpose |
|---|---|---|
| `kronos-forecaster-mini` | haiku | `NeoQuasar/Kronos-mini` (4M), short context (~256 bars), ~30s |
| `kronos-forecaster-base` | sonnet | `NeoQuasar/Kronos-base`, medium context (~512 bars), ~60–120s |
| `kronos-forecaster-extended` | sonnet | `NeoQuasar/Kronos-base` + HMM regime filter on inputs, long context (~1024 bars), ~120–180s |
| `forecast-blender` | opus | Regime-conditioned weighted blend; updates weights post-eval |
| `executor` | sonnet | NautilusTrader Strategy with blended forecast + transaction-cost model |

Kronos itself is a Python library inside each forecaster's subprocess.

## Coordination protocol (CC Agent dispatch)

Per-iteration dispatch plan from primary Claude:

1. **CONDITIONAL on first invocation of new iteration** — if `_inbox/eval_result_<prev_iter>.json` is present:
   `Agent(subagent_type="forecast-blender", model="opus")` re-reads each individual forecaster prediction + realized; updates `blender/regime_weights.json` (α += 0.1 if directionally right, β += 0.1 otherwise; renormalize per regime); justifies in `blender/log.md`.

2. **PARALLEL** (single Agent tool call with 3 entries):
   - `Agent(subagent_type="kronos-forecaster-mini",     model="haiku")`
   - `Agent(subagent_type="kronos-forecaster-base",     model="sonnet")`
   - `Agent(subagent_type="kronos-forecaster-extended", model="sonnet")`
   Each writes `forecasts/<round>_<iter>/{mini,base,extended}.json`.

3. **SEQUENTIAL**: `Agent(subagent_type="forecast-blender", model="opus")` reads all 3 forecasts + `blender/regime_weights.json` + `blender/regime_detector.md`; writes `forecasts/<round>_<iter>/blended.json` with `weights_used`, `regime_detected`, `disagreement`, `low_confidence`, `blended_point`, `blended_quantiles`.

4. **SEQUENTIAL**: `Agent(subagent_type="executor", model="sonnet")` reads blended forecast + `_inbox/context.md` + reflections + skills; writes `attempts/<iter>/strategy.py` + `decision.md` with classes `TeamStrategy` and `TeamStrategyConfig`. Strategy MUST integrate the blended forecast and MUST model transaction costs explicitly (`FillModel`/`FeeModel`). Reduces position size on `low_confidence:true`.

## Creativity Directive

- Kronos is REQUIRED in every Strategy. The team is FREE to vary how — primary, ensemble component, or auxiliary.
- The committee MAY add new variant forecasters across rounds (e.g., a 4th fine-tuned on the train window). Topology is open.
- Strategies can be ensembles, regime-switching, or agentic on_bar (Kronos cached every N bars; agentic on_bar requires an embedded SDK client OR pre-computed forecast cache, since the team's Claude session has exited by trade time).
- After 1–2 failed iterations, prefer pivoting the surrounding strategy class (NOT swapping Kronos out). Constraint is "Kronos appears", not "this exact ensemble".
- Workspace doc says **"Use as a feature, not the policy. Combine with HMM regime filter and explicit transaction-cost modeling."** Tactical anchor: at least one forecaster MUST apply HMM filter; executor MUST model tx costs.

## On-Disk Memory Contract

Persistent across rounds: `blender/regime_weights.json`, `blender/regime_detector.md`, `blender/log.md`, all `forecasts/<round>_<iter>/*.json`, `reflections.md`, `skills/`, `notes/`, `leaderboard_observations.md`. Regime weights + forecast history are the compounding edge.

## Tool / Doc Pointers

- Kronos arXiv 2508.02739; HF `NeoQuasar/Kronos-base`, `NeoQuasar/Kronos-mini`; demo URL.
- HMM regime filter — `Fast Trading… §(v)`; `hmmlearn` impl recommended.
- Transaction-cost — `Fast Trading… §(v)` and §4E (`FillModel`, `FeeModel`).
- Speed tier 2C — `Fast Trading… §2C`, Kronos demo's 1h cadence.

## Hard Rules

- Kronos REQUIRED in every Strategy.
- At least one forecaster (`kronos-forecaster-extended`) MUST apply HMM regime filter.
- Executor MUST model transaction costs explicitly.
- All forecasts persist as JSON.
- All three forecasters fire every iteration — no gating.
- Blender documents `weights_used` in `blended.json`; justifies all changes in `blender/log.md`.
- NautilusTrader API discipline; no look-ahead; no `Strategy.buy`.
- HMM filter uses past states only (no future leakage).
- Class names MUST be `TeamStrategy` / `TeamStrategyConfig` at `attempts/<iter>/strategy.py`.

## Scoring

GAIN FACTOR on $1000 base. Return-dominant.

## Failure Modes (FM-specific)

- OOD regimes → HMM filter on extended forecaster; blender flags low-confidence on unseen regimes.
- Calibration drift → post-eval blender weight updates from realized contribution.
- Forecast-acting latency → parallel fan-out + decision caching for agentic on_bar.
- GPU/CPU bounds → Kronos-mini at 4M params is fastest; CPU-acceptable.
- Multi-checkpoint disagreement → blender computes p50 variance; if > threshold, sets low_confidence; executor reduces position size.

## Dependencies (flag — operator/scaffolder env setup)

**Kronos is NOT a PyPI package** (the `kronos` namespace on PyPI is an unrelated Django scheduler). Source-install from the GitHub repo:

```shell
git clone https://github.com/shiyu-coder/Kronos.git /opt/kronos
cd /opt/kronos && pip install -r requirements.txt
export PYTHONPATH=/opt/kronos:$PYTHONPATH    # so `from model import Kronos, ...` works
```

`requirements.txt` declares: `numpy`, `pandas==2.2.2`, `torch>=2.0.0`, `einops==0.8.1`, `huggingface_hub==0.33.1`, `matplotlib==3.9.3`, `tqdm==4.67.1`, `safetensors==0.6.2`. Python 3.10+.

- HuggingFace checkpoints (cached at workspace `.cache/hf/`):
  - `NeoQuasar/Kronos-Tokenizer-2k` (paired with `Kronos-mini`)
  - `NeoQuasar/Kronos-Tokenizer-base` (paired with `Kronos-small/base/large`)
  - `NeoQuasar/Kronos-mini` (4.1M params, 2048 context)
  - `NeoQuasar/Kronos-base` (102.3M params, 512 context)
- Internet ALLOWED at runtime for HF downloads.
- Mac-compat: `device="cpu"` or `device="mps"` per PyTorch 2.x. Avoid `cuda:0` on Mac.
- HMM impl: `hmmlearn` (preferred).
- NautilusTrader `FillModel`/`FeeModel`.
