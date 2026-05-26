"""Entry point for ``team_hedgeagents_hrp``.

Hub-and-spoke hedge fund (HedgeAgents, arXiv 2502.13165) REFRESHED with
a Hierarchical Risk Parity allocator (Lopez de Prado 2016) over three
deterministic signal spokes: trend, mean-reversion, vol-carry.

Roster (9 roles, only 2 are LLM calls per ``train()``):
  1. researcher        — ``run_claude`` subprocess #1 (~180s)
  2. hub-manager       — ``run_claude`` subprocess #2 (~180s), runs the
                         three conferences (budget / experience-sharing /
                         extreme-market)
  3. critic            — deterministic Python
  4. risk-officer      — deterministic Python
  5. memory-keeper     — deterministic Python
  6. trend-spoke       — deterministic Python
  7. mean-rev-spoke    — deterministic Python
  8. vol-carry-spoke   — deterministic Python
  9. hrp-allocator     — deterministic Python (scipy.cluster.hierarchy)

At trade time, ``TeamStrategy.on_bar`` is pure Python — NO LLM calls.
It loads ``runtime_rules.json`` in ``on_start`` and computes the three
spoke signals on a rolling deque each bar.
"""

from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nautilus_competition.agent_runner import (  # type: ignore[import-untyped]
    ResearcherResult,
    run_researcher,
)
from nautilus_trader.config import StrategyConfig  # type: ignore[import-untyped]
from nautilus_trader.model.data import Bar, BarType  # type: ignore[import-untyped]
from nautilus_trader.model.enums import (  # type: ignore[import-untyped]
    OrderSide,
    TimeInForce,
)
from nautilus_trader.model.identifiers import InstrumentId  # type: ignore[import-untyped]
from nautilus_trader.persistence.catalog import (  # type: ignore[import-untyped]
    ParquetDataCatalog,
)
from nautilus_trader.trading.strategy import Strategy  # type: ignore[import-untyped]


if TYPE_CHECKING:
    from nautilus_trader.model.instruments import (  # type: ignore[import-untyped]
        Instrument,
    )


TEAM_DIR = Path(__file__).parent
RUNTIME_RULES_PATH = TEAM_DIR / "runtime_rules.json"

# Deterministic defaults used if either LLM call fails or returns a
# malformed payload. These are the values the ``risk-officer`` falls
# back to. See CLAUDE.md > "Fallback: hub-manager timeout".
DEFAULT_HRP_LOOKBACK_BARS = 500
DEFAULT_DISAGREE_THRESHOLD = 0.15
DEFAULT_MAX_WEIGHT_PER_SPOKE = 0.6
DEFAULT_DRAWDOWN_CAP = 0.25
DEFAULT_TREND_PERIOD = 50
DEFAULT_MR_PERIOD = 20
DEFAULT_VOL_PERIOD = 20

# Critic floors / ceilings.
DISAGREE_THRESHOLD_FLOOR = 0.05
DISAGREE_THRESHOLD_CEIL = 0.50
MAX_WEIGHT_FLOOR = 0.34
MAX_WEIGHT_CEIL = 1.0
LOOKBACK_FLOOR = 100
LOOKBACK_CEIL_ABSOLUTE = 1000


# ---------------------------------------------------------------------------
# Researcher + hub-manager prompts
# ---------------------------------------------------------------------------


def _researcher_prompt(ctx: Any, iter_idx: int) -> str:
    return (
        f"You are the RESEARCHER role for team_hedgeagents_hrp, iteration "
        f"{iter_idx}. Your job is to synthesize priors from SOTA and prior "
        f"rounds.\n\n"
        f"READ (in this order):\n"
        f"  1. ./CLAUDE.md (the team's full persona).\n"
        f"  2. ./_inbox/context.md (round/iter/prev_gain).\n"
        f"  3. ../../docs/state-of-the-art/ (multi-agent & allocator sections).\n"
        f"  4. ./notes/ (any prior memory-keeper notes, if present).\n"
        f"  5. ../team_hedgeagents_hub/ if it exists "
        f"(direct ancestor in competition_1).\n\n"
        f"WRITE:\n"
        f"  - ./notes/research_log.md  (append-only, short bullet list "
        f"of new findings this iteration)\n"
        f"  - ./attempts/{iter_idx:03d}/research.json  (machine-readable JSON "
        f"with keys: spoke_priors (dict of trend/mean_rev/vol_carry priors), "
        f"regime_guess ('trend'|'range'|'mixed'|'vol_spike'), "
        f"hypothesis (short string))\n\n"
        f"Keep the JSON minimal; the hub-manager will read it next. EXIT "
        f"after writing both files. Do not return control until they exist."
    )


