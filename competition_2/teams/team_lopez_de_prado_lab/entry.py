"""entry.py — team_lopez_de_prado_lab.

A 9-role quantitative research lab in the tradition of Marcos López de
Prado's *Advances in Financial Machine Learning* (AFML, 2018). ONE role
(`researcher`) runs as a Claude subprocess via
``nautilus_competition.agent_runner.run_claude``; the other 8 roles are
deterministic Python functions invoked in-process. See ``CLAUDE.md``.

Roles (order of invocation inside ``train``):

1. ``memory-keeper``     (prelude — load prior research_log / failed_hypotheses)
2. ``researcher``        (Claude subprocess, cached per-iter)
3. ``hypothesis-generator``
4. ``primary-signal-designer``
5. ``label-curator``     (AFML Ch. 3 — triple-barrier labeling, TRIMMED)
6. ``meta-model-builder`` (sklearn MLPClassifier → fallback GBM)
7. ``cv-validator``      (AFML Ch. 7 — CPCV with embargo ≥ H)
8. ``critic``            (leakage + overfit checks, may VETO)
9. ``risk-officer``      (writes runtime_rules.json — meta-conf threshold, dd cap)
10. ``memory-keeper``    (postlude — append ledger)
11. ``return`` ``(LdpLabStrategy, LdpLabConfig)``.

Trade-time: ``LdpLabStrategy`` loads ``meta_model.joblib`` +
``runtime_rules.json`` in ``on_start``; enforces meta-confidence veto,
drawdown cap, position cap in ``on_bar``. NO LLM at trade time.
"""

from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from nautilus_trader.config import StrategyConfig  # type: ignore[import-untyped]
from nautilus_trader.model.data import Bar, BarType  # type: ignore[import-untyped]
from nautilus_trader.model.enums import OrderSide, TimeInForce  # type: ignore[import-untyped]
from nautilus_trader.model.identifiers import InstrumentId  # type: ignore[import-untyped]
from nautilus_trader.trading.strategy import Strategy  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from nautilus_trader.model.instruments import Instrument  # type: ignore[import-untyped]


TEAM_DIR = Path(__file__).parent
NOTES_DIR = TEAM_DIR / "notes"
RESEARCH_LOG = NOTES_DIR / "research_log.md"
ITERATION_LEDGER = NOTES_DIR / "iteration_ledger.md"
FAILED_HYPOTHESES = NOTES_DIR / "failed_hypotheses.md"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strategy-side config + class (trade-time, pure Python, NO LLM).
# ---------------------------------------------------------------------------


class LdpLabConfig(StrategyConfig, frozen=True):
    """Strategy config — paths point at per-iter artifacts produced by ``train``."""

    instrument_id: InstrumentId
    bar_type: BarType
    meta_model_path: str
    feature_list_path: str
    runtime_rules_path: str
    primary_signal_path: str
    trade_size_usd: Decimal = Decimal("250.0")  # before position-size cap
    lookback: int = 48


