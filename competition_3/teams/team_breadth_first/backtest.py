"""Train-window backtest gate for team_breadth_first — harness-faithful.

Reuses the SAME engine + metric helpers the competition uses for its
eval/paper gates (`nautilus_competition._engine.build_backtest_engine` and
`._metrics.metrics_from_engine`), so a strategy that clears this gate is
measured exactly the way the harness will measure it.

Usage:
    uv run python backtest.py --strategy attempts/<iter>/strategy.py [--json-out PATH]

Prints one JSON line: {"gain": .., "win_rate": .., "num_trades": .., "pass": ..}

Gate (CLAUDE.md): pass == gain > 1.0 AND win_rate >= 0.5, on round-0 train.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# --- path wiring -------------------------------------------------------------
TEAM_DIR = Path(__file__).resolve().parent
COMPETITION_DIR = TEAM_DIR.parent.parent          # .../competition_3
WORKSPACE_ROOT = COMPETITION_DIR.parent           # .../nautilus-competition-run
for p in (str(WORKSPACE_ROOT),):
    if p not in sys.path:
        sys.path.insert(0, p)

from nautilus_competition._engine import build_backtest_engine  # noqa: E402
from nautilus_competition._metrics import metrics_from_engine    # noqa: E402
from nautilus_competition.config import load_competition_config  # noqa: E402

CONFIG_PATH = COMPETITION_DIR / "config.yaml"


def _resolve_round_index() -> int:
    """Resolve the harness round index from _inbox/context.md.

    The harness advances the round each session; gating on a hardcoded round 0
    would validate against the wrong train window. Falls back to 0 if the
    context file is missing or unparseable.
    """
    ctx = TEAM_DIR / "_inbox" / "context.md"
    for raw in ctx.read_text().splitlines():
        line = raw.strip().lstrip("-").strip()
        if line.startswith("round_index:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(
        f"round_index not found in {ctx} — refusing to silently gate round 0"
    )


ROUND_INDEX = _resolve_round_index()  # resolved from _inbox/context.md each round


def _load_strategy_module(strategy_path: Path):
    spec = importlib.util.spec_from_file_location("team_breadth_first_candidate", strategy_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def run(strategy_path: Path) -> dict:
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.identifiers import InstrumentId

    config = load_competition_config(CONFIG_PATH)
    window = config.windows[ROUND_INDEX].train
    print(
        f"[gate] round_index={ROUND_INDEX} train_window={window.start}..{window.end}",
        file=sys.stderr,
    )

    mod = _load_strategy_module(strategy_path)
    cfg = mod.TeamStrategyConfig(
        instrument_id=InstrumentId.from_str(config.instrument.symbol),
        bar_type=BarType.from_str(config.instrument.bar_type),
    )

    engine = build_backtest_engine(
        strategy_cls=mod.TeamStrategy,
        strategy_cfg=cfg,
        config=config,
        working_dir=COMPETITION_DIR,
        window=window,
    )
    engine.run()
    try:
        metrics = metrics_from_engine(
            engine,
            venue="BINANCE",
            currency="USDT",
            starting_balance=config.paper.starting_pot_usdt,
            strategy_id=None,
        )
    finally:
        engine.dispose()

    gain = 1.0 + metrics.total_return
    win_rate = metrics.win_rate
    num_trades = metrics.num_trades
    passed = bool(gain > 1.0 and win_rate >= 0.5)
    return {
        "gain": round(gain, 6),
        "win_rate": round(win_rate, 6),
        "num_trades": int(num_trades),
        "pass": passed,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", required=True, help="path to strategy.py")
    ap.add_argument("--json-out", default=None, help="optional path to also write the JSON result")
    args = ap.parse_args()

    strategy_path = Path(args.strategy)
    if not strategy_path.is_absolute():
        strategy_path = (TEAM_DIR / strategy_path).resolve()

    result = run(strategy_path)
    line = json.dumps(result)
    print(line)
    if args.json_out:
        Path(args.json_out).write_text(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
