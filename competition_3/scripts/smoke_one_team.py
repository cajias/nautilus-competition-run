"""Run one team for one round with reduced budgets.

Bypasses the harness; constructs a minimal TrainContext, calls
team.entry.train(ctx). Use to validate the team-author contract
before burning the full ~60h run.

Does NOT run a paper window. Validates only that the team's Claude
session writes attempts/000/strategy.py + backtest_result.json
within budget.
"""
from __future__ import annotations
import argparse
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import msgspec.structs
from nautilus_competition.config import AgentSpec, load_competition_config


def load_team_module(team_dir: Path):
    spec = importlib.util.spec_from_file_location(
        f"smoke.{team_dir.name}", team_dir / "entry.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("team", help="e.g. team_balanced")
    ap.add_argument("--max-attempts", type=int, default=2,
                    help="override inner-loop cap (default 2 for smoke)")
    args = ap.parse_args(argv)
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    cfg = load_competition_config(config_path)
    # AgentSpec is a frozen msgspec Struct — use replace() to override.
    new_agent = msgspec.structs.replace(
        cfg.agent, max_train_iterations=args.max_attempts
    )
    cfg = msgspec.structs.replace(cfg, agent=new_agent)
    team_dir = Path(__file__).resolve().parent.parent / "teams" / args.team
    if not team_dir.exists():
        print(f"team dir not found: {team_dir}", file=sys.stderr)
        return 2
    mod = load_team_module(team_dir)
    ctx = SimpleNamespace(
        config=cfg,
        round_index=0,
        iteration=0,
        prev_gain=None,
        prev_round_leaderboard=None,
        workspace_dir=Path(__file__).resolve().parent.parent,
        get_train_data=lambda: [],
        get_test_data=lambda: [],
    )
    strategy_cls, strategy_cfg = mod.train(ctx)
    print(f"[smoke] {args.team} produced: {strategy_cls.__name__}")
    print(f"[smoke] config: {strategy_cfg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
