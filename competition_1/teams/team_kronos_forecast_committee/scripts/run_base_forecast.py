"""
kronos-forecaster-base
Loads NeoQuasar/Kronos-base (102.3M params, 512-token context) and produces a
24-bar (2-hour) forecast with quantile bands from sample_count paths.

Usage:
    python run_base_forecast.py [--round R] [--iter I]

Output schema (required by blender):
  forecaster, round, iter, horizon_bars, bar_size_minutes, context_bars_used,
  last_close, point_close, quantiles {p10, p50, p90}, hmm_filter, tokenizer, notes
  + optional: error
"""
import argparse
import os
import sys
import json
import time
import logging
import traceback

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger(__name__)

# ── CLI args ───────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--round", type=int, default=0)
parser.add_argument("--iter",  type=int, default=0)
args, _ = parser.parse_known_args()

# ── Paths ──────────────────────────────────────────────────────────────────────
REPO_ROOT  = "/Users/rc/Projects/workspace/nautilus-competition-run"
TEAM_DIR   = os.path.join(
    REPO_ROOT,
    "competition_1/teams/team_kronos_forecast_committee",
)
CATALOG    = os.path.join(REPO_ROOT, "competition_1/data/catalog")

ROUND      = args.round
ITER       = args.iter
OUT_DIR    = os.path.join(TEAM_DIR, f"forecasts/{ROUND}_{ITER}")
OUT_PATH   = os.path.join(OUT_DIR, "base.json")

HORIZON    = 24
CONTEXT    = 512
SAMPLE_CNT = 8

# ── HF cache (shared workspace store) ─────────────────────────────────────────
os.environ.setdefault(
    "HF_HOME",
    os.path.join(REPO_ROOT, ".cache/hf"),
)

# ── Kronos on sys.path ─────────────────────────────────────────────────────────
KRONOS_ROOT = "/Users/rc/.local/kronos"
if KRONOS_ROOT not in sys.path:
    sys.path.insert(0, KRONOS_ROOT)


# ══════════════════════════════════════════════════════════════════════════════
def load_bars(catalog_path: str, max_bars: int = 512) -> pd.DataFrame:
    """Load the last max_bars 5-min BTCUSDT bars from the NautilusTrader catalog."""
    log.info("Loading bars from %s", catalog_path)
    from nautilus_trader.persistence.catalog import ParquetDataCatalog  # noqa: PLC0415

    catalog = ParquetDataCatalog(catalog_path)
    bars = catalog.bars(["BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL"])
    log.info("Catalog returned %d raw bars", len(bars))

    records = []
    for b in bars:
        records.append(
            {
                "open":       float(b.open),
                "high":       float(b.high),
                "low":        float(b.low),
                "close":      float(b.close),
                "volume":     float(b.volume),
                "timestamps": pd.Timestamp(b.ts_event, unit="ns", tz="UTC"),
            }
        )

    df = (
        pd.DataFrame(records)
        .sort_values("timestamps")
        .reset_index(drop=True)
        .tail(max_bars)
        .reset_index(drop=True)
    )
    log.info(
        "Using %d bars; last ts=%s", len(df), df["timestamps"].iloc[-1]
    )
    return df


# ══════════════════════════════════════════════════════════════════════════════
def run_kronos(df: pd.DataFrame) -> tuple[list, dict, str, float]:
    """
    Load Kronos-base and run SAMPLE_CNT single-path predictions to derive
    point forecast + quantiles (p10/p50/p90).

    Returns: (point_close, quantiles_dict, device, inference_time_s)
    """
    import torch  # noqa: PLC0415
    from model import Kronos, KronosTokenizer, KronosPredictor  # noqa: PLC0415

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    log.info("Kronos device=%s", device)

    log.info("Loading NeoQuasar/Kronos-Tokenizer-base …")
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    log.info("Loading NeoQuasar/Kronos-base …")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-base")

    predictor = KronosPredictor(
        model, tokenizer, max_context=CONTEXT, device=device
    )

    ohlc_cols  = ["open", "high", "low", "close"]
    extra_cols = [c for c in ["volume"] if c in df.columns]
    x_cols     = ohlc_cols + extra_cols
    x_df       = df[x_cols].copy().astype(float)
    x_ts       = df["timestamps"].reset_index(drop=True)

    last_ts = x_ts.iloc[-1]
    y_ts = pd.Series(
        pd.date_range(
            start=last_ts + pd.Timedelta(minutes=5),
            periods=HORIZON,
            freq="5min",
            tz="UTC",
        )
    )

    log.info(
        "Running %d Kronos samples (horizon=%d context=%d) …",
        SAMPLE_CNT, HORIZON, len(x_df),
    )
    t0 = time.time()
    paths = []
    for i in range(SAMPLE_CNT):
        pred_df = predictor.predict(
            df=x_df,
            x_timestamp=x_ts,
            y_timestamp=y_ts,
            pred_len=HORIZON,
            T=1.0,
            top_p=0.9,
            sample_count=1,
        )
        paths.append(pred_df["close"].values.tolist())
        log.info("  sample %d/%d done", i + 1, SAMPLE_CNT)

    elapsed = time.time() - t0
    log.info("Inference complete in %.1fs", elapsed)

    arr   = np.array(paths)   # (SAMPLE_CNT, HORIZON)
    point = np.mean(arr, axis=0).tolist()
    p10   = np.percentile(arr, 10, axis=0).tolist()
    p50   = np.percentile(arr, 50, axis=0).tolist()
    p90   = np.percentile(arr, 90, axis=0).tolist()

    return point, {"p10": p10, "p50": p50, "p90": p90}, device, elapsed


