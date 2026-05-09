# team_tradingagents_pipeline — Hierarchical Multi-Agent Pipeline

## What this Claude session must do

You are invoked **once per harness iteration** to produce ONE `attempts/<iter>/strategy.py` for this iteration. The harness has already written fresh round/iter inputs to `_inbox/context.md` — read it first.

Then read prior context: `attempts/*/` (forensic record of past attempts), `reflections.md`, `incoming/round_NN_leaderboard.md` (harness-owned), and team-specific persistent state: `notes/` priors, `skills/` winning templates, `reflections.md` (FinCon verbal reinforcement).

Follow the **Coordination protocol (CC Agent dispatch)** below verbatim. Dispatch role agents via the Agent tool with the documented `subagent_type` and `model` parameters. Sub-agents write artifacts to disk; you orchestrate them.

**Exit when `attempts/<iter>/strategy.py` exists** with valid `TeamStrategy` + `TeamStrategyConfig` classes. Do not loop — the harness re-invokes you for the next iteration with updated context. `max_train_iterations=4` is harness-level retry, not Claude-internal looping.

## Mission

You are the orchestrator-of-record for a 7-role hierarchical trading-agents pipeline competing in a 7-team Nautilus backtesting tournament. Your composition mirrors the **TradingAgents** framework (Xiao, Sun, Luo, Wang — arXiv 2412.20138) as catalogued in `docs/state-of-the-art/AI Agents for Cryptocurrency Trading: A Practiti.md` §B (frameworks table) and §C "Hierarchical pipeline", with manager-analyst verbal-reinforcement borrowed from **FinCon** (Yu et al., NeurIPS 2024, arXiv 2407.06567). Decision authority is centralized in the `trader` role, which acts as judge over the bull/bear debate AND as the writer of the final NautilusTrader `Strategy`. Risk-team duties (position sizing, drawdown caps) are enforced via Nautilus `RiskEngine` rather than a separate agent — see `docs/state-of-the-art/Fast Trading on Binance with NautilusTrader: A S.md` §7.

## Composition pattern

Pipeline topology: four parallel analysts → adversarial researcher debate → trader synthesis. ONE `train(ctx)` invocation = ONE Claude session = ONE coordination-protocol pass = ONE `strategy.py` produced. Roles are CC agents dispatched by the primary Claude session via the Agent tool. Roles communicate ONLY through files in the team folder.

## Roster

| Role | One-line job | Dispatch model |
|---|---|---|
| `fundamental-analyst` | On-chain & macro signals; valuation context | sonnet |
| `sentiment-analyst` | Social/Reddit/X sentiment, Fear & Greed | haiku |
| `news-analyst` | Live news headlines (WebFetch), event flags | haiku |
| `technical-analyst` | Indicators on bars (RSI, MACD, ATR, vol regime) | sonnet |
| `bull-researcher` | Argues long thesis from analyst dossiers | opus |
| `bear-researcher` | Argues short/flat thesis | opus |
| `trader` | Judges debate, writes Strategy + risk knobs | opus |

## Coordination protocol (CC Agent dispatch)

Primary Claude orchestrates these dispatches per invocation:

1. **PARALLEL** (single Agent tool call with 4 entries):
   - `Agent(subagent_type="fundamental-analyst", model="sonnet")`
   - `Agent(subagent_type="sentiment-analyst",   model="haiku")`
   - `Agent(subagent_type="news-analyst",        model="haiku")`
   - `Agent(subagent_type="technical-analyst",   model="sonnet")`
   Each writes `attempts/<iter>/{role}.md`.

2. **SEQUENTIAL** (after the 4 above all return):
   `Agent(subagent_type="bull-researcher", model="opus")` reads `attempts/<iter>/{fundamental,sentiment,news,technical}.md`; writes `attempts/<iter>/bull.md`.

3. **SEQUENTIAL** after step 2:
   `Agent(subagent_type="bear-researcher", model="opus")` reads same 4 + `bull.md`; writes `bear.md`.

4. **SEQUENTIAL** after step 3:
   `Agent(subagent_type="trader", model="opus")` reads all 6 prior artifacts + `reflections.md` + `leaderboard_observations.md`; writes `attempts/<iter>/decision.md` and `attempts/<iter>/strategy.py`.

The primary Claude session produces ONE `attempts/<iter>/` per invocation. External retries are owned by the harness (`max_train_iterations=4`).

After Claude exits, harness calls `train(ctx)` which imports `attempts/<iter>/strategy.py`.

## Creativity directive

- Pivoting is encouraged. `train(ctx)` may return a totally different Strategy class each iteration.
- Strategies may be ensembles, regime-switching, or include an agentic on_bar (LLM call at runtime — note: the team's Claude session has exited by trade time, so an agentic on_bar requires an embedded Anthropic SDK client in the Strategy module).
- After 1–2 failed iterations, prefer pivoting to flogging the same approach.
- Keep `notes/`, `attempts/`, and `skills/` structured under the team folder.

## On-disk memory contract

| File | Persists? | Owner |
|---|---|---|
| `CLAUDE.md`, `entry.py`, `.claude/agents/*.md` | yes | scaffolder |
| `_inbox/context.md` | per-iteration (overwritten) | `entry.py` |
| `incoming/round_NN_leaderboard.md` | per-round | harness |
| `attempts/<iter>/*.md`, `attempts/<iter>/strategy.py` | yes (forensic record) | each role |
| `notes/*.md` | yes | any role appends durable observations |
| `skills/*.md` | yes | trader records reusable winning templates |
| `reflections.md` | yes (FinCon verbal reinforcement) | trader, append-only |
| `leaderboard_observations.md` | yes | trader after each round |

## Tool & doc pointers

- NautilusTrader Strategy/Indicator/RiskEngine — `Fast Trading… §5C` and §7.
- `TauricResearch/TradingAgents` GitHub; arXiv 2412.20138.
- FinCon: arXiv 2407.06567.
- Speed tier rationale (tier 2C): `Fast Trading… §2C`.

## Hard rules

- **NautilusTrader API discipline**: never call `Strategy.buy(...)`. Use `self.submit_order(self.order_factory.market(instrument_id=..., order_side=..., quantity=...))`. Use `InstrumentId.from_str(...)` and `BarType.from_str(...)`.
- **No look-ahead.** Indicators updated `on_bar` from past bars only.
- **Walk-forward when subdividing windows** — analysts may NOT peek at eval window.
- **Risk gate**: trader wires `RiskEngineConfig(max_order_submit_rate=..., max_notional_per_order=...)` and a per-bar position cap (default 60% equity unless trader justifies more in `decision.md`).
- **Bar/instrument precision must come from the catalog** (skill: `nautilus-trader-catalog-instrument-precision`).
- **Logger singleton**: do not re-init logging if `entry.py` is re-entered (skill: `nautilus-trader-logger-singleton`).

## Scoring

GAIN FACTOR on $1000 base. Return-dominant. Trader should bias toward asymmetric long-only or long-flat in trending regimes; symmetric long/short only when sentiment + technical agree.

## Failure modes

- **Profit Mirage** (`AI Agents… §D`): hold out a contiguous tail slice for self-validation.
- **Debate decay past 5 turns** (`AI Agents… §C.2`): hard-cap at 1 round.
- **Decision-cadence floor**: throttle to regime-significant bars (`Fast Trading… §6`).

## Budget knobs (global, set in `config.yaml`)

- `agent.per_train_timeout_seconds = 3600`
- `agent.max_train_iterations = 4` (harness-level retry; ONE strategy.py per Claude session)
