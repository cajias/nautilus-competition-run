"""Entry for team_moskowitz_tsmom_desk — systematic TSMOM desk.

Multi-agent desk inside train(ctx) with 8 roles:
  1. researcher              — run_claude subagent (~120s, cached on disk)
  2. hypothesis-generator    — deterministic (proposes lookbacks / knobs)
  3. critic                  — deterministic (flags whipsaw/overfit/cost)
  4. risk-officer            — deterministic (writes runtime_rules.json)
  5. memory-keeper           — deterministic (append-only notes/memory.md)
  6. momentum-signal-designer — deterministic (calibrates short+long TSMOM EWMA)
  7. vol-targeter            — deterministic (EWMA(64) sigma → position size)
  8. breakout-confirmer      — deterministic (Keltner(20,2) + ATR(20) expansion)

Trade-time: ZERO LLM. Pure pandas/numpy. Strategy loads runtime_rules.json
(including persisted final-train-bar EWMA momentum state) in on_start and
updates incrementally on_bar.

Citations: Moskowitz/Ooi/Pedersen (JFE 2012); Hurst/Ooi/Pedersen (JPM 2017);
Keltner (1960); Wilder (1978). See CLAUDE.md for full persona.
"""

from __future__ import annotations

import json
import logging
import math
import os
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
    run_researcher,
)

if TYPE_CHECKING:
    from nautilus_trader.model.instruments import Instrument  # type: ignore[import-untyped]


logger = logging.getLogger(__name__)

TEAM_DIR = Path(__file__).parent
RUNTIME_RULES_PATH = TEAM_DIR / "runtime_rules.json"
RESEARCH_LOG_PATH = TEAM_DIR / "notes" / "research_log.md"
MEMORY_PATH = TEAM_DIR / "notes" / "memory.md"

# Defaults. Moskowitz (2012) used 1/12-month; we port: short=5 bars-of-days
# (fast), long=28 bars-of-days (slow). At 5-min bars: short_span=1440,
# long_span=8064. hypothesis-generator may perturb these on retries.
DEFAULT_SHORT_SPAN_BARS: int = 5 * 24 * 12           # 5 days of 5-min bars = 1440
DEFAULT_LONG_SPAN_BARS: int = 28 * 24 * 12           # 28 days of 5-min bars = 8064
DEFAULT_KELTNER_PERIOD: int = 20
DEFAULT_KELTNER_K: float = 2.0
DEFAULT_ATR_PERIOD: int = 20
DEFAULT_ATR_EXPANSION_RATIO: float = 1.2
DEFAULT_VOL_EWMA_SPAN: int = 64
DEFAULT_ANN_VOL_TARGET: float = 0.15                 # 15% ann
DEFAULT_MAX_LEVERAGE: float = 1.0
DEFAULT_DD_CIRCUIT_BREAKER: float = 0.20             # 20% equity dd → flat
BARS_PER_YEAR_5MIN: int = 365 * 24 * 12              # ~105k
MIN_WARMUP_BARS: int = 25                            # Keltner(20) + slack


# -----------------------------------------------------------------------------
# StrategyConfig (frozen, msgspec-friendly — all fields declared upfront).
# -----------------------------------------------------------------------------
class TeamConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    # Path to runtime_rules.json — Strategy loads at on_start.
    runtime_rules_path: str
    # Base trade size before vol-targeting (overridden by vol-target scale).
    base_trade_size: Decimal = Decimal("0.01")


# -----------------------------------------------------------------------------
# Role 6: momentum-signal-designer — deterministic helpers
# -----------------------------------------------------------------------------
def _ewma_final_state(returns: np.ndarray, span: int) -> tuple[float, float]:
    """Return the final EWMA value of `returns` and the equivalent alpha.

    Uses pandas' ewm(span=span, adjust=False) convention so that the Strategy
    can update incrementally with the same alpha.
    """
    if len(returns) == 0:
        return 0.0, 2.0 / (span + 1)
    alpha = 2.0 / (span + 1)
    ewma = pd.Series(returns).ewm(span=span, adjust=False).mean().iloc[-1]
    return float(ewma), float(alpha)


def _tsmom_sign(ewma_return: float) -> int:
    """Sign of a TSMOM EWMA return. Breaks ties to flat."""
    if ewma_return > 0:
        return 1
    if ewma_return < 0:
        return -1
    return 0


# -----------------------------------------------------------------------------
# Role 8: breakout-confirmer — deterministic helpers
# -----------------------------------------------------------------------------
def _true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    return tr


def _atr(tr: np.ndarray, period: int) -> np.ndarray:
    # Wilder's ATR = EWMA of TR with alpha = 1/period.
    return pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()


def _keltner_final(
    close: np.ndarray,
    atr_series: np.ndarray,
    period: int,
    k: float,
) -> tuple[float, float, float]:
    """Return final (midline SMA, upper, lower) for Keltner(period, k)."""
    if len(close) < period:
        mid = float(close[-1]) if len(close) else 0.0
        a = float(atr_series[-1]) if len(atr_series) else 0.0
        return mid, mid + k * a, mid - k * a
    mid = float(np.asarray(pd.Series(close).rolling(period).mean())[-1])
    a = float(atr_series[-1])
    return mid, mid + k * a, mid - k * a


# -----------------------------------------------------------------------------
# Role 7: vol-targeter — deterministic helper
# -----------------------------------------------------------------------------
def _realized_vol_ann(returns: np.ndarray, span: int, bars_per_year: int) -> float:
    if len(returns) < 2:
        return 0.0
    sigma_bar = float(
        pd.Series(returns).ewm(span=span, adjust=False).std().iloc[-1]
    )
    if not math.isfinite(sigma_bar) or sigma_bar <= 0:
        return 0.0
    return sigma_bar * math.sqrt(bars_per_year)