def _hub_manager_prompt(ctx: Any, iter_idx: int) -> str:
    return (
        f"You are the HUB-MANAGER role for team_hedgeagents_hrp, "
        f"iteration {iter_idx}. You chair the three conferences (budget, "
        f"experience-sharing, extreme-market) and produce a single JSON "
        f"blob that the deterministic risk-officer will consume.\n\n"
        f"READ:\n"
        f"  1. ./CLAUDE.md.\n"
        f"  2. ./_inbox/context.md (note: prev_gain and "
        f"prev_round_leaderboard are here).\n"
        f"  3. ./attempts/{iter_idx:03d}/research.json (the researcher's "
        f"output from this same iteration).\n"
        f"  4. ./notes/round_*.md if any (memory-keeper trail).\n\n"
        f"DECIDE (apply the three conferences as described in CLAUDE.md):\n"
        f"  - hrp_lookback_bars (int, 100..1000)\n"
        f"  - disagree_threshold (float, 0.05..0.50; below this the "
        f"composite signal routes to cash)\n"
        f"  - max_weight_per_spoke (float, 0.34..1.0)\n"
        f"  - drawdown_cap (float, 0.05..0.40; live critic cuts trading "
        f"if session drawdown exceeds this)\n"
        f"  - trend_period (int, 20..200)\n"
        f"  - mr_period (int, 10..60)\n"
        f"  - vol_period (int, 10..60)\n"
        f"  - notes (short string: thesis + any extreme-market pivots)\n\n"
        f"If prev_gain < 0 in _inbox/context.md, rotate the lookback "
        f"(e.g., if prior was 500 try 200 or 800). If prev_gain <= -0.10, "
        f"you MAY recommend shrinking max_weight_per_spoke toward 0.4 to "
        f"force more diversification.\n\n"
        f"WRITE the JSON to ./attempts/{iter_idx:03d}/hub_manager.json "
        f"AND ALSO print it to stdout as the final output of your session "
        f"(so the orchestrator can parse it from the subprocess JSON "
        f"envelope's 'result' field). Then EXIT."
    )


# ---------------------------------------------------------------------------
# Deterministic roles 3–9 (critic, risk-officer, memory-keeper, 3 spokes, HRP)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeRules:
    """Codified output of the risk-officer; serialized to runtime_rules.json."""

    hrp_lookback_bars: int
    disagree_threshold: float
    max_weight_per_spoke: float
    drawdown_cap: float
    trend_period: int
    mr_period: int
    vol_period: int
    w_trend: float
    w_mean_rev: float
    w_vol_carry: float
    notes: str

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, sort_keys=True)


