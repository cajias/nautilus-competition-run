"""Entry point for team_cont_stoikov_microstructure.

An 8-role microstructure trading floor:

    1. researcher            — `run_claude(...)`, ~180s, writes a research brief.
    2. hypothesis-generator  — pure Python; proposes proxy variants and thresholds.
    3. critic                — pure Python; flags proxy/regime failure modes.
    4. risk-officer          — pure Python; assembles runtime_rules.json.
    5. memory-keeper         — pure Python; appends to notes/cross_round.md.
    6. signal-engineer       — pure Python; computes OFI+VPIN on train bars,
                                calibrates thresholds via quantile.
    7. regime-gater          — pure Python; realized-vol + session gates.
    8. execution-trader      — pure Python; wires the live Strategy.

Only the researcher (role 1) uses an LLM, and only at train time. The live
Strategy is pure deterministic Python — no LLM at trade time.

Bar-level proxy disclaimer (see CLAUDE.md): tick-level Cont-Stoikov OFI and
Easley-López-O'Hara VPIN are adapted to 5-min OHLCV bars. Expect
directionality preserved, noise higher. Thresholds MUST be calibrated from
the train window each round.
"""

from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import numpy as np
import pandas as pd
from nautilus_trader.config import StrategyConfig  # type: ignore[import-untyped]
from nautilus_trader.model.data import Bar, BarType  # type: ignore[import-untyped]
from nautilus_trader.model.enums import OrderSide, TimeInForce  # type: ignore[import-untyped]
from nautilus_trader.model.identifiers import InstrumentId  # type: ignore[import-untyped]
from nautilus_trader.persistence.catalog import ParquetDataCatalog  # type: ignore[import-untyped]
from nautilus_trader.trading.strategy import Strategy  # type: ignore[import-untyped]

from nautilus_competition.agent_runner import (  # type: ignore[import-untyped]
    AgentError,
    AgentTimeoutError,
    run_claude,
)


if TYPE_CHECKING:
    from nautilus_trader.model.instruments import Instrument  # type: ignore[import-untyped]

# --------------------------------------------------------------------------- #
# Module-level constants
# --------------------------------------------------------------------------- #

TEAM_DIR = Path(__file__).parent
NOTES_DIR = TEAM_DIR / "notes"
ATTEMPTS_DIR = TEAM_DIR / "attempts"
CACHE_DIR = TEAM_DIR / "cache"

# Researcher budget: 420s of the 600s train window.
RESEARCHER_TIMEOUT_SECONDS = 420
# Reuse a cached researcher brief if younger than this.
RESEARCH_CACHE_MAX_AGE_SECONDS = 60 * 60  # 1 hour

# Train-time OFI persistence window (k bars aggregated).
TRAIN_OFI_K = 4
# Trade-time OFI persistence window — shorter because the paper window has
# only 3 bars total. Defined by bar 2.
TRADE_OFI_K = 2

# Default VPIN bucket size in bars (Easley et al. suggest 50 ticks/bar equivalent;
# we use 50 × 5-min bars = a rolling window of the previous 50 bars).
VPIN_BUCKET_BARS = 50

# Quantile thresholds for calibration.
VPIN_PERMIT_QUANTILE_BASE = 0.60
OFI_ENTRY_QUANTILE_BASE = 0.75
# After a loss, tighten.
VPIN_PERMIT_QUANTILE_TIGHTEN = 0.05
OFI_ENTRY_QUANTILE_TIGHTEN = 0.05

# Critic sanity: a signal firing on < this fraction of train bars is too sparse
# to trust; firing on > this fraction is likely a noise alias.
MIN_SIGNAL_RATE = 0.005
MAX_SIGNAL_RATE = 0.25

# Default per-trade trade size (BTC).
DEFAULT_TRADE_SIZE_BTC = Decimal("0.02")

logger = logging.getLogger("team_cont_stoikov_microstructure.entry")


# --------------------------------------------------------------------------- #
# StrategyConfig + Strategy (execution-trader role, trade-time)
# --------------------------------------------------------------------------- #


