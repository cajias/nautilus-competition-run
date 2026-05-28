---
name: nautilus-competition-team-author
description: |
  Per-team authoring contract for nautilus-competition. A team is a
  MULTI-AGENT system (5-role baseline: researcher + hypothesis-generator +
  critic + risk-officer + memory-keeper, plus paradigm-specific
  specialists) that runs INSIDE `train(ctx)` to crystallize a strategy +
  `runtime_rules.json`. Use when: (1) creating or editing a team folder
  under `<working-dir>/teams/<team_name>/`; (2) designing the internal
  agent roster and orchestrating it in `train()`; (3) writing the
  researcher's `run_claude(...)` prompt or any paradigm-specific
  specialist stub; (4) writing or modifying a team's `entry.py`
  `def train(ctx) -> tuple[type[Strategy], StrategyConfig]`; (5) deciding
  how to use `ctx.prev_gain` for the anti-stuck paradigm-swap; (6) using
  `ctx.get_train_data` / `ctx.get_test_data` / `ctx.prev_round_leaderboard`;
  (7) designing the trade-time live Python critic that reads
  `runtime_rules.json` (no LLM at trade-time); (8) sizing the bar type vs
  `paper.duration_minutes` so indicators warm up; (9) respecting window
  discipline (train + test only, NEVER eval or paper).
author: Claude Code
version: 2.2.0
date: 2026-05-26
---

# Authoring a `nautilus-competition` team

A team is a folder under `<working-dir>/teams/<team_name>/` that exposes
**one function**, `train(ctx)`, returning the `Strategy` class + config the
harness should backtest on the eval window. Get this contract right and
the operator's `compete run` will pick the team up automatically.

## A team is a multi-agent system — not a single persona

> **The single most important thing to get right.** A team is NOT one
> trader-persona writing one strategy. It is a roster of collaborating
> subagents that debate, critique, and crystallize a strategy inside
> `train(ctx)` each iteration. This is the framework's built-in
> anti-stuck mechanism.

### 5-role baseline roster

Every team starts from the same five roles. Paradigm-specific
specialists (signal-engineers, env-designers, HRP-allocators,
microstructure spokes, etc.) are added on top.

| Role | Implementation | Responsibility |
|---|---|---|
| **researcher** | `run_claude(...)` subprocess | Pull SOTA from `docs/state-of-the-art/`, prior `notes/*.md`, other teams' artifacts, external refs. Writes `attempts/<iter>/research.md`. |
| **hypothesis-generator** | Deterministic Python (or a second `run_claude` call) | Propose a concrete `StrategyConfig` (params, indicators, sizing). |
| **critic** | Deterministic Python | Score the hypothesis against `ctx.get_train_data()` / `get_test_data()`; veto when red-flagged. |
| **risk-officer** | Deterministic Python | Derive `runtime_rules.json` (drawdown cap, size caps, regime halts) — these rules are enforced at trade-time. |
| **memory-keeper** | Deterministic Python | Read `ctx.prev_round_leaderboard`, append to `notes/*.md`, surface prior-round outcomes + regressions. |

The researcher MUST be implemented as a Claude subprocess (`run_claude`)
— the other roles can start as deterministic Python stubs and be upgraded
to subprocesses as the paradigm demands.

### Researcher subprocess pattern

`run_claude(...)` invokes `claude --print --output-format json`. The
subprocess writes a **Bedrock JSON envelope** to stdout — not the raw
assistant message. The envelope shape:

```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "result": "<assistant message body, JSON-escaped as a single string>",
  "usage": {"input_tokens": 0, "output_tokens": 0}
}
```

The team's domain payload (e.g., a `feature_shortlist`, a thesis JSON,
a hypothesis dict) is inside the `result` field — usually as a fenced
` ```json ` block within the assistant message. **Searching for the
fenced block on the raw stdout fails**: the body inside `result` is
JSON-escaped (`\"`, `\n`, `\\` literals), so the backticks `find`
finds the `\`\`\`json` substring inside the escaped string and
`json.loads` rejects the un-unescaped body. The bare-JSON fallback
then parses the *envelope* and silently returns it (no domain keys),
which makes the researcher look like it succeeded while the team
falls back to a stub hypothesis.

#### Canonical unwrap helper

Every team that calls `run_claude(...)` for a researcher must unwrap
the envelope **before** running any fenced-block extractor:

