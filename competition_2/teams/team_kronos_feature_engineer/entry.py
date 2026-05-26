"""Entry point for team_kronos_feature_engineer.

Thesis: Kronos foundation model as a FEATURE EXTRACTOR feeding a classical
ML head (LightGBM / logistic); vol-targeted long/flat at trade-time.

Shape: `train(ctx)` is deterministic Python with exactly ONE `run_claude(...)`
subprocess call (the `researcher` role). Every other role in the 8-role
roster documented in CLAUDE.md is a pure Python function that reads the
researcher's JSON and applies rules. This keeps us inside the 600s budget.

Note on serialization: this file writes sklearn model artifacts using
pickle. The artifact is produced BY THIS FILE and CONSUMED BY THIS FILE's
Strategy class in the same team workspace — there is no untrusted input.
This is the standard sklearn persistence pattern; joblib would be
equivalent. Do NOT replace with JSON; sklearn estimators are not
JSON-serializable.
"""

from __future__ import annotations

import json
import logging
import math
import pickle  # noqa: S403 - trusted self-written artifacts only
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nautilus_competition.agent_runner import (  # type: ignore[import-untyped]
    run_researcher,
)
from nautilus_trader.config import StrategyConfig  # type: ignore[import-untyped]
from nautilus_trader.model.data import Bar, BarType  # type: ignore[import-untyped]
from nautilus_trader.model.enums import OrderSide, TimeInForce  # type: ignore[import-untyped]
from nautilus_trader.model.identifiers import InstrumentId  # type: ignore[import-untyped]
from nautilus_trader.persistence.catalog import ParquetDataCatalog  # type: ignore[import-untyped]
from nautilus_trader.trading.strategy import Strategy  # type: ignore[import-untyped]


if TYPE_CHECKING:
    from nautilus_trader.model.instruments import Instrument  # type: ignore[import-untyped]


LOGGER = logging.getLogger("team_kronos_feature_engineer")


TEAM_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

# Researcher subprocess timeout. Leaves ~180s of the 600s global budget for
# feature engineering + model fit + strategy assembly.
RESEARCHER_TIMEOUT_S = 420

# Fallback hypothesis if the researcher subprocess fails or emits malformed
# JSON. Deliberately classical-only so we always ship a round.
FALLBACK_HYPOTHESIS: dict[str, Any] = {
    "feature_shortlist": [
        {"name": "har_rv_1", "rationale": "classical baseline", "expected_sign": "neg"},
        {"name": "har_rv_5", "rationale": "classical baseline", "expected_sign": "neg"},
        {"name": "har_rv_22", "rationale": "classical baseline", "expected_sign": "neg"},
        {"name": "realized_skew_20", "rationale": "Amaya et al. 2015", "expected_sign": "unsure"},
        {"name": "vw_momentum_residual_20", "rationale": "Moskowitz 2012", "expected_sign": "pos"},
    ],
    "model_head": "logistic",
    "label_horizon_bars": 12,
    "label_def": "sign(close[t+h] - close[t])",
    "regime_gate": {"realized_vol_annualized_max": 1.8},
    "vol_target_annualized": 0.20,
    "drawdown_cap_pct": 0.15,
    "position_size_cap_pct": 0.60,
}


# ---------------------------------------------------------------------------
# Strategy + Config (trade-time — runs inside BacktestEngine / live paper)
# ---------------------------------------------------------------------------


class TeamConfig(StrategyConfig, frozen=True):
    """Trade-time config. Paths point at artifacts produced by train()."""

    instrument_id: InstrumentId
    bar_type: BarType
    model_path: str
    rules_path: str
    feature_spec_path: str
    trade_size_base: Decimal = Decimal("0.001")