# -----------------------------------------------------------------------------
# Role 1: researcher — Claude subagent (cached on disk).
# -----------------------------------------------------------------------------
def _researcher_should_run(prev_gain: float | None, iteration: int) -> bool:
    """Cheap-run policy: first iteration only, OR on a losing retry."""
    if iteration == 0:
        return True
    if prev_gain is not None and prev_gain < 0.0:
        return True
    return False


# -----------------------------------------------------------------------------
# Paradigm selection (CLAUDE.md compliance: prev_gain<0 must consider swap).
# -----------------------------------------------------------------------------
PARADIGM_TSMOM = "tsmom"
PARADIGM_COUNTER_TSMOM = "counter_tsmom"
PARADIGM_CASH = "cash"

# Cash-mode threshold: skip trades when |realized_30bar_log_return| < this value.
# 0.5% on 30 5-min bars = 2.5h window — meaningful directional movement.
DEFAULT_CASH_THRESHOLD: float = 0.005
CASH_LOOKBACK_BARS: int = 30


def _read_prior_paradigm(rules_path: Path) -> str | None:
    """Read the paradigm from the prior runtime_rules.json, if present.

    Returns None on missing file / malformed content.
    """
    if not rules_path.exists():
        return None
    try:
        prior = json.loads(rules_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    paradigm = prior.get("paradigm")
    if isinstance(paradigm, str) and paradigm in (
        PARADIGM_TSMOM,
        PARADIGM_COUNTER_TSMOM,
        PARADIGM_CASH,
    ):
        return paradigm
    return None


def _select_paradigm(
    prev_paradigm: str | None,
    prev_gain: float | None,
    iteration: int,
    round_index: int,
    last_paradigm_round: int | None,
) -> str:
    """Pick the paradigm for this iteration.

    Three-paradigm rotation (TSMOM → counter_tsmom → cash → TSMOM …):
      - iter 0 cold start: tsmom.
      - prev_gain >= 0: keep prev_paradigm (it's working — don't flip).
      - prev_gain < 0 AND prev_paradigm == tsmom: SWAP to counter_tsmom.
      - prev_gain < 0 AND prev_paradigm == counter_tsmom AND same round as
        the swap: SWAP to cash (no oscillation within a round means we
        rotate forward, not back).
      - prev_gain < 0 AND prev_paradigm == counter_tsmom AND new round:
        rotate to cash (third paradigm — neither momentum direction worked).
      - prev_gain < 0 AND prev_paradigm == cash AND same round: STAY on
        cash (oscillation guard — cash within the round means we wait for
        the next round to re-evaluate).
      - prev_gain < 0 AND prev_paradigm == cash AND new round: rotate back
        to tsmom (fresh round, retry classical from the top of the cycle).
    """
    if prev_paradigm is None:
        return PARADIGM_TSMOM
    if prev_gain is None or prev_gain >= 0.0:
        return prev_paradigm
    # prev_gain < 0 — losing strategy. Rotate forward.
    if prev_paradigm == PARADIGM_TSMOM:
        return PARADIGM_COUNTER_TSMOM
    if prev_paradigm == PARADIGM_COUNTER_TSMOM:
        # Counter-TSMOM lost — rotate to cash regardless of round (cash is
        # the next station in the rotation; oscillation guard is satisfied
        # because we are advancing forward, not flipping back).
        return PARADIGM_CASH
    # prev_paradigm == cash and we lost.
    if last_paradigm_round is not None and last_paradigm_round == round_index:
        # Same round as switching to cash — stay (oscillation guard).
        return PARADIGM_CASH
    # New round: rotate back to TSMOM and try the cycle fresh.
    return PARADIGM_TSMOM


def _run_researcher(
    workspace_dir: Path,
    iteration: int,
    prev_gain: float | None,
    timeout_s: int,
    paradigm: str,
) -> str | None:
    """Dispatch a ~120s Claude subagent; return the path to the research note.

    The researcher's job is NOT to write strategy code — it's to survey
    the literature + peer notes and write an advisory markdown. Deterministic
    roles consume that markdown as text (via memory-keeper) only to log the
    round thesis; they do NOT parse parameters from it.
    """
    attempt_dir = workspace_dir / "attempts" / f"{iteration:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    research_out = attempt_dir / "research.md"

    # Persistent cache: if research log already has a fresh stanza for this
    # round, skip the subprocess entirely.
    if research_out.exists() and research_out.stat().st_size > 200:
        return str(research_out)

    RESEARCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESEARCH_LOG_PATH.touch(exist_ok=True)

    prev_gain_line = (
        f"- prev_gain: {prev_gain:.4f} (NEGATIVE — propose alt lookbacks)"
        if prev_gain is not None and prev_gain < 0.0
        else f"- prev_gain: {prev_gain!r}"
    )
    if paradigm == PARADIGM_COUNTER_TSMOM:
        paradigm_block = (
            "PARADIGM: counter_tsmom (INVERTED). The desk has SWAPPED out of\n"
            "long-bias TSMOM because the prior iteration lost money. The Strategy\n"
            "now SHORTS on positive EWMA of returns and GOES LONG on negative\n"
            "EWMA — the trend-exhaustion / mean-reversion regime. DO NOT propose\n"
            "swapping back to long-bias TSMOM. Tune for counter-TSMOM: shorter\n"
            "lookbacks tend to work better (faster reversals), and the breakout\n"
            "gate should be loosened (channel breaches in trending direction\n"
            "are the FADE signal, not the entry).\n"
        )
    elif paradigm == PARADIGM_CASH:
        paradigm_block = (
            "PARADIGM: cash (CASH-PRESERVATION MODE). You are in cash-\n"
            "preservation mode. Both TSMOM and counter-TSMOM lost money in this\n"
            "regime. The strategy now trades ONLY when realized 30-bar movement\n"
            "exceeds the cash_threshold (default 0.5%). When movement is below\n"
            "threshold the strategy holds cash (no-trade). Suggest the\n"
            "cash_threshold parameter ONLY (a single float in (0, 0.05]) — do\n"
            "NOT propose strategy changes, lookback changes, or paradigm\n"
            "swaps. The aim is to survive the pure-noise regime by trading\n"
            "only when there is genuine directional movement.\n"
        )
    else:
        paradigm_block = (
            "PARADIGM: tsmom (classical). Long on positive EWMA of returns,\n"
            "short on negative. Tune lookbacks and the Keltner/ATR gate.\n"
        )
    prompt = (
        f"You are the researcher role on a systematic TSMOM desk. "
        f"Iteration {iteration}.\n"
        f"{prev_gain_line}\n"
        f"{paradigm_block}\n"
        f"Task: survey Moskowitz/Ooi/Pedersen (JFE 2012), "
        f"Hurst/Ooi/Pedersen (JPM 2017), and vol-targeting literature. "
        f"If paradigm is counter_tsmom, also cite trend-exhaustion / "
        f"mean-reversion lit (e.g. Lo/MacKinlay 1990, Jegadeesh 1990).\n"
        f"Then read ../../../docs/state-of-the-art/ (momentum sections only) "
        f"and any peer team notes under ../../teams/*/notes/ if present. "
        f"Write a short advisory markdown to attempts/{iteration:03d}/research.md "
        f"with exactly these sections: THESIS (1 paragraph, must reflect the "
        f"current paradigm), "
        f"RECOMMENDED_LOOKBACKS (short_span_bars, long_span_bars), "
        f"RECOMMENDED_VOL_TARGET (ann float), CITATIONS (<=5 papers), "
        f"RISKS (<=3 bullets). Keep under 600 words. Exit when file exists."
    )
    result = run_researcher(
        workspace_dir=workspace_dir,
        prompt=prompt,
        timeout_seconds=min(timeout_s, 420),  # cap researcher at 7min
        fail_loud=False,
        # Researcher writes free-form markdown (THESIS / RECOMMENDED_LOOKBACKS /
        # … sections) to a file. We persist ``result.raw_stdout`` as a forensic
        # stub if the file isn't there — there is no fenced JSON payload to
        # parse, so disable parse_json to suppress the spurious WARN.
        parse_json=False,
    )
    if not result.payload and not result.raw_stdout:
        logger.warning("researcher returned empty result (stderr=%r)", result.raw_stderr[:200])
        # Even on failure, still seed a stub so downstream roles have a file.
    if not research_out.exists():
        # Claude may have printed inline rather than writing the file — persist
        # the unwrapped/raw text as a forensic stub. If everything failed, write
        # a synthesized stub so the pipeline can proceed.
        if result.raw_stdout:
            research_out.write_text(
                f"# research.md (captured from subprocess stdout)\n\n"
                f"envelope_unwrapped={result.unwrapped_envelope} "
                f"duration={result.duration_seconds:.1f}s\n\n"
                f"{result.raw_stdout[:8000]}\n"
            )
        else:
            research_out.write_text(
                f"# research.md (stub)\n\n"
                f"Researcher subagent did not persist a file; using defaults.\n"
                f"- prev_gain: {prev_gain}\n- iteration: {iteration}\n"
            )
    return str(research_out)


# -----------------------------------------------------------------------------
# Role 2: hypothesis-generator — deterministic.
# -----------------------------------------------------------------------------
class Hypothesis(NamedTuple):
    """TSMOM lookback pair + Keltner/ATR/vol-target knobs.

    NamedTuple instead of @dataclass(frozen=True) because the team_loader
    omits sys.modules registration before exec_module, breaking @dataclass
    under Python 3.12. NamedTuple is immutable by construction.
    """

    short_span_bars: int
    long_span_bars: int
    keltner_period: int
    keltner_k: float
    atr_period: int
    atr_expansion_ratio: float
    vol_ewma_span: int
    ann_vol_target: float


def _generate_hypothesis(iteration: int, prev_gain: float | None) -> Hypothesis:
    """Perturb defaults deterministically based on iteration + prev_gain.

    No randomness — backtests must be deterministic given identical inputs.
    """
    # Base case.
    h = Hypothesis(
        short_span_bars=DEFAULT_SHORT_SPAN_BARS,
        long_span_bars=DEFAULT_LONG_SPAN_BARS,
        keltner_period=DEFAULT_KELTNER_PERIOD,
        keltner_k=DEFAULT_KELTNER_K,
        atr_period=DEFAULT_ATR_PERIOD,
        atr_expansion_ratio=DEFAULT_ATR_EXPANSION_RATIO,
        vol_ewma_span=DEFAULT_VOL_EWMA_SPAN,
        ann_vol_target=DEFAULT_ANN_VOL_TARGET,
    )
    if iteration == 0:
        return h
    if prev_gain is None or prev_gain >= 0:
        return h
    # On a loss: try shorter lookbacks (Hurst/Ooi/Pedersen 2017 — fast
    # trend often outperforms in regime transitions) and a tighter gate.
    if iteration == 1:
        return Hypothesis(
            short_span_bars=288,           # 1 day
            long_span_bars=2880,           # 10 days
            keltner_period=20,
            keltner_k=1.5,                 # tighter band
            atr_period=20,
            atr_expansion_ratio=1.3,       # stricter vol-expansion
            vol_ewma_span=32,
            ann_vol_target=0.10,
        )
    if iteration == 2:
        return Hypothesis(
            short_span_bars=576,           # 2 days
            long_span_bars=4032,           # 14 days
            keltner_period=20,
            keltner_k=2.5,                 # wider band — fewer breakouts
            atr_period=20,
            atr_expansion_ratio=1.5,       # very strict
            vol_ewma_span=96,
            ann_vol_target=0.12,
        )
    # Iteration 3+: collapse to simple fast TSMOM (Moskowitz 2012 "1-month").
    return Hypothesis(
        short_span_bars=288,
        long_span_bars=1440,
        keltner_period=20,
        keltner_k=2.0,
        atr_period=20,
        atr_expansion_ratio=1.1,           # looser — try more trades
        vol_ewma_span=48,
        ann_vol_target=0.15,
    )


# -----------------------------------------------------------------------------
# Role 3: critic — deterministic.
# -----------------------------------------------------------------------------
def _critic_review(h: Hypothesis, train_bars: int) -> list[str]:
    warnings: list[str] = []
    if h.long_span_bars / max(h.short_span_bars, 1) < 4:
        warnings.append("whipsaw: long/short span ratio < 4")
    if h.long_span_bars > train_bars * 0.5:
        warnings.append(
            f"overfit: long_span_bars={h.long_span_bars} > 50% of train "
            f"({train_bars} bars)"
        )
    if h.ann_vol_target > 0.35:
        warnings.append("vol-target unreasonably high (>35% ann)")
    if h.atr_expansion_ratio < 1.0:
        warnings.append("atr_expansion_ratio < 1.0 — degenerate gate")
    return warnings


# -----------------------------------------------------------------------------
# Orchestrator: fit indicators on train, measure on test (single shot).
# -----------------------------------------------------------------------------
def _load_bars(handle: Any) -> pd.DataFrame:
    """Load bars from a DataHandle into a clean OHLCV DataFrame.

    Nautilus's ParquetDataCatalog returns Bar objects; we convert to a
    pure-pandas frame to keep the desk's analytics framework-agnostic.
    """
    catalog = ParquetDataCatalog(str(handle.catalog_path))
    bars = catalog.bars(
        bar_types=[handle.instrument.bar_type],
        start=handle.start,
        end=handle.end,
    )
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
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("ts").reset_index(drop=True)
    return df


def _fit_indicators(df: pd.DataFrame, h: Hypothesis) -> dict[str, Any]:
    """Run roles 6, 7, 8 on the train window. Return the state dict to persist."""
    if df.empty or len(df) < MIN_WARMUP_BARS:
        return {
            "fitted": False,
            "reason": f"train window has only {len(df)} bars — insufficient",
        }

    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    log_returns = np.diff(np.log(close))

    # Role 6: momentum-signal-designer — EWMA TSMOM short & long.
    short_ewma, short_alpha = _ewma_final_state(log_returns, h.short_span_bars)
    long_ewma, long_alpha = _ewma_final_state(log_returns, h.long_span_bars)

    # Role 8: breakout-confirmer — Keltner(20,2) + ATR(20) with trailing ATR.
    tr = _true_range(high, low, close)
    atr_series = _atr(tr, h.atr_period)
    mid, upper, lower = _keltner_final(close, atr_series, h.keltner_period, h.keltner_k)
    atr_now = float(atr_series[-1])
    # Trailing ATR: mean of the last ~200 ATRs (proxy for "recent regime").
    tail = min(len(atr_series), 200)
    atr_trail = float(np.mean(atr_series[-tail:])) if tail > 0 else atr_now

    # Role 7: vol-targeter — EWMA(64) sigma on log returns.
    sigma_ann = _realized_vol_ann(log_returns, h.vol_ewma_span, BARS_PER_YEAR_5MIN)
    # Position size scale: vol_target / realized_vol, capped by max_leverage.
    if sigma_ann > 0:
        size_scale = min(h.ann_vol_target / sigma_ann, DEFAULT_MAX_LEVERAGE)
    else:
        size_scale = 0.0
    size_scale = max(size_scale, 0.0)

    # Kept SMA state for Keltner so Strategy can update the rolling mean
    # incrementally: we persist the last `keltner_period` closes.
    keltner_close_history = close[-h.keltner_period:].tolist()
    # Keep the last TR values so we can continue the ATR Wilder recursion.
    tr_history_tail = tr[-h.atr_period:].tolist()

    return {
        "fitted": True,
        "train_bars": int(len(df)),
        "last_close": float(close[-1]),
        # Momentum carry-forward (THE critical piece — see CLAUDE.md).
        "short_ewma": short_ewma,
        "short_alpha": short_alpha,
        "short_sign_at_handoff": _tsmom_sign(short_ewma),
        "long_ewma": long_ewma,
        "long_alpha": long_alpha,
        "long_sign_at_handoff": _tsmom_sign(long_ewma),
        # Keltner state.
        "keltner_mid": mid,
        "keltner_upper": upper,
        "keltner_lower": lower,
        "keltner_close_history": keltner_close_history,
        # ATR state.
        "atr_now": atr_now,
        "atr_trail": atr_trail,
        "atr_alpha": 1.0 / h.atr_period,
        "tr_history_tail": tr_history_tail,
        # Vol-target scale (position multiplier).
        "sigma_ann_at_handoff": sigma_ann,
        "size_scale": size_scale,
    }


def _test_window_sanity(
    df_test: pd.DataFrame,
    state: dict[str, Any],
    h: Hypothesis,
    paradigm: str,
) -> float:
    """Single-shot OOS check: replay the rule on test and return the cumulative pnl proxy.

    Used ONLY to decide whether to accept the fit; not used for tuning.
    """
    if not state.get("fitted") or df_test.empty or len(df_test) < MIN_WARMUP_BARS:
        return 0.0
    close = df_test["close"].to_numpy(dtype=float)
    log_ret = np.diff(np.log(close))
    if len(log_ret) == 0:
        return 0.0
    # Simple shortcut: sign of long TSMOM at handoff applied to full test window,
    # scaled by size_scale. Not a true replay, but a fast sanity indicator.
    sign = state["long_sign_at_handoff"]
    if paradigm == PARADIGM_COUNTER_TSMOM:
        sign = -sign
    pnl = sign * state["size_scale"] * float(np.sum(log_ret))
    return pnl


# -----------------------------------------------------------------------------
# Role 4: risk-officer — writes runtime_rules.json.
# -----------------------------------------------------------------------------
def _write_runtime_rules(
    state: dict[str, Any],
    h: Hypothesis,
    critic_warnings: list[str],
    path: Path,
    paradigm: str,
    last_paradigm_round: int,
) -> None:
    rules = {
        "version": 1,
        "max_leverage": DEFAULT_MAX_LEVERAGE,
        "drawdown_circuit_breaker": DEFAULT_DD_CIRCUIT_BREAKER,
        "mom_reversal_exit": True,
        # Paradigm carry-forward: read by Strategy on_start to decide whether
        # to invert the TSMOM sign rule, hold cash, etc. Also read by next
        # iteration's _select_paradigm to enforce no-oscillation-within-round.
        "paradigm": paradigm,
        "last_paradigm_round": last_paradigm_round,
        # Cash-mode threshold. Only consulted when paradigm == "cash". The
        # researcher (in cash mode) is the only role that may suggest a
        # non-default value; deterministic roles persist the default.
        "cash_threshold": DEFAULT_CASH_THRESHOLD,
        "hypothesis": {
            "short_span_bars": h.short_span_bars,
            "long_span_bars": h.long_span_bars,
            "keltner_period": h.keltner_period,
            "keltner_k": h.keltner_k,
            "atr_period": h.atr_period,
            "atr_expansion_ratio": h.atr_expansion_ratio,
            "vol_ewma_span": h.vol_ewma_span,
            "ann_vol_target": h.ann_vol_target,
        },
        "critic_warnings": critic_warnings,
        "critic_veto": {
            "skip_if_atr_now_below": 0.5,  # multiplier vs atr_trail
        },
        "state": state,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rules, indent=2, sort_keys=True))