```python
import json

def _unwrap_bedrock_envelope(stdout: str) -> str:
    """Return the assistant message body, peeling off Bedrock's envelope.

    `claude --print --output-format json` writes:
        {"type":"result","subtype":"success","is_error":false,
         "result":"<assistant message as escaped string>", ...}
    Older builds and error paths may write the assistant message
    directly. This handles both: parse, look for `result`, fall through
    on anything that doesn't shape-check.
    """
    try:
        envelope = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return stdout
    if isinstance(envelope, dict) and "result" in envelope:
        return str(envelope["result"])
    return stdout


def parse_researcher_output(stdout: str) -> dict:
    body = _unwrap_bedrock_envelope(stdout)
    # Fenced-block extractor runs on the unwrapped body, never raw stdout.
    start = body.find("```json")
    if start != -1:
        end = body.find("```", start + len("```json"))
        if end != -1:
            return json.loads(body[start + len("```json"):end].strip())
    # Bare-JSON fallback. Defensive guard: reject envelope shapes that
    # leaked through (dict with `type`+`result` but no domain keys).
    parsed = json.loads(body)
    if isinstance(parsed, dict) and parsed.get("type") == "result" and "result" in parsed:
        msg = "researcher returned bare envelope; domain keys missing"
        raise ValueError(msg)
    return parsed
```

The defensive guard in the bare-JSON fallback prevents the silent
stub-hypothesis regression: if the envelope leaks through both
extractors, it raises instead of returning a useless dict.

`team_kronos_feature_engineer/entry.py` is the canonical reference
for this pattern. Long-term the helper should move into
`nautilus_competition.agent_runner`; until then, per-team copies are
acceptable so long as every team uses the same shape.

#### Timeout floor: 420 seconds

`config.agent.per_train_timeout_seconds` defaults to 600. Per-team
overrides via `run_claude(..., timeout_seconds=...)` should stay
**>= 420 seconds** for any per-iteration researcher call.

Empirical measurements with the Bedrock backend + MCP warm-up:

- MCP warm-up alone: ~30 seconds.
- Single-iteration research with multi-file reads: 180-300 seconds.
- Tail spikes (model contention, network jitter): up to ~400 seconds.

Setting `timeout_seconds=180` causes spurious `AgentTimeoutError`s on
~5 of every 6 invocations. Bumping to 420 cuts that to ~1 in 6.
Cheaper than retrying — set the floor at 420.

#### Researcher cannot rely on the Write tool

The spawned `claude --print` session has Write-tool permissions
denied. Prompts that ask the researcher to "write your answer to
`attempts/<iter>/research.md`" hit 3+ permission denials before the
session falls back to inline output — and that inline output is the
escaped envelope, which is the path that triggers the unwrap bug
above.

**Demand inline ` ```json ` output in the prompt**, not file writes.
Canonical phrasing:

```text
Return your answer as a single JSON object inside a ```json fenced
code block. Do NOT use the Write tool — output the JSON inline in
your final assistant message. The orchestrator will parse stdout and
persist research.md itself.
```

The team's Python wrapper (`_researcher`) is responsible for
persisting the parsed body to `attempts/<iter>/research.md` after the
subprocess returns. This removes the permissions dependency and keeps
the research.md write atomic with respect to validation success.

### Runtime pattern (hybrid train-time LLM, live-Python trade-time)

1. **Train-time** inside `train(ctx)`:
   1. memory-keeper reads `notes/` + `ctx.prev_round_leaderboard`.
   2. researcher (Claude subprocess) pulls SOTA, writes
      `attempts/<iter>/research.md`.
   3. hypothesis-generator proposes a concrete `StrategyConfig`.
   4. critic backtests on `ctx.get_test_data()`; vetoes or approves.
   5. risk-officer crystallizes veto rules into `runtime_rules.json`.
   6. `train()` returns `(StrategyClass, StrategyConfig)`.

2. **Trade-time** inside the `Strategy`:
   - On `on_start()`, load `runtime_rules.json`.
   - On every `on_bar()`, a live **Python** critic (no LLM, no
     subprocess) consults the rules before submitting an order.
   - This keeps the 3-bar paper-trade window latency-safe.

### Notes / memory layout

```
teams/<team_name>/
├── CLAUDE.md                    # roster design + thesis
├── entry.py                     # train(ctx) + Strategy class
├── runtime_rules.json           # risk-officer output, loaded at trade-time
├── notes/                       # PERSISTENT across rounds (append-only)
│   └── thesis.md                #   curated by memory-keeper
└── attempts/                    # EPHEMERAL per iteration
    └── <iter>/
        └── research.md          #   researcher's notes for this iteration
