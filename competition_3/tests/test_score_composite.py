"""Tests for the composite-scoring wrapper."""
from __future__ import annotations
import json
from pathlib import Path
import pytest

from competition_3.scripts.score_composite import (
    compute_win_rate,
    apply_floor,
    composite_score,
    count_closed_trades,
    score_run,
)


def test_compute_win_rate_majority_winners(tmp_path: Path) -> None:
    log = tmp_path / "trades.jsonl"
    log.write_text(
        '{"event":"PositionClosed","realized_pnl":5.0}\n'
        '{"event":"PositionClosed","realized_pnl":-1.0}\n'
        '{"event":"PositionClosed","realized_pnl":3.0}\n'
        '{"event":"OrderFilled","realized_pnl":0}\n'
    )
    assert compute_win_rate(log) == pytest.approx(2 / 3)


def test_compute_win_rate_empty_log(tmp_path: Path) -> None:
    log = tmp_path / "trades.jsonl"
    log.write_text("")
    assert compute_win_rate(log) == 0.0


def test_count_closed_trades(tmp_path: Path) -> None:
    log = tmp_path / "trades.jsonl"
    log.write_text(
        '{"event":"PositionClosed","realized_pnl":5.0}\n'
        '{"event":"PositionClosed","realized_pnl":-1.0}\n'
        '{"event":"OrderFilled","realized_pnl":0}\n'
    )
    assert count_closed_trades(log) == 2


def test_apply_floor_below_gain_threshold() -> None:
    assert apply_floor(gain=0.95, win_rate=0.80) == 0.0


def test_apply_floor_below_winrate_threshold() -> None:
    assert apply_floor(gain=1.50, win_rate=0.40) == 0.0


def test_apply_floor_passes() -> None:
    assert apply_floor(gain=1.20, win_rate=0.60) == pytest.approx(1.20 * 0.60)


def test_composite_score_combines_correctly() -> None:
    assert composite_score(gain=1.10, win_rate=0.55) == pytest.approx(0.605)


def test_score_run_end_to_end(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "test-run"
    (run_dir / "teams" / "team_a" / "round_0").mkdir(parents=True)
    (run_dir / "teams" / "team_a" / "round_0" / "paper_trades.jsonl").write_text(
        '{"event":"PositionClosed","realized_pnl":1.0}\n'
        '{"event":"PositionClosed","realized_pnl":1.0}\n'
        '{"event":"PositionClosed","realized_pnl":-0.5}\n'
    )
    (run_dir / "leaderboard.json").write_text(json.dumps({
        "rounds": [
            {"round": 0, "teams": [{"name": "team_a", "total_return": 0.15}]}
        ]
    }))
    out = score_run(run_dir)
    assert out["team_a"]["total_composite"] == pytest.approx(1.15 * (2 / 3))
    assert out["team_a"]["rounds"][0]["closed_trades"] == 3
