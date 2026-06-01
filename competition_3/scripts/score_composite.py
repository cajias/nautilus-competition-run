"""Composite-scoring wrapper for competition_3.

Reads runs/<id>/leaderboard.json + per-team paper_trades.jsonl, computes
win_rate, applies floor (gain<=1.0 OR win_rate<0.5 -> 0), emits
leaderboard_composite.json, and pushes nautilus_competition_composite_score
to pushgateway.

Composite metric: gain_factor x win_rate.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Optional

import requests

FLOOR_GAIN = 1.0
FLOOR_WIN_RATE = 0.5


def compute_win_rate(trades_jsonl: Path) -> float:
    """Win rate over closed positions (realized_pnl > 0)."""
    if not trades_jsonl.exists():
        return 0.0
    wins = 0
    closed = 0
    for line in trades_jsonl.read_text().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if ev.get("event") != "PositionClosed":
            continue
        closed += 1
        if float(ev.get("realized_pnl", 0)) > 0:
            wins += 1
    return wins / closed if closed else 0.0


def composite_score(gain: float, win_rate: float) -> float:
    """Compute composite score as gain_factor multiplied by win_rate."""
    return gain * win_rate


def apply_floor(gain: float, win_rate: float) -> float:
    """Apply floor: returns 0.0 if gain <= FLOOR_GAIN or win_rate < FLOOR_WIN_RATE."""
    if gain <= FLOOR_GAIN or win_rate < FLOOR_WIN_RATE:
        return 0.0
    return composite_score(gain, win_rate)


def score_run(run_dir: Path) -> dict:
    """Score every team in every round of a harness run."""
    leaderboard = json.loads((run_dir / "leaderboard.json").read_text())
    out: dict[str, dict] = {}
    for round_entry in leaderboard.get("rounds", []):
        rnum = round_entry["round"]
        for t in round_entry.get("teams", []):
            name = t["name"]
            gain = 1.0 + float(t.get("total_return", 0))
            wr = compute_win_rate(
                run_dir / "teams" / name / f"round_{rnum}" / "paper_trades.jsonl"
            )
            score = apply_floor(gain, wr)
            slot = out.setdefault(name, {"rounds": [], "total_composite": 0.0})
            slot["rounds"].append({"round": rnum, "gain": gain, "win_rate": wr,
                                    "composite_score": score})
            slot["total_composite"] += score
    return out


def push_to_pushgateway(out: dict, run_id: str, url: str) -> None:
    """Push nautilus_competition_composite_score{team,round} for each round."""
    lines = []
    for team, payload in out.items():
        for r in payload["rounds"]:
            lines.append(
                f'nautilus_competition_composite_score{{team="{team}",round="{r["round"]}",run="{run_id}"}} '
                f'{r["composite_score"]}'
            )
    body = "\n".join(lines) + "\n"
    resp = requests.post(f"{url}/metrics/job/competition_3", data=body, timeout=15)
    resp.raise_for_status()


def main(argv: Optional[list] = None) -> int:
    """Entry point for the composite-scoring CLI."""
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path, help="runs/<run-id>/ directory")
    ap.add_argument("--push", action="store_true",
                    help="push composite score to pushgateway")
    ap.add_argument("--pushgateway-url", default="http://localhost:9091")
    args = ap.parse_args(argv)
    out = score_run(args.run_dir)
    (args.run_dir / "leaderboard_composite.json").write_text(
        json.dumps(out, indent=2, sort_keys=True))
    print(json.dumps(out, indent=2, sort_keys=True))
    if args.push:
        push_to_pushgateway(out, args.run_dir.name, args.pushgateway_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
