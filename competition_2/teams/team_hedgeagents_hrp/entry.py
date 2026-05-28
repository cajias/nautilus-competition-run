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
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

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

# Directional-pivot rule (Class B fix for bear-regime composite collapse).
# When the realized return over the most recent ``PIVOT_LOOKBACK_BARS``
# closes is sustained negative (<= -PIVOT_THRESHOLD), the composite gate
# is bypassed and the Strategy switches to a single short-trend kernel
# (negative EWMA of returns, threshold-driven entry).
PIVOT_LOOKBACK_BARS = 30
PIVOT_THRESHOLD = 0.005  # 0.5% — sustained negative drift over 30 bars
SHORT_TREND_EWMA_PERIOD = 30
SHORT_TREND_ENTRY_THRESHOLD = 0.0005  # |neg-ewma return| > 5bps -> short
AGREEMENT_SIZE_MULTIPLIER_FULL = 1.5
AGREEMENT_SIZE_MULTIPLIER_PARTIAL = 1.0

# Active-kernel enum values persisted to runtime_rules.json.
KERNEL_COMPOSITE = "composite"
KERNEL_SHORT_TREND = "short_trend"
KERNEL_FLAT = "flat"


# ---------------------------------------------------------------------------
# Researcher + hub-manager prompts
# ---------------------------------------------------------------------------


def _researcher_prompt(ctx: Any, iter_idx: int, active_kernel: str) -> str:
    return (
        # ── JSON OUTPUT SPEC FIRST (load-bearing for automated parser) ──
        f"OUTPUT FORMAT (mandatory): your FINAL message MUST be a single "
        f"fenced ```json code block — and NOTHING ELSE before or after it — "
        f"with EXACTLY these top-level keys:\n"
        f"  spoke_priors (object with sub-keys trend, mean_rev, vol_carry, "
        f"each holding a short prior string),\n"
        f"  regime_guess (one of: trend | range | mixed | vol_spike | bear),\n"
        f"  hypothesis (short string summarizing this iteration's thesis).\n"
        f"The team's deterministic code parses this stdout block and "
        f"persists it to ./attempts/{iter_idx:03d}/research.json. Do NOT "
        f"call the Write tool — Write is denied in this subprocess.\n\n"
        # ── CONTEXT ──
        f"You are the RESEARCHER role for team_hedgeagents_hrp, iteration "
        f"{iter_idx}. Your job is to synthesize priors from SOTA and prior "
        f"rounds.\n\n"
        f"ACTIVE KERNEL THIS ITERATION: '{active_kernel}'.\n"
        f"  - If 'composite': you are tuning the trend+mean-rev+vol-carry "
        f"HRP-weighted gate (3-spoke composite). Bias spoke_priors toward "
        f"the dominant regime.\n"
        f"  - If 'short_trend': the directional-pivot rule has fired — the "
        f"realized 30-bar return on closes is sustained negative. The "
        f"composite is BYPASSED; the Strategy is using a single short-trend "
        f"kernel (negative EWMA of returns, threshold-driven entry). Tune "
        f"trend_period/disagree_threshold for that kernel; spoke_priors are "
        f"informational only this iteration.\n"
        f"  - If 'flat': realized drift is near zero — Strategy will not "
        f"trade. Suggest priors that would help the next iteration pivot.\n\n"
        f"READ (in this order):\n"
        f"  1. ./CLAUDE.md (the team's full persona).\n"
        f"  2. ./_inbox/context.md (round/iter/prev_gain/active_kernel).\n"
        f"  3. ../../docs/state-of-the-art/ (multi-agent & allocator sections).\n"
        f"  4. ./notes/ (any prior memory-keeper notes, if present).\n"
        f"  5. ../team_hedgeagents_hub/ if it exists "
        f"(direct ancestor in competition_1).\n\n"
        # ── FINAL OUTPUT INSTRUCTION (repeated for emphasis) ──
        f"Output ONLY the fenced ```json block with the schema above. No "
        f"prose before or after the fence. The parser will reject any other "
        f"format."
    )