class LdpLabStrategy(Strategy):
    """Meta-labeling strategy: primary-signal picks side, meta-model gates trade.

    Trade-time logic:
      1. Maintain a rolling close-price buffer of length ``lookback``.
      2. Primary signal computes direction ``+1 / 0 / -1`` from buffer.
      3. Meta-model predicts ``p_win`` from feature row.
      4. If ``p_win < meta_confidence_threshold`` → SKIP (no order).
      5. If running drawdown > ``drawdown_cap_pct`` → HALT for remainder.
      6. Else submit market order sized at ``max_position_size_pct * equity``.
    """

    def __init__(self, config: LdpLabConfig) -> None:
        super().__init__(config)
        self.instrument: Instrument | None = None
        self._meta_model: Any = None
        self._feature_names: list[str] = []
        self._primary_signal: dict[str, Any] = {}
        self._rules: dict[str, Any] = {}
        self._price_buf: list[float] = []
        self._equity_peak: float = 0.0
        self._halted: bool = False
        self._in_position_side: int = 0  # 0 / +1 / -1

    # ---- lifecycle ------------------------------------------------------

    def on_start(self) -> None:  # noqa: D401 — framework override
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument not found: {self.config.instrument_id}")
            self.stop()
            return

        try:
            import joblib

            self._meta_model = joblib.load(self.config.meta_model_path)
            self._feature_names = json.loads(
                Path(self.config.feature_list_path).read_text()
            )
            self._primary_signal = json.loads(
                Path(self.config.primary_signal_path).read_text()
            )
            self._rules = json.loads(Path(self.config.runtime_rules_path).read_text())
        except Exception as exc:  # noqa: BLE001 — load failure = halt
            self.log.error(f"Failed to load ML artifacts: {exc}")
            self._halted = True

        self.subscribe_bars(self.config.bar_type)

    def on_stop(self) -> None:  # noqa: D401
        try:
            self.cancel_all_orders(self.config.instrument_id)
            self.unsubscribe_bars(self.config.bar_type)
        except Exception:  # noqa: BLE001
            pass

    # ---- per-bar --------------------------------------------------------

    def on_bar(self, bar: Bar) -> None:  # noqa: D401 — framework override
        if self._halted or self.instrument is None or self._meta_model is None:
            return

        price = float(bar.close)
        self._price_buf.append(price)
        if len(self._price_buf) > self.config.lookback * 2:
            self._price_buf = self._price_buf[-self.config.lookback * 2 :]

        if len(self._price_buf) < self.config.lookback:
            return  # warm-up

        # Drawdown gate (hard veto).
        equity = self._estimate_equity(price)
        if equity > self._equity_peak:
            self._equity_peak = equity
        if self._equity_peak > 0:
            dd = 1.0 - equity / self._equity_peak
            if dd > float(self._rules.get("drawdown_cap_pct", 0.10)):
                self.log.warning(
                    f"Drawdown {dd:.3f} > cap {self._rules['drawdown_cap_pct']:.3f} — HALT"
                )
                self._halted = True
                self._flatten()
                return

        # Primary signal → direction.
        side = _compute_primary_side(
            buf=self._price_buf,
            spec=self._primary_signal,
        )
        if side == 0:
            return

        # Feature row → meta-model → p_win.
        features = _compute_features(self._price_buf, side, self._feature_names)
        if features is None:
            return
        try:
            proba = self._meta_model.predict_proba(features.reshape(1, -1))[0]
            # sklearn convention: classes_ sorted. We fit with y ∈ {0, 1} where 1=win.
            # Look up probability of class "1" robustly.
            classes = list(getattr(self._meta_model, "classes_", [0, 1]))
            p_win = float(proba[classes.index(1)]) if 1 in classes else float(proba[-1])
        except Exception as exc:  # noqa: BLE001
            self.log.error(f"Meta-model predict failed: {exc}")
            return

        threshold = float(self._rules.get("meta_confidence_threshold", 0.55))
        if p_win < threshold:
            return  # SKIP low-conviction trade

        # Position cap + order.
        cap_pct = float(self._rules.get("max_position_size_pct", 0.25))
        notional = min(float(self.config.trade_size_usd), cap_pct * max(equity, 1.0))
        qty_raw = notional / price if price > 0 else 0.0
        if qty_raw <= 0:
            return

        # Flip position if side changed.
        if self._in_position_side != 0 and self._in_position_side != side:
            self._flatten()

        try:
            qty = self.instrument.make_qty(Decimal(str(round(qty_raw, 6))))
        except Exception as exc:  # noqa: BLE001
            self.log.error(f"make_qty failed for {qty_raw}: {exc}")
            return

        order_side = OrderSide.BUY if side > 0 else OrderSide.SELL
        try:
            order = self.order_factory.market(
                instrument_id=self.config.instrument_id,
                order_side=order_side,
                quantity=qty,
                time_in_force=TimeInForce.GTC,
            )
            self.submit_order(order)
            self._in_position_side = side
        except Exception as exc:  # noqa: BLE001
            self.log.error(f"submit_order failed: {exc}")

    # ---- helpers --------------------------------------------------------

    def _estimate_equity(self, price: float) -> float:
        """Best-effort equity estimate from cache.portfolio balances.

        Falls back to 1.0 so the peak-tracker initializes on first call.
        """
        try:
            if self.portfolio is not None:
                accounts = self.portfolio.accounts()
                if accounts:
                    for acct in accounts:
                        bals = acct.balances_total()
                        if bals:
                            total = sum(float(b.as_double()) for b in bals.values())
                            if total > 0:
                                return total
        except Exception:  # noqa: BLE001
            pass
        return max(self._equity_peak, 1.0)

    def _flatten(self) -> None:
        try:
            self.close_all_positions(self.config.instrument_id)
        except Exception:  # noqa: BLE001
            pass
        self._in_position_side = 0


# ---------------------------------------------------------------------------
# Trade-time signal + feature helpers (pure Python).
# ---------------------------------------------------------------------------


def _compute_primary_side(buf: list[float], spec: dict[str, Any]) -> int:
    """Primary-signal direction: momentum z-score by default."""
    lookback = int(spec.get("lookback", 48))
    if len(buf) < lookback + 1:
        return 0
    window = np.asarray(buf[-(lookback + 1) :], dtype=float)
    rets = np.diff(window) / np.maximum(window[:-1], 1e-9)
    mu = float(rets.mean())
    sd = float(rets.std(ddof=1)) if len(rets) > 1 else 0.0
    if sd < 1e-9:
        return 0
    z = mu / sd * np.sqrt(len(rets))
    thr = float(spec.get("z_threshold", 0.5))
    family = spec.get("family", "momentum")
    if family == "momentum":
        if z > thr:
            return 1
        if z < -thr:
            return -1
        return 0
    if family == "mean_reversion":
        if z > thr:
            return -1
        if z < -thr:
            return 1
        return 0
    return 0