class TeamStrategy(Strategy):
    """Trade-time: load model + rules in on_start; on each bar compute
    features, score, apply live critic rules (no LLM), size by vol-target.
    """

    def __init__(self, config: TeamConfig) -> None:
        super().__init__(config)
        self.instrument: Instrument | None = None
        self._model: Any = None
        self._rules: dict[str, Any] = {}
        self._feature_spec: dict[str, Any] = {}
        self._closes: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._volumes: list[float] = []
        # Minimum bars needed to compute all features (HAR-RV-22 → 23 bars).
        # At paper (3 bars, per config.yaml paper.duration_minutes=15 & 5min
        # bars) we won't be able to trade unless upstream warms us up. The
        # eval window is much larger (~21 days of 5-min bars ~ 6048 bars),
        # so warm-up is only a concern if the harness pipes paper bars into
        # this strategy without pre-seeding — which is the expected flow.
        self._min_bars_for_features: int = 23
        self._current_position_size: float = 0.0
        self._bars_seen: int = 0

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument not found: {self.config.instrument_id}")
            self.stop()
            return

        # Load runtime rules (pure JSON — no code execution).
        try:
            self._rules = json.loads(Path(self.config.rules_path).read_text())
        except Exception as e:  # pragma: no cover - defensive
            self.log.error(f"Failed to load rules from {self.config.rules_path}: {e}")
            self._rules = {}

        # Load feature spec so trade-time features mirror train-time.
        try:
            self._feature_spec = json.loads(Path(self.config.feature_spec_path).read_text())
        except Exception as e:  # pragma: no cover - defensive
            self.log.error(f"Failed to load feature_spec: {e}")
            self._feature_spec = {}

        # Load model. The artifact was written by THIS team's train() to
        # this same workspace — not untrusted input. Pickle is the standard
        # sklearn persistence format.
        try:
            with Path(self.config.model_path).open("rb") as f:
                self._model = pickle.load(f)  # noqa: S301 - trusted self-written artifact
        except Exception as e:  # pragma: no cover - defensive
            self.log.error(f"Failed to load model from {self.config.model_path}: {e}")
            self._model = None

        self.subscribe_bars(self.config.bar_type)

    def on_bar(self, bar: Bar) -> None:
        if self.instrument is None:
            return

        # Keep a bounded rolling buffer (we don't need more than ~128 bars).
        self._closes.append(float(bar.close))
        self._highs.append(float(bar.high))
        self._lows.append(float(bar.low))
        self._volumes.append(float(bar.volume))
        max_buf = 128
        if len(self._closes) > max_buf:
            self._closes = self._closes[-max_buf:]
            self._highs = self._highs[-max_buf:]
            self._lows = self._lows[-max_buf:]
            self._volumes = self._volumes[-max_buf:]
        self._bars_seen += 1

        # Warm-up: don't trade until features are stable.
        if len(self._closes) < self._min_bars_for_features:
            return
        if self._model is None:
            return

        # Compute live features (classical only at trade-time to keep latency
        # predictable; Kronos features are optional and only used if the
        # feature_spec instructed us to — not implemented for live to avoid
        # model-download surprises in paper.).
        feats = _compute_live_features(
            self._closes, self._highs, self._lows, self._volumes
        )
        if feats is None:
            return

        # Live critic: apply regime gate BEFORE scoring.
        realized_vol_cap = (
            self._rules.get("regime_gate", {})
            .get("realized_vol_annualized_max", math.inf)
        )
        rv_annualized = feats.get("realized_vol_annualized", 0.0)
        if rv_annualized > realized_vol_cap:
            self._maybe_rebalance_to(0.0)
            return

        # Score. Classical logistic / GBM → p_long in [0,1].
        try:
            X = [[feats[k] for k in self._feature_spec.get("feature_cols", [])]]
            if hasattr(self._model, "predict_proba"):
                p_long = float(self._model.predict_proba(X)[0][1])
            else:
                # Regression head — use sigmoid of raw output.
                raw = float(self._model.predict(X)[0])
                p_long = 1.0 / (1.0 + math.exp(-raw))
        except Exception as e:  # pragma: no cover - defensive
            self.log.error(f"Model scoring failed: {e}")
            return

        flat_threshold = self._rules.get("prediction_threshold_flat", 0.50)
        long_threshold = self._rules.get("prediction_threshold_long", 0.55)

        if p_long < flat_threshold:
            self._maybe_rebalance_to(0.0)
            return

        # Vol-target sizing.
        vol_target = self._rules.get("vol_target_annualized", 0.20)
        pos_cap = self._rules.get("position_size_cap_pct", 0.60)
        eps = 1e-6
        size_frac = min(vol_target / max(rv_annualized, eps), pos_cap)
        if p_long < long_threshold:
            # Weak long — halve sizing.
            size_frac *= 0.5
        self._maybe_rebalance_to(size_frac)

    def _maybe_rebalance_to(self, target_frac: float) -> None:
        """Coarse rebalance. Uses trade_size_base as the unit; target_frac is
        interpreted as a multiplier on the base unit. This is a simplification
        — a production strategy would compute qty from equity / price, but
        the harness tracks gain factor on $1000 starting pot, so a
        proportional unit approach is adequate.
        """
        if self.instrument is None:
            return

        delta = target_frac - self._current_position_size
        if abs(delta) < 0.05:  # deadband — avoid churn at paper
            return

        size = abs(delta) * float(self.config.trade_size_base)
        if size <= 0:
            return

        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        try:
            qty = self.instrument.make_qty(Decimal(str(size)))
        except Exception as e:  # pragma: no cover - defensive
            self.log.error(f"make_qty failed for size={size}: {e}")
            return

        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(order)
        self._current_position_size = target_frac

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        self.unsubscribe_bars(self.config.bar_type)


