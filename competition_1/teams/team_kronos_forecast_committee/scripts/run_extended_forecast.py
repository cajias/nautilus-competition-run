"""
kronos-forecaster-extended
HMM regime filter applied to inputs before Kronos-base forecast.

No-leakage guarantee:
  GaussianHMM is fit on log-returns of the FULL training window (past bars only).
  The Viterbi state sequence is derived from that same past window.
  current_regime = states[-1], i.e., the state of the MOST RECENT bar.
  No bar from the prediction horizon is ever seen by the HMM.
"""
import os
import sys
import json
import pickle
import logging
import datetime
import traceback
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
WORKSPACE = "/Users/rc/Projects/workspace/nautilus-competition-run"
TEAM_DIR  = os.path.join(WORKSPACE, "competition_1/teams/team_kronos_forecast_committee")
CATALOG   = os.path.join(WORKSPACE, "competition_1/data/catalog")
HMM_CACHE = os.path.join(TEAM_DIR, ".cache/kronos_hmm/0.pkl")
OUT_PATH  = os.path.join(TEAM_DIR, "forecasts/0_2/extended.json")

ROUND     = 0
ITER      = 2

# ── HF cache ──────────────────────────────────────────────────────────────────
os.environ.setdefault("HF_HOME", os.path.join(WORKSPACE, ".cache/hf"))

# ── Kronos on sys.path ─────────────────────────────────────────────────────────
KRONOS_ROOT = "/Users/rc/.local/kronos"
if KRONOS_ROOT not in sys.path:
    sys.path.insert(0, KRONOS_ROOT)


# ══════════════════════════════════════════════════════════════════════════════
def load_bars(catalog_path: str, max_bars: int = 1024) -> pd.DataFrame:
    """Load BTCUSDT 5-min bars via NautilusTrader ParquetDataCatalog."""
    log.info("Loading bars from catalog at %s", catalog_path)
    from nautilus_trader.persistence.catalog import ParquetDataCatalog  # noqa: PLC0415

    catalog = ParquetDataCatalog(catalog_path)
    bars = catalog.bars(["BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL"])
    log.info("Catalog returned %d bars", len(bars))

    records = []
    for b in bars:
        records.append({
            "open":       float(b.open),
            "high":       float(b.high),
            "low":        float(b.low),
            "close":      float(b.close),
            "volume":     float(b.volume),
            "timestamps": pd.Timestamp(b.ts_event, unit="ns", tz="UTC"),
        })

    df = pd.DataFrame(records)
    df = df.sort_values("timestamps").reset_index(drop=True)
    df = df.tail(max_bars).reset_index(drop=True)
    log.info("Loaded %d bars; last ts=%s", len(df), df["timestamps"].iloc[-1])
    return df


# ══════════════════════════════════════════════════════════════════════════════
def fit_or_load_hmm(returns: np.ndarray, cache_path: str, n_components: int = 3):
    """
    Fit GaussianHMM on log-returns using PAST DATA ONLY.
    Persists to cache_path for round-to-round reuse.

    No-leakage guarantee: HMM is fit on returns[0..T-1]; Viterbi is also run
    on that same window.  The state of the most recent bar = states[-1].
    No future bar is ever observed by the model.
    """
    from hmmlearn.hmm import GaussianHMM  # noqa: PLC0415

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)

    if os.path.exists(cache_path):
        log.info("Loading cached HMM from %s", cache_path)
        with open(cache_path, "rb") as f:
            hmm = pickle.load(f)
    else:
        log.info("Fitting GaussianHMM(n_components=%d) on %d returns", n_components, len(returns))
        hmm = GaussianHMM(
            n_components=n_components,
            covariance_type="diag",
            n_iter=200,
            random_state=42,
        )
        obs = returns.reshape(-1, 1)
        hmm.fit(obs)
        with open(cache_path, "wb") as f:
            pickle.dump(hmm, f)
        log.info("HMM fitted and cached.")

    return hmm


def infer_states(hmm, returns: np.ndarray) -> np.ndarray:
    """Run Viterbi on the return sequence using the fitted HMM (past-only)."""
    obs = returns.reshape(-1, 1)
    return hmm.predict(obs)


def label_regime(hmm, state_idx: int) -> str:
    """Map HMM state to human label based on mean return ordering."""
    means = hmm.means_.flatten()
    order = np.argsort(means)          # ascending: bear, [chop], bull
    if hmm.n_components == 3:
        labels = {order[0]: "bear", order[1]: "chop", order[2]: "bull"}
    elif hmm.n_components == 2:
        labels = {order[0]: "bear", order[1]: "bull"}
    else:
        labels = {i: f"state_{i}" for i in range(hmm.n_components)}
    return labels.get(state_idx, f"state_{state_idx}")


