# competition_3 — autoresearch-knob ablation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up `competition_3/` — 6 teams differentiated only by their `/autoresearch:autoresearch` knob preset, each iterating in-loop until train-backtest passes (gain>1.0 AND win-rate≥0.5), gated by OOS, then paper-trading until 20 closed trades or 90 min ceiling — and rank teams by composite `gain_factor × win_rate`.

**Architecture:**
- Wrapper-not-fork: harness emits standard `total_return`; `scripts/score_composite.py` post-processes to apply the composite metric and Prometheus push.
- One Claude session per `train(ctx)` invocation, identical to c1/c2 pattern (`importlib + sys.modules[name]=mod` for dataclass identity).
- Six teams share the same role agents (researcher / strategist / backtester / risk-officer) and the same Sonnet base; only the researcher's `/autoresearch` invocation knobs differ. Differences live in `teams/<team>/.claude/agents/researcher.md` only.
- Inner refinement loop sits inside the team's `train()` — autoresearch → strategy.py → train-backtest → pass-or-loop, capped at 5 attempts or 3600 s.

**Tech Stack:** Python 3.12, `uv`, `nautilus-trader`, `nautilus_competition` framework (APM-installed), Claude Code CLI, ParquetDataCatalog, Prometheus + pushgateway + Grafana, Binance Spot Testnet via `BINANCE_TESTNET_API_KEY/SECRET`.

**Spec:** `docs/superpowers/specs/2026-06-01-competition-3-autoresearch-ablation-design.md`

**Prior state to reconcile:**
- `competition_3/` already has 5 PLACEHOLDER team folders under a different design (paradigm-named, win-rate-floor 0.55, 1 round, 15-min paper, 1800 s timeout). Task 1 deletes them.
- `competition_3/config.yaml` and `competition_3/CLAUDE.md` exist with the old design — Task 2 rewrites them.
- `competition_3/scripts/` is empty.
- `competition_3/data/catalog/` may or may not have data — Task 5 verifies and re-seeds if needed.
- Top-10 USDT pair list (BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, MATIC) was validated against testnet in the prior session — use that list instead of the spec's aspirational 20 (testnet liquidity won't support 20 in practice).

---

## Task 1: Reconcile prior scaffolding — wipe what doesn't fit

**Files:**
- Delete: `competition_3/teams/team_parallel_ensemble/`
- Delete: `competition_3/teams/team_regime_adaptive/`
- Delete: `competition_3/teams/team_researcher_critic/`
- Delete: `competition_3/teams/team_researcher_memory_risk/`
- Delete: `competition_3/teams/team_solo_researcher/`

- [ ] **Step 1: Confirm placeholder state**

Run: `find competition_3/teams -mindepth 2 -maxdepth 2 | sort`
Expected: each team folder contains only `PLACEHOLDER.md` (or close to it). If any team has substantive `entry.py`/`CLAUDE.md`/`.claude/`, STOP and reread the contents before deleting.

- [ ] **Step 2: Remove the 5 paradigm-named team folders**

Run:
```bash
rm -rf competition_3/teams/team_parallel_ensemble
rm -rf competition_3/teams/team_regime_adaptive
rm -rf competition_3/teams/team_researcher_critic
rm -rf competition_3/teams/team_researcher_memory_risk
rm -rf competition_3/teams/team_solo_researcher
```

- [ ] **Step 3: Confirm `competition_3/teams/` is empty**

Run: `ls competition_3/teams/`
Expected: empty output.

- [ ] **Step 4: Commit**

```bash
git add -A competition_3/teams/
git commit -m "refactor(competition_3): drop paradigm-named team placeholders ahead of autoresearch-knob redesign"
```

---

## Task 2: Rewrite `competition_3/config.yaml` for the new design

**Files:**
- Modify: `competition_3/config.yaml` (full overwrite)

- [ ] **Step 1: Read framework config schema**