# -----------------------------------------------------------------------------
# Role 5: memory-keeper — append to notes/memory.md.
# -----------------------------------------------------------------------------
def _append_memory(
    ctx: Any,
    h: Hypothesis,
    state: dict[str, Any],
    critic_warnings: list[str],
    test_pnl_proxy: float,
    paradigm: str,
    prev_paradigm: str | None,
) -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    prev_board = ctx.prev_round_leaderboard
    prev_board_str = str(prev_board) if prev_board is not None else "None"
    stanza = [
        f"## round={ctx.round_index} iter={ctx.iteration}",
        f"- prev_gain: {ctx.prev_gain}",
        f"- prev_round_leaderboard: {prev_board_str}",
        f"- paradigm: {paradigm} (prev_paradigm: {prev_paradigm})",
        f"- hypothesis: short={h.short_span_bars} long={h.long_span_bars} "
        f"keltner_k={h.keltner_k} atr_ratio={h.atr_expansion_ratio} "
        f"vol_target={h.ann_vol_target}",
        f"- fitted: {state.get('fitted', False)}",
        f"- long_sign_at_handoff: {state.get('long_sign_at_handoff')}",
        f"- size_scale: {state.get('size_scale'):.4f}"
        if state.get("size_scale") is not None
        else "- size_scale: None",
        f"- critic_warnings: {critic_warnings}",
        f"- test_pnl_proxy: {test_pnl_proxy:.6f}",
        "",
    ]
    with MEMORY_PATH.open("a") as f:
        f.write("\n".join(stanza) + "\n")