def _hub_manager_prompt(ctx: Any, iter_idx: int) -> str:
    return (
        # ── JSON OUTPUT SPEC FIRST (load-bearing for automated parser) ──
        f"OUTPUT FORMAT (mandatory): your FINAL message MUST be a single "
        f"fenced ```json code block — and NOTHING ELSE before or after it — "
        f"with EXACTLY these top-level keys:\n"
        f"  hrp_lookback_bars (int, 100..1000),\n"
        f"  disagree_threshold (float, 0.05..0.50),\n"
        f"  max_weight_per_spoke (float, 0.34..1.0),\n"
        f"  drawdown_cap (float, 0.05..0.40),\n"
        f"  trend_period (int, 20..200),\n"
        f"  mr_period (int, 10..60),\n"
        f"  vol_period (int, 10..60),\n"
        f"  notes (short string: thesis + any extreme-market pivots).\n"
        f"The team's deterministic code parses this stdout block and "
        f"persists it to ./attempts/{iter_idx:03d}/hub_manager.json. Do "
        f"NOT call the Write tool — Write is denied in this subprocess.\n\n"
        # ── CONTEXT ──
        f"You are the HUB-MANAGER role for team_hedgeagents_hrp, "
        f"iteration {iter_idx}. You chair the three conferences (budget, "
        f"experience-sharing, extreme-market) and produce a single JSON "
        f"blob that the deterministic risk-officer will consume.\n\n"
        f"READ:\n"
        f"  1. ./CLAUDE.md.\n"
        f"  2. ./_inbox/context.md (note: prev_gain and "
        f"prev_round_leaderboard are here).\n"
        f"  3. ./attempts/{iter_idx:03d}/research.json (the researcher's "
        f"output from this same iteration; persisted to disk by the team's "
        f"Python code from the researcher's stdout JSON).\n"
        f"  4. ./notes/round_*.md if any (memory-keeper trail).\n\n"
        f"Apply the three conferences as described in CLAUDE.md.\n"
        f"If prev_gain < 0 in _inbox/context.md, rotate the lookback "
        f"(e.g., if prior was 500 try 200 or 800). If prev_gain <= -0.10, "
        f"you MAY recommend shrinking max_weight_per_spoke toward 0.4 to "
        f"force more diversification.\n\n"
        # ── FINAL OUTPUT INSTRUCTION (repeated for emphasis) ──
        f"Output ONLY the fenced ```json block with the schema above. No "
        f"prose before or after the fence. The parser will reject any other "
        f"format."
    )


# ---------------------------------------------------------------------------
# Deterministic roles 3–9 (critic, risk-officer, memory-keeper, 3 spokes, HRP)
# ---------------------------------------------------------------------------


class RuntimeRules(NamedTuple):
    """Codified output of the risk-officer; serialized to runtime_rules.json.

    NamedTuple instead of @dataclass(frozen=True) because the team_loader
    omits sys.modules registration before exec_module, breaking @dataclass
    under Python 3.12. NamedTuple is immutable by construction.
    """

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
    # Directional-pivot rule (Class B fix). active_kernel is one of
    # KERNEL_COMPOSITE, KERNEL_SHORT_TREND, or KERNEL_FLAT and is
    # decided at train-time from the realized return on the train-window
    # closes. The Strategy reads it in on_start and branches in on_bar.
    active_kernel: str
    pivot_lookback_bars: int
    pivot_threshold: float
    short_trend_period: int
    short_trend_threshold: float
    realized_return: float

    def to_json(self) -> str:
        # NamedTuple uses _asdict() (dataclass would have used self.__dict__).
        return json.dumps(self._asdict(), indent=2, sort_keys=True)


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


# ----- Directional-pivot rule (Class B fix) -----


def _realized_return(closes: list[float], lookback: int) -> float:
    """Realized return over the most recent ``lookback`` closes.

    Returns ``(closes[-1] / closes[-lookback-1]) - 1.0`` if enough bars,
    else 0.0. Used by the directional-pivot decision in train() AND
    every bar at trade time.
    """
    if len(closes) < lookback + 1:
        return 0.0
    prior = closes[-lookback - 1]
    if prior <= 0.0:
        return 0.0
    return closes[-1] / prior - 1.0


def _decide_kernel(realized: float, pivot_threshold: float) -> str:
    """Pick the active kernel from a realized-return reading.

    - realized <= -pivot_threshold (sustained negative drift): short-trend
    - realized >=  pivot_threshold (sustained positive drift): composite
    - otherwise (near zero): flat (no trade)
    """
    if realized <= -pivot_threshold:
        return KERNEL_SHORT_TREND
    if realized >= pivot_threshold:
        return KERNEL_COMPOSITE
    return KERNEL_FLAT


def _short_trend_signal(closes: list[float], period: int) -> float:
    """Negative-EWMA-of-returns short-trend kernel.

    Returns a signed signal in [-1, 1]: NEGATIVE when recent returns have
    been NEGATIVE on average (i.e. the EWMA of returns is < 0). The
    Strategy enters a short whenever |signal| > short_trend_threshold.
    """
    if len(closes) < period + 1 or period <= 1:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    ewma = 0.0
    # EWMA of bar-to-bar returns, oldest-first.
    start = max(1, len(closes) - period)
    for i in range(start, len(closes)):
        prev = closes[i - 1]
        if prev <= 0.0:
            continue
        ret = closes[i] / prev - 1.0
        ewma = alpha * ret + (1.0 - alpha) * ewma
    # Scale: 1bp average return -> ~0.1 signal. Clip to [-1, 1].
    raw = ewma * 1000.0
    return max(-1.0, min(1.0, raw))


