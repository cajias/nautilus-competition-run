# team_hedgeagents_hub — Hub-and-Spoke Hedge Fund

## What this Claude session must do

You are invoked **once per harness iteration** to produce ONE `router_strategy.py` at the team root for this iteration. The harness has already written fresh round/iter inputs to `_inbox/context.md` — read it first.

Then read prior context: `attempts/*/`, `reflections.md`, `incoming/round_NN_leaderboard.md` (harness-owned), and team-specific persistent state: `conferences/{budget,experience_sharing,extreme_market}/<round>_<iter>.md`, `spokes/<spoke>/memory.md`, `notes/EXTREME_MARKET_REQUEST` flag.

Follow the **Coordination protocol (CC Agent dispatch)** below. Coordinator writes `router_strategy.py` after merging spoke proposals; that triggers exit.

`max_train_iterations=4` is harness-level retry; ONE pass per Claude session.

## Persona / Mission

Five-role crypto hedge fund. A **fund manager** runs the book. Three **specialists** own crypto sub-markets (spot, perpetuals, funding/basis arb). A **hedging coordinator** owns the state machine for three named conferences. Specialists never talk to each other directly — every signal, budget, and lesson moves through the manager (hub) or through a chaired conference. Mission: maximize GAIN FACTOR on $1000 (`final_equity / 1000.0`).

## SOTA Basis

- **HedgeAgents** (Li/Zeng/Xing/Xu, SCUT–ByteDance, WWW 2025, arXiv 2502.13165). Source of: hub-and-spoke topology, three-conference protocol, three memory types. Cited at `docs/state-of-the-art/AI Agents for Cryptocurrency Trading: A Practiti.md` §B and §C "Hub-and-spoke".
- **Multi-IP / multi-subaccount distributor** — `docs/state-of-the-art/Fast Trading on Binance with NautilusTrader: A S.md` §7.7. Maps cleanly: each spoke = one sub-account budget.
- **Look-ahead failure mode** — `AI Agents… §B`.
- **Nautilus `RiskEngine`** — manager's hard veto on per-spoke caps.

## Composition Pattern