class TeamConfig(StrategyConfig, frozen=True):
    """Immutable config consumed by the live BacktestEngine / paper engine.

    Thresholds are baked in at train-time; the live strategy does not tune.
    """

    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal = DEFAULT_TRADE_SIZE_BTC
    # OFI proxy
    ofi_entry_threshold: float = 0.0
    ofi_k_bars: int = TRADE_OFI_K
    # VPIN proxy
    vpin_permit_threshold: float = 1.0
    vpin_bucket_bars: int = VPIN_BUCKET_BARS
    # Realized-vol gate (prior from train window)
    rv_prior: float = 0.0
    rv_cap: float = 1.0
    # Stop-loss (absolute fraction of entry price, e.g. 0.01 = 1%)
    stop_loss_pct: float = 0.01
    # Max bars held before forced exit (in case no signal fires to close)
    max_hold_bars: int = 3


class TeamStrategy(Strategy):
    """OFI + VPIN tactical-long Strategy.

    Live logic:
        on_bar:
          1. Compute per-bar OFI proxy.
          2. Maintain persistent_ofi = rolling sum over ofi_k_bars.
          3. Maintain VPIN via cumulative volume bucket.
          4. Maintain realized-vol rolling std (with prior).
          5. Gate: VPIN <= vpin_permit_threshold
                   AND persistent_ofi >= ofi_entry_threshold
                   AND rv_now <= rv_cap
          6. If flat and gate passes: BUY trade_size.
          7. If long: exit on stop-loss OR VPIN breach OR max_hold_bars OR
             sign(ofi_bar) < 0 for the current bar.
    """

    def __init__(self, config: TeamConfig) -> None:
        super().__init__(config)
        self.instrument: Instrument | None = None
        # Rolling OFI buffer (most recent `ofi_k_bars` bar OFIs)
        self._ofi_buffer: list[float] = []
        # Cumulative VPIN state: list of per-bar |2*buy_vol - V|, keep last `vpin_bucket_bars`
        self._vpin_buffer: list[float] = []
        self._vpin_vol_buffer: list[float] = []
        # Returns buffer for realized vol
        self._ret_buffer: list[float] = []
        # Prior close for return computation
        self._prev_close: float | None = None
        # Running estimate of std used for BVC sigma — seeded to RV prior
        self._bvc_sigma: float = max(config.rv_prior, 1e-9)
        # Position state
        self._long_entry_price: float | None = None
        self._bars_held: int = 0

    # ---- lifecycle ------------------------------------------------------- #

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument not found: {self.config.instrument_id}")
            self.stop()
            return
        self.subscribe_bars(self.config.bar_type)
        self.log.info(
            f"OFI-VPIN strategy armed: "
            f"ofi_threshold={self.config.ofi_entry_threshold:.4f} "
            f"vpin_threshold={self.config.vpin_permit_threshold:.4f} "
            f"rv_cap={self.config.rv_cap:.6f} "
            f"k_bars={self.config.ofi_k_bars}"
        )

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        self.unsubscribe_bars(self.config.bar_type)

    # ---- core loop ------------------------------------------------------- #

    def on_bar(self, bar: Bar) -> None:
        if self.instrument is None:
            return

        o = float(bar.open)
        h = float(bar.high)
        le = float(bar.low)
        c = float(bar.close)
        v = float(bar.volume)
        rng = max(h - le, 1e-9)

        # ---- 1. OFI bar-proxy ------------------------------------------- #
        direction = 1.0 if c > o else (-1.0 if c < o else 0.0)
        ofi_bar = direction * v * (abs(c - o) / rng)
        self._ofi_buffer.append(ofi_bar)
        if len(self._ofi_buffer) > self.config.ofi_k_bars:
            self._ofi_buffer.pop(0)
        persistent_ofi = sum(self._ofi_buffer)

        # ---- 2. returns + realized vol ---------------------------------- #
        ret = 0.0
        if self._prev_close is not None and self._prev_close > 0:
            ret = (c - self._prev_close) / self._prev_close
            self._ret_buffer.append(ret)
            if len(self._ret_buffer) > 20:
                self._ret_buffer.pop(0)
        self._prev_close = c
        rv_now = float(np.std(self._ret_buffer)) if len(self._ret_buffer) >= 2 else self.config.rv_prior

        # Blend bvc_sigma toward live std once we have enough samples
        if len(self._ret_buffer) >= 3:
            self._bvc_sigma = max(float(np.std(self._ret_buffer)), 1e-9)

        # ---- 3. VPIN bar-proxy ------------------------------------------ #
        # BVC split: buy_vol = V * Φ(ret / σ), sell_vol = V - buy_vol.
        # For bar 1 with no prior close we use open-close sign.
        bvc_z = ret / max(self._bvc_sigma, 1e-9) if self._prev_close is not None else (c - o) / max(abs(c - o), 1e-9)
        buy_vol = v * _phi(bvc_z)
        imbalance = abs(2.0 * buy_vol - v)
        self._vpin_buffer.append(imbalance)
        self._vpin_vol_buffer.append(v)
        if len(self._vpin_buffer) > self.config.vpin_bucket_bars:
            self._vpin_buffer.pop(0)
            self._vpin_vol_buffer.pop(0)
        total_vol = sum(self._vpin_vol_buffer)
        vpin_now = sum(self._vpin_buffer) / total_vol if total_vol > 0 else 0.0

        # ---- 4. live critic: pure Python gate set ----------------------- #
        vpin_permit = vpin_now <= self.config.vpin_permit_threshold
        ofi_permit = persistent_ofi >= self.config.ofi_entry_threshold
        rv_permit = rv_now <= self.config.rv_cap

        self.log.debug(
            f"bar: c={c:.2f} ofi={ofi_bar:+.2f} pers_ofi={persistent_ofi:+.2f} "
            f"vpin={vpin_now:.3f} rv={rv_now:.6f} "
            f"gates: vpin={vpin_permit} ofi={ofi_permit} rv={rv_permit}"
        )

        # ---- 5. position management ------------------------------------- #
        if self._long_entry_price is not None:
            self._bars_held += 1
            exit_reason: str | None = None
            if c <= self._long_entry_price * (1.0 - self.config.stop_loss_pct):
                exit_reason = "stop_loss"
            elif not vpin_permit:
                exit_reason = "vpin_breach"
            elif ofi_bar < 0.0:
                exit_reason = "ofi_flip"
            elif self._bars_held >= self.config.max_hold_bars:
                exit_reason = "max_hold"
            if exit_reason is not None:
                self._close_long(exit_reason)
            return

        # ---- 6. entry --------------------------------------------------- #
        # Entry requires at least k bars of OFI history (persistent_ofi defined).
        if len(self._ofi_buffer) < self.config.ofi_k_bars:
            return
        if vpin_permit and ofi_permit and rv_permit:
            self._open_long(c)

    # ---- helpers --------------------------------------------------------- #

    def _open_long(self, entry_price: float) -> None:
        if self.instrument is None:
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self.instrument.make_qty(self.config.trade_size),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._long_entry_price = entry_price
        self._bars_held = 0
        self.log.info(f"ENTRY @ {entry_price:.2f}")

    def _close_long(self, reason: str) -> None:
        if self.instrument is None:
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=self.instrument.make_qty(self.config.trade_size),
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        entry = self._long_entry_price or 0.0
        self.log.info(f"EXIT ({reason}) entry={entry:.2f} bars_held={self._bars_held}")
        self._long_entry_price = None
        self._bars_held = 0