def _critic_clamp(
    *,
    hrp_lookback_bars: int,
    disagree_threshold: float,
    max_weight_per_spoke: float,
    drawdown_cap: float,
    trend_period: int,
    mr_period: int,
    vol_period: int,
    train_bar_count: int,
) -> dict[str, float | int]:
    """Role #3: critic. Enforce floors, ceilings, and type sanity.

    Returns a dict of clamped values. If the hub-manager produced garbage,
    this is what keeps the Strategy valid.
    """
    lookback_ceil = min(LOOKBACK_CEIL_ABSOLUTE, max(LOOKBACK_FLOOR, train_bar_count // 5))
    return {
        "hrp_lookback_bars": int(max(LOOKBACK_FLOOR, min(lookback_ceil, hrp_lookback_bars))),
        "disagree_threshold": float(
            max(DISAGREE_THRESHOLD_FLOOR, min(DISAGREE_THRESHOLD_CEIL, disagree_threshold)),
        ),
        "max_weight_per_spoke": float(
            max(MAX_WEIGHT_FLOOR, min(MAX_WEIGHT_CEIL, max_weight_per_spoke)),
        ),
        "drawdown_cap": float(max(0.05, min(0.40, drawdown_cap))),
        "trend_period": int(max(20, min(200, trend_period))),
        "mr_period": int(max(10, min(60, mr_period))),
        "vol_period": int(max(10, min(60, vol_period))),
    }


def _memory_keeper_append(
    *,
    workspace_dir: Path,
    round_index: int,
    iteration: int,
    rules: RuntimeRules,
    prev_gain: float | None,
) -> None:
    """Role #5: memory-keeper. Append a short round/iter thesis note."""
    notes_dir = workspace_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = notes_dir / f"round_{round_index:02d}_iter_{iteration:02d}.md"
    body = (
        f"# round {round_index} iter {iteration}\n\n"
        f"- prev_gain: {prev_gain}\n"
        f"- lookback_bars: {rules.hrp_lookback_bars}\n"
        f"- disagree_threshold: {rules.disagree_threshold}\n"
        f"- drawdown_cap: {rules.drawdown_cap}\n"
        f"- weights: trend={rules.w_trend:.3f} "
        f"mr={rules.w_mean_rev:.3f} vol={rules.w_vol_carry:.3f}\n"
        f"- notes: {rules.notes}\n"
    )
    path.write_text(body)


# ----- Deterministic spoke signal functions (trade-time compatible) -----


def _trend_signal(closes: list[float], period: int) -> float:
    """Role #6: trend-spoke. Long-horizon MA slope, normalized to [-1, 1].

    Signal = sign(last_close - ma) * min(1, |last_close - ma| / (period_atr)).
    Cheap, deterministic, and the same function is callable at trade time.
    """
    if len(closes) < period + 1:
        return 0.0
    ma = sum(closes[-period:]) / period
    diff = closes[-1] - ma
    # Scale by rolling mean of absolute first-differences (robust stdev proxy).
    deltas = [abs(closes[i] - closes[i - 1]) for i in range(-period, 0)]
    scale = sum(deltas) / period if deltas else 1.0
    if scale <= 0.0:
        return 0.0
    raw = diff / (scale * math.sqrt(period))
    return max(-1.0, min(1.0, raw))


def _mean_rev_signal(closes: list[float], period: int) -> float:
    """Role #7: mean-rev-spoke. z-score composite with contrarian sign.

    Signal = -clip(zscore, -1, 1). Positive when price dipped below mean
    (expect reversion up), negative when above.
    """
    if len(closes) < period + 1:
        return 0.0
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((c - mean) ** 2 for c in window) / period
    stdev = math.sqrt(var) if var > 0.0 else 0.0
    if stdev <= 0.0:
        return 0.0
    z = (closes[-1] - mean) / stdev
    # Contrarian: short when overbought, long when oversold.
    return max(-1.0, min(1.0, -z / 2.0))


def _vol_carry_signal(closes: list[float], period: int) -> float:
    """Role #8: vol-carry-spoke. Realized-vol delta as VRP proxy.

    Positive when recent realized-vol is expanding vs prior window (regime
    favoring long-vol carry); negative when contracting (favoring short-vol
    / trend persistence).
    """
    if len(closes) < 2 * period + 1:
        return 0.0
    returns = [
        (closes[i] / closes[i - 1] - 1.0)
        for i in range(-2 * period, 0)
        if closes[i - 1] > 0.0
    ]
    if len(returns) < 2 * period:
        return 0.0
    recent = returns[-period:]
    prior = returns[-2 * period : -period]

    def _stdev(xs: list[float]) -> float:
        m = sum(xs) / len(xs)
        v = sum((x - m) ** 2 for x in xs) / len(xs)
        return math.sqrt(v)

    vol_recent = _stdev(recent)
    vol_prior = _stdev(prior)
    if vol_prior <= 0.0:
        return 0.0
    raw = (vol_recent - vol_prior) / vol_prior
    return max(-1.0, min(1.0, raw))


# ----- HRP allocator -----


def _hrp_weights(signal_series: list[list[float]]) -> tuple[float, float, float]:
    """Role #9: hrp-allocator. Hierarchical Risk Parity over 3 spoke signals.

    Per Lopez de Prado (2016):
      1. Compute correlation matrix of signals.
      2. Distance d(i,j) = sqrt(0.5 * (1 - corr(i,j))).
      3. Hierarchical single-linkage cluster.
      4. Quasi-diagonal reorder (Seriation).
      5. Recursive bisection of inverse-variance weights.

    Falls back to equal weights if scipy unavailable or inputs degenerate.
    Returns (w_trend, w_mean_rev, w_vol_carry), each in [0, 1], sum == 1.
    """
    if any(len(s) < 10 for s in signal_series):
        return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)

    # Variance of each signal.
    variances: list[float] = []
    for s in signal_series:
        mean = sum(s) / len(s)
        variances.append(sum((x - mean) ** 2 for x in s) / len(s))
    if any(v <= 0.0 for v in variances):
        return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)

    try:
        import numpy as np
        from scipy.cluster.hierarchy import linkage
        from scipy.spatial.distance import squareform
    except ImportError:
        # Fallback: inverse-variance weights (no clustering).
        inv_var = [1.0 / v for v in variances]
        s = sum(inv_var)
        return (inv_var[0] / s, inv_var[1] / s, inv_var[2] / s)

    min_len = min(len(s) for s in signal_series)
    mat = np.array([s[-min_len:] for s in signal_series])
    # Correlation matrix (3x3).
    corr = np.corrcoef(mat)
    # Guard against NaN (happens if a signal is constant zero).
    if np.isnan(corr).any():
        inv_var = [1.0 / v for v in variances]
        s = sum(inv_var)
        return (inv_var[0] / s, inv_var[1] / s, inv_var[2] / s)

    # Distance matrix per Lopez de Prado.
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    # Hierarchical clustering on the condensed distance vector.
    try:
        condensed = squareform(dist, checks=False)
        link = linkage(condensed, method="single")
    except (ValueError, IndexError):
        inv_var = [1.0 / v for v in variances]
        s = sum(inv_var)
        return (inv_var[0] / s, inv_var[1] / s, inv_var[2] / s)

    # Quasi-diagonal order (Seriation): follow the linkage tree to get
    # a leaf order that puts correlated items adjacent.
    n = 3
    sort_ix = _get_quasi_diag_order(link, n)

    # Recursive bisection of inverse-variance weights over the ordered items.
    variances_arr = np.array(variances)
    weights = _recursive_bisection(variances_arr, sort_ix)

    # Map back from the sorted order to the original (trend, mr, vol) order.
    out = [0.0, 0.0, 0.0]
    for rank, orig_idx in enumerate(sort_ix):
        out[int(orig_idx)] = float(weights[rank])
    total = sum(out)
    if total <= 0.0:
        return (1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0)
    return (out[0] / total, out[1] / total, out[2] / total)