```

- `notes/` is persistent — append only, the memory-keeper owns curation.
- `attempts/<iter>/` is safe to delete between rounds.

### Anti-stuck mechanism

When `ctx.prev_gain is not None and ctx.prev_gain < 0`, the previous
iteration lost money on eval. The roster MUST swap paradigms, not
perturb parameters:

1. memory-keeper surfaces the prior-round failure to the roster.
2. researcher receives an "explore alternatives" prompt — pull a
   *different* SOTA direction than last iteration's.
3. hypothesis-generator is required to emit a materially different
   config (different indicator family, different bar type, different
   sizing rule).
4. critic raises its veto threshold.

The whole point of 5 agents is that they can disagree and swap
approaches when one paradigm stops working. A single-persona team
cannot do this.

### The seeded scaffold

`compete init-team` produces the full 5-role orchestration shell in
`entry.py` (functions `_memory_keeper`, `_researcher_prompt`,
`_researcher`, `_hypothesis_generator`, `_critic`, `_risk_officer`,
`_persist_runtime_rules`, and a `train()` that wires them in the right
order). The researcher's `run_claude` call is defensively wrapped so the
scaffold still runs in CI without a `claude` binary — but real teams
must flesh out the paradigm-specific prompt and specialists.

## Folder shape

```
<working-dir>/teams/<team_name>/
├── CLAUDE.md             # required — roster design + thesis
├── entry.py              # required — train(ctx) orchestrating the 5 roles
├── runtime_rules.json    # written by risk-officer, loaded at trade-time
├── notes/                # PERSISTENT across rounds (memory-keeper owns)
│   └── thesis.md
├── attempts/             # EPHEMERAL per iteration (researcher owns)
│   └── <iter>/research.md
└── incoming/             # created by harness; round leaderboards land here
```

`CLAUDE.md` and `entry.py` are the only files the harness strictly
requires; `runtime_rules.json`, `notes/`, and `attempts/` are
conventions the 5-role roster follows. The harness imports the module
under a unique name (`team_<folder>`) via
`importlib.util.spec_from_file_location`, so name collisions between
teams are not possible.

## The `train(ctx)` contract

```python
def train(ctx: TrainContext) -> tuple[type[Strategy], StrategyConfig]:
    ...
```

The harness calls `train()` once per iteration. If the returned strategy's
**eval-window gain** is `> 1.0`, the team's round advances to paper.
Otherwise the harness retries up to `config.agent.max_train_iterations`
times — each retry passes `ctx.prev_gain = (previous_gain_factor) - 1`.
After exhausting retries, a `FAILED` marker is written and the harness
moves on.

You return the **Strategy class and a StrategyConfig** — not an
instantiated strategy. The harness instantiates it inside the
`BacktestEngine` (and again, separately, for paper).

### `TrainContext` fields

```python
@dataclass(frozen=True, slots=True)
class TrainContext:
    round_index: int                              # 0-based
    iteration: int                                # 0-based; 0 on first call this round
    workspace_dir: Path                           # this team's folder
    get_train_data: Callable[[], DataHandle]      # round's train window
    get_test_data:  Callable[[], DataHandle]      # round's test window
    prev_gain: float | None                       # None on iter 0; previous gain factor minus 1 on retries
    prev_round_leaderboard: Path | None           # last round's leaderboard.md, or None on round 0
    config: CompetitionConfig                     # the loaded config.yaml