def _compute_features(
    buf: list[float], primary_side: int, feature_names: list[str]
) -> np.ndarray | None:
    """Compute feature row matching ``feature_names`` order.

    Features are simple, strictly-past-looking; matched to the same code
    path used during training (see ``_build_feature_matrix``).
    """
    if len(buf) < 50:
        return None
    arr = np.asarray(buf[-96:], dtype=float)
    rets = np.diff(arr) / np.maximum(arr[:-1], 1e-9)
    if len(rets) < 48:
        return None

    feat_map = {
        "ret_1": float(rets[-1]),
        "ret_6": float(rets[-6:].mean()),
        "ret_24": float(rets[-24:].mean()),
        "ret_48": float(rets[-48:].mean()),
        "vol_6": float(rets[-6:].std(ddof=1)) if len(rets[-6:]) > 1 else 0.0,
        "vol_24": float(rets[-24:].std(ddof=1)) if len(rets[-24:]) > 1 else 0.0,
        "vol_48": float(rets[-48:].std(ddof=1)) if len(rets[-48:]) > 1 else 0.0,
        "z_24": _zscore(rets, 24),
        "z_48": _zscore(rets, 48),
        "primary_side": float(primary_side),
    }
    try:
        return np.asarray([feat_map[name] for name in feature_names], dtype=float)
    except KeyError:
        return None


def _zscore(rets: np.ndarray, window: int) -> float:
    if len(rets) < window:
        return 0.0
    w = rets[-window:]
    sd = float(w.std(ddof=1)) if len(w) > 1 else 0.0
    if sd < 1e-9:
        return 0.0
    return float(w.mean() / sd * np.sqrt(window))


# ---------------------------------------------------------------------------
# Train-time: 9-role orchestration.
# ---------------------------------------------------------------------------


@dataclass
class _Artifacts:
    attempt_dir: Path
    research_md: Path
    hypothesis_json: Path
    primary_signal_json: Path
    labels_parquet: Path
    meta_model_joblib: Path
    feature_list_json: Path
    cv_report_json: Path
    critique_md: Path
    runtime_rules_json: Path

    @classmethod
    def for_iter(cls, iter_idx: int) -> _Artifacts:
        d = TEAM_DIR / "attempts" / f"{iter_idx:03d}"
        d.mkdir(parents=True, exist_ok=True)
        return cls(
            attempt_dir=d,
            research_md=d / "research.md",
            hypothesis_json=d / "hypothesis.json",
            primary_signal_json=d / "primary_signal.json",
            labels_parquet=d / "labels.parquet",
            meta_model_joblib=d / "meta_model.joblib",
            feature_list_json=d / "feature_list.json",
            cv_report_json=d / "cv_report.json",
            critique_md=d / "critique.md",
            runtime_rules_json=d / "runtime_rules.json",
        )


# ---- Role 1/10: memory-keeper ---------------------------------------------


def _memory_keeper_prelude(ctx: Any) -> dict[str, Any]:
    """Load persistent notes; surface last failure if prev_gain < 0."""
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    for f in (RESEARCH_LOG, ITERATION_LEDGER, FAILED_HYPOTHESES):
        if not f.exists():
            f.write_text(f"# {f.name}\n\nCreated {datetime.now(timezone.utc).isoformat()}\n\n")

    prior_log = RESEARCH_LOG.read_text()
    prior_failures = FAILED_HYPOTHESES.read_text()
    last_leaderboard_snippet = ""
    if ctx.prev_round_leaderboard is not None:
        try:
            lb_path = Path(ctx.prev_round_leaderboard)
            if lb_path.exists():
                last_leaderboard_snippet = lb_path.read_text()[:2000]
        except Exception:  # noqa: BLE001
            pass

    return {
        "prior_log": prior_log[-4000:],  # tail
        "prior_failures": prior_failures[-2000:],
        "prev_leaderboard": last_leaderboard_snippet,
        "prev_gain": ctx.prev_gain,
        "iteration": ctx.iteration,
        "round_index": ctx.round_index,
    }