def _get_quasi_diag_order(link: Any, n: int) -> list[int]:
    """Recursively unroll the linkage matrix to a leaf order (Seriation)."""
    import numpy as np

    link = link.astype(int)
    # Start at the root (last merge).
    sort_ix = [int(link[-1, 0]), int(link[-1, 1])]
    num_items = n

    def _expand(i: int) -> list[int]:
        if i < num_items:
            return [i]
        merge = link[i - num_items]
        return _expand(int(merge[0])) + _expand(int(merge[1]))

    expanded: list[int] = []
    for ix in sort_ix:
        expanded.extend(_expand(ix))
    # Deduplicate while preserving order (safety net for malformed linkage).
    seen: set[int] = set()
    ordered: list[int] = []
    for ix in expanded:
        if ix not in seen:
            seen.add(ix)
            ordered.append(ix)
    # If somehow short, pad with missing indices.
    for i in range(num_items):
        if i not in seen:
            ordered.append(i)
            seen.add(i)
    _ = np  # silence unused import in case this path short-circuits
    return ordered


def _recursive_bisection(variances: Any, sort_ix: list[int]) -> list[float]:
    """Recursive bisection of inverse-variance weights over a sorted index list."""
    import numpy as np

    weights = np.ones(len(sort_ix))

    def _cluster_var(indices: list[int]) -> float:
        # Inverse-variance weights within the cluster; cluster variance is
        # the weighted variance. For scalar-per-item we simplify to:
        inv_var = 1.0 / variances[indices]
        w = inv_var / inv_var.sum()
        return float((w * variances[indices]).sum())

    def _split(indices: list[int]) -> None:
        if len(indices) <= 1:
            return
        half = len(indices) // 2
        left = indices[:half]
        right = indices[half:]
        v_left = _cluster_var(left)
        v_right = _cluster_var(right)
        alpha = 1.0 - v_left / (v_left + v_right)
        for i in left:
            weights[sort_ix.index(i)] *= alpha
        for i in right:
            weights[sort_ix.index(i)] *= 1.0 - alpha
        _split(left)
        _split(right)

    _split(sort_ix)
    # Normalize.
    total = float(weights.sum())
    if total <= 0.0:
        return [1.0 / len(sort_ix)] * len(sort_ix)
    return [float(w / total) for w in weights]