def _phi(z: float) -> float:
    """Standard-normal CDF via scipy-free numpy erf."""
    import math

    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


# --------------------------------------------------------------------------- #
# The 8-role pipeline (train-time only)
# --------------------------------------------------------------------------- #


# NOTE: ``typing.NamedTuple`` instead of ``@dataclass`` — team_loader.py in
# nautilus_competition does not register the team module in ``sys.modules``
# before ``exec_module``, and Python 3.12 ``dataclass`` decorators call
# ``_is_type`` which requires the module to be in ``sys.modules``. NamedTuple
# avoids that machinery entirely.
class Thresholds(NamedTuple):
    """Calibrated thresholds produced by the signal-engineer."""

    ofi_entry: float
    vpin_permit: float
    rv_prior: float
    rv_cap: float
    ofi_k_bars: int
    vpin_bucket_bars: int
    signal_fire_rate: float


# ---- Role 1: researcher (LLM subprocess) --------------------------------- #


def _researcher(ctx: object, iter_idx: int) -> str:
    """Spawn Claude once to produce a short research brief.

    Cached across iterations inside a round: if `cache/research_brief.md`
    exists and is younger than RESEARCH_CACHE_MAX_AGE_SECONDS, reuse it.

    On researcher failure we DEGRADE GRACEFULLY — the deterministic pipeline
    runs with a canned brief so the team still returns a valid Strategy.
    """
    CACHE_DIR.mkdir(exist_ok=True)
    brief_path = CACHE_DIR / "research_brief.md"
    prev_gain = getattr(ctx, "prev_gain", None)

    # Re-use cache on non-retry calls
    if prev_gain is None and brief_path.exists():
        age = time.time() - brief_path.stat().st_mtime
        if age < RESEARCH_CACHE_MAX_AGE_SECONDS:
            logger.info("researcher: reusing cached brief (age=%.0fs)", age)
            return brief_path.read_text()

    prompt = _build_researcher_prompt(ctx, iter_idx)

    try:
        result = run_claude(
            workspace_dir=TEAM_DIR,
            prompt=prompt,
            command=["claude", "--print", "--output-format", "json"],
            timeout_seconds=RESEARCHER_TIMEOUT_SECONDS,
        )
    except (AgentTimeoutError, AgentError) as exc:
        logger.warning("researcher: Claude call failed (%s); using canned brief", exc)
        brief = _canned_brief(ctx)
    else:
        # Extract `result` field from the JSON payload; fall back to raw stdout.
        try:
            payload = json.loads(result.stdout)
            brief = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(brief, str) or not brief.strip():
                brief = result.stdout
        except (json.JSONDecodeError, ValueError):
            brief = result.stdout
        if result.returncode != 0:
            logger.warning(
                "researcher: Claude exited rc=%s; using canned fallback", result.returncode
            )
            brief = _canned_brief(ctx)

    # Persist to both caches.
    brief_path.write_text(brief)
    NOTES_DIR.mkdir(exist_ok=True)
    (NOTES_DIR / "research_log.md").write_text(
        (NOTES_DIR / "research_log.md").read_text() + f"\n\n---\n## iter {iter_idx}\n\n{brief}"
        if (NOTES_DIR / "research_log.md").exists()
        else f"# research_log.md\n\n## iter {iter_idx}\n\n{brief}"
    )
    iter_dir = ATTEMPTS_DIR / f"{iter_idx:03d}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "research.md").write_text(brief)
    return brief


