"""Entry point — invokes Claude once per iteration, loads attempts/<iter>/strategy.py.

Inner refinement loop happens INSIDE the Claude session via the team's
role agents (researcher -> strategist -> backtester -> risk-officer);
this entry.py is the harness-facing edge.
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

from nautilus_competition.agent_runner import run_claude
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId

TEAM_DIR = Path(__file__).parent
TEAM_NAME = TEAM_DIR.name


def _format_context(ctx) -> str:
    return (
        f"# Round Context\n"
        f"- team_name: {TEAM_NAME}\n"
        f"- round_index: {ctx.round_index}\n"
        f"- iteration: {ctx.iteration}\n"
        f"- prev_gain: {ctx.prev_gain}\n"
        f"- prev_round_leaderboard: {ctx.prev_round_leaderboard}\n"
        f"- workspace_dir: {ctx.workspace_dir}\n"
        f"- anchor_instrument: {ctx.config.instrument.symbol}\n"
        f"- catalog_path: {ctx.config.catalog.path}\n"
    )


def train(ctx):
    iter_idx = ctx.iteration
    attempt_dir = TEAM_DIR / "attempts" / f"{iter_idx:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (TEAM_DIR / "_inbox").mkdir(exist_ok=True)
    (TEAM_DIR / "_inbox" / "context.md").write_text(_format_context(ctx))

    prompt = (
        f"You are the orchestrator for {TEAM_NAME} iteration {iter_idx}. "
        f"Read CLAUDE.md, then run the inner refinement loop documented "
        f"there. The loop runs the researcher -> strategist -> "
        f"backtester -> risk-officer pipeline, capped at "
        f"{ctx.config.agent.max_train_iterations} attempts. "
        f"When you land a passing attempt (gain_train > 1.0 AND "
        f"win_rate_train >= 0.5), write the final strategy.py to "
        f"attempts/{iter_idx:03d}/strategy.py and exit. If none of the "
        f"5 attempts passes, write attempts/{iter_idx:03d}/strategy.py "
        f"that holds cash (no orders) and exit with a diagnostics note."
    )

    result = run_claude(
        workspace_dir=TEAM_DIR,
        prompt=prompt,
        command=["claude", "--print", "--output-format", "json"],
        timeout_seconds=ctx.config.agent.per_train_timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Claude session failed (rc={result.returncode}). "
            f"stderr={result.stderr[:300]!r} stdout={result.stdout[:600]!r}"
        )

    strategy_path = attempt_dir / "strategy.py"
    if not strategy_path.exists():
        raise RuntimeError(
            f"Claude session finished without writing {strategy_path}. "
            f"stdout tail={result.stdout[-600:]!r}"
        )

    spec = importlib.util.spec_from_file_location(
        f"{TEAM_NAME}_strategy_{iter_idx:03d}", strategy_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # CRITICAL: dataclass introspection needs this
    spec.loader.exec_module(mod)

    instr = ctx.config.instrument
    cfg = mod.TeamStrategyConfig(
        instrument_id=InstrumentId.from_str(instr.symbol),
        bar_type=BarType.from_str(instr.bar_type),
    )
    return mod.TeamStrategy, cfg
