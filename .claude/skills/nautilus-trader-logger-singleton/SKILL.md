---
name: nautilus-trader-logger-singleton
description: |
  Fix for nautilus_trader's global Rust logger panicking on second init within
  the same Python process. Use when: (1) you see "thread '<unnamed>' panicked
  at crates/common/src/ffi/logging.rs:146:14: Failed to initialize logging:
  attempted to set a logger after the logging system was already initialized",
  (2) a second `BacktestEngine` instantiation crashes mid-process even when
  the first one succeeded, (3) `Fatal Python error: Aborted` from a nautilus
  test after a prior test in the same pytest run already created an engine,
  (4) running `compete run` / any harness that creates multiple
  BacktestEngine instances per run aborts the second engine. Covers the
  bypass_logging fix, the pytest-process-isolation pattern, and why
  TradingNode → BacktestEngine sequences hit it too.
author: Claude Code
version: 1.0.0
date: 2026-05-07
---

# nautilus_trader logger singleton — multi-engine-per-process fix

## Problem

`nautilus_trader.common.component` initializes a **global, process-wide Rust
logger** the first time a `BacktestEngine` (or any logging-enabled component)
is constructed. The Rust `log` crate's `set_logger` is one-shot per process —
the second call **aborts** the process with a Rust panic that bubbles up as
`Fatal Python error: Aborted`.

This is invisible from the docstrings of `BacktestEngine` and
`BacktestEngineConfig`. You only hit it when you legitimately need to run
more than one engine in the same Python process — common in:

- Harnesses that run **eval + paper** phases sequentially (each builds its
  own `BacktestEngine`).
- pytest runs where two test files each create a `BacktestEngine`.
- A multi-team competition runner that loops over teams, building a fresh
  engine per team per phase.

## Trigger conditions (any of these)

Stack trace excerpts that confirm the diagnosis:

```
thread '<unnamed>' (...) panicked at crates/common/src/ffi/logging.rs:146:14:
Failed to initialize logging: attempted to set a logger after the logging
system was already initialized
```

```
Fatal Python error: Aborted
...
File ".../nautilus_trader/system/kernel.py", line 229, in __init__
File ".../nautilus_competition/paper_phase.py", line 104, in _build_simulated_engine
```

The panic always traces through `logging.rs:146` (or similar `set_logger`
site) and originates inside `kernel.py:__init__` or
`backtest/engine.cpython-*-darwin.so`'s `PyInit_engine`.

If a SUBPROCESS that calls `compete run` / your harness exits with
returncode `-6` (SIGABRT on macOS) and stderr contains the
`logging.rs:146` line, this is it.

## Solution

### Fix 1 — for code that creates multiple engines per process

Pass an explicit `BacktestEngineConfig` with `LoggingConfig(bypass_logging=True)`
to **every** `BacktestEngine` constructor:

```python
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig

engine = BacktestEngine(
    config=BacktestEngineConfig(
        logging=LoggingConfig(bypass_logging=True),
    ),
)
```

This is safe to apply uniformly — even the *first* engine works fine with
`bypass_logging=True`. Don't try to be clever with "init once then bypass" —
the global singleton state isn't observable, so a uniform bypass is the only
robust pattern.

### Fix 2 — for pytest

`bypass_logging=True` in your test fixtures fixes most cases, but if a test
*explicitly* needs logging, **isolate engine-using test files into separate
pytest invocations**:

```bash
# Each command runs in a fresh Python process
uv run pytest tests/test_eval_phase.py
uv run pytest tests/test_paper_phase.py
uv run pytest tests/ --ignore=tests/test_eval_phase.py --ignore=tests/test_paper_phase.py
```

Or use `pytest-forked`:

```bash
uv pip install pytest-forked
uv run pytest --forked tests/
```

## Verification

After applying the fix:

1. The panic disappears from the stack trace.
2. Multiple engines coexist in one process without aborting.
3. The harness's subprocess exits 0, not -6.

A fast smoke test:

```python
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig

cfg = BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True))
e1 = BacktestEngine(config=cfg)
e2 = BacktestEngine(config=cfg)   # would SIGABRT without bypass
e1.dispose()
e2.dispose()
print("ok")
```

If this prints `ok`, the fix is in place.

## Why this happens (background)

`nautilus_trader` is built on Rust — its component layer uses the
[`log`](https://docs.rs/log) crate, whose `log::set_logger` can only be
called **once per process**. The Python `BacktestEngine` constructor calls
into Rust to install a logger backend. The second call returns
`SetLoggerError`, which the Rust side treats as fatal and panics, which the
Python interpreter sees as `Aborted` (SIGABRT).

`bypass_logging=True` skips the `set_logger` call entirely, letting any
number of engines coexist. The only cost is no Rust-side log output from
that engine — usually fine because Python-side `logging` still works.

## Notes

- This is a **known constraint**, not a bug in the user's code. It's been
  the case across multiple `nautilus_trader` releases.
- `TradingNode` (live mode) has the same logger and the same constraint —
  if you mix `TradingNode` and `BacktestEngine` in one process, both need
  bypass.
- The constraint is **per process**, not per thread. `subprocess.run` with
  a fresh Python invocation always starts clean.
- Running tests in pytest with `--forked` works because each test gets its
  own subprocess.
- Engine `.dispose()` does NOT reset the logger state — once initialized,
  the global is sticky for the life of the process.

## Example — orchestrator that runs eval then paper per team

```python
# nautilus_competition/eval_phase.py
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig

def run_eval(...):
    engine = BacktestEngine(
        config=BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)),
    )
    try:
        engine.add_venue(...)
        engine.add_instrument(...)
        engine.add_data(bars)
        engine.add_strategy(strategy_cls(strategy_cfg))
        engine.run()
        return _extract_result(engine)
    finally:
        engine.dispose()
```

`paper_phase.py` does the same. The orchestrator can call them in any order,
any number of times, without hitting the singleton panic.

## References

- nautilus_trader Rust panic site: `crates/common/src/ffi/logging.rs:146`
  (set_logger error path).
- Rust `log` crate docs: <https://docs.rs/log/latest/log/fn.set_logger.html>
  ("set_logger may only be called once during a program's execution").
- `LoggingConfig` API: `nautilus_trader.config.LoggingConfig` —
  `bypass_logging: bool = False` is the relevant field.