def _build_researcher_prompt(ctx: object, iter_idx: int) -> str:
    prev_gain = getattr(ctx, "prev_gain", None)
    loss_hint = ""
    if prev_gain is not None and prev_gain < 0.0:
        loss_hint = (
            f"\n\n**CRITICAL**: previous iteration LOST money "
            f"(prev_gain={prev_gain:+.4f}). Propose ALTERNATIVE proxy "
            f"formulations: tick-rule BVC vs our Φ(ret/σ) BVC, "
            f"different k in persistent_ofi (3,4,5,8), different VPIN "
            f"bucket size (25,50,100 bars)."
        )
    return (
        f"You are the RESEARCHER for team_cont_stoikov_microstructure, "
        f"iteration {iter_idx}. Write a concise (≤600 words) research brief "
        f"covering:\n"
        f"1. Current OFI / VPIN proxy formulations at 5-min bar grain.\n"
        f"2. Cite Cont-Kukanov-Stoikov 2014, Easley-López-O'Hara 2012, Kyle 1985.\n"
        f"3. Recommended quantile thresholds for entry + VPIN veto.\n"
        f"4. Known bar-grain failure modes (choppy range days, gap opens).\n"
        f"{loss_hint}\n\n"
        f"Write your brief to STDOUT. Do NOT spawn subagents. Do NOT edit "
        f"any files — the calling Python process will write the brief to "
        f"disk. Keep under 600 words."
    )