# ══════════════════════════════════════════════════════════════════════════════
def flat_fallback(last_close: float, reason: str) -> dict:
    """
    Produce a naive flat forecast with a small vol-scaled spread so the blender
    can still run if Kronos inference fails.
    """
    log.warning("Fallback forecast.  Reason: %s", reason)
    sigma = last_close * 0.001   # 0.1% per bar ~ loose but reasonable
    rng   = np.random.default_rng(42)
    noise = rng.normal(0, sigma, size=HORIZON)
    point = (last_close + np.cumsum(noise)).tolist()
    p10   = (np.array(point) - 3 * sigma).tolist()
    p90   = (np.array(point) + 3 * sigma).tolist()

    return {
        "forecaster":        "kronos-base",
        "round":             ROUND,
        "iter":              ITER,
        "horizon_bars":      HORIZON,
        "bar_size_minutes":  5,
        "context_bars_used": 0,
        "last_close":        last_close,
        "point_close":       point,
        "quantiles":         {"p10": p10, "p50": point, "p90": p90},
        "hmm_filter":        False,
        "tokenizer":         "NeoQuasar/Kronos-Tokenizer-base",
        "fallback":          True,
        "error":             reason,
        "notes":             f"FALLBACK: {reason}",
    }


# ══════════════════════════════════════════════════════════════════════════════
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    log.info("Output path: %s", OUT_PATH)

    # 1. Load bars
    try:
        df = load_bars(CATALOG, max_bars=CONTEXT)
    except Exception as exc:
        log.error("Bar load failed: %s", exc)
        result = flat_fallback(95000.0, f"Bar load failed: {exc}")
        with open(OUT_PATH, "w") as fh:
            json.dump(result, fh, indent=2)
        log.info("Fallback JSON written to %s", OUT_PATH)
        return

    last_close = float(df["close"].iloc[-1])
    context_end_ts = df["timestamps"].iloc[-1].isoformat()
    log.info("last_close=%.2f  context_end=%s", last_close, context_end_ts)

    # 2. Run Kronos
    try:
        point_close, quantiles, device, elapsed = run_kronos(df)
    except Exception as exc:
        log.error("Kronos inference failed:\n%s", traceback.format_exc())
        result = flat_fallback(last_close, f"Kronos inference error: {exc}")
        with open(OUT_PATH, "w") as fh:
            json.dump(result, fh, indent=2)
        log.info("Fallback JSON written to %s", OUT_PATH)
        return

    # 3. Write output
    result = {
        "forecaster":            "kronos-base",
        "round":                 ROUND,
        "iter":                  ITER,
        "horizon_bars":          HORIZON,
        "bar_size_minutes":      5,
        "context_bars_used":     len(df),
        "last_close":            last_close,
        "point_close":           point_close,
        "quantiles":             quantiles,
        "hmm_filter":            False,
        "tokenizer":             "NeoQuasar/Kronos-Tokenizer-base",
        "device":                device,
        "sample_count":          SAMPLE_CNT,
        "inference_time_s":      round(elapsed, 1),
        "context_window_end_ts": context_end_ts,
        "notes": (
            f"Real Kronos-base inference, device={device}, "
            f"sample_count={SAMPLE_CNT}, horizon={HORIZON} bars "
            f"(2h at 5-min cadence), context={len(df)} bars. "
            f"Round {ROUND} iter {ITER}: input window identical to iter 0 "
            f"(single catalog parquet through 2026-05-01T00:04:59.999); "
            f"forecast variation from stochastic sampling only."
        ),
    }

    with open(OUT_PATH, "w") as fh:
        json.dump(result, fh, indent=2)

    log.info("SUCCESS — forecast written to %s", OUT_PATH)
    log.info("point_close[0:3] = %s", point_close[:3])


if __name__ == "__main__":
    main()