# ---------------------------------------------------------------------------
# Feature helpers (shared train + trade time)
# ---------------------------------------------------------------------------


def _compute_live_features(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
) -> dict[str, float] | None:
    """Compute the three classical feature families from a rolling buffer of
    bars. Mirrors the train-time feature engineer's logic. Returns None if
    the buffer is too short.
    """
    if len(closes) < 23:
        return None

    # Log returns.
    rets: list[float] = []
    for i in range(1, len(closes)):
        if closes[i - 1] <= 0 or closes[i] <= 0:
            return None
        rets.append(math.log(closes[i] / closes[i - 1]))

    def _rv(returns: list[float], window: int) -> float:
        if len(returns) < window:
            return 0.0
        tail = returns[-window:]
        return sum(r * r for r in tail)

    har_rv_1 = _rv(rets, 1)
    har_rv_5 = _rv(rets, 5)
    har_rv_22 = _rv(rets, 22)

    # Realized skew (20-window).
    skew_tail = rets[-20:] if len(rets) >= 20 else rets
    mean = sum(skew_tail) / len(skew_tail) if skew_tail else 0.0
    var = sum((r - mean) ** 2 for r in skew_tail) / len(skew_tail) if skew_tail else 0.0
    std = math.sqrt(var) if var > 0 else 1e-9
    m3 = sum((r - mean) ** 3 for r in skew_tail) / len(skew_tail) if skew_tail else 0.0
    realized_skew = m3 / (std**3) if std > 0 else 0.0

    # Vol-weighted momentum residual (20-window).
    mom_tail = rets[-20:] if len(rets) >= 20 else rets
    cum_ret = sum(mom_tail)
    mom_std = math.sqrt(sum(r * r for r in mom_tail) / len(mom_tail)) if mom_tail else 1e-9
    vw_momentum_residual = cum_ret / (mom_std + 1e-9)

    # Realized annualized vol (for regime gate + vol-targeting).
    # 5-min bars → 12 bars/hour × 24 × 365 = 105_120 per year.
    rv_var_22 = _rv(rets, 22)
    bars_per_year = 12 * 24 * 365
    rv_annualized = math.sqrt(rv_var_22 * (bars_per_year / 22))

    return {
        "har_rv_1": har_rv_1,
        "har_rv_5": har_rv_5,
        "har_rv_22": har_rv_22,
        "realized_skew_20": realized_skew,
        "vw_momentum_residual_20": vw_momentum_residual,
        "realized_vol_annualized": rv_annualized,
    }


# ---------------------------------------------------------------------------
# Role helpers — deterministic Python
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RoundPaths:
    """Per-iteration artifact paths."""

    attempt_dir: Path
    research_md: Path
    hypothesis_json: Path
    critic_md: Path
    features_pkl: Path
    feature_spec_json: Path
    model_pkl: Path
    model_meta_json: Path
    validation_json: Path
    rules_json: Path


def _paths_for(iter_idx: int) -> _RoundPaths:
    attempt_dir = TEAM_DIR / "attempts" / f"{iter_idx:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    return _RoundPaths(
        attempt_dir=attempt_dir,
        research_md=attempt_dir / "research.md",
        hypothesis_json=attempt_dir / "hypothesis.json",
        critic_md=attempt_dir / "critic.md",
        features_pkl=attempt_dir / "features.pkl",
        feature_spec_json=attempt_dir / "feature_spec.json",
        model_pkl=attempt_dir / "model.pkl",
        model_meta_json=attempt_dir / "model_meta.json",
        validation_json=attempt_dir / "validation.json",
        rules_json=TEAM_DIR / "runtime_rules.json",
    )