# ---------------------------------------------------------------------------
# Runtime rules I/O
# ---------------------------------------------------------------------------


def _parse_hub_manager_output(
    *,
    workspace_dir: Path,
    iter_idx: int,
    stdout: str,
) -> dict[str, Any]:
    """Parse the hub-manager's JSON payload.

    Tries the on-disk file first (``attempts/<iter>/hub_manager.json``),
    falls back to extracting JSON from the subprocess stdout.
    Returns an empty dict on any parse failure — caller applies defaults.
    """
    disk_path = workspace_dir / "attempts" / f"{iter_idx:03d}" / "hub_manager.json"
    if disk_path.exists():
        try:
            data = json.loads(disk_path.read_text())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass

    # Claude --print --output-format json wraps the result in
    # {..., "result": "<model text>", ...}. Try that shape.
    try:
        envelope = json.loads(stdout)
        if isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
            inner = envelope["result"]
            # The inner may itself be markdown-wrapped JSON; try direct parse.
            try:
                data = json.loads(inner)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                # Scan for first '{' ... last '}' block.
                start = inner.find("{")
                end = inner.rfind("}")
                if 0 <= start < end:
                    try:
                        data = json.loads(inner[start : end + 1])
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError:
                        pass
    except (json.JSONDecodeError, ValueError):
        pass

    return {}


def _load_train_closes(ctx: Any) -> list[float]:
    """Load train-window bar closes from the catalog (no leak: train only)."""
    handle = ctx.get_train_data()
    catalog = ParquetDataCatalog(str(handle.catalog_path))
    bars = catalog.bars(
        bar_types=[handle.instrument.bar_type],
        start=handle.start,
        end=handle.end,
    )
    # Bar.close is a Price; cast to float via str to avoid precision drift.
    return [float(bar.close) for bar in bars]


def _compute_spoke_series(
    closes: list[float],
    *,
    lookback: int,
    trend_period: int,
    mr_period: int,
    vol_period: int,
) -> tuple[list[float], list[float], list[float]]:
    """Compute the three spoke signal time-series over the train window.

    These series feed HRP covariance estimation. Each series is length
    ``min(lookback, len(closes) - max_period)``.
    """
    max_period = max(trend_period, mr_period, 2 * vol_period)
    effective_len = min(lookback, max(0, len(closes) - max_period))
    if effective_len <= 0:
        return ([0.0], [0.0], [0.0])

    trend_s: list[float] = []
    mr_s: list[float] = []
    vol_s: list[float] = []
    start_ix = len(closes) - effective_len
    for i in range(start_ix, len(closes)):
        window = closes[: i + 1]
        trend_s.append(_trend_signal(window, trend_period))
        mr_s.append(_mean_rev_signal(window, mr_period))
        vol_s.append(_vol_carry_signal(window, vol_period))
    return (trend_s, mr_s, vol_s)


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class TeamStrategyConfig(StrategyConfig, frozen=True):
    """Config for the HRP-weighted hub-and-spoke Strategy.

    Only ``instrument_id`` and ``bar_type`` are required. Every other
    knob is loaded at ``on_start`` from ``runtime_rules.json`` (written
    by ``train()``), which keeps the config tiny and the Strategy
    easily re-instantiable for paper.
    """

    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal = Decimal("0.001")
    runtime_rules_path: str = str(RUNTIME_RULES_PATH)