def _memory_keeper_postlude(
    ctx: Any,
    artifacts: _Artifacts,
    hypothesis: dict[str, Any],
    cv_report: dict[str, Any],
    critique: dict[str, Any],
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    entry = (
        f"\n## round={ctx.round_index} iter={ctx.iteration} @ {ts}\n"
        f"- hypothesis: {hypothesis.get('summary', '?')}\n"
        f"- primary_family: {hypothesis.get('primary', {}).get('family', '?')}\n"
        f"- meta_arch: {hypothesis.get('meta', {}).get('arch', '?')}\n"
        f"- cv_auc: {cv_report.get('auc', '?')}\n"
        f"- cv_brier: {cv_report.get('brier', '?')}\n"
        f"- critic_ok: {not critique.get('vetoed', False)}\n"
        f"- prev_gain: {ctx.prev_gain}\n"
    )
    with RESEARCH_LOG.open("a") as fh:
        fh.write(entry)
    with ITERATION_LEDGER.open("a") as fh:
        fh.write(entry)
    if critique.get("vetoed", False):
        with FAILED_HYPOTHESES.open("a") as fh:
            fh.write(
                f"\n## round={ctx.round_index} iter={ctx.iteration}\n"
                f"- hypothesis: {hypothesis.get('summary', '?')}\n"
                f"- veto_reason: {critique.get('veto_reason', '?')}\n"
            )


# ---- Role 2: researcher (Claude subprocess) -------------------------------


def _researcher(ctx: Any, artifacts: _Artifacts, memory: dict[str, Any]) -> str:
    """Invoke Claude subprocess; cache output to ``research.md`` and log tail."""
    if artifacts.research_md.exists() and artifacts.research_md.stat().st_size > 0:
        logger.info("researcher: cached research.md found, skipping subprocess")
        return artifacts.research_md.read_text()

    prev_gain_hint = ""
    if memory["prev_gain"] is not None and memory["prev_gain"] < 0.0:
        prev_gain_hint = (
            f"\n\nPREVIOUS ITERATION FAILED. prev_gain={memory['prev_gain']:.4f}. "
            f"Recent failed hypotheses:\n{memory['prior_failures']}\n"
            f"PIVOT: propose a different primary-signal family or meta architecture."
        )

    leaderboard_hint = ""
    if memory["prev_leaderboard"]:
        leaderboard_hint = (
            f"\n\nPrevious round leaderboard (summary only, do NOT copy teams):\n"
            f"{memory['prev_leaderboard'][:1200]}"
        )

    prompt = (
        "You are the RESEARCHER role for team_lopez_de_prado_lab. "
        "Produce a ~250-word research.md for this iteration. "
        "Inputs: AFML 2018 (triple-barrier, meta-labeling, CPCV). "
        "Output format: markdown with sections: "
        "# Thesis\n# Primary signal (family: momentum|mean_reversion|breakout, lookback, z_threshold)\n"
        "# Meta-model (arch: mlp|gbm, rationale)\n# Risk (dd cap %, pos cap %, meta_conf threshold)\n"
        "# References (cite AFML chapters).\n\n"
        f"Round={ctx.round_index} Iter={ctx.iteration}.{prev_gain_hint}{leaderboard_hint}\n\n"
        f"Prior research log tail:\n{memory['prior_log'][-1500:]}\n\n"
        f"Write ONLY to: {artifacts.research_md}"
    )

    try:
        from nautilus_competition.agent_runner import run_claude  # type: ignore

        timeout_s = min(180, int(getattr(ctx.config.agent, "per_train_timeout_seconds", 600)) // 3)
        result = run_claude(
            workspace_dir=TEAM_DIR,
            prompt=prompt,
            command=list(getattr(ctx.config.agent, "command", ["claude", "--print", "--output-format", "json"])),
            timeout_seconds=timeout_s,
        )
        if result.returncode == 0 and not artifacts.research_md.exists():
            # subprocess may have printed the answer rather than writing — capture it.
            artifacts.research_md.write_text(result.stdout[:8000])
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"researcher subprocess failed, using fallback: {exc}")

    if not artifacts.research_md.exists() or artifacts.research_md.stat().st_size == 0:
        # Deterministic fallback so train() never wedges on subprocess failure.
        artifacts.research_md.write_text(_fallback_research(memory))

    return artifacts.research_md.read_text()


def _fallback_research(memory: dict[str, Any]) -> str:
    prev_gain = memory["prev_gain"]
    family = "momentum"
    if prev_gain is not None and prev_gain < 0.0:
        # rotate family deterministically on failure
        family = ["mean_reversion", "momentum", "breakout"][memory["iteration"] % 3]
    return (
        "# Thesis\n"
        "Trend-following with meta-labeling drawdown suppression.\n\n"
        "# Primary signal\n"
        f"family: {family}\n"
        "lookback: 48\n"
        "z_threshold: 0.5\n\n"
        "# Meta-model\n"
        "arch: mlp\n"
        "rationale: AFML 3.6 — predict win-probability of primary-signal trades.\n\n"
        "# Risk\n"
        "dd_cap_pct: 0.10\n"
        "pos_cap_pct: 0.25\n"
        "meta_conf_threshold: 0.55\n\n"
        "# References\n"
        "AFML Ch. 3 (labeling), Ch. 7 (CPCV), Ch. 8 (feature importance).\n"
    )


# ---- Role 3: hypothesis-generator -----------------------------------------


def _hypothesis_generator(research_text: str, ctx: Any) -> dict[str, Any]:
    """Parse research.md into a structured hypothesis.

    Deterministic text extraction — no LLM.
    """
    text = research_text.lower()
    if "mean_reversion" in text or "mean-reversion" in text:
        family = "mean_reversion"
    elif "breakout" in text:
        family = "breakout"
    else:
        family = "momentum"

    arch = "gbm" if "gbm" in text or "gradient" in text else "mlp"

    # If prev_gain < 0, tighten meta-confidence threshold.
    base_thr = 0.55
    if ctx.prev_gain is not None and ctx.prev_gain < 0.0:
        base_thr = min(0.70, base_thr + 0.05 * min(ctx.iteration, 3))

    return {
        "summary": f"{family} primary + {arch} meta",
        "primary": {"family": family, "lookback": 48, "z_threshold": 0.5},
        "meta": {"arch": arch},
        "risk": {
            "dd_cap_pct": 0.10,
            "pos_cap_pct": 0.25,
            "meta_conf_threshold": base_thr,
        },
        "horizon_H": 24,
        "pt_mult": 2.0,
        "sl_mult": 1.0,
    }


# ---- Role 4: primary-signal-designer --------------------------------------


def _primary_signal_designer(hypothesis: dict[str, Any]) -> dict[str, Any]:
    p = hypothesis["primary"]
    return {
        "family": p["family"],
        "lookback": int(p["lookback"]),
        "z_threshold": float(p["z_threshold"]),
    }


# ---- Role 5: label-curator (AFML Ch. 3) -----------------------------------


def _triple_barrier_labels(
    closes: np.ndarray,
    side: np.ndarray,
    horizon_H: int,
    pt_mult: float,
    sl_mult: float,
    vol: np.ndarray,
) -> np.ndarray:
    """Triple-barrier labels in {-1, 0, +1}.

    Labels are TRIMMED — any ``t`` whose vertical barrier ``t + H`` extends
    past the last index is labeled 0 (no trade) rather than being clipped
    (which would leak).
    """
    n = len(closes)
    labels = np.zeros(n, dtype=np.int8)
    for t in range(n - horizon_H):
        s = int(side[t])
        if s == 0:
            continue
        c0 = closes[t]
        v = vol[t] if vol[t] > 1e-9 else 1e-4
        pt = c0 * (1.0 + s * pt_mult * v)
        sl = c0 * (1.0 - s * sl_mult * v)
        for j in range(1, horizon_H + 1):
            c = closes[t + j]
            if s > 0:
                if c >= pt:
                    labels[t] = 1
                    break
                if c <= sl:
                    labels[t] = -1
                    break
            else:
                if c <= pt:
                    labels[t] = 1
                    break
                if c >= sl:
                    labels[t] = -1
                    break
        # vertical barrier: if loop exits without break, labels[t] stays 0 (timeout).
    # Trim: any t such that t + H > n - 1 is already 0 from init (we iterated only t < n - H).
    return labels


def _rolling_std(rets: np.ndarray, window: int) -> np.ndarray:
    out = np.zeros_like(rets)
    for i in range(window, len(rets)):
        w = rets[i - window : i]
        out[i] = w.std(ddof=1) if len(w) > 1 else 0.0
    return out


def _primary_side_series(closes: np.ndarray, spec: dict[str, Any]) -> np.ndarray:
    """Compute +1/0/-1 side at every bar using the primary-signal spec."""
    lookback = int(spec["lookback"])
    thr = float(spec["z_threshold"])
    family = spec["family"]
    side = np.zeros(len(closes), dtype=np.int8)
    rets = np.diff(closes) / np.maximum(closes[:-1], 1e-9)
    for i in range(lookback + 1, len(closes)):
        w = rets[i - lookback - 1 : i]
        mu = w.mean()
        sd = w.std(ddof=1) if len(w) > 1 else 0.0
        if sd < 1e-9:
            continue
        z = mu / sd * np.sqrt(len(w))
        if family == "momentum":
            if z > thr:
                side[i] = 1
            elif z < -thr:
                side[i] = -1
        elif family == "mean_reversion":
            if z > thr:
                side[i] = -1
            elif z < -thr:
                side[i] = 1
        # breakout: simplified — use close vs rolling max/min instead
        elif family == "breakout":
            hi = closes[i - lookback : i].max()
            lo = closes[i - lookback : i].min()
            if closes[i] > hi:
                side[i] = 1
            elif closes[i] < lo:
                side[i] = -1
    return side


def _label_curator(
    closes: np.ndarray,
    primary_spec: dict[str, Any],
    hypothesis: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    """Return (side_array, triple_barrier_labels). Labels trimmed at end."""
    side = _primary_side_series(closes, primary_spec)
    rets = np.diff(closes) / np.maximum(closes[:-1], 1e-9)
    vol = _rolling_std(rets, window=48)
    # align vol length with closes
    vol_full = np.concatenate([[vol[0] if len(vol) else 1e-4], vol])
    labels = _triple_barrier_labels(
        closes=closes,
        side=side,
        horizon_H=int(hypothesis["horizon_H"]),
        pt_mult=float(hypothesis["pt_mult"]),
        sl_mult=float(hypothesis["sl_mult"]),
        vol=vol_full,
    )
    return side, labels


# ---- Role 6: meta-model-builder -------------------------------------------


_FEATURE_NAMES = [
    "ret_1",
    "ret_6",
    "ret_24",
    "ret_48",
    "vol_6",
    "vol_24",
    "vol_48",
    "z_24",
    "z_48",
    "primary_side",
]


def _build_feature_matrix(closes: np.ndarray, side: np.ndarray) -> np.ndarray:
    n = len(closes)
    rets = np.diff(closes) / np.maximum(closes[:-1], 1e-9)
    rets_full = np.concatenate([[0.0], rets])  # align to closes length

    def _safe_mean(a: np.ndarray) -> float:
        return float(a.mean()) if len(a) else 0.0

    def _safe_std(a: np.ndarray) -> float:
        return float(a.std(ddof=1)) if len(a) > 1 else 0.0

    rows = np.zeros((n, len(_FEATURE_NAMES)), dtype=float)
    for i in range(n):
        if i < 48:
            continue
        w6 = rets_full[i - 6 : i]
        w24 = rets_full[i - 24 : i]
        w48 = rets_full[i - 48 : i]
        sd24 = _safe_std(w24)
        sd48 = _safe_std(w48)
        rows[i, 0] = rets_full[i - 1]
        rows[i, 1] = _safe_mean(w6)
        rows[i, 2] = _safe_mean(w24)
        rows[i, 3] = _safe_mean(w48)
        rows[i, 4] = _safe_std(w6)
        rows[i, 5] = sd24
        rows[i, 6] = sd48
        rows[i, 7] = (_safe_mean(w24) / sd24 * np.sqrt(24)) if sd24 > 1e-9 else 0.0
        rows[i, 8] = (_safe_mean(w48) / sd48 * np.sqrt(48)) if sd48 > 1e-9 else 0.0
        rows[i, 9] = float(side[i])
    return rows


def _meta_model_builder(
    features: np.ndarray,
    labels: np.ndarray,
    side: np.ndarray,
    hypothesis: dict[str, Any],
) -> tuple[Any, np.ndarray, np.ndarray]:
    """Fit meta-model. Target = 1 if label matches side direction, else 0.

    Only rows where ``side != 0 AND label != 0`` are used for training.
    Returns (model, X_train, y_train).
    """
    mask = (side != 0) & (labels != 0)
    X = features[mask]
    # Meta-label: did the primary-signal trade WIN? (label == +1 when it did)
    y = (labels[mask] == 1).astype(int)

    if len(X) < 50 or len(np.unique(y)) < 2:
        # degenerate — fall back to trivial model that says "never trade".
        return _TrivialModel(p_win=0.0), X, y

    arch = hypothesis["meta"]["arch"]
    try:
        if arch == "gbm":
            from sklearn.ensemble import GradientBoostingClassifier

            model = GradientBoostingClassifier(
                n_estimators=80, max_depth=3, random_state=42
            )
        else:
            from sklearn.neural_network import MLPClassifier

            model = MLPClassifier(
                hidden_layer_sizes=(32, 16),
                max_iter=200,
                random_state=42,
                early_stopping=True,
            )
        model.fit(X, y)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"meta-model fit failed: {exc}; using trivial fallback")
        model = _TrivialModel(p_win=0.0)
    return model, X, y


class _TrivialModel:
    """Trivial fallback: always returns fixed p_win. Matches sklearn predict_proba."""

    def __init__(self, p_win: float) -> None:
        self.p_win = float(p_win)
        self.classes_ = np.array([0, 1])

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        n = X.shape[0]
        return np.tile([1.0 - self.p_win, self.p_win], (n, 1))


# ---- Role 7: cv-validator (CPCV with embargo, AFML Ch. 7) -----------------


def _cv_validator(
    model_factory: Any,
    X: np.ndarray,
    y: np.ndarray,
    embargo: int,
    n_splits: int = 5,
) -> dict[str, Any]:
    """Purged k-fold CV with embargo — approximation of CPCV sufficient for budget.

    Returns OOS AUC + Brier averaged across folds.
    """
    if len(X) < n_splits * 10 or len(np.unique(y)) < 2:
        return {"auc": 0.5, "brier": 0.25, "folds": 0, "degenerate": True}

    try:
        from sklearn.metrics import brier_score_loss, roc_auc_score
    except Exception:  # noqa: BLE001
        return {"auc": 0.5, "brier": 0.25, "folds": 0, "degenerate": True}

    n = len(X)
    fold_size = n // n_splits
    aucs: list[float] = []
    briers: list[float] = []
    for k in range(n_splits):
        test_start = k * fold_size
        test_end = test_start + fold_size if k < n_splits - 1 else n
        train_mask = np.ones(n, dtype=bool)
        # purge + embargo both sides
        lo = max(0, test_start - embargo)
        hi = min(n, test_end + embargo)
        train_mask[lo:hi] = False
        X_tr, y_tr = X[train_mask], y[train_mask]
        X_te, y_te = X[test_start:test_end], y[test_start:test_end]
        if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
            continue
        try:
            # Rebuild a fresh model per fold.
            fresh = _rebuild_model(model_factory)
            fresh.fit(X_tr, y_tr)
            proba = fresh.predict_proba(X_te)
            classes = list(getattr(fresh, "classes_", [0, 1]))
            p1 = proba[:, classes.index(1)] if 1 in classes else proba[:, -1]
            aucs.append(float(roc_auc_score(y_te, p1)))
            briers.append(float(brier_score_loss(y_te, p1)))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"CV fold {k} failed: {exc}")

    if not aucs:
        return {"auc": 0.5, "brier": 0.25, "folds": 0, "degenerate": True}
    return {
        "auc": float(np.mean(aucs)),
        "brier": float(np.mean(briers)),
        "folds": len(aucs),
        "degenerate": False,
    }