Run: `find . -path ./node_modules -prune -o -name "config.py" -print | grep nautilus_competition | head -1 | xargs head -100`
Verify: `windows` is a list of `{train, test, paper}` triples; `paper.duration_minutes`, `agent.per_train_timeout_seconds`, `agent.max_train_iterations`, `scoring.weights {sharpe,total_return,max_drawdown}` keys are real. If schema differs, ADAPT step 2 inline (don't invent keys).

- [ ] **Step 2: Overwrite `competition_3/config.yaml`**

Replace ENTIRE file with:

```yaml
# competition_3 — autoresearch-knob ablation
# Each team uses /autoresearch:autoresearch with a different preset
# (breadth × depth × verification × loop). Composite gain × win-rate scoring
# applied as a post-processing wrapper (scripts/score_composite.py).
name: competition_3

# 5 rounds. Each round has its own train/test split. Paper window is live
# Binance testnet. Strategy self-terminates at 20 closed trades.
windows:
  - train: {start: "2026-04-01T00:00:00Z", end: "2026-04-22T00:00:00Z"}
    test:  {start: "2026-04-22T00:00:00Z", end: "2026-04-29T00:00:00Z"}
    paper: {start: "2026-04-29T00:00:00Z", end: "2026-04-30T00:00:00Z"}
  - train: {start: "2026-04-08T00:00:00Z", end: "2026-04-29T00:00:00Z"}
    test:  {start: "2026-04-29T00:00:00Z", end: "2026-05-06T00:00:00Z"}
    paper: {start: "2026-05-06T00:00:00Z", end: "2026-05-07T00:00:00Z"}
  - train: {start: "2026-04-15T00:00:00Z", end: "2026-05-06T00:00:00Z"}
    test:  {start: "2026-05-06T00:00:00Z", end: "2026-05-13T00:00:00Z"}
    paper: {start: "2026-05-13T00:00:00Z", end: "2026-05-14T00:00:00Z"}
  - train: {start: "2026-04-22T00:00:00Z", end: "2026-05-13T00:00:00Z"}
    test:  {start: "2026-05-13T00:00:00Z", end: "2026-05-20T00:00:00Z"}
    paper: {start: "2026-05-20T00:00:00Z", end: "2026-05-21T00:00:00Z"}
  - train: {start: "2026-04-29T00:00:00Z", end: "2026-05-20T00:00:00Z"}
    test:  {start: "2026-05-20T00:00:00Z", end: "2026-05-27T00:00:00Z"}
    paper: {start: "2026-05-27T00:00:00Z", end: "2026-05-28T00:00:00Z"}

paper:
  mode: live
  duration_minutes: 90        # hard ceiling; strategy self-stops at 20 closed trades
  starting_pot_usdt: 1000.0

# Engine bootstrap instrument. Teams subscribe to any subset of the 10
# pre-seeded catalog symbols at runtime via ParquetDataCatalog.
instrument:
  symbol: "BTCUSDT.BINANCE"
  bar_type: "BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL"

agent:
  command: ["claude", "--print", "--output-format", "json"]
  per_train_timeout_seconds: 3600
  max_train_iterations: 5

# Harness emits standard total_return. scripts/score_composite.py applies
# the composite gain × win-rate metric with floor (gain > 1.0 AND
# win_rate >= 0.5; below-floor strategies get composite_score = 0).
scoring:
  weights:
    sharpe: 0.0
    total_return: 1.0
    max_drawdown: 0.0

catalog:
  path: data/catalog
```

NOTE on dates: paper window dates are nominal — `paper.mode: live` means the harness opens a live testnet session and ignores window dates for trading (they're used for the eval-window backtest only, but we don't run eval here). Confirm this against framework code in step 1 — if eval window is required, add identical dates.

- [ ] **Step 3: Validate config parses**

Run: `uv run python -c "from nautilus_competition.config import load_competition_config; from pathlib import Path; cfg = load_competition_config(Path('competition_3/config.yaml')); print(cfg.name, len(cfg.windows), cfg.agent.per_train_timeout_seconds)"`
Expected: `competition_3 5 3600`

- [ ] **Step 4: Commit**

```bash
git add competition_3/config.yaml
git commit -m "feat(competition_3): config for 6-team x 5-round autoresearch ablation"
```

---

## Task 3: Verify `/autoresearch:autoresearch` arg shape

This task MUST come before any team researcher prompt is written. The spec acknowledges the exact CLI args are unknown — we pin them here.

**Files:**
- Read: `~/.claude/plugins/cache/**/autoresearch/**/SKILL.md` (or wherever the skill is installed)
- Create: `competition_3/docs/autoresearch_knob_mapping.md`

- [ ] **Step 1: Locate the autoresearch skill on disk**

Run: `find ~/.claude/plugins -name "SKILL.md" -path "*autoresearch*" 2>/dev/null | head -5`
Expected: one path, e.g. `~/.claude/plugins/cache/autoresearch/<ver>/skills/autoresearch/SKILL.md`. If multiple, pick the highest version.

- [ ] **Step 2: Read the skill and extract knob arguments**

Read the skill file. Extract:
- How is depth/recursion specified (flag name, default, range)?
- How is breadth/parallelism specified?
- How is the verifier panel sized?
- Is there a "loop-until-dry" / completeness-critic option?
- What is the standard invocation? (e.g., `/autoresearch:autoresearch <question> --depth 3 --branches 5 --verify 3`)

- [ ] **Step 3: Document the knob mapping**

Create `competition_3/docs/autoresearch_knob_mapping.md`:

```markdown
# /autoresearch knob mapping for the 6 teams

Skill version: <recorded from step 1>
Skill path: <recorded from step 1>

## Confirmed knobs (from skill source)

| Knob | Flag / arg | Range | Default |
|------|-----------|-------|---------|
| Breadth | `<actual>` | <actual> | <actual> |
| Depth | `<actual>` | <actual> | <actual> |
| Verification | `<actual>` | <actual> | <actual> |
| Loop discipline | `<actual>` | <actual> | <actual> |

## Preset invocations

team_breadth_first:  /autoresearch:autoresearch <Q> <args mapped to many-shallow-light-firstpass>
team_depth_first:    /autoresearch:autoresearch <Q> <args mapped to few-deep-medium-firstpass>
team_adversarial:    /autoresearch:autoresearch <Q> <args mapped to medium-medium-heavy5-firstpass>
team_speed_run:      /autoresearch:autoresearch <Q> <args mapped to low-shallow-minimal1-firstpass>
team_balanced:       /autoresearch:autoresearch <Q> <args mapped to medium-medium-medium3-firstpass>
team_completeness:   /autoresearch:autoresearch <Q> <args mapped to medium-medium-medium3-loopuntildry2>

If the actual skill does NOT expose one of these knobs as a flag, document
the closest behavioral substitute (e.g., emulate via prompt wording).
```

Fill all the `<actual>` and `<args>` placeholders from step 2 reading — no remaining angle brackets.

- [ ] **Step 4: Commit**

```bash
git add competition_3/docs/autoresearch_knob_mapping.md
git commit -m "docs(competition_3): pin /autoresearch knob mapping for 6 team presets"
```

---

## Task 4: Rewrite `competition_3/CLAUDE.md` for the new rules

**Files:**
- Modify: `competition_3/CLAUDE.md` (full overwrite)

- [ ] **Step 1: Overwrite the file**

Replace ENTIRE `competition_3/CLAUDE.md` with:

```markdown
# competition_3 — Competition-Level Rules

Inherited by every team session under `competition_3/teams/*`. Per-team
strategy details live in each team's own `CLAUDE.md`.

## The game

6 teams. Each team uses `/autoresearch:autoresearch` with a different
configuration preset (breadth × depth × verification × loop). All other
inputs are equal: same model (Sonnet), same catalog, same role agents.

Goal: produce a strategy that wins the **most paper trades** AND **makes
the most money**, summed as `composite_score = gain_factor × win_rate`
per round, summed across 5 rounds.

## Multi-asset universe

The catalog at `data/catalog/` contains 5-MIN bars for 10 USDT spot pairs:
BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, MATIC (all suffixed
`.BINANCE`). Trade any subset.

The harness `config.yaml` declares `BTCUSDT.BINANCE` as the engine-bootstrap
instrument. Teams may subscribe to additional pairs at runtime by loading
`ParquetDataCatalog(ctx.config.catalog.path)` inside their strategy.

## Round = "iterate until backtest passes, then paper trade"

Inside `train(ctx)`:
1. Researcher invokes `/autoresearch:autoresearch` with the team's preset.
2. Strategist writes `attempts/<iter>/strategy.py` from autoresearch findings.
3. Backtester runs train-window backtest on `ctx.get_train_data()`.
4. **Passing criteria**: `gain_train > 1.0 AND win_rate_train >= 0.5`.
   - Pass → return strategy. Fail → loop back to step 1 with diagnostics.
5. Inner loop cap: **5 attempts OR 3600 s**, whichever first. Exceeding either = forfeit.

After `train()` returns:
6. Harness backtests on `ctx.get_test_data()` (OOS gate, same threshold).
7. Paper trade on Binance testnet — `paper.duration_minutes = 90` ceiling;
   strategy `self.stop()` after 20 closed trades.

## Scoring

Per round: `composite_score = gain_factor × win_rate`, with floor:
- `gain_factor <= 1.0` OR `win_rate < 0.5` → `composite_score = 0`.

Final ranking: sum of per-round `composite_score` across all 5 rounds.

Implemented by `scripts/score_composite.py` post-harness. Harness scoring
key remains `total_return: 1.0` — wrapper applies the composite.

## Role agents (all 6 teams)

- `researcher.md` — drives `/autoresearch` with the team's preset; produces
  research findings used by the strategist.
- `strategist.md` — translates findings into `attempts/<iter>/strategy.py` +
  `runtime_rules.json`.
- `backtester.md` — runs train-window backtest, evaluates passing criteria,
  emits diagnostics on failure.
- `risk-officer.md` — enforces `runtime_rules.json` constraints (position
  size, stop loss, max drawdown).
```

- [ ] **Step 2: Commit**

```bash
git add competition_3/CLAUDE.md
git commit -m "docs(competition_3): rewrite CLAUDE.md for autoresearch-knob design"
```

---

## Task 5: Seed top-10 USDT pair catalog (if not already seeded)

**Files:**
- Create: `competition_3/scripts/seed_top10_catalog.py`
- Output: `competition_3/data/catalog/` ParquetDataCatalog

- [ ] **Step 1: Check if catalog is already populated**

Run: `find competition_3/data/catalog -name "*.parquet" 2>/dev/null | head -5 && du -sh competition_3/data/catalog/ 2>/dev/null`
- If output shows ≥ 10 instruments with bars covering 2026-04-01..2026-05-28 (i.e. ≥ 30 days), skip to step 5.
- Otherwise continue.

- [ ] **Step 2: Verify seeder pattern from competition_1**

Run: `cat competition_1/scripts/seed_real_catalog.py` (the reference implementation that handles Binance precision properly).
Note: how it constructs `Price.from_str(f"{float(o):.<precision>f}")` per instrument.

- [ ] **Step 3: Create `competition_3/scripts/seed_top10_catalog.py`**

Mirror the c1 pattern but loop over 10 symbols. Full content:

```python
"""Seed competition_3 data catalog with top-10 USDT spot pairs.

Fetches 5-MIN bars from Binance public REST (not testnet — public spot
endpoint has historical liquidity for these pairs) for the window
2026-03-25..2026-05-30 (30 days padded around the competition windows)
and writes them to `competition_3/data/catalog/` as ParquetDataCatalog.

Per-instrument precision is looked up from Binance exchangeInfo; Price
and Quantity are constructed via `Price.from_str(f"{v:.{p}f}")` to avoid
Decimal precision panics on parse.
"""
from __future__ import annotations
import sys, time
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal

import requests
from nautilus_trader.adapters.binance.spot.providers import BinanceSpotInstrumentProvider
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
           "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT"]
START = datetime(2026, 3, 25, tzinfo=timezone.utc)
END = datetime(2026, 5, 30, tzinfo=timezone.utc)
INTERVAL = "5m"
CATALOG = Path(__file__).resolve().parent.parent / "data" / "catalog"


def fetch_klines(sym: str, start_ms: int, end_ms: int) -> list[list]:
    """Page through Binance klines REST in 1000-row chunks."""
    out = []
    cur = start_ms
    while cur < end_ms:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": sym, "interval": INTERVAL, "startTime": cur,
                    "endTime": end_ms, "limit": 1000},
            timeout=30,
        )
        r.raise_for_status()
        chunk = r.json()
        if not chunk:
            break
        out.extend(chunk)
        cur = int(chunk[-1][6]) + 1   # next open time = last closeTime + 1ms
        time.sleep(0.2)   # polite to public endpoint
    return out


def precision_from_filter(info: dict, ftype: str) -> int:
    for f in info["filters"]:
        if f["filterType"] == ftype:
            step = f.get("tickSize" if ftype == "PRICE_FILTER" else "stepSize")
            return abs(Decimal(step).as_tuple().exponent)
    return 8


def main() -> int:
    CATALOG.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(CATALOG))
    info = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=30).json()
    info_by_sym = {s["symbol"]: s for s in info["symbols"]}
    spec = BarSpecification(5, BarAggregation.MINUTE, PriceType.LAST)
    venue = Venue("BINANCE")

    for sym in SYMBOLS:
        info_s = info_by_sym.get(sym)
        if info_s is None:
            print(f"[skip] {sym}: not on exchangeInfo")
            continue
        p_prec = precision_from_filter(info_s, "PRICE_FILTER")
        q_prec = precision_from_filter(info_s, "LOT_SIZE")
        iid = InstrumentId(Symbol(sym), venue)
        bar_type = BarType(iid, spec, AggregationSource.EXTERNAL)
        klines = fetch_klines(sym, int(START.timestamp() * 1000), int(END.timestamp() * 1000))
        if not klines:
            print(f"[skip] {sym}: no klines returned")
            continue
        bars = []
        for k in klines:
            t_ns = int(k[6]) * 1_000_000   # closeTime ms -> ns
            o, h, l, c, v = k[1], k[2], k[3], k[4], k[5]
            bars.append(Bar(
                bar_type=bar_type,
                open=Price.from_str(f"{float(o):.{p_prec}f}"),
                high=Price.from_str(f"{float(h):.{p_prec}f}"),
                low=Price.from_str(f"{float(l):.{p_prec}f}"),
                close=Price.from_str(f"{float(c):.{p_prec}f}"),
                volume=Quantity.from_str(f"{float(v):.{q_prec}f}"),
                ts_event=t_ns,
                ts_init=t_ns,
            ))
        catalog.write_data(bars)
        print(f"[ok]  {sym}: {len(bars)} bars  (p_prec={p_prec} q_prec={q_prec})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the seeder**

Run: `uv run python competition_3/scripts/seed_top10_catalog.py 2>&1 | tee /tmp/seed_out.log`
Expected (per symbol): `[ok]  <SYM>: ~5800 bars  (p_prec=N q_prec=M)` — 30 days × 24h × 12 bars/h ≈ 8640 bars max. If a symbol returns < 4000 bars, investigate testnet/public-API drift before continuing.
Estimated runtime: 5–15 min total.

- [ ] **Step 5: Verify catalog is queryable**

Run:
```bash
uv run python -c "
from pathlib import Path
from nautilus_trader.persistence.catalog import ParquetDataCatalog
cat = ParquetDataCatalog(str(Path('competition_3/data/catalog')))
ids = cat.instrument_ids() if hasattr(cat, 'instrument_ids') else cat.bar_types()
print(f'Items: {len(list(ids))}')
"
```
Expected: `Items: 10` (or 10 bar types, depending on framework version).

- [ ] **Step 6: Commit the seeder** (catalog data is gitignored)

```bash
git add competition_3/scripts/seed_top10_catalog.py
git commit -m "feat(competition_3): top-10 USDT catalog seeder (Binance public REST, precision-rounded)"
```

---

## Task 6: TDD the composite scorer wrapper

**Files:**
- Create: `competition_3/scripts/score_composite.py`
- Create: `competition_3/tests/test_score_composite.py`
- Create: `competition_3/tests/__init__.py` (empty)

- [ ] **Step 1: Write the failing tests**

Create `competition_3/tests/__init__.py` as an empty file.

Create `competition_3/tests/test_score_composite.py`:

```python
"""Tests for the composite-scoring wrapper."""
from __future__ import annotations
import json
from pathlib import Path
import pytest

from competition_3.scripts.score_composite import (
    compute_win_rate,
    apply_floor,
    composite_score,
    score_run,
)


def test_compute_win_rate_majority_winners(tmp_path: Path) -> None:
    log = tmp_path / "trades.jsonl"
    log.write_text(
        '{"event":"PositionClosed","realized_pnl":5.0}\n'
        '{"event":"PositionClosed","realized_pnl":-1.0}\n'
        '{"event":"PositionClosed","realized_pnl":3.0}\n'
        '{"event":"OrderFilled","realized_pnl":0}\n'   # ignored
    )
    assert compute_win_rate(log) == pytest.approx(2 / 3)


def test_compute_win_rate_empty_log(tmp_path: Path) -> None:
    log = tmp_path / "trades.jsonl"
    log.write_text("")
    assert compute_win_rate(log) == 0.0


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
```

- [ ] **Step 2: Run tests, verify they all fail**

Run: `cd competition_3 && uv run pytest tests/test_score_composite.py -v 2>&1 | tail -20`
Expected: `ModuleNotFoundError: No module named 'competition_3.scripts.score_composite'` — module doesn't exist yet.

- [ ] **Step 3: Write the minimal implementation**

Create `competition_3/scripts/score_composite.py`:

```python
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
import os
from pathlib import Path
from typing import Optional

import requests   # only used by the pushgateway path

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
    return gain * win_rate


def apply_floor(gain: float, win_rate: float) -> float:
    if gain <= FLOOR_GAIN or win_rate < FLOOR_WIN_RATE:
        return 0.0
    return composite_score(gain, win_rate)


def score_run(run_dir: Path) -> dict:
    """Score every team in every round of a harness run.

    Returns dict {team: {rounds: [...], total_composite: float}}.
    `total_return` in leaderboard.json is a percent (0.15 = +15%); we
    convert to gain_factor = 1 + total_return.
    """
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
```

- [ ] **Step 4: Set up package-style imports for the tests**

Create `competition_3/__init__.py` (empty) and `competition_3/scripts/__init__.py` (empty).

- [ ] **Step 5: Run tests, verify they pass**

Run: `cd competition_3 && uv run pytest tests/test_score_composite.py -v 2>&1 | tail -15`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add competition_3/__init__.py competition_3/scripts/__init__.py competition_3/scripts/score_composite.py competition_3/tests/__init__.py competition_3/tests/test_score_composite.py
git commit -m "feat(competition_3): composite scorer (gain x win-rate with floor) + tests"
```

---

## Task 7: Shared TeamStrategy base with 20-trade self-stop

**Files:**
- Create: `competition_3/shared/__init__.py` (empty)
- Create: `competition_3/shared/team_strategy_base.py`
- Create: `competition_3/tests/test_team_strategy_base.py`

- [ ] **Step 1: Write the failing test for the trade-counter logic**

Create `competition_3/tests/test_team_strategy_base.py`:

```python
"""Tests for the shared self-stop trade-counter helper."""
from __future__ import annotations
from competition_3.shared.team_strategy_base import TradeCloseCounter


def test_counter_starts_at_zero() -> None:
    assert TradeCloseCounter(target=20).count == 0
    assert not TradeCloseCounter(target=20).should_stop()


def test_counter_reaches_target() -> None:
    c = TradeCloseCounter(target=20)
    for _ in range(19):
        c.bump()
        assert not c.should_stop()
    c.bump()
    assert c.should_stop()


def test_counter_keeps_counting_past_target() -> None:
    c = TradeCloseCounter(target=3)
    for _ in range(5):
        c.bump()
    assert c.count == 5
    assert c.should_stop()
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd competition_3 && uv run pytest tests/test_team_strategy_base.py -v 2>&1 | tail -10`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the shared base**

Create `competition_3/shared/__init__.py` (empty).

Create `competition_3/shared/team_strategy_base.py`:

```python
"""Shared base + helpers for all competition_3 team strategies.

The interesting piece is `TradeCloseCounter` — a small testable helper
that lets `TeamStrategyBase.on_position_closed()` decide when to call
`self.stop()`. Kept as a separate class so we can unit-test the
self-stop logic without a BacktestEngine.
"""
from __future__ import annotations
from dataclasses import dataclass

from nautilus_trader.trading.strategy import Strategy


@dataclass
class TradeCloseCounter:
    """Counts closed positions and signals when to self-stop the paper run."""
    target: int = 20
    count: int = 0

    def bump(self) -> None:
        self.count += 1

    def should_stop(self) -> bool:
        return self.count >= self.target


class TeamStrategyBase(Strategy):
    """Common bits: 20-trade self-stop, multi-instrument-aware on_start hook.

    Concrete strategies override `on_start_subscribe()` to subscribe to
    whichever symbols their /autoresearch found promising, and
    `on_bar(bar)` to do whatever they do.
    """

    SELF_STOP_AFTER_TRADES = 20

    def on_start(self) -> None:
        self._closed_counter = TradeCloseCounter(self.SELF_STOP_AFTER_TRADES)
        self.on_start_subscribe()

    def on_start_subscribe(self) -> None:
        """Override to subscribe to the team's chosen instruments + bar types."""
        raise NotImplementedError

    def on_position_closed(self, event) -> None:
        self._closed_counter.bump()
        if self._closed_counter.should_stop():
            self.log.info(
                f"competition_3: reached {self._closed_counter.target} closed trades; "
                f"self-stopping paper window"
            )
            self.stop()
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd competition_3 && uv run pytest tests/test_team_strategy_base.py -v 2>&1 | tail -10`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add competition_3/shared/__init__.py competition_3/shared/team_strategy_base.py competition_3/tests/test_team_strategy_base.py
git commit -m "feat(competition_3): TeamStrategyBase with TradeCloseCounter self-stop helper"
```

---

## Task 8: Shared role-agent prompt templates

**Files:**
- Create: `competition_3/shared/agent_templates/researcher.md.tmpl`
- Create: `competition_3/shared/agent_templates/strategist.md`
- Create: `competition_3/shared/agent_templates/backtester.md`
- Create: `competition_3/shared/agent_templates/risk-officer.md`

These are TEMPLATES — Task 9 materializes per-team copies.

- [ ] **Step 1: Author `researcher.md.tmpl`**

Create `competition_3/shared/agent_templates/researcher.md.tmpl`:

```markdown
---
name: researcher
description: Drives /autoresearch:autoresearch with the {{TEAM_NAME}} preset and translates findings into a trading-strategy brief.
tools: Read, Write, Edit, Bash, Skill, Grep, Glob
model: sonnet
---

# Researcher — {{TEAM_NAME}}

## Your job

Run `/autoresearch:autoresearch` ONCE per iteration with the {{TEAM_NAME}}
knob preset, then crystallize the findings into a strategy brief at
`_inbox/research_brief.md`.

## Your autoresearch preset

{{AUTORESEARCH_INVOCATION}}

(The exact CLI args are pinned in `competition_3/docs/autoresearch_knob_mapping.md`.)

## The question you investigate

You investigate ONE question per iteration. Choose it from this priority list:

1. If `ctx.prev_gain` < 1.0 (last attempt failed): "Why did our last
   strategy (`attempts/<prev-iter>/strategy.py`) fail? What did
   `attempts/<prev-iter>/diagnostics.md` say? What is the smallest
   change that would fix it?"
2. If this is iteration 1: "Across the 10 catalog symbols
   (`data/catalog/`), which short-horizon pattern (5-MIN bars, hold
   minutes-to-hours) currently has the strongest backtest evidence
   AND can be implemented with `nautilus-trader` indicators?"
3. Otherwise: "What aspect of our last iteration's strategy could be
   refined to clear the passing gate?"

## Output

Write `_inbox/research_brief.md` with:
- The question you investigated
- The autoresearch invocation you ran (full CLI string)
- Top 3 findings (each: claim + evidence + confidence)
- A 1-paragraph strategy direction for the strategist

## Passing gate (for the strategist + backtester pipeline)

`gain_train > 1.0 AND win_rate_train >= 0.5` on `ctx.get_train_data()`.
If your last brief failed, your job is to find *why* and propose a fix.

## NEVER

- Skip /autoresearch and freelance from training data.
- Make up symbols not in the catalog.
- Write strategy.py yourself — that's the strategist's job.
```

- [ ] **Step 2: Author `strategist.md`**

Create `competition_3/shared/agent_templates/strategist.md`:

```markdown
---
name: strategist
description: Translates a research brief into a complete strategy.py + runtime_rules.json under attempts/<iter>/.
tools: Read, Write, Edit, Bash, Grep, Glob
model: sonnet
---

# Strategist

## Your job

Read `_inbox/research_brief.md`, then write a complete
`attempts/<iter>/strategy.py` + `attempts/<iter>/runtime_rules.json`.

## strategy.py contract

```python
from dataclasses import dataclass
from competition_3.shared.team_strategy_base import TeamStrategyBase
from nautilus_trader.trading.strategy import StrategyConfig
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import BarType


@dataclass
class TeamStrategyConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    # add your own fields below


class TeamStrategy(TeamStrategyBase):
    def on_start_subscribe(self) -> None:
        # subscribe to whichever instruments your strategy needs
        ...

    def on_bar(self, bar) -> None:
        # your logic
        ...
```

Must:
- Subclass `TeamStrategyBase` (inherits 20-trade self-stop).
- Override `on_start_subscribe()` to subscribe to instruments by id.
- Use `self.submit_order(...)` via `self.order_factory` to place orders.
- Quantities & prices: use `Price.from_str(f"{v:.{precision}f}")` and
  `Quantity.from_str(...)` for the relevant instrument precision —
  precision panics WILL kill the round.

## runtime_rules.json

JSON dict with:
- `max_position_usdt`: cap per symbol (default 500)
- `stop_loss_pct`: float (default 0.02)
- `take_profit_pct`: float (default 0.04)
- `max_open_positions`: int (default 3)

## NEVER

- Reach into `eval` or `paper` windows in `train()`.
- Import network libraries (requests, urllib).
- Use `Path('...').read_text()` on paths outside `competition_3/teams/<this team>/`.
```

- [ ] **Step 3: Author `backtester.md`**

Create `competition_3/shared/agent_templates/backtester.md`:

```markdown
---
name: backtester
description: Runs the strategist's strategy.py on ctx.get_train_data() and reports pass/fail vs the gate.
tools: Read, Write, Edit, Bash, Grep, Glob
model: sonnet
---

# Backtester

## Your job

Run the train-window backtest, evaluate the passing criteria, write a
diagnostics report.

## Procedure

1. Read `attempts/<iter>/strategy.py`.
2. Run a `nautilus_trader` `BacktestEngine` on the data from
   `ctx.get_train_data()`. Compute `gain_factor = final_equity /
   starting_equity` and `win_rate = wins / closed_positions`.
3. Pass criteria: `gain > 1.0 AND win_rate >= 0.5`.
4. Write `attempts/<iter>/backtest_result.json`:
   ```json
   {"gain": 1.07, "win_rate": 0.58, "closed_trades": 32, "pass": true}
   ```
5. Write `attempts/<iter>/diagnostics.md` covering:
   - Number of trades opened/closed
   - Win-rate breakdown by symbol
   - Largest single loss (drawdown contribution)
   - Hypotheses for why it passed/failed
   - One concrete change the researcher could investigate next iteration

## NEVER

- Modify strategy.py yourself.
- Touch `eval` or `paper` windows.
```

- [ ] **Step 4: Author `risk-officer.md`**

Create `competition_3/shared/agent_templates/risk-officer.md`:

```markdown
---
name: risk-officer
description: Audits runtime_rules.json against the strategy.py and rejects unsafe combinations.
tools: Read, Write, Edit, Grep, Glob
model: sonnet
---

# Risk officer

## Your job

Before backtest, audit:
- `attempts/<iter>/runtime_rules.json`
- `attempts/<iter>/strategy.py`

Reject (write FAIL to `attempts/<iter>/risk_audit.md`) if:
- `max_position_usdt * max_open_positions > 0.5 * starting_pot_usdt` (1000)
- `stop_loss_pct >= take_profit_pct`
- Strategy submits orders with no stop loss path
- Strategy uses leverage (this competition is spot only)

Otherwise write PASS with a 2-sentence summary.
```

- [ ] **Step 5: Commit the templates**

```bash
git add competition_3/shared/agent_templates/
git commit -m "feat(competition_3): role-agent templates for the 6-team roster"
```

---

## Task 9: Materialize 6 team folders

**Files:**
- Create: `competition_3/teams/team_breadth_first/`
- Create: `competition_3/teams/team_depth_first/`
- Create: `competition_3/teams/team_adversarial/`
- Create: `competition_3/teams/team_speed_run/`
- Create: `competition_3/teams/team_balanced/`
- Create: `competition_3/teams/team_completeness/`

Each team folder gets:
- `entry.py` — identical across teams (just the team name in the prompt)
- `CLAUDE.md` — team-specific intro + reference to /autoresearch preset
- `.claude/agents/researcher.md` — TEAM-SPECIFIC (filled from `researcher.md.tmpl`)
- `.claude/agents/strategist.md` — COPY of template
- `.claude/agents/backtester.md` — COPY of template
- `.claude/agents/risk-officer.md` — COPY of template

- [ ] **Step 1: Read the knob mapping**

Read `competition_3/docs/autoresearch_knob_mapping.md` from Task 3. Extract the 6 preset invocation strings.

- [ ] **Step 2: For each of the 6 teams, create the folder + entry.py**

For each `<team>` in `[team_breadth_first, team_depth_first, team_adversarial, team_speed_run, team_balanced, team_completeness]`:

Create `competition_3/teams/<team>/entry.py` (SAME content for all 6):

```python
"""Entry point — invokes Claude once per iteration, loads attempts/<iter>/strategy.py.

Inner refinement loop happens INSIDE the Claude session via the team's
role agents (researcher -> strategist -> backtester -> risk-officer);
this entry.py is the harness-facing edge.
"""
from __future__ import annotations
import importlib.util
import json
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
```

- [ ] **Step 3: Materialize per-team `.claude/agents/`**

For each `<team>` and its preset invocation `<INVOCATION>`:

```bash
mkdir -p competition_3/teams/<team>/.claude/agents
cp competition_3/shared/agent_templates/strategist.md competition_3/teams/<team>/.claude/agents/
cp competition_3/shared/agent_templates/backtester.md competition_3/teams/<team>/.claude/agents/
cp competition_3/shared/agent_templates/risk-officer.md competition_3/teams/<team>/.claude/agents/
# researcher: substitute TEAM_NAME and AUTORESEARCH_INVOCATION placeholders
sed -e "s|{{TEAM_NAME}}|<team>|g" \
    -e "s|{{AUTORESEARCH_INVOCATION}}|<INVOCATION>|g" \
    competition_3/shared/agent_templates/researcher.md.tmpl \
    > competition_3/teams/<team>/.claude/agents/researcher.md
```

Use the 6 invocations from `competition_3/docs/autoresearch_knob_mapping.md` (Task 3 output).

- [ ] **Step 4: Create per-team `CLAUDE.md`**

For each `<team>`, write `competition_3/teams/<team>/CLAUDE.md`:

```markdown
# Team: <team>

## Your /autoresearch preset

<one-sentence description from the spec § 4 table>

Full invocation lives in `.claude/agents/researcher.md`.

## Inner refinement loop (run inside this Claude session)

Cap: 5 attempts OR competition harness's `per_train_timeout_seconds` (3600 s).

For each attempt `<iter>`:

1. Dispatch the **researcher** agent. It runs /autoresearch and writes
   `_inbox/research_brief.md`.
2. Dispatch the **strategist** agent. It reads the brief, writes
   `attempts/<iter>/strategy.py` + `attempts/<iter>/runtime_rules.json`.
3. Dispatch the **risk-officer** agent. It audits both files.
   - FAIL → strategist revises, then risk-officer re-audits. If still
     FAIL after 2 risk passes, abandon this attempt and start the next.
4. Dispatch the **backtester** agent. It runs train-backtest, writes
   `attempts/<iter>/backtest_result.json` + `diagnostics.md`.
5. Read `backtest_result.json`:
   - If `pass: true` → COPY this iteration's `strategy.py` to
     `attempts/<round_iter>/strategy.py` where `<round_iter>` matches
     the harness iteration index, then EXIT the loop.
   - Else → loop to step 1 with the diagnostics in context for the
     researcher.

If 5 attempts pass without a passing strategy:
- Write a "hold cash, no orders" strategy.py to
  `attempts/<round_iter>/strategy.py`.
- Exit with a note that no passing strategy was found this round.

## Don't

- Don't run /autoresearch with a different knob preset than the one in
  researcher.md — that breaks the ablation.
- Don't write strategy.py outside `attempts/<iter>/` — the harness
  imports from a specific path.
- Don't touch test or paper windows.
```

Use the team-specific description from spec §4:
- team_breadth_first: "Wide net of ideas, take the best surface-level signal."
- team_depth_first: "One thesis, drilled deep, beats scattershot."
- team_adversarial: "Aggressive refutation produces robust strategies."
- team_speed_run: "Fast cheap iterations beat one careful pass."
- team_balanced: "Sensible defaults — the control / baseline."
- team_completeness: "Iterating 'what's missing?' finds the edge others miss."

- [ ] **Step 5: Smoke-test ONE team's structure (no run yet)**

Run:
```bash
ls competition_3/teams/team_balanced/.claude/agents/
test -f competition_3/teams/team_balanced/entry.py && echo OK_ENTRY
test -f competition_3/teams/team_balanced/CLAUDE.md && echo OK_CLAUDE_MD
grep -q "team_balanced" competition_3/teams/team_balanced/.claude/agents/researcher.md && echo OK_TEAM_NAME_SUB
```
Expected: 4 agent files listed + `OK_ENTRY`, `OK_CLAUDE_MD`, `OK_TEAM_NAME_SUB`.

- [ ] **Step 6: Verify framework discovers all 6 teams**

Run:
```bash
uv run python -c "
from pathlib import Path
from nautilus_competition.team_loader import discover_teams
teams = discover_teams(Path('competition_3/teams'))
print('Discovered:', sorted(t.name for t in teams))
"
```
Expected: `Discovered: ['team_adversarial', 'team_balanced', 'team_breadth_first', 'team_completeness', 'team_depth_first', 'team_speed_run']`

- [ ] **Step 7: Commit**

```bash
git add competition_3/teams/
git commit -m "feat(competition_3): 6 teams differentiated by /autoresearch knob preset"
```

---

## Task 10: Wire 3 new Prometheus metrics + Grafana panels

**Files:**
- Modify: `observability/prometheus/metrics.md` (or equivalent metric-name registry — pick the existing pattern from c1/c2)
- Modify: `observability/grafana/dashboards/competition.json` (existing dashboard)

- [ ] **Step 1: Locate existing observability assets**

Run: `find . -path ./node_modules -prune -o -name "*.json" -print | xargs grep -l "nautilus_competition" 2>/dev/null | head -5`
Result: probably under `observability/` or under one of the previous competitions. Adopt the matching directory pattern.

- [ ] **Step 2: Document the 3 new metrics**

Add to the metric registry document a section:

```markdown
## competition_3 metrics

| Metric | Labels | Source |
|--------|--------|--------|
| `nautilus_competition_inner_iterations` | `team`, `round` | emitted by each team's orchestrator at end of round |
| `nautilus_competition_paper_trades_closed` | `team`, `round` | emitted by `score_composite.py` at score time |
| `nautilus_competition_composite_score` | `team`, `round`, `run` | emitted by `score_composite.py --push` |
```

- [ ] **Step 3: Wire emission of `inner_iterations`**

In each team's `entry.py`, AFTER the Claude session, attempt to read
`attempts/<iter>/inner_iterations.txt` (written by the team orchestrator
when it exits its inner loop). If present, push to pushgateway:

```python
# after spec.loader.exec_module(mod), before return:
try:
    n = int((attempt_dir / "inner_iterations.txt").read_text().strip())
    import requests
    requests.post(
        "http://localhost:9091/metrics/job/competition_3",
        data=f'nautilus_competition_inner_iterations{{team="{TEAM_NAME}",round="{ctx.round_index}"}} {n}\n',
        timeout=5,
    )
except Exception:
    pass   # observability is best-effort; never block a return
```

In each team's `CLAUDE.md`, append a final step in the inner loop docs:
> When exiting the loop (pass OR forfeit), write the number of attempts
> taken to `attempts/<round_iter>/inner_iterations.txt`.

- [ ] **Step 4: Add Grafana panels**

In the competition dashboard JSON (located in step 1), add three panels:
- "Inner iterations to pass" — bar chart of `nautilus_competition_inner_iterations` by team
- "Paper trades closed" — bar chart of `nautilus_competition_paper_trades_closed` by team
- "Composite leaderboard" — table of `sum(nautilus_competition_composite_score) by (team)` sorted desc

(Pattern existing panels in the dashboard — datasource UID, panel layout grid.)

- [ ] **Step 5: Commit**

```bash
git add observability/ competition_3/teams/*/entry.py competition_3/teams/*/CLAUDE.md
git commit -m "feat(competition_3): wire 3 new metrics + Grafana panels for ablation visibility"
```

---

## Task 11: Smoke-test one team end-to-end

**Files:**
- Create: `competition_3/scripts/smoke_one_team.py`

This is the gate before the full ~60h launch.

- [ ] **Step 1: Author the smoke runner**

Create `competition_3/scripts/smoke_one_team.py`:

```python
"""Run one team for one round in a reduced config.

Bypasses the harness; constructs a minimal TrainContext, calls
team.entry.train(ctx), then runs a 5-min paper window on testnet.
Use to validate the team-author contract before burning the full run.
"""
from __future__ import annotations
import argparse
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from nautilus_competition.config import load_competition_config


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
                    help="override inner loop cap")
    ap.add_argument("--paper-minutes", type=int, default=5)
    args = ap.parse_args(argv)
    config_path = Path(__file__).resolve().parent.parent / "config.yaml"
    cfg = load_competition_config(config_path)
    # narrow the budget for smoke
    cfg.agent.max_train_iterations = args.max_attempts
    cfg.paper.duration_minutes = args.paper_minutes
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
        get_train_data=lambda: [],   # smoke: backtester will need real data; this is a hookup test
        get_test_data=lambda: [],
    )
    strategy_cls, strategy_cfg = mod.train(ctx)
    print(f"[smoke] {args.team} produced: {strategy_cls.__name__}")
    print(f"[smoke] config: {strategy_cfg}")
    print("[smoke] (paper window NOT executed by this script; verify by reading "
          "attempts/000/strategy.py and backtest_result.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the smoke against team_balanced**

Run: `uv run python competition_3/scripts/smoke_one_team.py team_balanced 2>&1 | tee /tmp/smoke.log`
Expected (success):
- The Claude session runs (≤ 30 min with max-attempts=2)
- `competition_3/teams/team_balanced/attempts/000/strategy.py` exists
- `competition_3/teams/team_balanced/attempts/000/backtest_result.json` exists with `pass: true`
- Final line: `[smoke] team_balanced produced: TeamStrategy`

If it fails:
- Empty stderr but rc != 0 → check stdout (the team's Claude session error is in JSON there). See skill `claude-print-subprocess-error-streams`.
- "ModuleNotFoundError nautilus_competition" → forgot `uv run`.
- "dataclass _is_type" panic → entry.py is missing `sys.modules[spec.name] = mod` before `exec_module`.
- "AttributeError 'TrainContext'" → mismatched ctx attribute names; reconcile against `nautilus_competition/types.py`.

Debug fully before continuing. **Do NOT proceed to Task 12 if smoke fails.**

- [ ] **Step 3: Commit the smoke runner**

```bash
git add competition_3/scripts/smoke_one_team.py
git commit -m "feat(competition_3): one-team smoke runner for pre-launch validation"
```

---

## Task 12: Finalize `competition_3/README.md`

**Files:**
- Modify: `competition_3/README.md`

- [ ] **Step 1: Overwrite the README**

Replace ENTIRE `competition_3/README.md` with:

```markdown
# competition_3 — autoresearch-knob ablation

Sister competitions: `../competition_1/` (SOTA + foundation-model teams),
`../competition_2/` (paradigm-named teams).

## What this competition tests

Each of 6 teams uses `/autoresearch:autoresearch` to drive trading-strategy
investigation, but with a different knob preset (breadth × depth ×
verification × loop discipline). Everything else is held constant —
same Sonnet model, same 10-symbol catalog, same role agents, same passing
gate. The winner has the strategy with the highest composite
`gain_factor × win_rate` summed across 5 rounds.

## Run it

```bash
# from workspace root
uv run compete run competition_3
```

After the run finishes (or while it's running, per-round):

```bash
uv run python competition_3/scripts/score_composite.py runs/<run-id>/ --push
```

This applies the composite metric, writes `leaderboard_composite.json`,
and pushes Prometheus metrics for the Grafana dashboard.

## The 6 teams

| Team | /autoresearch preset |
|------|---------------------|
| team_breadth_first | many shallow branches, light verify, single pass |
| team_depth_first | few deep branches, medium verify, single pass |
| team_adversarial | medium breadth/depth, 5-verifier panel, single pass |
| team_speed_run | low breadth, shallow, minimal verify, single pass |
| team_balanced | medium across all axes — control |
| team_completeness | medium breadth/depth, "what's missing?" until 2 dry rounds |

Exact CLI args: `competition_3/docs/autoresearch_knob_mapping.md`.

## Scoring

```
composite_score_round = gain_factor × win_rate
floor:                  gain ≤ 1.0 OR win_rate < 0.5 → 0
final_score = Σ composite_score_round  (over 5 rounds)
```

## Smoke before launch

```bash
uv run python competition_3/scripts/smoke_one_team.py team_balanced
```

Must succeed before committing the ~60h full run.
```

- [ ] **Step 2: Commit**

```bash
git add competition_3/README.md
git commit -m "docs(competition_3): README with run command, scoring, and pre-launch smoke"
```

---

## Task 13: Pre-launch checklist (manual gate)

**Files:** none — this is a human checklist for the operator.

- [ ] Verify Binance testnet creds: `[[ -n "$BINANCE_TESTNET_API_KEY" ]] && [[ -n "$BINANCE_TESTNET_API_SECRET" ]] && echo OK_CREDS`
- [ ] Verify Claude CLI reachable: `claude --version && echo OK_CLI`
- [ ] Verify APM lock matches: `apm install 2>&1 | grep -q "Installed" && echo OK_APM`
- [ ] Verify Prometheus + pushgateway + Grafana up: `curl -sf http://localhost:9091/-/healthy > /dev/null && curl -sf http://localhost:3000/api/health > /dev/null && echo OK_OBS`
- [ ] Verify catalog populated: `[[ $(find competition_3/data/catalog -name "*.parquet" | wc -l) -gt 10 ]] && echo OK_CATALOG`
- [ ] Verify Claude API quota: check the most recent rate-limit response from a recent `claude --print` call; quota must allow ≥ 60h of sustained calls.
- [ ] Verify smoke test passed (Task 11).
- [ ] **DO NOT proceed to full launch if any check fails.**

Launch command (NOT part of this plan — operator runs it after the gate):
```bash
uv run compete run competition_3 2>&1 | tee runs/competition_3_$(date +%Y%m%d_%H%M%S).log
```

---

## Self-Review notes

| Check | Result |
|---|---|
| Spec coverage | Goal (§1) → Task 4/12; Scoring (§2) → Task 6; Round lifecycle (§3) → Tasks 7+9 (entry.py inner loop); 6 teams (§4) → Task 9; Symbol universe (§5) → Task 5 (10 not 20 — see note in plan header); Harness customizations (§6) → Task 6 (wrapper) + Task 7 (self-stop); Directory layout (§7) → Tasks 1, 2, 9; Execution sequence (§8) → Tasks 11, 13; Risks (§9) → covered in Task 11 debug bullets; Success criteria (§11) → measured by leaderboard_composite.json after launch |
| Placeholder scan | No TBDs in the plan body itself. `<team>`, `<INVOCATION>`, `<actual>` in Task 3 are the planner output the engineer FILLS IN at execution time, not placeholders left for "later" |
| Type consistency | `TeamStrategyConfig` / `TeamStrategy` / `TeamStrategyBase` / `TradeCloseCounter` names match across Tasks 7, 8, 9 |
| Scope check | Single subsystem (one competition). Single plan. No decomposition needed. |

**One scope deviation from spec:** plan uses 10 symbols (testnet-validated from prior session) instead of spec's aspirational 20. Captured in the plan header; spec § 5 already permits "≥ 15 minimum if some pairs lack liquidity" — this is a minor downscope.
