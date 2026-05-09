# team_rdagent_quant_lab — Research → Development → Feedback (RD-Agent(Q)-style)

## What this Claude session must do

You are invoked **once per harness iteration** to produce ONE winning Strategy artifact for this iteration. The harness has already written fresh round/iter inputs to `_inbox/context.md` — read it first.

Then read prior context: `attempts/*/`, `incoming/round_NN_leaderboard.md` (harness-owned), and team-specific persistent state: `forest/{accepted,rejected}/<id>.md` and `forest/index.jsonl` (the compounding edge across iterations and rounds), `bandit/state.json` + `log.jsonl`, `arms/<arm>/prompts.md`.

Follow the **Coordination protocol (CC Agent dispatch)** below. Run ONE R→D→F pass: bandit picks an arm, synthesis emits k=8–16 hypotheses, several are implemented and internally Gate-1/2/3 validated, feedback writes forest nodes, bandit updates posteriors. Then commit the best Gate-passing candidate by writing `_inbox/winning_hypothesis.json` with `{round, iter, hypothesis_id, code_path}`. Synthesis depth is k=8–16 hypotheses per session, NOT k=20–40 (revised down from prior spec to fit the global 3600s budget).

`max_train_iterations=4` is harness-level retry. Internal validation-agent runs CPCV on training window only; the harness owns the eval-window backtest. Forest grows across harness iterations and across rounds — that's the team's compounding edge.

## Persona / Mission

We are a quantitative research lab, not a trading desk. Edge: the systematic search procedure itself. Strategy-discovery as sequential decision over hypothesis space, with multi-armed bandit allocating compute across arms and a semantic knowledge forest compounding across rounds.

This team implements the RD-Agent(Q) blueprint (arXiv 2505.15155, NeurIPS 2025; repo `microsoft/RD-Agent`, built on `microsoft/Qlib`). Per `docs/state-of-the-art/State of the Art in Quantitative Trading and Age.md` §PART 2 §B/§C: most rigorously validated agentic-quant system; 2× annualized return vs Alpha158/TRA with 70% fewer factors; <$10/experiment.

## Composition Pattern: Typed R → D → F + Bandit Executive

- **Research (R)** — `specification-agent` + `synthesis-agent`
- **Development (D)** — `implementation-agent` (Co-STEER) + `validation-agent`
- **Feedback (F)** — `feedback-agent`
- **Executive function** — `bandit-scheduler`

All six roles are CC agents dispatched by the primary Claude session within a single iteration's 3600s budget. The bandit-scheduler runs first; remaining roles are dispatched per-arm as the bandit selects.

## Roster

| Role | Job | Model |
|---|---|---|
| `specification-agent` | Turn business goal + DataHandle + arm + forest summary into focused prompt | sonnet |
| `synthesis-agent` | Generate k diverse hypotheses, condition on forest | opus |
| `implementation-agent` (Co-STEER) | Write Strategy Python against NautilusTrader API | sonnet |
| `validation-agent` | Run BacktestEngine, compute IC/IR/ARR/MDD, six gates | haiku |
| `feedback-agent` | Append to forest with semantic tags, reason over topology | opus |
| `bandit-scheduler` | Thompson sampling over arms; spawn new arm on plateau | sonnet |

## Bandit Arms (Initial)

Thompson sampling over Beta posteriors. Reward = clipped, normalized **gain factor** of surviving Strategy on post-cutoff holdout (0 if no Gate-5 survivor).

- **`factor-mining`** — synthesis emits factor expressions in WorldQuant-101 / Qlib `Alpha158` operator grammar (`ts_rank`, `delta`, `corr`, `decay_linear`, …). Strategy = linear combination over surviving factors.
- **`model-search`** — synthesis emits ML model architectures (LightGBM / TabNet / TFT / TRA) over fixed feature bundle.
- **`agentic` (force-spawnable, lazy)** — synthesis emits an agentic on_bar policy (with embedded Anthropic SDK client). NOT initialized at round 0. Bandit MUST force-spawn after 1–2 plateaus (≤5% best-gain improvement over 3 consecutive iters on both initial arms).

## Pivot License

bandit-scheduler authorized to spawn new arm when existing plateau. New arms written to `arms/<arm>/prompts.md` with seed prompt by feedback-agent (forest-wide context).

## Knowledge Forest Semantics

Semantic, not opaque. Every node:
```
{ "id": "<round>_<iter>_<hyp_idx>", "parent_id": "<id or null>",
  "status": "accepted"|"rejected",
  "failure_class": "overfit"|"look-ahead"|"alpha-decay"|"regime-brittle"|"gate-5-fail"|"n/a",
  "arm": "factor-mining"|"model-search"|"agentic",
  "hypothesis_text": "...",
  "eval": { "ic":..., "ir":..., "sharpe_cpcv":..., "dsr":...,
            "oos_sharpe":..., "regime_sharpe":{...}, "gain_factor":... } }
```
Synthesis-agent receives forest summary scoped to current arm: top-N accepted (templates to mutate) + top-N recently rejected (failure classes to avoid). **Compounding edge across rounds** — disk persistence mandatory.

## Six Validation Gates (verbatim from `State of the Art… §D`)