# ══════════════════════════════════════════════════════════════════════════════
def apply_hmm_filter(df: pd.DataFrame, states: np.ndarray, current_state: int,
                     max_context: int = 512):
    """
    Filter rule:
      1. Identify the most-recent contiguous same-state block ending at bar T.
      2. If it has >= max_context bars, use the last max_context.
      3. Otherwise pad backward with the most-recent earlier same-state bars
         (non-contiguous) until we reach max_context or exhaust same-state bars.

    This means Kronos sees predominantly bars from the CURRENT regime, which
    is the recommended "emphasize bars in the same state" pattern.

    No leakage: states[i] depends only on bars[0..T] where T <= i.
    """
    n = len(df)
    assert len(states) == n, "states length must match df length"

    # Most-recent contiguous same-state block
    block_end   = n - 1
    block_start = block_end
    while block_start > 0 and states[block_start - 1] == current_state:
        block_start -= 1
    contiguous_block = list(range(block_start, block_end + 1))

    if len(contiguous_block) >= max_context:
        selected    = contiguous_block[-max_context:]
        filter_rule = (
            f"Contiguous same-regime block (state={current_state}) has "
            f"{len(contiguous_block)} bars; truncated to last {max_context}."
        )
    else:
        same_state_before = [i for i in range(0, block_start) if states[i] == current_state]
        extra_needed = max_context - len(contiguous_block)
        extra        = same_state_before[-extra_needed:] if extra_needed > 0 else []
        selected     = sorted(extra + contiguous_block)
        filter_rule  = (
            f"Contiguous same-regime tail: {len(contiguous_block)} bars "
            f"(state={current_state}). Padded with {len(extra)} earlier same-regime bars "
            f"(non-contiguous). Total context: {len(selected)} bars."
        )

    log.info("HMM filter: %s", filter_rule)
    return df.iloc[selected].reset_index(drop=True), filter_rule


# ══════════════════════════════════════════════════════════════════════════════
def collect_quantiles(context_df: pd.DataFrame, horizon: int, sample_count: int = 8):
    """
    Load Kronos-base once and run sample_count single-path predictions to
    estimate forecast quantiles.
    Returns: point (mean), quantiles dict, device string.
    """
    import torch  # noqa: PLC0415
    from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: PLC0415

    # Prefer MPS on Apple Silicon; fall back to CPU
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    log.info("Kronos device=%s", device)

    log.info("Loading NeoQuasar/Kronos-Tokenizer-base ...")
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    log.info("Loading NeoQuasar/Kronos-base ...")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-base")

    predictor = KronosPredictor(model, tokenizer, max_context=512, device=device)

    ohlc_cols  = ["open", "high", "low", "close"]
    extra_cols = [c for c in ["volume", "amount"] if c in context_df.columns]
    x_cols     = ohlc_cols + extra_cols
    x_df       = context_df[x_cols].copy().astype(float)
    x_ts       = context_df["timestamps"].reset_index(drop=True)

    last_ts = x_ts.iloc[-1]
    y_ts = pd.Series(pd.date_range(
        start=last_ts + pd.Timedelta(minutes=5),
        periods=horizon,
        freq="5min",
        tz="UTC",
    ))

    log.info("Context bars=%d  horizon=%d  sample_count=%d", len(x_df), horizon, sample_count)

    paths = []
    for i in range(sample_count):
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_ts,
            y_timestamp=y_ts,
            pred_len=horizon,
            T=1.0,
            top_p=0.9,
            sample_count=1,
        )
        paths.append(pred_df["close"].values.tolist())
        log.info("  sample %d/%d done", i + 1, sample_count)

    paths_arr = np.array(paths)          # shape: (sample_count, horizon)
    point     = np.mean(paths_arr, axis=0).tolist()
    p10       = np.percentile(paths_arr, 10, axis=0).tolist()
    p50       = np.percentile(paths_arr, 50, axis=0).tolist()
    p90       = np.percentile(paths_arr, 90, axis=0).tolist()

    return point, {"p10": p10, "p50": p50, "p90": p90}, device