def _memory_keeper_consult(ctx: Any) -> str:
    """Role #5 (pre-researcher): surface prior-round state for the prompt."""
    notes_dir = TEAM_DIR / "notes"
    notes_dir.mkdir(exist_ok=True)

    lines = [
        "# Prior round context",
        f"- round_index: {ctx.round_index}",
        f"- iteration: {ctx.iteration}",
        f"- prev_gain: {ctx.prev_gain}",
    ]

    theses = sorted(notes_dir.glob("round_*_thesis.md"))
    if theses:
        latest = theses[-1]
        lines.append(f"\n## Latest prior thesis ({latest.name})\n")
        lines.append(latest.read_text()[:4000])
    else:
        lines.append("\n(No prior round theses — this is round 0.)")

    log = notes_dir / "research_log.md"
    if log.exists():
        lines.append("\n## Research log (tail)\n")
        lines.append(log.read_text()[-2000:])

    return "\n".join(lines)


def _memory_keeper_append_thesis(
    ctx: Any,
    hypothesis: dict[str, Any],
    validation: dict[str, Any],
    rules: dict[str, Any],
) -> None:
    """Role #5 (post-hypothesis): persist this round's thesis."""
    notes_dir = TEAM_DIR / "notes"
    notes_dir.mkdir(exist_ok=True)
    thesis_path = (
        notes_dir
        / f"round_{ctx.round_index:03d}_iter_{ctx.iteration:03d}_thesis.md"
    )
    thesis_path.write_text(
        "\n".join(
            [
                f"# Round {ctx.round_index}, iter {ctx.iteration} thesis",
                "",
                f"- prev_gain (on entry): {ctx.prev_gain}",
                f"- feature_shortlist: {[f['name'] for f in hypothesis.get('feature_shortlist', [])]}",
                f"- model_head: {hypothesis.get('model_head')}",
                f"- label_horizon_bars: {hypothesis.get('label_horizon_bars')}",
                "",
                "## Rules crystallized for trade-time",
                "```json",
                json.dumps(rules, indent=2),
                "```",
                "",
                "## Validation (CPCV on train window)",
                "```json",
                json.dumps(validation, indent=2),
                "```",
                "",
            ]
        )
    )

    registry = notes_dir / "feature_registry.md"
    header = "# Feature registry\n\nAppend-only log of which features have been tried.\n\n"
    if not registry.exists():
        registry.write_text(header)
    with registry.open("a") as f:
        for feat in hypothesis.get("feature_shortlist", []):
            f.write(
                f"- round={ctx.round_index} iter={ctx.iteration} "
                f"name={feat.get('name')} sign={feat.get('expected_sign')}\n"
            )

    # Append actionable findings to the persistent research log.
    log = notes_dir / "research_log.md"
    header_text = "# Research log\n\nAppend-only log of researcher findings.\n\n"
    if not log.exists():
        log.write_text(header_text)
    with log.open("a") as f:
        f.write(
            f"\n## round={ctx.round_index} iter={ctx.iteration}\n"
            f"- features: {[f['name'] for f in hypothesis.get('feature_shortlist', [])]}\n"
            f"- head: {hypothesis.get('model_head')}\n"
            f"- cpcv_accuracy: {validation.get('mean_accuracy')}\n"
        )


def _researcher(
    ctx: Any,
    prior_context_md: str,
    paths: _RoundPaths,
) -> dict[str, Any]:
    """Role #1: the single run_claude call. Returns parsed JSON or falls back."""
    (TEAM_DIR / "_inbox").mkdir(exist_ok=True)
    (TEAM_DIR / "_inbox" / "context.md").write_text(prior_context_md)

    retry_hint = ""
    if ctx.prev_gain is not None and ctx.prev_gain < 0:
        retry_hint = (
            f"\nPRIOR ITERATION FAILED (prev_gain={ctx.prev_gain:.4f}). Propose a "
            f"MATERIALLY DIFFERENT feature shortlist — swap HAR-RV for "
            f"realized-bipower, relax the regime gate, or switch model head "
            f"from GBM to logistic. Avoid parameter nudges."
        )

    prompt = (
        f"You are the researcher role for team_kronos_feature_engineer, "
        f"iteration {ctx.iteration} of round {ctx.round_index}. "
        f"Read CLAUDE.md, _inbox/context.md, and notes/research_log.md. "
        f"Source priorities: (1) competition_2/docs/state-of-the-art/ if it "
        f"exists, (2) competition_1/teams/*/reflections.md + notes/*, "
        f"(3) external arXiv (Kronos 2508.02739, HAR-RV Corsi 2009, realized "
        f"skew Amaya et al. 2015, vol-weighted momentum Moskowitz 2012). "
        f"Produce a feature shortlist + model head + regime gate + risk knobs. "
        f"Write your full analysis to attempts/{ctx.iteration:03d}/research.md "
        f"and include a fenced ```json block with exactly these keys: "
        f"feature_shortlist (list of {{name, rationale, expected_sign, paper_ref?}}), "
        f"model_head (one of lightgbm|logistic|gbm_sklearn), "
        f"label_horizon_bars (int), label_def (str), "
        f"regime_gate ({{realized_vol_annualized_max: float}}), "
        f"vol_target_annualized (float), drawdown_cap_pct (float), "
        f"position_size_cap_pct (float). "
        f"Available feature names MUST be drawn from: har_rv_1, har_rv_5, "
        f"har_rv_22, realized_skew_20, vw_momentum_residual_20, "
        f"kronos_last_hidden_mean (optional). Exit when done.{retry_hint}"
    )

    result = run_researcher(
        workspace_dir=TEAM_DIR,
        prompt=prompt,
        timeout_seconds=RESEARCHER_TIMEOUT_S,
        fail_loud=False,
    )

    paths.research_md.write_text(
        f"# Researcher output (envelope_unwrapped={result.unwrapped_envelope}, "
        f"duration={result.duration_seconds:.1f}s)\n\n"
        f"{result.raw_stdout[:20000]}\n"
    )

    if not result.payload:
        LOGGER.warning(
            "researcher returned empty payload (raw_stdout_len=%d); using fallback",
            len(result.raw_stdout),
        )
        return dict(FALLBACK_HYPOTHESIS)
    if not _hypothesis_is_valid(result.payload):
        LOGGER.warning("researcher payload missing required keys; using fallback")
        return dict(FALLBACK_HYPOTHESIS)
    return result.payload