def _canned_brief(ctx: object) -> str:
    prev_gain = getattr(ctx, "prev_gain", None)
    return (
        "# Canned microstructure brief (researcher offline)\n\n"
        "- **OFI proxy (Cont-Kukanov-Stoikov 2014 adapted)**: "
        "`ofi_bar = sign(close-open) * volume * |close-open|/range`. "
        "Persistent OFI = rolling sum over k=4 bars at train-time.\n"
        "- **VPIN proxy (Easley-López-O'Hara 2012 BVC variant)**: bar-clock "
        "`buy_vol = V * Φ(ret/σ)`, `|2*buy_vol - V|` summed over a 50-bar "
        "volume bucket, normalized by total volume. Veto when VPIN > 60th pct.\n"
        "- **Kyle 1985** adverse-selection: VPIN veto is the bar-grain analogue "
        "of Kyle's liquidity-demand scaling.\n"
        "- **Entry**: persistent_ofi >= 75th pct of train distribution AND "
        "vpin <= 60th pct AND realized-vol in normal band.\n"
        "- **Failure modes**: (a) gap opens distort OFI sign, (b) stablecoin-"
        "flash-crash days saturate VPIN, (c) weekend thin books.\n"
        f"- **prev_gain** = {prev_gain}; "
        f"{'no adjustment' if prev_gain is None or prev_gain >= 0 else 'tighten quantiles +5 pct'}.\n"
    )


# ---- Role 6: signal-engineer (the load-bearing one) ---------------------- #


def _load_train_bars(ctx: object) -> pd.DataFrame:
    """Load the train window as an OHLCV DataFrame indexed by ts_event."""
    handle = ctx.get_train_data()  # type: ignore[attr-defined]
    catalog = ParquetDataCatalog(str(handle.catalog_path))
    bars = catalog.bars(
        bar_types=[handle.instrument.bar_type],
        start=handle.start,
        end=handle.end,
    )
    if not bars:
        raise RuntimeError(f"No train bars for {handle.instrument.bar_type} in {handle.catalog_path}")

    rows = []
    for b in bars:
        rows.append(
            {
                "ts": int(b.ts_event),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.volume),
            }
        )
    df = pd.DataFrame(rows).set_index("ts").sort_index()
    logger.info("signal-engineer: loaded %d train bars", len(df))
    return df


def _compute_ofi_series(df: pd.DataFrame, k: int) -> pd.Series:
    """OFI bar-proxy + k-bar persistent OFI rolling sum."""
    rng = (df["high"] - df["low"]).clip(lower=1e-9)
    direction = np.sign(df["close"] - df["open"])
    ofi_bar = direction * df["volume"] * (df["close"] - df["open"]).abs() / rng
    return ofi_bar.rolling(window=k, min_periods=1).sum()


def _compute_vpin_series(df: pd.DataFrame, bucket_bars: int) -> pd.Series:
    """BVC-based VPIN bar-proxy over rolling volume bucket."""
    ret = df["close"].pct_change().fillna(0.0)
    sigma = ret.rolling(window=50, min_periods=10).std().bfill().clip(lower=1e-9)
    from scipy.stats import norm  # type: ignore[import-untyped]
    try:
        phi = pd.Series(norm.cdf(ret / sigma), index=df.index)
    except Exception:
        # Fallback if scipy not available: use logistic approx.
        z = ret / sigma
        phi = 1.0 / (1.0 + np.exp(-1.702 * z))
    buy_vol = df["volume"] * phi
    imbalance = (2.0 * buy_vol - df["volume"]).abs()
    vol_sum = df["volume"].rolling(window=bucket_bars, min_periods=1).sum()
    imb_sum = imbalance.rolling(window=bucket_bars, min_periods=1).sum()
    return imb_sum / vol_sum.clip(lower=1e-9)