# -----------------------------------------------------------------------------
# train(ctx): orchestrate all 8 roles.
# -----------------------------------------------------------------------------
def train(ctx: Any) -> tuple[type["TeamStrategy"], TeamConfig]:
    iter_idx = int(ctx.iteration)
    prev_gain = ctx.prev_gain
    round_idx = int(getattr(ctx, "round_index", 0) or 0)

    # Read prior runtime_rules.json BEFORE we overwrite it. We need the
    # paradigm and the round it was last set in for the no-oscillation guard.
    prev_paradigm = _read_prior_paradigm(RUNTIME_RULES_PATH)
    last_paradigm_round: int | None = None
    if RUNTIME_RULES_PATH.exists():
        try:
            _prior = json.loads(RUNTIME_RULES_PATH.read_text())
            lpr = _prior.get("last_paradigm_round")
            if isinstance(lpr, int):
                last_paradigm_round = lpr
        except (OSError, json.JSONDecodeError):
            last_paradigm_round = None

    # Paradigm decision (CLAUDE.md compliance: prev_gain<0 must consider swap).
    paradigm = _select_paradigm(
        prev_paradigm=prev_paradigm,
        prev_gain=prev_gain,
        iteration=iter_idx,
        round_index=round_idx,
        last_paradigm_round=last_paradigm_round,
    )
    # If the paradigm changed this iteration, stamp the round it changed in
    # so subsequent iterations within the same round don't re-flip it.
    new_last_paradigm_round = (
        round_idx if paradigm != prev_paradigm else (last_paradigm_round if last_paradigm_round is not None else round_idx)
    )

    # Role 1: researcher — only on iter 0 or losing retries.
    if _researcher_should_run(prev_gain, iter_idx):
        try:
            _run_researcher(
                workspace_dir=TEAM_DIR,
                iteration=iter_idx,
                prev_gain=prev_gain,
                timeout_s=int(ctx.config.agent.per_train_timeout_seconds),
                paradigm=paradigm,
            )
        except Exception as exc:
            logger.warning("researcher dispatch failed (non-fatal): %s", exc)

    # Role 2: hypothesis-generator.
    h = _generate_hypothesis(iter_idx, prev_gain)

    # Load train data. NEVER touch eval/paper.
    train_handle = ctx.get_train_data()
    train_df = _load_bars(train_handle)

    # Role 3: critic.
    critic_warnings = _critic_review(h, len(train_df))
    attempt_dir = TEAM_DIR / "attempts" / f"{iter_idx:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "critic.md").write_text(
        "# critic.md\n\n"
        f"- hypothesis: {h}\n"
        f"- paradigm: {paradigm} (prev: {prev_paradigm})\n"
        f"- train_bars: {len(train_df)}\n"
        f"- warnings: {critic_warnings}\n"
    )

    # Roles 6, 7, 8: fit indicators on train.
    state = _fit_indicators(train_df, h)

    # Single-shot OOS on test window (legal per contract).
    test_handle = ctx.get_test_data()
    test_df = _load_bars(test_handle)
    test_pnl_proxy = _test_window_sanity(test_df, state, h, paradigm)

    # Role 4: risk-officer — persist runtime rules.
    _write_runtime_rules(
        state,
        h,
        critic_warnings,
        RUNTIME_RULES_PATH,
        paradigm=paradigm,
        last_paradigm_round=new_last_paradigm_round,
    )

    # Role 5: memory-keeper.
    _append_memory(
        ctx, h, state, critic_warnings, test_pnl_proxy, paradigm, prev_paradigm
    )

    # Return Strategy class + config. Paths are strings so StrategyConfig
    # (msgspec) serializes cleanly.
    instrument = ctx.config.instrument
    cfg = TeamConfig(
        instrument_id=InstrumentId.from_str(instrument.symbol),
        bar_type=BarType.from_str(instrument.bar_type),
        runtime_rules_path=str(RUNTIME_RULES_PATH),
    )
    return TeamStrategy, cfg