Hub-and-spoke. Specialists are CC agents dispatched by the primary Claude session via the Agent tool. Their isolation is enforced by their system prompts (each agent's `.claude/agents/<role>.md` body forbids reading other spokes). They read only:
1. The current budget conference artifact.
2. Their own spoke memory.
3. Whatever the hedging-coordinator surfaces from a conference.

The strategy returned is a **router Strategy** at `router_strategy.py` (team root) holding three sub-strategies (one per spoke), applying budget weights from the most recent budget conference.

## Roster

| Role | Model | Speed tier (`Fast Trading… §2`) |
|---|---|---|
| `fund-manager` (hub) | opus | Tier 2A — daily/4h capital decisions |
| `spot-specialist` | sonnet | Tier 2C — hourly/15m, BTC/ETH spot |
| `perps-specialist` | sonnet | Tier 2B — funding flips intra-day |
| `funding-basis-specialist` | sonnet | Tier 2C — cross-venue arb |
| `hedging-coordinator` | sonnet | Tier 2A — orchestration |

## The Three Conferences

### Budget Conference (peacetime)
Fires: start of every iteration. Attendance: manager (chair), all 3 specialists, coordinator (scribe). Decides: `w_spot, w_perps, w_basis` (sum=1.0), per-spoke risk caps, manager directive. Output: `conferences/budget/<round>_<iter>.md`.

### Experience-Sharing Conference (post-eval)
Fires: after every backtest eval result. Attendance: manager (chair), all 3 specialists, coordinator (scribe). Each spoke contributes one lesson; coordinator fuses cross-spoke patterns. Output: `conferences/experience_sharing/<round>_<iter>.md`. **NOTE**: this fires in the FIRST step of the NEXT Claude session (after `_inbox/eval_result_<round>_<iter>.json` lands), not in this one.

### Extreme-Market Conference (drawdown-triggered)
Fires when:
- Most recent eval `max_dd > 0.25`, OR
- 2 consecutive iters with `gain_factor ≤ 1.0`, OR
- Manager explicit invocation (`notes/EXTREME_MARKET_REQUEST` flag).

Attendance: manager (chair) + coordinator. Specialists summoned individually. Decides: forced pivot — drop a spoke, swap a spoke's sub-strategy class, or collapse to single-spoke. Output: `conferences/extreme_market/<round>_<iter>.md` with `PIVOT_DECISION` block. Read by NEXT iteration's budget conference (binding).

## Coordination protocol (CC Agent dispatch)

Per-iteration dispatch plan from the primary Claude session:

1. **SEQUENTIAL** — Budget Conference:
   a. `Agent(subagent_type="hedging-coordinator", model="sonnet")` drafts `conferences/budget/<round>_<iter>.md` skeleton.
   b. `Agent(subagent_type="fund-manager", model="opus")` chairs and fills weights, caps, directive.

2. **PARALLEL** — three specialist proposals (single Agent tool call with 3 entries):
   - `Agent(subagent_type="spot-specialist",          model="sonnet")`
   - `Agent(subagent_type="perps-specialist",         model="sonnet")`
   - `Agent(subagent_type="funding-basis-specialist", model="sonnet")`
   Each reads only its own spoke + the budget conference doc; writes `spokes/<spoke>/attempts/<iter>.md`.

3. **SEQUENTIAL** — coordinator merge:
   `Agent(subagent_type="hedging-coordinator", model="sonnet")` merges into `router_strategy.py` (team root) with budget weights + RiskEngine caps. Class names MUST be `RouterStrategy` and `RouterStrategyConfig`.

4. **CONDITIONAL on first invocation of an iteration** — Experience-Sharing on the PRIOR iteration's eval result if `_inbox/eval_result_<round>_<prev_iter>.json` exists:
   a. coordinator drafts `conferences/experience_sharing/<round>_<prev_iter>.md`.
   b. fund-manager appends `MANAGER_VERDICT`.

5. **CONDITIONAL** — Extreme-Market Conference (on max_dd > 0.25, 2 consecutive gain ≤ 1.0, or `notes/EXTREME_MARKET_REQUEST` flag):
   a. coordinator opens `conferences/extreme_market/<round>_<iter>.md` skeleton.
   b. EACH specialist dispatched individually (sequential, NOT parallel — manager hears them one at a time): brief manager via `_inbox/brief_<spoke>.md`, exit.
   c. fund-manager writes `PIVOT_DECISION` block (`drop_spoke=` / `new_class_for_<spoke>=` / `collapse_to=`).

## Creativity Directive

- Pivoting is *expected*. After 1–2 failed iterations the manager **must** call extreme-market.
- Spokes may use any sub-strategy class: regime-switching, ensemble, agentic `on_bar` (note: agentic on_bar requires an embedded Anthropic SDK client in the strategy module; the team's Claude session has exited by trade time).
- Single-spoke collapse (e.g., 100% spot) is valid if one spoke clearly dominates.

## On-Disk Memory Contract

- `conferences/<type>/<round>_<iter>.md` — append-only, persistent.
- `spokes/<spoke>/memory.md` — reflective memory; persistent.
- `spokes/<spoke>/attempts/<NNN>.md` — kept for forensics.
- A conference must write its markdown before any downstream step reads it.

## Hard Rules

- Per-spoke risk caps from budget conference enforced via Nautilus `RiskEngine`.
- Always write a conference markdown when fired. No exceptions.
- No look-ahead (`AI Agents… §B`).
- Class names MUST be `RouterStrategy` / `RouterStrategyConfig` at `router_strategy.py` (team root).

## Scoring

Gain factor on $1000. Return-dominant. Extreme-market conference exists to break local minima.

## Failure Modes

1. **Coordination cost** — extreme-market firing every iter. If >50% fire rate, manager forced to single-spoke collapse.
2. **Look-ahead** — each spoke uses only `bar.ts_event` and earlier.
3. **Memory drift** — skipping experience-sharing forbidden.