def _hypothesis_is_valid(obj: dict[str, Any]) -> bool:
    required = {
        "feature_shortlist",
        "model_head",
        "label_horizon_bars",
        "regime_gate",
        "vol_target_annualized",
        "drawdown_cap_pct",
        "position_size_cap_pct",
    }
    if not required.issubset(obj.keys()):
        return False
    shortlist = obj.get("feature_shortlist")
    if not isinstance(shortlist, list) or not shortlist:
        return False
    if obj.get("model_head") not in {"lightgbm", "logistic", "gbm_sklearn"}:
        return False
    return True


def _hypothesis_generator(
    research_json: dict[str, Any],
    prior_context: str,
    ctx: Any,
) -> dict[str, Any]:
    """Role #2: take researcher JSON, normalize, enforce allowed feature names."""
    allowed_features = {
        "har_rv_1",
        "har_rv_5",
        "har_rv_22",
        "realized_skew_20",
        "vw_momentum_residual_20",
        "kronos_last_hidden_mean",
    }
    shortlist = []
    for feat in research_json.get("feature_shortlist", []):
        if not isinstance(feat, dict):
            continue
        name = feat.get("name")
        if name in allowed_features:
            shortlist.append(
                {
                    "name": name,
                    "rationale": feat.get("rationale", ""),
                    "expected_sign": feat.get("expected_sign", "unsure"),
                }
            )
    if not shortlist:
        LOGGER.warning("no valid features in researcher output; using fallback")
        shortlist = list(FALLBACK_HYPOTHESIS["feature_shortlist"])

    return {
        "feature_shortlist": shortlist,
        "model_head": research_json.get("model_head", FALLBACK_HYPOTHESIS["model_head"]),
        "label_horizon_bars": int(
            research_json.get(
                "label_horizon_bars", FALLBACK_HYPOTHESIS["label_horizon_bars"]
            )
        ),
        "label_def": research_json.get("label_def", FALLBACK_HYPOTHESIS["label_def"]),
        "regime_gate": dict(
            research_json.get("regime_gate", FALLBACK_HYPOTHESIS["regime_gate"])
        ),
        "vol_target_annualized": float(
            research_json.get(
                "vol_target_annualized", FALLBACK_HYPOTHESIS["vol_target_annualized"]
            )
        ),
        "drawdown_cap_pct": float(
            research_json.get(
                "drawdown_cap_pct", FALLBACK_HYPOTHESIS["drawdown_cap_pct"]
            )
        ),
        "position_size_cap_pct": float(
            research_json.get(
                "position_size_cap_pct",
                FALLBACK_HYPOTHESIS["position_size_cap_pct"],
            )
        ),
        "prior_context_summary_len": len(prior_context),
    }