def _agreement_multiplier(s_trend: float, s_mr: float, s_vol: float) -> tuple[float, int]:
    """Signed-agreement multiplier for trade_size scaling.

    Returns (multiplier, signed_direction):
      - all three same non-zero sign → (1.5, +/-1)
      - exactly two same non-zero sign → (1.0, +/-1) (direction = majority)
      - otherwise → (0.0, 0) (skip — full disagreement)
    """
    signs = [
        1 if s_trend > 0 else (-1 if s_trend < 0 else 0),
        1 if s_mr > 0 else (-1 if s_mr < 0 else 0),
        1 if s_vol > 0 else (-1 if s_vol < 0 else 0),
    ]
    pos = sum(1 for s in signs if s > 0)
    neg = sum(1 for s in signs if s < 0)
    if pos == 3:
        return (AGREEMENT_SIZE_MULTIPLIER_FULL, 1)
    if neg == 3:
        return (AGREEMENT_SIZE_MULTIPLIER_FULL, -1)
    if pos == 2:
        return (AGREEMENT_SIZE_MULTIPLIER_PARTIAL, 1)
    if neg == 2:
        return (AGREEMENT_SIZE_MULTIPLIER_PARTIAL, -1)
    return (0.0, 0)


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
        # Directional-pivot rule state.
        self._active_kernel: str = KERNEL_COMPOSITE
        self._pivot_lookback_bars: int = PIVOT_LOOKBACK_BARS
        self._pivot_threshold: float = PIVOT_THRESHOLD
        self._short_trend_period: int = SHORT_TREND_EWMA_PERIOD
        self._short_trend_threshold: float = SHORT_TREND_ENTRY_THRESHOLD

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
        self._active_kernel = str(data.get("active_kernel", self._active_kernel))
        self._pivot_lookback_bars = int(
            data.get("pivot_lookback_bars", self._pivot_lookback_bars),
        )
        self._pivot_threshold = float(
            data.get("pivot_threshold", self._pivot_threshold),
        )
        self._short_trend_period = int(
            data.get("short_trend_period", self._short_trend_period),
        )
        self._short_trend_threshold = float(
            data.get("short_trend_threshold", self._short_trend_threshold),
        )
        self.log.info(
            f"Loaded runtime_rules: active_kernel={self._active_kernel} "
            f"pivot_lookback={self._pivot_lookback_bars} "
            f"pivot_threshold={self._pivot_threshold:.4f}",
        )

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
        # Warm-up guard: need enough for the full composite stack AND the
        # pivot-lookback window so the directional rule can fire.
        min_bars = (
            max(
                self._trend_period,
                self._mr_period,
                2 * self._vol_period,
                self._short_trend_period,
                self._pivot_lookback_bars,
            )
            + 1
        )
        if len(closes_list) < min_bars:
            return

        # ── Directional-pivot rule (re-evaluated EVERY bar) ─────────────
        # Re-decide the active kernel from the live realized-return reading.
        # The persisted runtime_rules.active_kernel is the *train-time*
        # decision used to seed researcher/hub-manager priors; trade-time
        # uses the live reading so a regime flip mid-eval window switches
        # kernels without needing another train() call.
        realized = _realized_return(closes_list, self._pivot_lookback_bars)
        live_kernel = _decide_kernel(realized, self._pivot_threshold)

        if live_kernel == KERNEL_FLAT:
            self._ensure_flat()
            return

        if live_kernel == KERNEL_SHORT_TREND:
            # Single short-trend kernel: negative EWMA of returns,
            # threshold-driven entry. Composite gate is BYPASSED.
            s_short = _short_trend_signal(closes_list, self._short_trend_period)
            if abs(s_short) < self._short_trend_threshold * 1000.0:
                # Threshold compares against the same scale as the signal
                # (signal is EWMA*1000). Below threshold -> stay flat.
                self._ensure_flat()
                return
            # Bear-regime kernel: only act on the SHORT side. If the EWMA
            # has flipped positive in a sustained-bear window, that's noise
            # — stay flat rather than chase it long.
            if s_short > 0.0:
                self._ensure_flat()
                return
            target_fraction = max(-1.0, min(1.0, s_short))
            target_qty = Decimal(str(target_fraction)) * self.config.trade_size
            self._rebalance_to(target_qty)
            return

        # ── Composite kernel ────────────────────────────────────────────
        s_trend = _trend_signal(closes_list, self._trend_period)
        s_mr = _mean_rev_signal(closes_list, self._mr_period)
        s_vol = _vol_carry_signal(closes_list, self._vol_period)
        composite = self._w_trend * s_trend + self._w_mr * s_mr + self._w_vol * s_vol

        if abs(composite) < self._disagree_threshold:
            self._ensure_flat()
            return

        # Agreement-scaled sizing: 3 agree -> 1.5x, 2 agree -> 1.0x, else skip.
        size_mult, agreement_dir = _agreement_multiplier(s_trend, s_mr, s_vol)
        if size_mult <= 0.0:
            # Full disagreement on direction — skip this bar.
            self._ensure_flat()
            return

        # Sanity: composite sign should match agreement direction (it almost
        # always will, since composite is a weighted sum). If not, trust the
        # agreement majority over the weighted sum.
        composite_sign = 1 if composite > 0 else -1
        effective_sign = agreement_dir if agreement_dir != 0 else composite_sign

        target_fraction = max(-1.0, min(1.0, abs(composite))) * effective_sign
        scaled = Decimal(str(target_fraction * size_mult)) * self.config.trade_size
        self._rebalance_to(scaled)

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
    (workspace_dir / "attempts" / f"{iter_idx:03d}").mkdir(parents=True, exist_ok=True)
    (workspace_dir / "notes").mkdir(exist_ok=True)

    # Budget discipline: split the per-train timeout between the two LLM
    # calls and leave a safety margin for deterministic work.
    total_budget_s = int(ctx.config.agent.per_train_timeout_seconds)
    per_llm_budget_s = max(60, (total_budget_s - 120) // 2)

    # ------------------------------------------------------------------
    # Directional-pivot rule (Class B fix): decide the active kernel BEFORE
    # the researcher runs so the prompt can tell the LLM what it's tuning.
    # ------------------------------------------------------------------
    try:
        train_closes_for_pivot = _load_train_closes(ctx)
    except (FileNotFoundError, OSError, ValueError):
        train_closes_for_pivot = []
    train_realized = _realized_return(train_closes_for_pivot, PIVOT_LOOKBACK_BARS)
    active_kernel = _decide_kernel(train_realized, PIVOT_THRESHOLD)

    # Write the inbox AFTER deciding the kernel so the researcher can see it.
    (workspace_dir / "_inbox" / "context.md").write_text(
        _format_context(ctx)
        + f"- active_kernel: {active_kernel}\n"
        + f"- realized_return_30bar: {train_realized:.6f}\n"
    )

    # ------------------------------------------------------------------
    # Role #1: researcher (LLM call #1)
    # ------------------------------------------------------------------
    # Subprocess Write tool is denied; the researcher emits its JSON on
    # stdout (parsed by run_researcher into result.payload) and we persist
    # it to disk here so the hub-manager prompt's "READ research.json" step
    # finds the file.
    research_result = _safe_run_claude(
        workspace_dir=workspace_dir,
        prompt=_researcher_prompt(ctx, iter_idx, active_kernel),
        timeout_seconds=per_llm_budget_s,
        label="researcher",
    )
    research_path = (
        workspace_dir / "attempts" / f"{iter_idx:03d}" / "research.json"
    )
    if research_result.payload:
        research_path.write_text(
            json.dumps(research_result.payload, indent=2, sort_keys=True)
        )
        # Append a one-line note to research_log.md for cross-iter memory.
        log_path = workspace_dir / "notes" / "research_log.md"
        regime = research_result.payload.get("regime_guess", "?")
        hypothesis = str(research_result.payload.get("hypothesis", ""))[:200]
        existing = log_path.read_text() if log_path.exists() else "# research_log.md\n"
        log_path.write_text(
            existing + f"\n- iter {iter_idx}: regime={regime} | {hypothesis}\n"
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

    # Subprocess Write tool is denied — persist the parsed payload here so
    # the on-disk forensic record of the iteration is complete and so future
    # iterations (or other roles) can read hub_manager.json from disk.
    if hub_payload:
        hub_path = (
            workspace_dir / "attempts" / f"{iter_idx:03d}" / "hub_manager.json"
        )
        hub_path.write_text(json.dumps(hub_payload, indent=2, sort_keys=True))

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
    # Train-window bars (already loaded above for the pivot decision).
    # ------------------------------------------------------------------
    closes = train_closes_for_pivot

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
        notes=(
            f"[active_kernel={active_kernel} "
            f"realized_30bar={train_realized:+.5f}] " + notes_str
        ),
        active_kernel=active_kernel,
        pivot_lookback_bars=PIVOT_LOOKBACK_BARS,
        pivot_threshold=PIVOT_THRESHOLD,
        short_trend_period=SHORT_TREND_EWMA_PERIOD,
        short_trend_threshold=SHORT_TREND_ENTRY_THRESHOLD,
        realized_return=float(train_realized),
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
