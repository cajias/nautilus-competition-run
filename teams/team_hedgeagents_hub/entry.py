"""Entry point for team_hedgeagents_hub.

VARIANT: returns the merged RouterStrategy from router_strategy.py at team root
(written by the hedging-coordinator's merge step), not from attempts/<iter>/.
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
    (TEAM_DIR / "_inbox").mkdir(exist_ok=True)
    (TEAM_DIR / "_inbox" / "context.md").write_text(_format_context(ctx))

    result = run_claude(
        workspace_dir=TEAM_DIR,
        prompt=(
            f"You are the team orchestrator for iteration {iter_idx}. "
            f"Read CLAUDE.md and follow the Coordination protocol exactly. "
            f"Dispatch role agents via the Agent tool. Produce "
            f"router_strategy.py at the team root via the hedging-coordinator's "
            f"merge step, with classes `RouterStrategy` and `RouterStrategyConfig`. "
            f"Exit when done."
        ),
        command=["claude", "--print", "--output-format", "json"],
        timeout_seconds=ctx.config.agent.per_train_timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude session failed: {result.stderr[:400]}")

    router_path = TEAM_DIR / "router_strategy.py"
    if not router_path.exists():
        raise RuntimeError(f"Coordinator did not produce {router_path}")

    spec = importlib.util.spec_from_file_location(
        f"router_strategy_{iter_idx:03d}", router_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = mod.RouterStrategyConfig(**ctx.default_cfg_kwargs())
    return mod.RouterStrategy, cfg