```

The eval and paper windows are deliberately **NOT** exposed. They are the
harness's gate and measurement, not the team's training data. Touching
those windows during `train()` would leak the gate.

### `prev_gain` semantics

- `iteration == 0`: `prev_gain is None`. First call this round.
- `iteration > 0`: `prev_gain = (last eval gain factor) - 1.0`.
  - `0.0` means break-even.
  - Negative means the last attempt lost money on the eval window.
  - Positive but `<= 0.0` (impossible) — sanity-check your retry logic.

Use `prev_gain` to decide whether to perturb a parameter, swap a
strategy, or re-run with the same config (rarely useful — backtests are
deterministic given identical inputs).

#### Retry guidance: when to swap vs. perturb

> **When `prev_gain < 0`: swap paradigm, do not perturb parameters.** A
> negative gain means the previous iteration lost money on the eval
> window. Tightening a stop-loss, nudging a window length, or shrinking
> position size within the SAME indicator family rarely turns a losing
> strategy profitable — it usually just reduces the magnitude of the
> loss. Instead, materially change the signal source: swap a momentum
> signal for a mean-reversion signal, replace a single-asset model with
> a regime-conditional one, or switch the entry rule's underlying
> feature class (price→volume, return→volatility, lookback→change-of-
> character).
>
> **When `prev_gain >= 0` but `< 0.05` (marginal positive):** the
> paradigm may be working but is too weak to clear the gate after costs.
> Tune within the family: experiment with feature scaling, longer/
> shorter lookback, position-size scaling on conviction. This is the
> *only* case where parameter perturbation is the right move.

This is the same anti-stuck rule the 5-role roster encodes (see
"Anti-stuck mechanism" above) — `prev_gain` is the trigger that the
memory-keeper hands to the researcher each iteration.

### Iteration budget and promotion

Each round gives your team `max_train_iterations` attempts (default 5;
check the active competition config). The harness calls your `train()`
once per iteration, evaluates the returned strategy on the eval window,
and gates on `gain_factor > 1.0` (final equity strictly greater than
starting equity — flat-equity strategies that never trade hit
`gain_factor = 1.0` exactly and do NOT advance).

As soon as one iteration crosses the threshold, your team advances to
paper and the round ends for you. If you exhaust the budget without
crossing the threshold, the harness writes a `FAILED.json` with
`cause: "max_iterations_exhausted"`, your paper directory stays empty,
and your composite score for the round is `0.0`.

A round that ends with `FAILED.json` is **not** the end of your team —
fresh budget arrives next round. But every iteration spent perturbing
parameters within a failing paradigm is an iteration that won't be
available for the paradigm that might work. Decide early: if iteration
1 returned `gain_factor < 0.95`, swap on iteration 2 — don't burn three
more iterations tuning a known loser.

### `DataHandle` fields

```python
@dataclass(frozen=True, slots=True)
class DataHandle:
    catalog_path: Path           # absolute path to the ParquetDataCatalog
    instrument: InstrumentSpec   # symbol + bar_type live on this
    start: str                   # ISO 8601
    end: str                     # ISO 8601
```

`InstrumentSpec` exposes `.symbol` (e.g. `"BTCUSDT.BINANCE"`) and
`.bar_type` (e.g. `"BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL"`). It is the
**same** object as `ctx.config.instrument` — the two are kept cohesive
on purpose so you never pass symbol and bar_type as separate strings.

A `DataHandle` is a pointer, not loaded data. Open the catalog yourself
inside `train()` if you need bars:

```python
from nautilus_trader.persistence.catalog import ParquetDataCatalog

handle = ctx.get_train_data()
catalog = ParquetDataCatalog(str(handle.catalog_path))
bars = catalog.bars(
    bar_types=[handle.instrument.bar_type],
    start=handle.start,
    end=handle.end,
)
```

## Train / test / eval discipline

The harness exposes **train** and **test** windows. The eval window is
held out for the gate, and paper is the (live or simulated) trading
window. **Do not peek at eval or paper.**

- Use **train** to fit / search / tune.
- Use **test** to do a single out-of-sample sanity check before returning.
- The harness runs the returned `(Strategy, StrategyConfig)` against
  **eval** automatically — the team doesn't run an eval backtest itself.

If a team's `train()` reads from any catalog window it wasn't handed via
`get_train_data` / `get_test_data`, that's a leak. Don't do it.

## Bar-type vs paper-duration constraint

Your strategy's slowest indicator needs at least `~2x its period` bars to
warm up before it produces a useful signal. The eval window is fixed by
the round config; you tune the **bar interval** to fit.

A safe rule of thumb:

```
paper_duration_minutes / bar_minutes >= 2 * slowest_indicator_period
```

Concrete example: paper window 4320 minutes (72h), bar = 5 minutes →
864 bars per paper run. A 200-period EMA needs ~400 bars to warm up; you
get ~464 bars of actual signal. A 500-period EMA would only have ~364
bars of signal — borderline. Pick the bar interval accordingly.

The same arithmetic applies to the eval window — undersized indicators
will look great in train and fail in eval.

## Spawning Claude from inside `train()` (optional)

The harness ships an `agent_runner.run_claude` helper. **It's optional.**
`train()` may use any approach: hand-coded grid search, an LLM call via
any SDK, deterministic logic, whatever produces a `(Strategy,
StrategyConfig)` pair.

```python
from nautilus_competition.agent_runner import (
    AgentResult,
    AgentTimeoutError,
    run_claude,
)