def _signal_engineer(ctx: object, prev_gain: float | None) -> Thresholds:
    """Calibrate OFI / VPIN / RV thresholds from train bars."""
    df = _load_train_bars(ctx)
    ofi_series = _compute_ofi_series(df, TRAIN_OFI_K)
    vpin_series = _compute_vpin_series(df, VPIN_BUCKET_BARS)
    ret = df["close"].pct_change().dropna()
    rv_series = ret.rolling(window=20, min_periods=5).std().bfill()

    # Base quantiles (may be tightened on prev loss)
    tighten = prev_gain is not None and prev_gain < 0.0
    ofi_q = OFI_ENTRY_QUANTILE_BASE + (OFI_ENTRY_QUANTILE_TIGHTEN if tighten else 0.0)
    vpin_q = VPIN_PERMIT_QUANTILE_BASE - (VPIN_PERMIT_QUANTILE_TIGHTEN if tighten else 0.0)
    ofi_q = min(ofi_q, 0.95)
    vpin_q = max(vpin_q, 0.30)

    # ofi_entry: persistent-OFI distribution is signed — we gate on positive OFI,
    # so use quantile of positive-only tail.
    ofi_pos = ofi_series[ofi_series > 0]
    ofi_entry = float(ofi_pos.quantile(ofi_q)) if len(ofi_pos) > 0 else 0.0
    vpin_permit = float(vpin_series.quantile(vpin_q))
    rv_prior = float(rv_series.mean())
    rv_cap = float(rv_series.quantile(0.90))  # skip the top 10 % vol bars

    # Count how often all three train-window gates would fire as a sanity check.
    fires = (
        (ofi_series >= ofi_entry)
        & (vpin_series <= vpin_permit)
        & (rv_series.reindex(df.index).bfill() <= rv_cap)
    )
    fire_rate = float(fires.mean())
    logger.info(
        "signal-engineer: ofi_entry=%.4f vpin_permit=%.4f rv_prior=%.6f "
        "rv_cap=%.6f fire_rate=%.4f (tighten=%s)",
        ofi_entry,
        vpin_permit,
        rv_prior,
        rv_cap,
        fire_rate,
        tighten,
    )
    return Thresholds(
        ofi_entry=ofi_entry,
        vpin_permit=vpin_permit,
        rv_prior=rv_prior,
        rv_cap=rv_cap,
        ofi_k_bars=TRADE_OFI_K,  # trade-time k, not train-time k
        vpin_bucket_bars=VPIN_BUCKET_BARS,
        signal_fire_rate=fire_rate,
    )


# ---- Roles 2,3,4,5,7,8: deterministic pipeline --------------------------- #


def _hypothesis_generator(_ctx: object, _prev_gain: float | None) -> list[str]:
    """Deterministic — returns the list of proxy variants to keep in the pipeline."""
    return ["ofi_directional_weighted", "vpin_bvc_bar_clock", "rv_realized_20bar"]


def _critic(thresholds: Thresholds) -> list[str]:
    """Flag failure modes based on calibration output."""
    warnings: list[str] = []
    if thresholds.signal_fire_rate < MIN_SIGNAL_RATE:
        warnings.append(
            f"signal too sparse ({thresholds.signal_fire_rate:.4f} < {MIN_SIGNAL_RATE}) — "
            f"entry will rarely trigger in paper; consider loosening ofi_entry quantile"
        )
    if thresholds.signal_fire_rate > MAX_SIGNAL_RATE:
        warnings.append(
            f"signal too dense ({thresholds.signal_fire_rate:.4f} > {MAX_SIGNAL_RATE}) — "
            f"noise alias risk; consider tightening"
        )
    if thresholds.vpin_permit <= 0.05:
        warnings.append("vpin_permit unusually low — most bars flagged toxic")
    return warnings


def _regime_gater(thresholds: Thresholds) -> Thresholds:
    """Currently a pass-through — future hook for session / DOW filters."""
    return thresholds


def _risk_officer(
    thresholds: Thresholds,
    critic_warnings: list[str],
    iter_idx: int,
) -> dict[str, Any]:
    """Write runtime_rules.json and return the dict used to build StrategyConfig."""
    rules = {
        "ofi_entry_threshold": thresholds.ofi_entry,
        "ofi_k_bars": thresholds.ofi_k_bars,
        "vpin_permit_threshold": thresholds.vpin_permit,
        "vpin_bucket_bars": thresholds.vpin_bucket_bars,
        "rv_prior": thresholds.rv_prior,
        "rv_cap": thresholds.rv_cap,
        "stop_loss_pct": 0.01,
        "max_hold_bars": 3,
        "critic_warnings": critic_warnings,
        "train_signal_fire_rate": thresholds.signal_fire_rate,
    }
    iter_dir = ATTEMPTS_DIR / f"{iter_idx:03d}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "runtime_rules.json").write_text(json.dumps(rules, indent=2))
    (iter_dir / "thresholds.json").write_text(json.dumps(rules, indent=2))
    (TEAM_DIR / "runtime_rules.json").write_text(json.dumps(rules, indent=2))
    return rules


