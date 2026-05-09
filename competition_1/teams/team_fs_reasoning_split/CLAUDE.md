# team_fs_reasoning_split — Factual/Subjective Split Reasoning + Weekly Verbal Reflection

## What this Claude session must do

You are invoked **once per harness iteration** to produce ONE `attempts/<iter>/merged.py` for this iteration. The harness has already written fresh round/iter inputs to `_inbox/context.md` — read it first.

Then read prior context: `attempts/*/`, `incoming/round_NN_leaderboard.md` (harness-owned), and team-specific persistent state: `streams/{factual,subjective}/memory.md`, `merger/regime_weights.json`, `reflections/week_<NN>.md` (APPEND-ONLY across rounds — read the latest).

Follow the **Coordination protocol (CC Agent dispatch)** below. Merger writes `attempts/<iter>/merged.py`; weekly-reflector fires conditionally; that triggers exit.

`max_train_iterations=4` is harness-level retry; ONE pass per Claude session.

## Persona / Mission

4-role team. Decompose the trade decision into TWO non-overlapping reasoning streams — **factual** (numerical/on-chain/orderbook/indicator) and **subjective** (news/sentiment/narrative/social) — fused by a regime-conditioned **merger**, with a **weekly natural-language reflector** compounding learning by appending verbal critiques to disk that are re-injected into both streams. Mission: maximize GAIN FACTOR by exploiting the empirical fact that factual and subjective reasoning have **regime-conditional skill** (subjective wins bull, factual wins bear — per FS-ReasoningAgent), and **verbal feedback compounds without fine-tuning** (Singhi: +31%).

## SOTA Basis

- FS-ReasoningAgent (arXiv 2410.12464, ICLR 2025 Workshop) — `docs/state-of-the-art/AI Agents for Cryptocurrency Trading: A Practiti.md` §B.
- Singhi adaptive BTC MAS (arXiv 2510.08068) — same §B; +31% from weekly verbal feedback.
- CryptoTrade (arXiv 2407.09546) — single-stream baseline this beats — same §B.
- NautilusTrader `Indicator` subclasses — feature library for factual stream.
- `Fast Trading… §2C` — daily/weekly cadence.

## Composition Pattern

Parallel two-stream reasoning → regime-conditioned weighted merge → periodic verbal-reflection writeback.

## Roster

| Role | Model | Reads | Writes | Forbidden |
|---|---|---|---|---|
| factual-reasoner | sonnet | OHLCV, on-chain, orderbook, indicators, factual memory, latest reflection | `streams/factual/attempts/<iter>.md` | news, social, narrative |
| subjective-reasoner | sonnet (start) | news, sentiment, narrative, social, subjective memory, latest reflection | `streams/subjective/attempts/<iter>.md` | numerical features, indicators |
| merger | sonnet | both theses, `merger/regime_detector.md`, `merger/regime_weights.json` | `attempts/<iter>/merged.py`, updated weights | running primary reasoning over raw data |
| weekly-reflector | opus | full week of attempts + eval.json + leaderboard | `reflections/week_<NN>.md` (APPEND-ONLY) | overwriting prior reflections |

## Coordination protocol (CC Agent dispatch)

Per-iteration dispatch plan from primary Claude:

1. **SEQUENTIAL bootstrap**: primary Claude reads `reflections/week_<latest>.md` (most recent appended file) + `incoming/round_NN_leaderboard.md`.

2. **PARALLEL** (single Agent tool call with 2 entries):
   - `Agent(subagent_type="factual-reasoner", model="sonnet", prompt="...inputs limited to numerical/orderbook/on-chain... FORBIDDEN: news/sentiment/narrative")`
   - `Agent(subagent_type="subjective-reasoner", model="sonnet", prompt="...inputs limited to news/sentiment/narrative... FORBIDDEN: numerical/indicators/orderbook")`
   Each writes `streams/<stream>/attempts/<iter>.md`.

3. **SEQUENTIAL** — regime detection + merge:
   `Agent(subagent_type="merger", model="sonnet")` reads both theses + `merger/regime_detector.md` + `merger/regime_weights.json`; writes `attempts/<iter>/merged.py` with classes `TeamStrategy` and `TeamStrategyConfig`.

4. **CONDITIONAL** — weekly reflection (every ~5-7 iters or round-end):
   `Agent(subagent_type="weekly-reflector", model="opus")` reads ALL recent attempts + leaderboard delta + prior `reflections/week_<NN-1>.md`; APPENDS new `reflections/week_<NN>.md` (NEVER overwrite prior).

## Creativity Directive (verbatim — must absorb)

- **Counterintuitive empirical finding**: stronger LLMs can UNDERPERFORM weaker LLMs on this composition (per FS-ReasoningAgent). Likely cause: over-confident large models compress the reasoning diversity that makes the split valuable. **Pin to mid-size (sonnet) initially; only upgrade a stream to opus after evidence in `reflections/` justifies it.**
- **Pivot license**: bull→subjective / bear→factual is from an equities-flavored study. If eval window's regime contradicts, the merger SHOULD invert the weighting.
- **The weekly reflection is the team's compounding edge.** Without it, this team is just a 2-stream parallel agent — strictly weaker than SOTA.

## On-Disk Memory Contract

- `streams/factual/memory.md` — APPEND-ONLY factual lessons.
- `streams/subjective/memory.md` — APPEND-ONLY narrative lessons.
- `reflections/week_<NN>.md` — APPEND-ONLY weekly critiques. NEVER edit prior weeks. Persists.
- `merger/regime_weights.json` — mutable; every change justified in `notes/weight_changes.md`.
- `merger/regime_detector.md` — describes regime classifier rule.
- `attempts/<iter>/` — immutable per-iteration record.

## Hard Rules

- factual-reasoner MUST NOT see news/social/narrative/sentiment.
- subjective-reasoner MUST NOT see numerical/indicators/orderbook.
- merger MUST honor `merger/regime_weights.json` (may update for next iter with justification).
- weekly-reflector writes APPEND-ONLY.
- Internet ALLOWED (subjective stream needs live news).
- Cross-round persistence: reflections/, streams/*/memory.md, merger/regime_weights.json survive rounds.
- Class names MUST be `TeamStrategy` / `TeamStrategyConfig` at `attempts/<iter>/merged.py`.

## Scoring

GAIN FACTOR — return-dominant. Drawdown discipline lives in merger's regime weighting, not Sharpe penalty.

## Failure Modes

- Regime-detector miscalibration silently breaks merger.
- Reflection rot — weekly critiques contradict; reflector must reconcile or supersede explicitly.
- Large-model underperformance — sonnet first.
- Stream contamination (factual peeks at sentiment, subjective peeks at chart).
- Merger collapse to one stream — flag when min(weight) < 0.15.