def _critic(hypothesis: dict[str, Any]) -> dict[str, Any]:
    """Role #3: leakage + sanity checklist. Advisory only."""
    flags: list[str] = []
    if hypothesis.get("label_horizon_bars", 0) <= 0:
        flags.append("label_horizon_bars must be > 0 — defaulting to 12")
        hypothesis["label_horizon_bars"] = 12
    if hypothesis.get("label_horizon_bars", 0) > 96:
        flags.append(
            f"label_horizon_bars={hypothesis['label_horizon_bars']} is "
            f"unusually long — risk of alpha decay"
        )
    # Drop Kronos features from the trade-time set (we don't compute them live).
    shortlist = [
        f for f in hypothesis["feature_shortlist"] if not f["name"].startswith("kronos_")
    ]
    if len(shortlist) < len(hypothesis["feature_shortlist"]):
        flags.append(
            "dropped Kronos features from trade-time set (not computed live)"
        )
    if not shortlist:
        flags.append("post-filter shortlist empty — restoring classical baseline")
        shortlist = list(FALLBACK_HYPOTHESIS["feature_shortlist"])
    hypothesis["feature_shortlist"] = shortlist

    vt = float(hypothesis.get("vol_target_annualized", 0.20))
    if vt <= 0 or vt > 0.80:
        flags.append(f"vol_target_annualized {vt} out of [0,0.8] — clamped")
        hypothesis["vol_target_annualized"] = max(0.05, min(vt, 0.40))

    ps = float(hypothesis.get("position_size_cap_pct", 0.60))
    if ps <= 0 or ps > 1.0:
        flags.append(f"position_size_cap_pct {ps} out of [0,1] — clamped")
        hypothesis["position_size_cap_pct"] = max(0.05, min(ps, 0.95))

    return {"hypothesis": hypothesis, "flags": flags}


def _load_train_bars(ctx: Any) -> list[dict[str, float]]:
    """Open the ParquetDataCatalog and return a list of OHLCV dicts sorted by
    ts_event. Train window ONLY. Never touches eval/paper.
    """
    handle = ctx.get_train_data()
    catalog = ParquetDataCatalog(str(handle.catalog_path))
    bars = catalog.bars(
        bar_types=[handle.instrument.bar_type],
        start=handle.start,
        end=handle.end,
    )
    out = []
    for b in bars:
        try:
            out.append(
                {
                    "ts": int(b.ts_event),
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": float(b.volume),
                }
            )
        except Exception:  # pragma: no cover - tolerate odd bar types
            continue
    out.sort(key=lambda r: r["ts"])
    return out


def _feature_engineer(
    bars: list[dict[str, float]],
    hypothesis: dict[str, Any],
    paths: _RoundPaths,
) -> tuple[list[list[float]], list[int], list[str]]:
    """Role #6: compute feature matrix + labels from train bars.

    Returns (X, y, feature_cols). Kronos features are intentionally NOT
    computed here (even at train-time) to avoid any surprise model
    downloads that might exceed the 600s budget. Kronos is a stated optional
    that would be wired in a follow-up iteration; for now the classical
    feature set is what's live-computable anyway.
    """
    feature_cols = [
        f["name"]
        for f in hypothesis["feature_shortlist"]
        if not f["name"].startswith("kronos_")
    ]
    if not feature_cols:
        feature_cols = ["har_rv_1", "har_rv_5", "har_rv_22"]

    horizon = int(hypothesis.get("label_horizon_bars", 12))
    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    volumes = [b["volume"] for b in bars]

    X: list[list[float]] = []
    y: list[int] = []

    warmup = 23
    for t in range(warmup, len(closes) - horizon):
        feats = _compute_live_features(
            closes[: t + 1], highs[: t + 1], lows[: t + 1], volumes[: t + 1]
        )
        if feats is None:
            continue
        row = [feats.get(col, 0.0) for col in feature_cols]
        if any(math.isnan(v) or math.isinf(v) for v in row):
            continue
        fut = closes[t + horizon]
        cur = closes[t]
        if cur <= 0 or fut <= 0:
            continue
        label = 1 if fut > cur else 0
        X.append(row)
        y.append(label)

    paths.feature_spec_json.write_text(
        json.dumps(
            {
                "feature_cols": feature_cols,
                "label_horizon_bars": horizon,
                "warmup_bars": warmup,
                "n_samples": len(X),
            },
            indent=2,
        )
    )
    # Persist the feature matrix for forensics (self-written artifact).
    with paths.features_pkl.open("wb") as f:
        pickle.dump({"X": X, "y": y, "feature_cols": feature_cols}, f)  # noqa: S301

    return X, y, feature_cols


