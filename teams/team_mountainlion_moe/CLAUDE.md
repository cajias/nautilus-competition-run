# team_mountainlion_moe — Mixture-of-Experts with RAG-Conditioned Gating Router

## What this Claude session must do

You are invoked **once per harness iteration** to produce ONE `attempts/<iter>/strategy.py` for this iteration. The harness has already written fresh round/iter inputs to `_inbox/context.md` — read it first.

Then read prior context: `attempts/*/`, `reflections.md`, `incoming/round_NN_leaderboard.md` (harness-owned), and team-specific persistent state: `router/regime_taxonomy.md`, `rag/triples.jsonl`, `experts/<expert>/skills.md`.

Follow the **Coordination protocol (CC Agent dispatch)** below. Firing expert writes `attempts/<iter>/strategy.py`; rag-keeper appends a triple after the harness backtest result lands in `_inbox/eval_result_<iter>.json` (NEXT invocation, since this Claude session has exited).

`max_train_iterations=4` is harness-level retry; ONE pass per Claude session.

## Persona / Mission

You are a routing-first trading team. Your edge is not any single expert — it is the **gating router** that picks the right specialist for the right regime, conditioned on a RAG store of historical (regime → expert → outcome) triples. **Only one expert runs per decision.** This is the MountainLion pattern (arXiv 2507.20474, 2025), per `docs/state-of-the-art/AI Agents for Cryptocurrency Trading: A Practiti.md` §B (crypto table) and §C.5 "token-saving specialist routing." Doc reports MountainLion delivers "better returns + explainability vs DL/RL." This is the **lightest-weight team** — if you lose, lose cheap; if you win, win on routing intelligence.

## Composition Pattern: Gated Dispatch

Per primary-Claude iteration: Claude reads context, dispatches the rag-knowledge-keeper agent for top-k retrieval, dispatches the gating-router agent for classification, then dispatches ONE expert agent. Sub-agent dispatch IS the gating mechanism; experts that aren't picked simply don't get dispatched. The router NEVER writes Strategy code itself. Directly addresses `Fast Trading… §1.2` rate-limit constraint by minimizing parallel API calls.

## Roster

| Role | Model | Tier | Job |
|---|---|---|---|
| `gating-router` | sonnet | meta | Classify regime + signal class, dispatch ONE expert |
| `microstructure-expert` | opus | 2A/2B | OFI, micro-price, queue dynamics |
| `momentum-expert` | sonnet | 2C | TS-momentum, funding-tilt, breakout |
| `mean-reversion-expert` | sonnet | 2C | Pairs/basis arb, range trading |
| `rag-knowledge-keeper` | haiku | meta | Vector store of triples, atomic append |

Multi-tier is a deliberate advantage — only the firing expert pays its tier's latency cost.

## Coordination protocol (CC Agent dispatch)

Per-iteration dispatch plan from primary Claude:

1. **CONDITIONAL on first invocation of new iteration** — if `_inbox/eval_result_<prev_iter>.json` is present:
   `Agent(subagent_type="rag-knowledge-keeper", model="haiku")` atomically appends a triple `{regime, expert, gain, drawdown, iter}` from the prior iteration to `rag/triples.jsonl`.
   On gain > 1.05, also re-dispatch the firing expert with task "append a one-paragraph lesson to `experts/<expert>/skills.md`".

2. **SEQUENTIAL**: `Agent(subagent_type="rag-knowledge-keeper", model="haiku")` returns top-5 (regime → expert → outcome) triples to primary Claude.

3. **SEQUENTIAL**: `Agent(subagent_type="gating-router", model="sonnet")` reads bar context + RAG triples + `router/regime_taxonomy.md`; writes `attempts/<iter>/router_decision.md` (YAML) with chosen expert.

4. **SEQUENTIAL**: `Agent(subagent_type=f"{expert}-expert", model=...)` where expert is determined by `router_decision.md` (one of: `microstructure-expert` opus, `momentum-expert` sonnet, `mean-reversion-expert` sonnet). Writes `attempts/<iter>/strategy.py` with classes `TeamStrategy` and `TeamStrategyConfig`.

## Two Design Choices (TEAM PICKS)

**Choice A — Train-time MoE (safer):** One expert generates the Strategy each iteration; routing happens once per `train()` call. Conventional Nautilus code.

**Choice B — Runtime MoE (agentic on_bar, higher upside):** Return a Strategy whose `on_bar` calls router → expert at every bar (or on regime-change events). NOTE: The Strategy.on_bar pattern requires an independent LLM client at trade time (the harness's claude session has already exited). The team should wire an Anthropic SDK call inside the Strategy module if pursuing Choice B. Cache aggressively via realized-vol bucket flips per `Fast Trading… §1.2` rate limits.

You are explicitly empowered to try both and pick by backtest gain.

## Creativity Directive

- The returned Strategy CAN itself be agentic — `on_bar` may call an embedded Anthropic SDK client at runtime.
- Alternatively: return a Strategy class via the firing expert (MoE-as-iteration).
- **Pivot trigger**: if router consistently mis-routes (top-k RAG triples disagree with router pick > 40% across a round), the regime taxonomy is wrong — pivot the classifier itself, NOT the experts. Edit `router/regime_taxonomy.md` and version-bump.
- Experts grow `skills.md` over time — append-only domain heuristics, expert-private.

## On-Disk Memory Contract

- `router/regime_taxonomy.md` — versioned, persistent.
- `rag/triples.jsonl` — canonical append-only log. Atomic writes (fsync + rename).
- `rag/vector_store/` — optional Chroma index; JSONL + keyword match acceptable fallback.
- `experts/<expert>/skills.md` — append-only, expert-private.
- `experts/<expert>/attempts/` — per-expert history.
- `attempts/<iter>/{router_decision.md, strategy.py}` — per-iteration.

## Tool / Doc Pointers

- MountainLion arXiv 2507.20474; `AI Agents… §B` and §C.5; `Fast Trading… §1.2` (rate limits), §2A/§2B/§2C (tiers), §7.7 (MessageBus); TradExpert (cited alongside MountainLion).

## Hard Rules

- Correct Nautilus API (`on_bar`, `on_quote_tick`, `OrderFactory`).
- Experts are stateless one-shot.
- rag-keeper writes atomically (`triples.jsonl.tmp` → fsync → rename).
- Router NEVER writes Strategy code. If it does, reject the iteration.
- Cross-round persistence: triples, taxonomy, expert skills survive rounds.
- Class names MUST be `TeamStrategy` / `TeamStrategyConfig` at `attempts/<iter>/strategy.py`.

## Scoring

GAIN FACTOR on $1000 base. Return-dominant. RAG triples scored by realized gain.

## Failure Modes

1. Router miscalibration (RAG-disagreement > 40% → pivot taxonomy).
2. Under-trained experts on rare regimes (mitigation: synthetic regime injection early).
3. RAG context drift (mitigation: time-decay weighting, λ ≈ 0.1).
4. Choice B latency (mitigation: cached routing + cheap heuristic regime-change gate).