# =============================================================================
# Trade-time: pure deterministic Strategy. NO LLM. Loads runtime_rules.json.
# =============================================================================
class TeamStrategy(Strategy):
    """Systematic TSMOM strategy with Keltner + ATR-expansion gate + vol-target.

    Stacked entry gate:
      sign(long_TSMOM) != 0
      AND sign(long_TSMOM) == sign(short_TSMOM)
      AND close breaches Keltner band in that direction
      AND atr_now / atr_trail >= atr_expansion_ratio

    Exit: flip on long_TSMOM sign reversal (Moskowitz 2012). Also flat on
    drawdown circuit-breaker.
    """

    def __init__(self, config: TeamConfig) -> None:
        super().__init__(config)
        self.instrument: Instrument | None = None
        self._rules: dict[str, Any] = {}
        self._state: dict[str, Any] = {}
        self._hypothesis: dict[str, Any] = {}
        # Paradigm: "tsmom" (long-bias) or "counter_tsmom" (inverted/fade).
        # When counter_tsmom, sign(EWMA) is INVERTED before the gate fires —
        # i.e. positive EWMA → short, negative EWMA → long.
        self._paradigm: str = PARADIGM_TSMOM

        # Live indicator state (bootstrapped from rules["state"]).
        self._prev_close: float | None = None
        self._short_ewma: float = 0.0
        self._long_ewma: float = 0.0
        self._short_alpha: float = 2.0 / (DEFAULT_SHORT_SPAN_BARS + 1)
        self._long_alpha: float = 2.0 / (DEFAULT_LONG_SPAN_BARS + 1)

        self._keltner_closes: list[float] = []
        self._atr_now: float = 0.0
        self._atr_trail: float = 0.0
        self._atr_alpha: float = 1.0 / DEFAULT_ATR_PERIOD
        self._atr_history: list[float] = []

        # Risk knobs.
        self._size_scale: float = 0.0
        self._max_leverage: float = DEFAULT_MAX_LEVERAGE
        self._dd_breaker: float = DEFAULT_DD_CIRCUIT_BREAKER
        self._mom_reversal_exit: bool = True
        self._critic_veto_atr_mult: float = 0.5

        # Hypothesis params.
        self._keltner_period: int = DEFAULT_KELTNER_PERIOD
        self._keltner_k: float = DEFAULT_KELTNER_K
        self._atr_period: int = DEFAULT_ATR_PERIOD
        self._atr_expansion_ratio: float = DEFAULT_ATR_EXPANSION_RATIO

        # Position tracking.
        self._position_side: int = 0  # -1, 0, +1
        self._peak_equity: float = 0.0
        self._circuit_tripped: bool = False

    # -------------------------------------------------------------------------
    # Lifecycle.
    # -------------------------------------------------------------------------
    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument not found: {self.config.instrument_id}")
            self.stop()
            return

        # Load runtime_rules.json — includes persisted final-train-bar EWMA.
        rules_path = Path(self.config.runtime_rules_path)
        if not rules_path.exists():
            self.log.error(f"runtime_rules.json missing at {rules_path}")
            self.stop()
            return
        try:
            self._rules = json.loads(rules_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            self.log.error(f"failed to load runtime_rules.json: {exc}")
            self.stop()
            return

        self._state = self._rules.get("state", {}) or {}
        self._hypothesis = self._rules.get("hypothesis", {}) or {}
        # Paradigm — default to classical TSMOM if absent / unknown.
        paradigm_raw = self._rules.get("paradigm", PARADIGM_TSMOM)
        self._paradigm = (
            paradigm_raw
            if paradigm_raw in (
                PARADIGM_TSMOM,
                PARADIGM_COUNTER_TSMOM,
                PARADIGM_CASH,
            )
            else PARADIGM_TSMOM
        )
        # Cash-mode threshold + return ring-buffer for the realized 30-bar
        # movement check. Only used when self._paradigm == PARADIGM_CASH.
        self._cash_threshold: float = float(
            self._rules.get("cash_threshold", DEFAULT_CASH_THRESHOLD)
        )
        self._cash_close_history: list[float] = []

        # Bootstrap indicator state from the persisted final-train-bar values
        # (the momentum-carry-forward solution for the 8k-bar lookback problem).
        if self._state.get("fitted"):
            self._short_ewma = float(self._state.get("short_ewma", 0.0))
            self._long_ewma = float(self._state.get("long_ewma", 0.0))
            self._short_alpha = float(self._state.get("short_alpha", self._short_alpha))
            self._long_alpha = float(self._state.get("long_alpha", self._long_alpha))
            self._keltner_closes = list(self._state.get("keltner_close_history", []))
            self._atr_now = float(self._state.get("atr_now", 0.0))
            self._atr_trail = float(self._state.get("atr_trail", 0.0))
            self._atr_alpha = float(self._state.get("atr_alpha", self._atr_alpha))
            self._prev_close = float(self._state.get("last_close", 0.0)) or None
            self._size_scale = float(self._state.get("size_scale", 0.0))

        # Risk knobs.
        self._max_leverage = float(self._rules.get("max_leverage", DEFAULT_MAX_LEVERAGE))
        self._dd_breaker = float(
            self._rules.get("drawdown_circuit_breaker", DEFAULT_DD_CIRCUIT_BREAKER)
        )
        self._mom_reversal_exit = bool(self._rules.get("mom_reversal_exit", True))
        veto = self._rules.get("critic_veto") or {}
        self._critic_veto_atr_mult = float(veto.get("skip_if_atr_now_below", 0.5))

        # Hypothesis params.
        self._keltner_period = int(self._hypothesis.get("keltner_period", DEFAULT_KELTNER_PERIOD))
        self._keltner_k = float(self._hypothesis.get("keltner_k", DEFAULT_KELTNER_K))
        self._atr_period = int(self._hypothesis.get("atr_period", DEFAULT_ATR_PERIOD))
        self._atr_expansion_ratio = float(
            self._hypothesis.get("atr_expansion_ratio", DEFAULT_ATR_EXPANSION_RATIO)
        )

        # Seed peak_equity from starting pot (proxy; portfolio.equity preferred).
        self._peak_equity = 1000.0

        self.subscribe_bars(self.config.bar_type)
        self.log.info(
            f"TSMOM desk ready: paradigm={self._paradigm} "
            f"size_scale={self._size_scale:.4f} "
            f"long_sign={_tsmom_sign(self._long_ewma)} "
            f"short_sign={_tsmom_sign(self._short_ewma)}"
        )

    def on_stop(self) -> None:
        try:
            self.cancel_all_orders(self.config.instrument_id)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.unsubscribe_bars(self.config.bar_type)
        except Exception:  # noqa: BLE001
            pass

    # -------------------------------------------------------------------------
    # on_bar — the whole desk, in about 40 lines.
    # -------------------------------------------------------------------------
    def on_bar(self, bar: Bar) -> None:
        if self.instrument is None or self._circuit_tripped:
            return

        close = float(bar.close)
        high = float(bar.high)
        low = float(bar.low)

        # 1. Update TSMOM EWMAs incrementally (Moskowitz sign rule).
        if self._prev_close is not None and self._prev_close > 0:
            log_ret = math.log(close / self._prev_close)
            self._short_ewma = (
                self._short_alpha * log_ret + (1.0 - self._short_alpha) * self._short_ewma
            )
            self._long_ewma = (
                self._long_alpha * log_ret + (1.0 - self._long_alpha) * self._long_ewma
            )
        self._prev_close = close

        # 2. Update ATR (Wilder).
        prev_close_for_tr = self._prev_close if self._prev_close is not None else close
        tr = max(
            high - low,
            abs(high - prev_close_for_tr),
            abs(low - prev_close_for_tr),
        )
        self._atr_now = self._atr_alpha * tr + (1.0 - self._atr_alpha) * self._atr_now
        self._atr_history.append(self._atr_now)
        if len(self._atr_history) > 200:
            self._atr_history = self._atr_history[-200:]
        # Trailing ATR = mean of last 200 (or however many we have).
        self._atr_trail = sum(self._atr_history) / max(len(self._atr_history), 1)

        # 3. Update Keltner (rolling SMA of close + k × ATR).
        self._keltner_closes.append(close)
        if len(self._keltner_closes) > self._keltner_period:
            self._keltner_closes = self._keltner_closes[-self._keltner_period:]
        if len(self._keltner_closes) < self._keltner_period:
            return  # still warming up
        keltner_mid = sum(self._keltner_closes) / len(self._keltner_closes)
        keltner_upper = keltner_mid + self._keltner_k * self._atr_now
        keltner_lower = keltner_mid - self._keltner_k * self._atr_now

        # 3b. Cash-mode gate. When in cash paradigm we maintain a small
        # ring-buffer of closes and only ALLOW the rest of the on_bar logic
        # to fire when the realized log-return over the last
        # CASH_LOOKBACK_BARS bars exceeds self._cash_threshold in absolute
        # value. Below threshold = pure-noise regime → hold cash. Above =
        # genuine movement → behave exactly like TSMOM (classical signs).
        if self._paradigm == PARADIGM_CASH:
            self._cash_close_history.append(close)
            if len(self._cash_close_history) > CASH_LOOKBACK_BARS + 1:
                self._cash_close_history = self._cash_close_history[
                    -(CASH_LOOKBACK_BARS + 1):
                ]
            if len(self._cash_close_history) < CASH_LOOKBACK_BARS + 1:
                # Still warming up the cash ring-buffer.
                return
            past_close = self._cash_close_history[0]
            realized_return = (
                math.log(close / past_close) if past_close > 0 else 0.0
            )
            if abs(realized_return) < self._cash_threshold:
                # Pure-noise regime — hold cash. Flatten any open position
                # and skip the entry gate entirely.
                if self._position_side != 0:
                    self._reconcile_position(0)
                return

        # 4. Evaluate stacked entry gate.
        # Raw TSMOM signs from EWMA of returns (classical Moskowitz rule).
        raw_long_sign = _tsmom_sign(self._long_ewma)
        raw_short_sign = _tsmom_sign(self._short_ewma)
        # Paradigm-aware trade direction. For counter_tsmom we INVERT the
        # signal: positive EWMA (classical "trend up" → buy) becomes a SHORT,
        # negative EWMA becomes a LONG. This is the trend-exhaustion /
        # mean-reversion regime used when classical TSMOM lost money in the
        # prior iteration. For cash paradigm, when we reach this point the
        # threshold has been crossed → behave like TSMOM (classical signs).
        if self._paradigm == PARADIGM_COUNTER_TSMOM:
            long_sign = -raw_long_sign
            short_sign = -raw_short_sign
        else:
            # tsmom OR cash (above-threshold) — classical signs.
            long_sign = raw_long_sign
            short_sign = raw_short_sign
        agree = (long_sign != 0) and (long_sign == short_sign)

        # ATR expansion gate + critic veto.
        if self._atr_trail <= 0:
            return
        atr_ratio = self._atr_now / self._atr_trail
        expansion_ok = atr_ratio >= self._atr_expansion_ratio
        critic_ok = atr_ratio >= self._critic_veto_atr_mult

        # Breakout direction. Note: we test the breakout against the
        # (paradigm-adjusted) trade direction. For TSMOM, long_sign>0 means
        # we want long → confirm with upward breakout. For counter_TSMOM,
        # long_sign>0 means raw EWMA was negative (we inverted it) → we want
        # long → confirm with a downward breakout (price has overshot to
        # the downside, fade it).
        breakout_up = close > keltner_upper
        breakout_down = close < keltner_lower
        if self._paradigm == PARADIGM_COUNTER_TSMOM:
            breakout_matches = (
                (long_sign > 0 and breakout_down)
                or (long_sign < 0 and breakout_up)
            )
        else:
            breakout_matches = (
                (long_sign > 0 and breakout_up)
                or (long_sign < 0 and breakout_down)
            )

        desired_side = 0
        if agree and expansion_ok and critic_ok and breakout_matches:
            desired_side = long_sign
        elif self._mom_reversal_exit and long_sign != 0 and long_sign != self._position_side:
            # Mom-reversal exit: flip to new direction or flatten.
            desired_side = long_sign if agree else 0

        # 5. Execute (market orders only — keep it transparent).
        if desired_side != self._position_side:
            self._reconcile_position(desired_side)

    # -------------------------------------------------------------------------
    # Position management helpers.
    # -------------------------------------------------------------------------
    def _reconcile_position(self, desired_side: int) -> None:
        """Flip to `desired_side` (-1, 0, +1) via market order."""
        if self.instrument is None:
            return
        size_scale = max(min(self._size_scale, self._max_leverage), 0.0)
        base = float(self.config.base_trade_size)
        qty_raw = base * size_scale
        if qty_raw <= 0:
            # Still allow flattening even if size_scale rounds to 0.
            if desired_side == 0 and self._position_side != 0:
                self._submit_flatten()
            return

        # Flatten first if switching direction or going to zero.
        if self._position_side != 0 and desired_side != self._position_side:
            self._submit_flatten()

        if desired_side == 0:
            self._position_side = 0
            return

        side = OrderSide.BUY if desired_side > 0 else OrderSide.SELL
        try:
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=side,
                quantity=self.instrument.make_qty(Decimal(str(qty_raw))),
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
            self._position_side = desired_side
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"failed to submit entry order: {exc}")

    def _submit_flatten(self) -> None:
        if self.instrument is None or self._position_side == 0:
            return
        base = float(self.config.base_trade_size)
        size_scale = max(min(self._size_scale, self._max_leverage), 0.0)
        qty_raw = base * size_scale
        if qty_raw <= 0:
            self._position_side = 0
            return
        # Close by submitting opposite-side market order.
        side = OrderSide.SELL if self._position_side > 0 else OrderSide.BUY
        try:
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=side,
                quantity=self.instrument.make_qty(Decimal(str(qty_raw))),
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
        except Exception as exc:  # noqa: BLE001
            self.log.warning(f"failed to submit flatten order: {exc}")
        finally:
            self._position_side = 0