def _rebuild_model(model: Any) -> Any:
    """Clone an sklearn-like model; fall back to ``model`` itself on failure."""
    try:
        from sklearn.base import clone

        return clone(model)
    except Exception:  # noqa: BLE001
        return model


# ---- Role 8: critic --------------------------------------------------------


def _critic(
    hypothesis: dict[str, Any],
    labels: np.ndarray,
    side: np.ndarray,
    cv_report: dict[str, Any],
    horizon_H: int,
    train_bars: int,
) -> dict[str, Any]:
    """Mechanical checks. Returns {'vetoed': bool, 'veto_reason': str, 'notes': [...]}."""
    notes: list[str] = []
    vetoed = False
    veto_reason = ""

    # Check 1: labels trimmed at end (last H bars should be 0)
    tail_sum = int(np.abs(labels[-horizon_H:]).sum()) if len(labels) >= horizon_H else 0
    if tail_sum > 0:
        vetoed = True
        veto_reason = f"Labels present in last {horizon_H} bars — leakage risk"
    notes.append(f"tail_label_count={tail_sum}")

    # Check 2: CV degenerate?
    if cv_report.get("degenerate", False):
        notes.append("CV degenerate (too few samples or single class)")
    # Check 3: AUC floor
    auc = float(cv_report.get("auc", 0.5))
    if auc < 0.52:
        vetoed = True
        veto_reason = veto_reason or f"OOS AUC {auc:.3f} < 0.52"
    notes.append(f"oos_auc={auc:.4f}")
    # Check 4: side balance — too-sparse side will underweight meta training
    nonzero_side = int((side != 0).sum())
    if nonzero_side < max(50, train_bars * 0.02):
        notes.append(f"sparse_primary_signal={nonzero_side} (warn)")

    return {"vetoed": vetoed, "veto_reason": veto_reason, "notes": notes}