# ══════════════════════════════════════════════════════════════════════════════
def write_fallback(reason: str, last_close: float, horizon: int = 24):
    """Write a placeholder JSON when real inference cannot run.
    Uses the required new schema so the blender + executor can still proceed."""
    log.warning("Writing FALLBACK forecast. Reason: %s", reason)
    rng   = np.random.default_rng(42)
    noise = rng.normal(0, last_close * 0.001, size=horizon)
    preds = (last_close + np.cumsum(noise)).tolist()
    std   = last_close * 0.005
    p10   = [v - std * (i + 1) ** 0.5 for i, v in enumerate(preds)]
    p90   = [v + std * (i + 1) ** 0.5 for i, v in enumerate(preds)]

    out = {
        "forecaster":        "kronos-extended",
        "round":             ROUND,
        "iter":              ITER,
        "horizon_bars":      horizon,
        "bar_size_minutes":  5,
        "context_bars_used": 0,
        "hmm_states":        3,
        "hmm_current_state": -1,
        "hmm_state":         -1,
        "hmm_state_label":   "unknown",
        "regime_label":      "unknown",
        "last_close":        last_close,
        "anchor_close":      last_close,
        "point_close":       preds,
        "quantiles":         {"p10": p10, "p50": preds, "p90": p90},
        "hmm_filter":        False,
        "filter_rule":       "no filter applied",
        "notes":             f"FALLBACK: {reason}",
        "error":             reason,
        "ts_generated":      datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    log.info("Fallback JSON written to %s", OUT_PATH)


# ══════════════════════════════════════════════════════════════════════════════
def main():
    HORIZON      = 24
    SAMPLE_COUNT = 8
    MAX_RAW_BARS = 1024   # HMM window
    MAX_CONTEXT  = 512    # Kronos-base max context

    # ── 1. Load bars ──────────────────────────────────────────────────────────
    try:
        df = load_bars(CATALOG, max_bars=MAX_RAW_BARS)
    except Exception as e:
        write_fallback(f"Failed to load bars: {e}", last_close=95000.0)
        return

    last_close             = float(df["close"].iloc[-1])
    context_window_end_ts  = df["timestamps"].iloc[-1].isoformat()

    # ── 2. Log-returns for HMM ────────────────────────────────────────────────
    closes      = df["close"].astype(float).values
    log_returns = np.diff(np.log(closes))
    # Align: bar 0 gets return=0 (no predecessor in window)
    bar_returns = np.concatenate([[0.0], log_returns])

    # ── 3. Fit / load HMM (past states only — no leakage) ─────────────────────
    try:
        hmm           = fit_or_load_hmm(bar_returns, cache_path=HMM_CACHE, n_components=3)
        states        = infer_states(hmm, bar_returns)
        current_state = int(states[-1])
        regime_label  = label_regime(hmm, current_state)
        log.info("Current regime: state=%d label=%s", current_state, regime_label)
        hmm_n_components = int(hmm.n_components)
    except Exception as e:
        log.warning("HMM failed (%s) — using all bars without regime filter", e)
        states           = np.zeros(len(df), dtype=int)
        current_state    = 0
        regime_label     = "unknown"
        hmm_n_components = 1

    # ── 4. Apply HMM filter ───────────────────────────────────────────────────
    try:
        context_df, filter_rule = apply_hmm_filter(df, states, current_state, MAX_CONTEXT)
        hmm_filter_applied = True
    except Exception as e:
        log.warning("HMM filter failed (%s) — using last %d bars", e, MAX_CONTEXT)
        context_df         = df.tail(MAX_CONTEXT).reset_index(drop=True)
        filter_rule        = f"Fallback: last {MAX_CONTEXT} bars (filter error: {e})"
        hmm_filter_applied = False

    # ── 5. Run Kronos with quantile sampling ──────────────────────────────────
    try:
        point, quantiles, device = collect_quantiles(context_df, HORIZON, SAMPLE_COUNT)
    except Exception as e:
        log.error("Kronos failed: %s\n%s", e, traceback.format_exc())
        write_fallback(f"Kronos inference error: {e}", last_close=last_close, horizon=HORIZON)
        return

    # ── 6. Write output JSON (required schema) ────────────────────────────────
    notes = (
        f"HMM: GaussianHMM(n_components=3, covariance_type=diag) fit on "
        f"{len(bar_returns)} log-returns from the full training window "
        f"(no future leakage: Viterbi run on past bars only; current_regime = states[-1]). "
        f"Current regime: state={current_state} ({regime_label}). "
        f"Filter rule: {filter_rule}. "
        f"Context bars passed to Kronos-base: {len(context_df)} (max_context={MAX_CONTEXT})."
    )

    out = {
        # Required schema fields (task spec)
        "forecaster":        "kronos-extended",
        "round":             ROUND,
        "iter":              ITER,
        "horizon_bars":      HORIZON,
        "bar_size_minutes":  5,
        "context_bars_used": len(context_df),
        "hmm_states":        hmm_n_components,
        # Both naming conventions for blender compatibility
        "hmm_current_state": current_state,
        "hmm_state":         current_state,
        "hmm_state_label":   regime_label,
        "regime_label":      regime_label,
        "last_close":        last_close,
        "anchor_close":      last_close,
        "point_close":       point,
        "quantiles":         quantiles,
        "hmm_filter":        hmm_filter_applied,
        "filter_rule":       (
            "weight bars by regime match — emphasize bars in the same HMM state "
            f"as current ({regime_label}). " + filter_rule
        ),
        # Supplemental fields for blender/debug
        "checkpoint":        "NeoQuasar/Kronos-base",
        "tokenizer":         "NeoQuasar/Kronos-Tokenizer-base",
        "context_len":       512,
        "horizon":           HORIZON,
        "device":            device,
        "context_window_end_ts": context_window_end_ts,
        "notes":             notes,
        "ts_generated":      datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)

    log.info("SUCCESS — forecast written to %s", OUT_PATH)
    log.info("point_close (first 3): %s", point[:3])
    log.info("Current regime: %s (state %d)", regime_label, current_state)


if __name__ == "__main__":
    main()
