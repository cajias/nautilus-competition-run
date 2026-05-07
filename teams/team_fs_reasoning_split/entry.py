"""Entry point for team_fs_reasoning_split.

VARIANT: loads attempts/<iter>/merged.py (not strategy.py). The merger writes
this file with classes TeamStrategy and TeamStrategyConfig.
"""

import importlib.util
from pathlib import Path

from nautilus_competition.agent_runner import run_claude

TEAM_DIR = Path(__file__).parent


def _format_context(ctx) -> str:
    return (
        f"# Round Context\n"
        f"- round_index: {ctx.round_index}\n"
        f"- iteration: {ctx.iteration}\n"
        f"- prev_gain: {ctx.prev_gain}\n"
        f"- prev_round_leaderboard: {ctx.prev_round_leaderboard}\n"
        f"- workspace_dir: {ctx.workspace_dir}\n"
        f"- instrument: {ctx.config.instrument.symbol}\n"
        f"- bar_type: {ctx.config.instrument.bar_type}\n"
    )


def train(ctx):
    iter_idx = ctx.iteration
    attempt_dir = TEAM_DIR / "attempts" / f"{iter_idx:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (TEAM_DIR / "_inbox").mkdir(exist_ok=True)
    (TEAM_DIR / "_inbox" / "context.md").write_text(_format_context(ctx))

    result = run_claude(
        workspace_dir=TEAM_DIR,
        prompt=(
            f"You are the team orchestrator for iteration {iter_idx}. "
            f"Read CLAUDE.md and follow the Coordination protocol exactly. "
            f"Dispatch role agents via the Agent tool. Produce "
            f"attempts/{iter_idx:03d}/merged.py via the merger's fan-in step "
            f"with classes `TeamStrategy` and `TeamStrategyConfig`. "
            f"Exit when done."
        ),
        command=["claude", "--print", "--output-format", "json"],
        timeout_seconds=ctx.config.agent.per_train_timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude session failed: {result.stderr[:400]}")

    strategy_path = attempt_dir / "merged.py"
    if not strategy_path.exists():
        raise RuntimeError(f"Merger did not produce {strategy_path}")

    spec = importlib.util.spec_from_file_location(
        f"fs_merged_{iter_idx:03d}", strategy_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = mod.TeamStrategyConfig(**ctx.default_cfg_kwargs())
    return mod.TeamStrategy, cfg
