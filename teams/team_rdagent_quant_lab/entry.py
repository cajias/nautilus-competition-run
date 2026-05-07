"""Entry point for team_rdagent_quant_lab.

VARIANT: reads _inbox/winning_hypothesis.json (written by primary Claude
before exit) to determine which code_<h>.py is the survivor.
"""

import importlib.util
import json
from pathlib import Path

from nautilus_competition.agent_runner import run_claude
from nautilus_trader.model.data import BarType
from nautilus_trader.model.identifiers import InstrumentId

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
            f"Run ONE R→D→F pass: bandit picks an arm, synthesis emits "
            f"k=8-16 hypotheses, several are implemented and internally "
            f"validated against Gates 1-3, feedback writes forest nodes, "
            f"bandit updates posteriors, then commit the best Gate-passing "
            f"candidate by writing _inbox/winning_hypothesis.json with "
            f'{{"round": {ctx.round_index}, "iter": {iter_idx}, '
            f'"hypothesis_id": "<id>", "code_path": "attempts/<r>_<it>/code_<h>.py"}}. '
            f"Class names in the survivor MUST be TeamStrategy and "
            f"TeamStrategyConfig. Exit when done."
        ),
        command=["claude", "--print", "--output-format", "json"],
        timeout_seconds=ctx.config.agent.per_train_timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Claude session failed: {result.stderr[:400]}")

    decision_path = TEAM_DIR / "_inbox" / "winning_hypothesis.json"
    if not decision_path.exists():
        raise RuntimeError("RD-Agent loop did not commit a winning hypothesis")

    decision = json.loads(decision_path.read_text())
    code_path = TEAM_DIR / decision["code_path"]
    if not code_path.exists():
        raise RuntimeError(f"Winning hypothesis points at missing {code_path}")

    spec = importlib.util.spec_from_file_location(
        f"rdagent_strategy_{iter_idx:03d}", code_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    instrument = ctx.config.instrument
    cfg = mod.TeamStrategyConfig(
        instrument_id=InstrumentId.from_str(instrument.symbol),
        bar_type=BarType.from_str(instrument.bar_type),
    )
    return mod.TeamStrategy, cfg