result: AgentResult = run_claude(
    workspace_dir,                                # cwd for the subprocess
    prompt,                                       # appended to command argv
    command=["claude", "--print", "--output-format", "json"],
    timeout_seconds=600,
    extra_env=None,                               # optional dict[str, str] merged on os.environ
)
# result.returncode, result.stdout, result.stderr, result.workdir
```

`AgentTimeoutError` raises on `subprocess.TimeoutExpired`. The default
timeout is shadowed by `config.agent.per_train_timeout_seconds` in the
operator's `config.yaml`.

A typical pattern: drop a `prompt.md` into `workspace_dir`, call
`run_claude(...)`, parse the JSON response, write a derived `entry.py` —
**but that's only useful if your team imports its own freshly written
helper modules.** The harness only ever calls `train()`, so the
subprocess's effects must land somewhere `train()` reads.

## Minimal `entry.py`

The canonical shape a team `entry.py` must satisfy. `compete init-team`
seeds exactly this orchestration shape — fill in the paradigm-specific
specialists and researcher prompt as TODO-marked:

```python
from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

from nautilus_competition.agent_runner import AgentError, run_claude


if TYPE_CHECKING:
    from nautilus_competition.context import TrainContext


class TeamConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal = Decimal("0.001")


class TeamStrategy(Strategy):
    """Loads runtime_rules.json at on_start(); live Python critic in on_bar()."""
    # ...see the seeded scaffold for the full lifecycle hooks.


def _memory_keeper(ctx): ...          # read notes/ + prev_round_leaderboard
def _researcher_prompt(ctx, mem): ... # paradigm-specific prompt (stuck->swap)
def _researcher(ctx, mem):             # spawn run_claude(...) defensively
    try:
        result = run_claude(
            ctx.workspace_dir,
            _researcher_prompt(ctx, mem),
            command=ctx.config.agent.command,
            timeout_seconds=ctx.config.agent.per_train_timeout_seconds,
        )
        # persist result.stdout to attempts/<iter>/research.md
    except (AgentError, FileNotFoundError, OSError):
        # fall back so the scaffold runs even without claude on PATH
        ...

def _hypothesis_generator(ctx, mem, research): ...  # propose StrategyConfig
def _critic(ctx, hypothesis): ...                   # veto / approve
def _risk_officer(ctx, hypothesis, critique):       # write runtime_rules.json
    rules = {...}
    (ctx.workspace_dir / "runtime_rules.json").write_text(json.dumps(rules))
    return rules


def train(ctx: "TrainContext") -> tuple[type[TeamStrategy], TeamConfig]:
    memory = _memory_keeper(ctx)
    research = _researcher(ctx, memory)
    hypothesis = _hypothesis_generator(ctx, memory, research)
    critique = _critic(ctx, hypothesis)
    _rules = _risk_officer(ctx, hypothesis, critique)

    instrument = ctx.config.instrument
    return TeamStrategy, TeamConfig(
        instrument_id=InstrumentId.from_str(instrument.symbol),
        bar_type=BarType.from_str(instrument.bar_type),
        trade_size=Decimal(str(hypothesis.get("trade_size", "0.001"))),
    )
```

The demo reference team at
`examples/demo_competition/teams/team_demo/entry.py` is a deterministic
buy-and-hold — use it as a nautilus_trader API reference, but NOT as
the shape of a new team. Every new team must carry the 5-role roster.

## Gotchas

- `StrategyConfig` rejects bare `str` for `instrument_id` / `bar_type` —
  they must be `InstrumentId` / `BarType`. Use `.from_str(...)`.
- Order entry is `submit_order(order_factory.market(...))`. There is no
  `Strategy.buy` in the installed `nautilus_trader`.
- Don't mix instruments from `TestInstrumentProvider` with bars from a
  catalog — see the `nautilus-trader-catalog-instrument-precision` skill.
  The harness already loads instruments from the catalog; your strategy
  should fetch via `self.cache.instrument(...)`, never construct its own.
- Reading `ctx.prev_round_leaderboard` is the supported way to see what
  the field did last round. The path may be `None` on round 0; guard.

## References

- `docs/team-contract.md` — the canonical contract this skill summarizes.
- `examples/demo_competition/teams/team_demo/entry.py` — the e2e test pin.
- `nautilus-competition-operator` skill — what the operator side of this
  contract looks like (when does `train()` get called, where do its
  outputs land).
- `nautilus-trader-logger-singleton`,
  `nautilus-trader-catalog-instrument-precision` — load-bearing
  framework gotchas; both can bite a team's strategy on the eval engine.