# ---- Role 9: risk-officer -------------------------------------------------


def _risk_officer(
    hypothesis: dict[str, Any],
    cv_report: dict[str, Any],
    critique: dict[str, Any],
) -> dict[str, Any]:
    """Derive runtime rules. Higher Brier → higher threshold (trade less)."""
    base_thr = float(hypothesis["risk"]["meta_conf_threshold"])
    brier = float(cv_report.get("brier", 0.25))
    # Brier calibration bump: if Brier > 0.22, raise threshold.
    if brier > 0.22:
        base_thr = min(0.80, base_thr + (brier - 0.22) * 2.0)

    # If critic flagged anything, be conservative.
    if critique.get("notes"):
        for n in critique["notes"]:
            if n.startswith("sparse_primary_signal"):
                base_thr = min(0.80, base_thr + 0.03)

    return {
        "meta_confidence_threshold": round(base_thr, 4),
        "drawdown_cap_pct": float(hypothesis["risk"]["dd_cap_pct"]),
        "max_position_size_pct": float(hypothesis["risk"]["pos_cap_pct"]),
    }


# ---------------------------------------------------------------------------
# Data loading — strictly from the train window.
# ---------------------------------------------------------------------------


def _load_train_closes(ctx: Any) -> np.ndarray:
    """Load train-window close prices as a float64 numpy array.

    Instruments are loaded from the same catalog as the bars (see
    ``nautilus-trader-catalog-instrument-precision`` skill).
    """
    handle = ctx.get_train_data()
    from nautilus_trader.persistence.catalog import ParquetDataCatalog  # type: ignore

    catalog = ParquetDataCatalog(str(handle.catalog_path))
    # API: catalog.bars can be a method or attribute depending on version.
    # Handle both; normalize to a list.
    bars: list[Any] = []
    try:
        bars = catalog.bars(  # type: ignore[attr-defined]
            bar_types=[handle.instrument.bar_type],
            start=handle.start,
            end=handle.end,
        )
    except TypeError:
        # Some versions accept positional / different kwargs.
        bars = catalog.bars([handle.instrument.bar_type], handle.start, handle.end)  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"catalog.bars failed: {exc}")
        bars = []

    closes: list[float] = []
    for b in bars:
        try:
            closes.append(float(b.close))
        except Exception:  # noqa: BLE001
            try:
                closes.append(float(b.close.as_double()))  # nautilus Price
            except Exception:  # noqa: BLE001
                continue
    if not closes:
        logger.warning("No closes loaded from train window — using synthetic fallback")
        rng = np.random.default_rng(42)
        # ~21k bars, geometric-ish walk.
        steps = rng.normal(0.0, 0.001, size=21_000)
        return float(30_000.0) * np.exp(np.cumsum(steps))
    return np.asarray(closes, dtype=float)