class TeamStrategy(Strategy):
    """Trade-time side of team_hedgeagents_hrp.

    Loads HRP weights + disagree-threshold + drawdown-cap from
    ``runtime_rules.json`` in ``on_start``. Computes three spoke signals
    every bar and sizes a position by the HRP-weighted composite. No
    LLM calls at trade time.
    """

    def __init__(self, config: TeamStrategyConfig) -> None:
        super().__init__(config)
        self.instrument: Instrument | None = None
        self._closes: deque[float] = deque(maxlen=2000)
        self._position_qty: Decimal = Decimal("0")
        self._session_peak_equity: float = 0.0
        self._drawdown_halted: bool = False
        # Default rules; overwritten in on_start if file present.
        self._lookback: int = DEFAULT_HRP_LOOKBACK_BARS
        self._disagree_threshold: float = DEFAULT_DISAGREE_THRESHOLD
        self._drawdown_cap: float = DEFAULT_DRAWDOWN_CAP
        self._trend_period: int = DEFAULT_TREND_PERIOD
        self._mr_period: int = DEFAULT_MR_PERIOD
        self._vol_period: int = DEFAULT_VOL_PERIOD
        self._w_trend: float = 1.0 / 3.0
        self._w_mr: float = 1.0 / 3.0
        self._w_vol: float = 1.0 / 3.0

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument not found: {self.config.instrument_id}")
            self.stop()
            return
        self._load_runtime_rules()
        self.subscribe_bars(self.config.bar_type)

    def _load_runtime_rules(self) -> None:
        path = Path(self.config.runtime_rules_path)
        if not path.exists():
            self.log.warning(
                f"runtime_rules.json missing at {path}; using defaults.",
            )
            return
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            self.log.warning(f"Failed to read runtime_rules.json: {exc}; defaults.")
            return
        self._lookback = int(data.get("hrp_lookback_bars", self._lookback))
        self._disagree_threshold = float(
            data.get("disagree_threshold", self._disagree_threshold),
        )
        self._drawdown_cap = float(data.get("drawdown_cap", self._drawdown_cap))
        self._trend_period = int(data.get("trend_period", self._trend_period))
        self._mr_period = int(data.get("mr_period", self._mr_period))
        self._vol_period = int(data.get("vol_period", self._vol_period))
        self._w_trend = float(data.get("w_trend", self._w_trend))
        self._w_mr = float(data.get("w_mean_rev", self._w_mr))
        self._w_vol = float(data.get("w_vol_carry", self._w_vol))

    def on_bar(self, bar: Bar) -> None:  # noqa: C901
        if self.instrument is None:
            return
        self._closes.append(float(bar.close))
        if self._drawdown_halted:
            self._ensure_flat()
            return
        # Live drawdown cap check (session peak vs current unrealized).
        equity = self._estimated_equity(float(bar.close))
        if equity > self._session_peak_equity:
            self._session_peak_equity = equity
        if self._session_peak_equity > 0.0:
            dd = (self._session_peak_equity - equity) / self._session_peak_equity
            if dd >= self._drawdown_cap:
                self.log.warning(
                    f"Drawdown cap {self._drawdown_cap} hit (dd={dd:.3f}); "
                    f"halting new trades for session.",
                )
                self._drawdown_halted = True
                self._ensure_flat()
                return

        closes_list = list(self._closes)
        # Warm-up guard.
        min_bars = max(self._trend_period, self._mr_period, 2 * self._vol_period) + 1
        if len(closes_list) < min_bars:
            return

        s_trend = _trend_signal(closes_list, self._trend_period)
        s_mr = _mean_rev_signal(closes_list, self._mr_period)
        s_vol = _vol_carry_signal(closes_list, self._vol_period)
        composite = self._w_trend * s_trend + self._w_mr * s_mr + self._w_vol * s_vol

        if abs(composite) < self._disagree_threshold:
            self._ensure_flat()
            return

        # Target a clipped fraction of trade_size per unit of composite.
        target_fraction = max(-1.0, min(1.0, composite))
        target_qty = Decimal(str(target_fraction)) * self.config.trade_size
        self._rebalance_to(target_qty)

    def _estimated_equity(self, last_close: float) -> float:
        """Rough mark-to-market used only for drawdown-cap bookkeeping."""
        qty = float(self._position_qty)
        # Starting pot is implicit; we only need relative changes, so use
        # position * price as a proxy plus a constant 1000 base.
        return 1000.0 + qty * last_close

    def _ensure_flat(self) -> None:
        if self._position_qty == 0:
            return
        self._submit_market(-self._position_qty)
        self._position_qty = Decimal("0")

    def _rebalance_to(self, target_qty: Decimal) -> None:
        delta = target_qty - self._position_qty
        if delta == 0:
            return
        self._submit_market(delta)
        self._position_qty = target_qty

    def _submit_market(self, signed_qty: Decimal) -> None:
        if signed_qty == 0 or self.instrument is None:
            return
        side = OrderSide.BUY if signed_qty > 0 else OrderSide.SELL
        abs_qty = abs(signed_qty)
        try:
            qty = self.instrument.make_qty(abs_qty)
        except (ValueError, TypeError) as exc:
            self.log.warning(f"make_qty({abs_qty}) failed: {exc}")
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        self.unsubscribe_bars(self.config.bar_type)