1. **Code-runs** — 5-day smoke run.
2. **In-sample IC > 0.02 and IR > 0.3**.
3. **CPCV Sharpe > 1.0 net, > 0.5 net** — combinatorial purged CV with embargo ≥ holding horizon.
4. **Deflated Sharpe Ratio > 0** with TRUE trial count (every hypothesis evaluated this round, not just survivors).
5. **Post-cutoff OOS net Sharpe > 0.3, consistent sign**.
6. **Regime-segmented Sharpe > 0** across bull/bear/chop.

Validation-agent emits `gates/<round>_<iter>.json` with pass/fail per gate. Note: Gates 1-3 are run INTERNALLY in the Claude session; Gate 4 uses TRUE trial count from `bandit/log.jsonl`; Gates 5-6 require multi-iteration data and may be deferred. The harness's eval-window backtest is the externally-binding test.

## Scoring Alignment

Winning criterion = gain factor on $1000. Gate 5 preserved as INTERNAL quality filter. Validator's scoring vector re-weighted so final ranking among Gate-5 survivors is post-cutoff dollar gain (not deflated Sharpe):
```
score = gate5_pass ? oos_gain_factor : 0
```
Bandit reward = `clip(score - 1.0, 0, 2.0)`.

## Coordination protocol (CC Agent dispatch)

Per (internal R→D→F) pass within ONE Claude session, primary Claude:

1. **SEQUENTIAL**: `Agent(subagent_type="bandit-scheduler", model="sonnet")` reads `bandit/state.json` + `pivot_signal.json` (if present); writes `attempts/<round>_<it>/arm_chosen.txt`.

2. **SEQUENTIAL**: `Agent(subagent_type="specification-agent", model="sonnet")` reads arm + forest summary + DataHandle schema; writes `attempts/<round>_<it>/spec.md`.

3. **SEQUENTIAL**: `Agent(subagent_type="synthesis-agent", model="opus")` emits k=8–16 hypotheses to `attempts/<round>_<it>/hypotheses.md`.

4. **PARALLEL** where budget allows — per top-h hypotheses:
   `Agent(subagent_type="implementation-agent", model="sonnet")` writes `attempts/<round>_<it>/code_<h>.py`.
   Then `Agent(subagent_type="validation-agent", model="haiku")` writes `attempts/<round>_<it>/eval_<h>.json` + `gates/<round>_<it>.json`.

5. **SEQUENTIAL**: `Agent(subagent_type="feedback-agent", model="opus")` appends to `forest/{accepted|rejected}/<id>.md` and `forest/index.jsonl`; writes `attempts/<round>_<it>/feedback.md`. May write `bandit/pivot_signal.json` on plateau.

6. **SEQUENTIAL**: `bandit-scheduler` dispatched again to update arm Beta posteriors based on best Gate-passing survivor's gain.

7. The primary Claude session selects the best Gate-passing candidate and writes `_inbox/winning_hypothesis.json` with `{round, iter, hypothesis_id, code_path}` referencing the chosen `code_<h>.py`. Then exits.

## Compute Budget

Global `agent.per_train_timeout_seconds = 3600`. With k=8–16 hypotheses per session and ~60s per internal backtest, the budget allows ~30 min of generation/validation + 30 min of synthesis/feedback overhead. **If forest growth < 10 nodes per round under the cap, escalate to team-lead — may need a per-team timeout exception.**

## Creativity Directive

- **Pivot license**: bandit may spawn `agentic` arm (or further new arms) after 1–2 plateaus. Force-spawn mandatory after 2nd plateau.
- **Strategy form unconstrained**: classical alpha formulas, ML-driven, agentic on_bar — validation only sees the gain.
- **Failure-class tagging mandatory**: feedback-agent MUST classify rejections into the enum so synthesis avoids the failure mode.
- **Forest, not list**: `parent_id` enables mutation chains and ancestry reasoning.

## Tool / Doc Pointers

- RD-Agent(Q) arXiv 2505.15155, repo `microsoft/RD-Agent`.
- AlphaAgent arXiv 2502.16789 (alpha-decay regularization).
- AlphaJungle arXiv 2505.11122 (LLM-MCTS hypothesis search; synthesis fallback).
- Qlib `Alpha158` operator vocabulary.
- `State of the Art… §PART 2 §B/§C/§D` and §Stage 3.
- NautilusTrader `BacktestEngine` as validator harness.
- Fee/latency model — `Fast Trading… §4E`.

## Hard Rules

1. Correct NautilusTrader API.
2. CPCV with embargo ≥ holding horizon.
3. Post-cutoff holdout reserved at round start; never touched by synthesis.
4. Deflated Sharpe uses TRUE trial count (`bandit/log.jsonl` line count).
5. Speed tier: 2C (`Fast Trading… §2C`).
6. Class names in each `code_<h>.py` MUST be `TeamStrategy` and `TeamStrategyConfig`.
7. The session MUST write `_inbox/winning_hypothesis.json` before exit, naming the survivor's `code_path`.

## Failure Modes

- Bandit over-exploits one arm (Thompson mitigates; feedback-agent monitors KL divergence).
- In-sample overfit (Gate 4 firewall; if trial count > 100 and DSR shrinks to 0, force regime reset).
- <5% survival rate (per §Stage 3, expected; if <2% for two iters, force-spawn agentic arm).