# ---------------------------------------------------------------------------
# train() — orchestrator entry point.
# ---------------------------------------------------------------------------


def train(ctx: Any) -> tuple[type[LdpLabStrategy], LdpLabConfig]:
    """Orchestrate 9 roles → return (Strategy class, StrategyConfig)."""
    iter_idx = int(getattr(ctx, "iteration", 0))
    artifacts = _Artifacts.for_iter(iter_idx)

    # Role 1: memory-keeper prelude
    memory = _memory_keeper_prelude(ctx)

    # Role 2: researcher (LLM subprocess, cached)
    research_text = _researcher(ctx, artifacts, memory)

    # Role 3: hypothesis-generator
    hypothesis = _hypothesis_generator(research_text, ctx)
    artifacts.hypothesis_json.write_text(json.dumps(hypothesis, indent=2))

    # Role 4: primary-signal-designer
    primary_spec = _primary_signal_designer(hypothesis)
    artifacts.primary_signal_json.write_text(json.dumps(primary_spec, indent=2))

    # Load train data.
    try:
        closes = _load_train_closes(ctx)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"train data load failed: {exc}\n{traceback.format_exc()}")
        closes = np.asarray([30_000.0 + i * 0.1 for i in range(21_000)], dtype=float)

    # Role 5: label-curator
    side, labels = _label_curator(closes, primary_spec, hypothesis)

    # Role 6: meta-model-builder
    features = _build_feature_matrix(closes, side)
    model, X_train, y_train = _meta_model_builder(features, labels, side, hypothesis)

    # Persist model + feature list.
    try:
        import joblib

        joblib.dump(model, artifacts.meta_model_joblib)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"joblib.dump failed: {exc}")
    artifacts.feature_list_json.write_text(json.dumps(_FEATURE_NAMES))

    # Role 7: cv-validator (CPCV-lite with embargo = horizon_H)
    cv_report = _cv_validator(
        model,
        X_train,
        y_train,
        embargo=int(hypothesis["horizon_H"]),
        n_splits=5,
    )
    artifacts.cv_report_json.write_text(json.dumps(cv_report, indent=2))

    # Role 8: critic
    critique = _critic(
        hypothesis=hypothesis,
        labels=labels,
        side=side,
        cv_report=cv_report,
        horizon_H=int(hypothesis["horizon_H"]),
        train_bars=len(closes),
    )
    critique_md = (
        f"# Critique — round={ctx.round_index} iter={iter_idx}\n\n"
        f"- vetoed: {critique['vetoed']}\n"
        f"- reason: {critique['veto_reason']}\n"
        f"- notes: {critique['notes']}\n"
    )
    artifacts.critique_md.write_text(critique_md)

    # Role 9: risk-officer
    rules = _risk_officer(hypothesis, cv_report, critique)
    artifacts.runtime_rules_json.write_text(json.dumps(rules, indent=2))

    # Role 10: memory-keeper postlude
    _memory_keeper_postlude(ctx, artifacts, hypothesis, cv_report, critique)

    # Optional test-window sanity (read-only; does NOT change training).
    try:
        if hasattr(ctx, "get_test_data"):
            _ = ctx.get_test_data()  # touch for harness bookkeeping
    except Exception:  # noqa: BLE001
        pass

    # Build & return (StrategyClass, StrategyConfig).
    instrument = ctx.config.instrument
    config = LdpLabConfig(
        instrument_id=InstrumentId.from_str(instrument.symbol),
        bar_type=BarType.from_str(instrument.bar_type),
        meta_model_path=str(artifacts.meta_model_joblib),
        feature_list_path=str(artifacts.feature_list_json),
        runtime_rules_path=str(artifacts.runtime_rules_json),
        primary_signal_path=str(artifacts.primary_signal_json),
        lookback=int(primary_spec["lookback"]),
    )
    return LdpLabStrategy, config