def _model_builder(
    X: list[list[float]],
    y: list[int],
    feature_cols: list[str],
    hypothesis: dict[str, Any],
    paths: _RoundPaths,
) -> Any:
    """Role #7: fit the chosen head. Falls back to logistic if the requested
    head's library isn't installed — deterministic, no silent skips.
    """
    head = hypothesis.get("model_head", "logistic")
    model: Any = None

    if head == "lightgbm":
        try:
            import lightgbm as lgb  # type: ignore[import-not-found]

            model = lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=5,
                learning_rate=0.05,
                num_leaves=31,
                min_child_samples=20,
                verbosity=-1,
            )
            model.fit(X, y)
        except Exception as e:  # pragma: no cover - env-dependent
            LOGGER.warning("lightgbm unavailable (%s); falling back to sklearn GBM", e)
            model = None
            head = "gbm_sklearn"

    if head == "gbm_sklearn" and model is None:
        try:
            from sklearn.ensemble import GradientBoostingClassifier  # type: ignore[import-untyped]

            model = GradientBoostingClassifier(
                n_estimators=100, max_depth=3, learning_rate=0.05
            )
            model.fit(X, y)
        except Exception as e:  # pragma: no cover - env-dependent
            LOGGER.warning("sklearn GBM unavailable (%s); falling back to logistic", e)
            model = None
            head = "logistic"

    if model is None:
        try:
            from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

            model = LogisticRegression(max_iter=200, C=1.0)
            model.fit(X, y)
        except Exception as e:  # pragma: no cover - env-dependent
            LOGGER.warning("sklearn unavailable (%s); using dumb-majority", e)
            model = _MajorityClassifier(y)
            head = "majority"

    paths.model_meta_json.write_text(
        json.dumps(
            {
                "head": head,
                "feature_cols": feature_cols,
                "n_samples": len(X),
                "n_features": len(feature_cols),
            },
            indent=2,
        )
    )
    with paths.model_pkl.open("wb") as f:
        pickle.dump(model, f)  # noqa: S301 - trusted self-written artifact
    return model


class _MajorityClassifier:
    """Ultra-degenerate fallback: predicts the training-set majority class."""

    def __init__(self, y: list[int]) -> None:
        self._p = sum(y) / max(len(y), 1) if y else 0.5

    def predict_proba(self, X: list[list[float]]) -> list[list[float]]:
        return [[1 - self._p, self._p] for _ in X]

    def predict(self, X: list[list[float]]) -> list[int]:
        return [1 if self._p >= 0.5 else 0 for _ in X]

    def fit(self, X: list[list[float]], y: list[int]) -> _MajorityClassifier:
        # No-op; used so CPCV's refit doesn't crash.
        return self


def _validator(
    X: list[list[float]],
    y: list[int],
    model: Any,
    paths: _RoundPaths,
) -> dict[str, Any]:
    """Role #8: simple time-series CV with embargo on the train window ONLY.

    Not full CPCV (budget-bound); 5-fold contiguous time-series split with
    embargo = label_horizon_bars on each side.
    """
    if not X:
        out: dict[str, Any] = {"folds": [], "mean_accuracy": 0.0, "n_samples": 0}
        paths.validation_json.write_text(json.dumps(out, indent=2))
        return out

    n = len(X)
    k = 5
    fold_size = n // k
    embargo = 12  # at least label_horizon_bars
    accs: list[float] = []
    for i in range(k):
        test_start = i * fold_size
        test_end = test_start + fold_size if i < k - 1 else n
        train_X = (
            X[: max(0, test_start - embargo)]
            + X[min(n, test_end + embargo) :]
        )
        train_y = (
            y[: max(0, test_start - embargo)]
            + y[min(n, test_end + embargo) :]
        )
        test_X = X[test_start:test_end]
        test_y = y[test_start:test_end]
        if not train_X or not test_X:
            continue
        try:
            clone = _shallow_clone(model)
            clone.fit(train_X, train_y)
            if hasattr(clone, "predict"):
                preds = clone.predict(test_X)
            else:
                continue
            correct = sum(int(p) == int(t) for p, t in zip(preds, test_y))
            accs.append(correct / len(test_y))
        except Exception as e:  # pragma: no cover - env-dependent
            LOGGER.warning("CV fold %d failed: %s", i, e)
            continue

    out = {
        "folds": accs,
        "mean_accuracy": sum(accs) / len(accs) if accs else 0.0,
        "n_samples": n,
        "n_folds": len(accs),
    }
    paths.validation_json.write_text(json.dumps(out, indent=2))
    return out