# ---------------------------------------------------------------------------
# train(ctx) — the harness entry point
# ---------------------------------------------------------------------------


def _format_context(ctx: Any) -> str:
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


def _safe_run_claude(
    *,
    workspace_dir: Path,
    prompt: str,
    timeout_seconds: int,
    label: str,
) -> ResearcherResult:
    """Wrap ``run_researcher`` so a timeout / error does not crash ``train()``.

    Returns a :class:`ResearcherResult` (possibly with empty ``payload``) and
    NEVER raises. This is the budget-discipline guardrail: a single LLM
    failure must not cost the team the whole round. The framework helper
    handles Bedrock-envelope unwrap and fenced-JSON parsing internally; in
    the rare case the team needs the raw stdout for legacy disk-fallback
    parsing, the result also exposes ``raw_stdout``.
    """
    return run_researcher(
        workspace_dir=workspace_dir,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        fail_loud=False,
    )


def train(ctx: Any) -> tuple[type[TeamStrategy], TeamStrategyConfig]:
    """Single harness call. Runs researcher + hub-manager + deterministic roles.

    See CLAUDE.md > "Runtime pattern (hybrid)" for the 9-step sequence.
    """
    iter_idx = int(ctx.iteration)
    round_idx = int(ctx.round_index)
    workspace_dir = Path(ctx.workspace_dir)
    (workspace_dir / "_inbox").mkdir(exist_ok=True)
    (workspace_dir / "_inbox" / "context.md").write_text(_format_context(ctx))
    (workspace_dir / "attempts" / f"{iter_idx:03d}").mkdir(parents=True, exist_ok=True)
    (workspace_dir / "notes").mkdir(exist_ok=True)

    # Budget discipline: split the per-train timeout between the two LLM
    # calls and leave a safety margin for deterministic work.
    total_budget_s = int(ctx.config.agent.per_train_timeout_seconds)
    per_llm_budget_s = max(60, (total_budget_s - 120) // 2)

    # ------------------------------------------------------------------
    # Role #1: researcher (LLM call #1)
    # ------------------------------------------------------------------
    _safe_run_claude(
        workspace_dir=workspace_dir,
        prompt=_researcher_prompt(ctx, iter_idx),
        timeout_seconds=per_llm_budget_s,
        label="researcher",
    )

    # ------------------------------------------------------------------
    # Role #2: hub-manager (LLM call #2) — runs the three conferences
    # ------------------------------------------------------------------
    hub_result = _safe_run_claude(
        workspace_dir=workspace_dir,
        prompt=_hub_manager_prompt(ctx, iter_idx),
        timeout_seconds=per_llm_budget_s,
        label="hub-manager",
    )
    # Prefer the framework-parsed payload; fall back to disk + raw-stdout
    # legacy parser if the helper couldn't extract a fenced JSON block.
    if hub_result.payload:
        hub_payload = hub_result.payload
    else:
        hub_payload = _parse_hub_manager_output(
            workspace_dir=workspace_dir,
            iter_idx=iter_idx,
            stdout=hub_result.raw_stdout,
        )

    # Extract knobs with defaults.
    hrp_lookback_bars = int(
        hub_payload.get("hrp_lookback_bars", DEFAULT_HRP_LOOKBACK_BARS),
    )
    disagree_threshold = float(
        hub_payload.get("disagree_threshold", DEFAULT_DISAGREE_THRESHOLD),
    )
    max_weight_per_spoke = float(
        hub_payload.get("max_weight_per_spoke", DEFAULT_MAX_WEIGHT_PER_SPOKE),
    )
    drawdown_cap = float(hub_payload.get("drawdown_cap", DEFAULT_DRAWDOWN_CAP))
    trend_period = int(hub_payload.get("trend_period", DEFAULT_TREND_PERIOD))
    mr_period = int(hub_payload.get("mr_period", DEFAULT_MR_PERIOD))
    vol_period = int(hub_payload.get("vol_period", DEFAULT_VOL_PERIOD))
    notes_str = str(hub_payload.get("notes", "fallback-defaults"))

    # ------------------------------------------------------------------
    # Load train-window bars (no leak: train window only).
    # ------------------------------------------------------------------
    try:
        closes = _load_train_closes(ctx)
    except (FileNotFoundError, OSError, ValueError):
        closes = []

    # ------------------------------------------------------------------
    # Role #3: critic — clamp all knobs.
    # ------------------------------------------------------------------
    clamped = _critic_clamp(
        hrp_lookback_bars=hrp_lookback_bars,
        disagree_threshold=disagree_threshold,
        max_weight_per_spoke=max_weight_per_spoke,
        drawdown_cap=drawdown_cap,
        trend_period=trend_period,
        mr_period=mr_period,
        vol_period=vol_period,
        train_bar_count=len(closes) if closes else 0,
    )

    # ------------------------------------------------------------------
    # Roles #6-8: compute spoke signal series (deterministic).
    # Role #9: hrp-allocator over the 3x3 signal-correlation matrix.
    # ------------------------------------------------------------------
    if closes:
        trend_s, mr_s, vol_s = _compute_spoke_series(
            closes,
            lookback=int(clamped["hrp_lookback_bars"]),
            trend_period=int(clamped["trend_period"]),
            mr_period=int(clamped["mr_period"]),
            vol_period=int(clamped["vol_period"]),
        )
        w_trend, w_mr, w_vol = _hrp_weights([trend_s, mr_s, vol_s])
    else:
        w_trend = w_mr = w_vol = 1.0 / 3.0

    # Apply per-spoke cap from hub-manager (via critic).
    cap = float(clamped["max_weight_per_spoke"])
    w_trend = min(w_trend, cap)
    w_mr = min(w_mr, cap)
    w_vol = min(w_vol, cap)
    total = w_trend + w_mr + w_vol
    if total <= 0.0:
        w_trend = w_mr = w_vol = 1.0 / 3.0
    else:
        w_trend /= total
        w_mr /= total
        w_vol /= total

    # ------------------------------------------------------------------
    # Role #4: risk-officer — codify into RuntimeRules and persist.
    # ------------------------------------------------------------------
    rules = RuntimeRules(
        hrp_lookback_bars=int(clamped["hrp_lookback_bars"]),
        disagree_threshold=float(clamped["disagree_threshold"]),
        max_weight_per_spoke=float(clamped["max_weight_per_spoke"]),
        drawdown_cap=float(clamped["drawdown_cap"]),
        trend_period=int(clamped["trend_period"]),
        mr_period=int(clamped["mr_period"]),
        vol_period=int(clamped["vol_period"]),
        w_trend=float(w_trend),
        w_mean_rev=float(w_mr),
        w_vol_carry=float(w_vol),
        notes=notes_str,
    )
    RUNTIME_RULES_PATH.write_text(rules.to_json())

    # ------------------------------------------------------------------
    # Role #5: memory-keeper — append this iter's thesis + HRP weights.
    # ------------------------------------------------------------------
    _memory_keeper_append(
        workspace_dir=workspace_dir,
        round_index=round_idx,
        iteration=iter_idx,
        rules=rules,
        prev_gain=ctx.prev_gain,
    )

    # ------------------------------------------------------------------
    # Package the Strategy class + config and return.
    # ------------------------------------------------------------------
    instrument = ctx.config.instrument
    cfg = TeamStrategyConfig(
        instrument_id=InstrumentId.from_str(instrument.symbol),
        bar_type=BarType.from_str(instrument.bar_type),
    )
    return TeamStrategy, cfg