def _memory_keeper(ctx: object, iter_idx: int, rules: dict[str, Any]) -> None:
    """Append cross-round thesis to notes/cross_round.md."""
    NOTES_DIR.mkdir(exist_ok=True)
    cross_round = NOTES_DIR / "cross_round.md"
    round_idx = getattr(ctx, "round_index", None)
    prev_gain = getattr(ctx, "prev_gain", None)
    prev_lb = getattr(ctx, "prev_round_leaderboard", None)
    lb_note = ""
    if prev_lb is not None:
        lb_path = Path(prev_lb)
        if lb_path.exists():
            try:
                lb_text = lb_path.read_text()
                # Keep just the first 300 chars to avoid bloat.
                lb_note = f"\nLast round leaderboard excerpt: {lb_text[:300]!r}"
            except OSError:
                lb_note = ""
    stanza = (
        f"\n\n---\n"
        f"## round={round_idx} iter={iter_idx}\n"
        f"- prev_gain: {prev_gain}\n"
        f"- ofi_entry: {rules['ofi_entry_threshold']:.4f}\n"
        f"- vpin_permit: {rules['vpin_permit_threshold']:.4f}\n"
        f"- rv_cap: {rules['rv_cap']:.6f}\n"
        f"- fire_rate: {rules['train_signal_fire_rate']:.4f}\n"
        f"- critic: {rules['critic_warnings']}"
        f"{lb_note}\n"
    )
    if cross_round.exists():
        cross_round.write_text(cross_round.read_text() + stanza)
    else:
        cross_round.write_text("# cross_round.md\n" + stanza)


# --------------------------------------------------------------------------- #
# train(ctx)
# --------------------------------------------------------------------------- #


def train(ctx: object) -> tuple[type[TeamStrategy], TeamConfig]:
    """8-role microstructure pipeline — returns Strategy class + config.

    Flow:
      1. researcher        (LLM, cached)
      2. hypothesis-generator
      3. signal-engineer   (calibration on train bars)
      4. regime-gater
      5. critic
      6. risk-officer      (writes runtime_rules.json)
      7. memory-keeper     (appends to notes/cross_round.md)
      8. execution-trader  (builds StrategyConfig)
    """
    iter_idx = int(getattr(ctx, "iteration", 0))
    prev_gain = getattr(ctx, "prev_gain", None)

    NOTES_DIR.mkdir(exist_ok=True)
    ATTEMPTS_DIR.mkdir(exist_ok=True)
    (ATTEMPTS_DIR / f"{iter_idx:03d}").mkdir(parents=True, exist_ok=True)

    # 1. researcher (LLM, cached; graceful fallback to canned brief)
    _researcher(ctx, iter_idx)

    # 2. hypothesis-generator
    _hypothesis_generator(ctx, prev_gain)

    # 3. signal-engineer — calibrate thresholds from train window
    thresholds = _signal_engineer(ctx, prev_gain)

    # 4. regime-gater (pass-through for now)
    thresholds = _regime_gater(thresholds)

    # 5. critic
    warnings = _critic(thresholds)
    for w in warnings:
        logger.warning("critic: %s", w)

    # 6. risk-officer — writes runtime_rules.json, returns rule dict
    rules = _risk_officer(thresholds, warnings, iter_idx)

    # 7. memory-keeper
    _memory_keeper(ctx, iter_idx, rules)

    # 8. execution-trader — build Strategy + Config
    instrument = ctx.config.instrument  # type: ignore[attr-defined]
    cfg = TeamConfig(
        instrument_id=InstrumentId.from_str(instrument.symbol),
        bar_type=BarType.from_str(instrument.bar_type),
        trade_size=DEFAULT_TRADE_SIZE_BTC,
        ofi_entry_threshold=thresholds.ofi_entry,
        ofi_k_bars=thresholds.ofi_k_bars,
        vpin_permit_threshold=thresholds.vpin_permit,
        vpin_bucket_bars=thresholds.vpin_bucket_bars,
        rv_prior=thresholds.rv_prior,
        rv_cap=thresholds.rv_cap,
    )
    return TeamStrategy, cfg