def _shallow_clone(model: Any) -> Any:
    """Best-effort re-instantiation of a sklearn-style model for CV folds."""
    try:
        from sklearn.base import clone  # type: ignore[import-untyped]

        return clone(model)
    except Exception:
        return model


def _risk_officer(
    hypothesis: dict[str, Any],
    validation: dict[str, Any],
    ctx: Any,
    paths: _RoundPaths,
) -> dict[str, Any]:
    """Role #4: crystallize runtime_rules.json. Tightens caps if validation
    was weak (mean_accuracy < 0.53) or if prev_round_leaderboard shows the
    field had huge drawdowns.
    """
    rules = {
        "drawdown_cap_pct": float(hypothesis["drawdown_cap_pct"]),
        "position_size_cap_pct": float(hypothesis["position_size_cap_pct"]),
        "vol_target_annualized": float(hypothesis["vol_target_annualized"]),
        "regime_gate": dict(hypothesis["regime_gate"]),
        "label_horizon_bars": int(hypothesis["label_horizon_bars"]),
        "prediction_threshold_long": 0.55,
        "prediction_threshold_flat": 0.50,
    }

    mean_acc = float(validation.get("mean_accuracy", 0.0))
    if mean_acc < 0.52:
        rules["position_size_cap_pct"] = min(rules["position_size_cap_pct"], 0.30)
        rules["prediction_threshold_long"] = 0.60
    elif mean_acc < 0.55:
        rules["position_size_cap_pct"] = min(rules["position_size_cap_pct"], 0.45)

    # If prior round's leaderboard exists, tighten caps on evidence of pain.
    lb = ctx.prev_round_leaderboard
    if lb is not None:
        try:
            lb_path = Path(lb)
            if lb_path.exists() and "max_dd" in lb_path.read_text():
                rules["position_size_cap_pct"] = min(rules["position_size_cap_pct"], 0.40)
        except Exception:
            pass

    paths.rules_json.write_text(json.dumps(rules, indent=2))
    return rules


# ---------------------------------------------------------------------------
# train() — the harness entry point
# ---------------------------------------------------------------------------


def train(ctx: Any) -> tuple[type[TeamStrategy], TeamConfig]:
    iter_idx = int(ctx.iteration)
    paths = _paths_for(iter_idx)

    # Step 0 — memory-keeper consults prior rounds (before researcher runs).
    prior_context_md = _memory_keeper_consult(ctx)

    # Step 1 — researcher (ONE run_claude call).
    research_json = _researcher(ctx, prior_context_md, paths)

    # Step 2 — hypothesis-generator (deterministic).
    hypothesis = _hypothesis_generator(research_json, prior_context_md, ctx)

    # Step 3 — critic (deterministic; may demote features).
    critic_out = _critic(hypothesis)
    hypothesis = critic_out["hypothesis"]
    paths.critic_md.write_text(
        "# Critic flags\n\n"
        + "\n".join(f"- {f}" for f in critic_out["flags"])
        + f"\n\n## Post-critic hypothesis\n\n```json\n{json.dumps(hypothesis, indent=2)}\n```\n"
    )
    paths.hypothesis_json.write_text(json.dumps(hypothesis, indent=2))

    # Step 4 — feature-engineer. Load train bars, build matrix + labels.
    bars = _load_train_bars(ctx)
    if len(bars) < 200:
        raise RuntimeError(
            f"train window returned only {len(bars)} bars — too few for fitting"
        )
    X, y, feature_cols = _feature_engineer(bars, hypothesis, paths)

    # Step 5 — model-builder. Fit + persist.
    model = _model_builder(X, y, feature_cols, hypothesis, paths)

    # Step 6 — validator (time-series CV with embargo on train window).
    validation = _validator(X, y, model, paths)

    # Step 7 — risk-officer. Crystallize runtime_rules.json.
    rules = _risk_officer(hypothesis, validation, ctx, paths)

    # Step 8 — memory-keeper. Append round thesis + feature registry.
    _memory_keeper_append_thesis(ctx, hypothesis, validation, rules)

    # Strategy config — paths must be absolute so the BacktestEngine can load.
    instrument = ctx.config.instrument
    cfg = TeamConfig(
        instrument_id=InstrumentId.from_str(instrument.symbol),
        bar_type=BarType.from_str(instrument.bar_type),
        model_path=str(paths.model_pkl.resolve()),
        rules_path=str(paths.rules_json.resolve()),
        feature_spec_path=str(paths.feature_spec_json.resolve()),
    )
    return TeamStrategy, cfg
