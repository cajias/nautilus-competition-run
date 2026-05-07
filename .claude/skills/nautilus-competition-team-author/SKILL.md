---
name: nautilus-competition-team-author
description: |
  Per-team authoring contract for nautilus-competition. Use when:
  (1) creating or editing a team folder under
  `<working-dir>/teams/<team_name>/`; (2) writing or modifying a team's
  `entry.py` `def train(ctx) -> tuple[type[Strategy], StrategyConfig]`;
  (3) deciding how to use `ctx.prev_gain`, `ctx.get_train_data`, or
  `ctx.prev_round_leaderboard`; (4) calling `agent_runner.run_claude` to
  spawn a Claude subprocess from inside `train()`; (5) sizing the bar
  type vs `paper.duration_minutes` so indicators have time to warm up;
  (6) deciding which time windows a team is allowed to read (train +
  test, NEVER eval or paper).
author: Claude Code
version: 1.0.0
date: 2026-05-07
---

# Authoring a `nautilus-competition` team

A team is a folder under `<working-dir>/teams/<team_name>/` that exposes
**one function**, `train(ctx)`, returning the `Strategy` class + config the
harness should backtest on the eval window. Get this contract right and
the operator's `compete run` will pick the team up automatically.

## Folder shape

```
<working-dir>/teams/<team_name>/
├── CLAUDE.md     # required — agent persona / instructions (free-form)
├── entry.py      # required — exposes def train(ctx) -> (type[Strategy], StrategyConfig)
└── incoming/     # created by harness; round leaderboards land here
```

`CLAUDE.md` and `entry.py` are the only required files. Everything else
inside the team folder is free for the team to use as scratch / cache /
agent state. The harness imports the module under a unique name
(`team_<folder>`) via `importlib.util.spec_from_file_location`, so name
collisions between teams are not possible.

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

### `DataHandle` fields

```python
@dataclass(frozen=True, slots=True)
class DataHandle:
    catalog_path: Path     # absolute path to the ParquetDataCatalog
    instrument: str        # e.g. "BTCUSDT.BINANCE"
    bar_type: str          # e.g. "BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL"
    start: str             # ISO 8601
    end: str               # ISO 8601
```

A `DataHandle` is a pointer, not loaded data. Open the catalog yourself
inside `train()` if you need bars:

```python
from nautilus_trader.persistence.catalog import ParquetDataCatalog

handle = ctx.get_train_data()
catalog = ParquetDataCatalog(str(handle.catalog_path))
bars = catalog.bars(bar_types=[handle.bar_type], start=handle.start, end=handle.end)
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

A deterministic buy-and-hold (the canonical demo team that the
end-to-end test pins against, mirrored from
`examples/demo_competition/teams/team_demo/entry.py`):

```python
from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy


class DemoConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal = Decimal("0.001")


class DemoStrategy(Strategy):
    def __init__(self, config: DemoConfig) -> None:
        super().__init__(config)
        self.instrument = None
        self._bought = False

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.stop()
            return
        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if self._bought or self.instrument is None:
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self.instrument.make_qty(self.config.trade_size),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._bought = True


def train(ctx):
    instrument = ctx.config.instrument
    return DemoStrategy, DemoConfig(
        instrument_id=InstrumentId.from_str(instrument.symbol),
        bar_type=BarType.from_str(instrument.bar_type),
    )
```

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
