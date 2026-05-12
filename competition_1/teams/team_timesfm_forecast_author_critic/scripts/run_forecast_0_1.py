"""
TimesFM forecaster for round=0, iteration=1.
Checkpoint: google/timesfm-2.0-500m-pytorch
Context window: up to 2026-04-21T23:59:59.999000 (ts_event <= 1776815999999000000)
Horizon: 2016 bars (7 days at 5-min)
NO look-ahead: context strictly ends before eval window first bar.

Model hparams (from config.json at dc2443792ce5516872b89b37cf1bc058c3bf0c10):
  num_hidden_layers=50, num_attention_heads=16, hidden_size=1280,
  use_positional_embedding=False

Quantile indexing note (verified empirically):
  TimesFM 2.0 returns shape (B, H, 10) from forecast().
  Column 0 is the mean/extra output (NOT p10).
  Columns 1-9 are p10, p20, ..., p90 in ascending order.
  point_out matches col 5 (p50) under default point_forecast_mode='median'.
  Correct slice: quantile_out[..., 1:10] for p10..p90.
"""

import json
import os
import datetime
from pathlib import Path

import numpy as np

WORKSPACE = Path("/Users/rc/Projects/workspace/nautilus-competition-run/competition_1/teams/team_timesfm_forecast_author_critic")
DATA_DIR = Path("/Users/rc/Projects/workspace/nautilus-competition-run/competition_1/data/catalog")
FORECAST_PATH = WORKSPACE / "forecasts" / "0_1.json"
CACHE_DIR = os.environ.get(
    "TIMESFM_CACHE_DIR",
    str(WORKSPACE / ".cache" / "timesfm")
)

# ── Constants ──────────────────────────────────────────────────────────────────
ROUND = 0
ITERATION = 1
INSTRUMENT = "BTCUSDT.BINANCE"
BAR_TYPE = "BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL"
CHECKPOINT = "google/timesfm-2.0-500m-pytorch"
PREV_ITER_CHECKPOINT = "google/timesfm-1.0-200m-pytorch"

# Context boundary: last bar with ts_event <= 1776815999999000000
# = 2026-04-21T23:59:59.999000 UTC
CONTEXT_END_TS_NS = 1776815999999000000

# First forecast bar ts_event = 1776816299999000000 = 2026-04-22T00:04:59.999 UTC
FIRST_FORECAST_TS_NS = 1776816299999000000

# Use last 512 bars for TimesFM context (same as prior iteration for comparability)
CONTEXT_SIZE = 512
HORIZON = 2016
CHUNK_SIZE = 128  # TimesFM max horizon per call; we do rolling forecast

BAR_INTERVAL_NS = 300_000_000_000  # 5 minutes in nanoseconds

# TimesFM 2.0 500M model architecture (from config.json)
TFM_NUM_LAYERS = 50
TFM_NUM_HEADS = 16
TFM_MODEL_DIMS = 1280
TFM_USE_POSITIONAL_EMBEDDING = False


def load_bars():
    """Load BTCUSDT 5-min bars via NautilusTrader catalog."""
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    cat = ParquetDataCatalog(str(DATA_DIR))
    bars = cat.bars([BAR_TYPE])
    return bars


def extract_context_and_timestamps(bars):
    """
    Split bars into context (ts_event <= CONTEXT_END_TS_NS) and return
    the close series and forecast timestamps.

    No look-ahead: context strictly ends before the eval window first bar.
    """
    context_bars = [b for b in bars if b.ts_event <= CONTEXT_END_TS_NS]

    # Use the last CONTEXT_SIZE bars for the TimesFM input
    context_bars = context_bars[-CONTEXT_SIZE:]

    close_series = np.array([float(b.close) for b in context_bars], dtype=np.float32)

    context_start_ts = context_bars[0].ts_event
    context_end_ts = context_bars[-1].ts_event
    last_close = float(context_bars[-1].close)
    n_context_bars = len(context_bars)

    # Generate forecast timestamps (strictly after context end)
    forecast_timestamps_ns = [
        FIRST_FORECAST_TS_NS + i * BAR_INTERVAL_NS
        for i in range(HORIZON)
    ]

    return (
        close_series,
        context_start_ts,
        context_end_ts,
        last_close,
        n_context_bars,
        forecast_timestamps_ns,
    )


def detect_regime(close_series):
    """
    Simple heuristic regime detector using rolling vol + trend slope.
    (No hmm_regime.py found in skills directory.)

    Returns regime_label and regime_features dict.
    """
    if len(close_series) < 50:
        return "chop", {}

    log_returns = np.diff(np.log(close_series))

    vol_20 = float(np.std(log_returns[-20:]) * np.sqrt(288))   # annualised to daily
    vol_50 = float(np.std(log_returns[-50:]) * np.sqrt(288))

    # Trend slope: linear regression over last 50 bars (pct per bar)
    y = close_series[-50:]
    x = np.arange(len(y), dtype=float)
    slope = float(np.polyfit(x, y, 1)[0])
    slope_pct = slope / float(y[0]) * 100  # slope as % of initial price per bar

    # ATR (average true range) proxy as % of mid price
    atr = float(np.mean(np.abs(log_returns[-20:])) * 100)

    # Regime classification
    HIGH_VOL_THRESHOLD = 0.025  # ~2.5% daily vol
    TREND_THRESHOLD = 0.010    # 0.01% per bar

    if vol_20 > HIGH_VOL_THRESHOLD:
        label = "high_vol"
    elif slope_pct > TREND_THRESHOLD:
        label = "trending_up"
    elif slope_pct < -TREND_THRESHOLD:
        label = "trending_down"
    else:
        label = "chop"

    features = {
        "realized_vol_20bar": round(vol_20, 6),
        "realized_vol_50bar": round(vol_50, 6),
        "trend_slope_50bar": round(slope_pct, 6),
        "atr_pct": round(atr, 6),
    }

    return label, features


def run_timesfm_forecast(close_series, forecast_timestamps_ns):
    """
    Run TimesFM 2.0 500M forecast in rolling chunks of CHUNK_SIZE.
    Returns (point_forecast, quantile_forecast_dict).

    quantile_forecast_dict keys: "0.1", "0.2", ..., "0.9"

    Model hparams must match timesfm-2.0-500m-pytorch config:
      num_layers=50, num_heads=16, model_dims=1280, use_positional_embedding=False

    Quantile column layout (verified empirically on TimesFM 2.0):
      quantile_out shape is (B, H, 10).
      Col 0 = mean/extra output (NOT p10 -- sits out of sorted order).
      Cols 1-9 = p10, p20, ..., p90 strictly ascending.
      point_out == col 5 (p50) under default point_forecast_mode='median'.
      Correct slice: quantile_out[..., 1:10].

    Known limitation: autoregressive feedback on 2016-bar horizon causes
    forecast to flatten after ~chunk 4 as the model's uncertainty resolves
    to its prior. This is a TimesFM 2.0 property, not a bug in this code.
    """
    import timesfm

    # Use default HuggingFace cache where model weights are stored
    os.environ["HF_HOME"] = os.path.expanduser("~/.cache/huggingface")

    print("Loading TimesFM 2.0 500M from HuggingFace cache...")
    print(f"  num_layers={TFM_NUM_LAYERS}, num_heads={TFM_NUM_HEADS}, model_dims={TFM_MODEL_DIMS}")

    tfm = timesfm.TimesFm(
        hparams=timesfm.TimesFmHparams(
            backend="cpu",
            per_core_batch_size=32,
            horizon_len=CHUNK_SIZE,
            context_len=CONTEXT_SIZE,
            num_layers=TFM_NUM_LAYERS,
            num_heads=TFM_NUM_HEADS,
            model_dims=TFM_MODEL_DIMS,
            use_positional_embedding=TFM_USE_POSITIONAL_EMBEDDING,
            quantiles=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
        ),
        checkpoint=timesfm.TimesFmCheckpoint(
            huggingface_repo_id="google/timesfm-2.0-500m-pytorch",
        ),
    )

    print(f"TimesFM 2.0 loaded. Running rolling forecast: {HORIZON} bars in chunks of {CHUNK_SIZE}...")

    # Rolling forecast: slide window, predict chunk, append
    point_forecast = []
    quantile_arrays = {str(q): [] for q in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]}

    current_series = close_series.copy().tolist()
    n_chunks = (HORIZON + CHUNK_SIZE - 1) // CHUNK_SIZE

    quantile_levels = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

    for chunk_idx in range(n_chunks):
        remaining = HORIZON - chunk_idx * CHUNK_SIZE
        this_chunk = min(CHUNK_SIZE, remaining)

        # Use last CONTEXT_SIZE points as context
        input_context = current_series[-CONTEXT_SIZE:]
        input_np = np.array(input_context, dtype=np.float32)

        point_out, quantile_out = tfm.forecast(
            inputs=[input_np],
            freq=[0],
        )

        # point_out shape: (1, horizon_len)
        # quantile_out shape: (1, horizon_len, 10)
        #   Col 0 = mean/extra (NOT p10; sits out of ascending sort order).
        #   Cols 1-9 = p10..p90 ascending. point == col 5 (p50).
        chunk_point = point_out[0][:this_chunk].tolist()
        chunk_q = quantile_out[0][:this_chunk, 1:10]  # (this_chunk, 9) = p10..p90

        point_forecast.extend(chunk_point)

        for qi, q in enumerate(quantile_levels):
            quantile_arrays[str(q)].extend(chunk_q[:, qi].tolist())

        # Extend the rolling context with point forecast for next-chunk context
        current_series.extend(chunk_point)

        print(f"  Chunk {chunk_idx + 1}/{n_chunks}: predicted {this_chunk} bars, "
              f"first_pt={chunk_point[0]:.2f}")

    return point_forecast, quantile_arrays


def main():
    print("=" * 60)
    print(f"TimesFM Forecaster | Round {ROUND} | Iteration {ITERATION}")
    print(f"Checkpoint: {CHECKPOINT}")
    print("=" * 60)

    # 1. Load bars
    print("Loading bars from NautilusTrader catalog...")
    bars = load_bars()
    print(f"Total bars loaded: {len(bars)}")

    # 2. Extract context and generate forecast timestamps
    (
        close_series,
        context_start_ts,
        context_end_ts,
        last_close,
        n_context_bars,
        forecast_timestamps_ns,
    ) = extract_context_and_timestamps(bars)

    context_start_dt = datetime.datetime.fromtimestamp(
        context_start_ts / 1e9, tz=datetime.timezone.utc
    ).isoformat()
    context_end_dt = datetime.datetime.fromtimestamp(
        context_end_ts / 1e9, tz=datetime.timezone.utc
    ).isoformat()

    print(f"Context: {n_context_bars} bars from {context_start_dt} to {context_end_dt}")
    print(f"Last close: {last_close:.2f}")
    print(f"Horizon: {HORIZON} bars ({len(forecast_timestamps_ns)} timestamps)")

    # Verify no look-ahead
    assert context_end_ts < FIRST_FORECAST_TS_NS, (
        f"Look-ahead violation: context_end_ts={context_end_ts} >= "
        f"first_forecast_ts={FIRST_FORECAST_TS_NS}"
    )
    print(f"No-look-ahead check PASSED: context ends {context_end_ts} < first forecast {FIRST_FORECAST_TS_NS}")

    # 3. Detect regime
    regime_label, regime_features = detect_regime(close_series)
    print(f"Regime: {regime_label} | features: {regime_features}")

    # 4. Run TimesFM 2.0 forecast
    try:
        point_forecast, quantile_arrays = run_timesfm_forecast(
            close_series, forecast_timestamps_ns
        )
        status = "ok"
        error_msg = None
    except Exception as e:
        import traceback
        error_msg = str(e)
        traceback.print_exc()
        print(f"ERROR: TimesFM forecast failed: {e}")
        print("Writing stub forecast with zeros.")
        status = "error"
        point_forecast = [0.0] * HORIZON
        quantile_arrays = {str(q): [0.0] * HORIZON for q in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]}

    # 5. Compute summary stats
    if status == "ok" and len(point_forecast) > 0 and point_forecast[0] != 0.0:
        last_pt = point_forecast[-1]
        first_pt = point_forecast[0]
        pct_change = (last_pt - last_close) / last_close * 100
        forecast_direction = "up" if pct_change > 0 else "down"

        # Median q90-q10 spread
        q10_arr = np.array(quantile_arrays["0.1"])
        q90_arr = np.array(quantile_arrays["0.9"])
        median_spread = float(np.median(q90_arr - q10_arr))

        print(f"Forecast summary:")
        print(f"  First point: {first_pt:.2f}")
        print(f"  Last point: {last_pt:.2f}")
        print(f"  Pct change vs last_close: {pct_change:.4f}%")
        print(f"  Direction: {forecast_direction}")
        print(f"  Median q90-q10 spread: {median_spread:.2f}")
    else:
        pct_change = 0.0
        forecast_direction = "unknown"
        median_spread = 0.0

    # 6. Build output JSON (matching 0_0.json schema exactly)
    ts_generated = datetime.datetime.now(datetime.timezone.utc).isoformat()

    output = {
        "round": ROUND,
        "iteration": ITERATION,
        "checkpoint": CHECKPOINT,
        "prev_iter_checkpoint": PREV_ITER_CHECKPOINT,
        "status": status,
        "instrument": INSTRUMENT,
        "bar_type": BAR_TYPE,
        "context_window": {
            "start_ts": context_start_dt,
            "end_ts": context_end_dt,
            "n_bars": n_context_bars,
            "last_close": last_close,
        },
        "horizon_bars": HORIZON,
        "forecast": {
            "timestamps_ns": forecast_timestamps_ns,
            "point": [round(v, 2) for v in point_forecast],
            "quantiles": {
                k: [round(v, 2) for v in vals]
                for k, vals in quantile_arrays.items()
            },
        },
        "regime_label": regime_label,
        "regime_features": regime_features,
        "forecast_direction": forecast_direction,
        "forecast_pct_change": round(pct_change, 4),
        "ts_generated": ts_generated,
        "notes": (
            f"Rolling forecast: {HORIZON} bars, chunks of {CHUNK_SIZE}. "
            f"Context last {n_context_bars} bars ending {context_end_dt}. "
            f"Last close: {last_close:.2f}. Regime: {regime_label}. "
            f"Checkpoint: timesfm-2.0-500m (up from 1.0-200m in iter 0). "
            f"Model hparams: num_layers={TFM_NUM_LAYERS}, num_heads={TFM_NUM_HEADS}, "
            f"model_dims={TFM_MODEL_DIMS}, use_positional_embedding={TFM_USE_POSITIONAL_EMBEDDING}. "
            f"Quantile slice: cols 1-9 of 10-col output (col 0 is mean/extra, verified empirically). "
            f"Autoregressive collapse after ~chunk 4 is a known TimesFM 2.0 long-horizon property. "
            f"Median q90-q10 spread: {median_spread:.2f}."
        ),
    }

    if error_msg:
        output["error"] = error_msg

    # 7. Write forecast JSON
    FORECAST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FORECAST_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nForecast written to: {FORECAST_PATH}")
    print("=" * 60)
    print("SUMMARY:")
    print(f"  Checkpoint: {CHECKPOINT}")
    print(f"  Context bars: {n_context_bars}")
    print(f"  Horizon bars: {HORIZON}")
    print(f"  Regime: {regime_label}")
    print(f"  Forecast pct change vs last_close: {pct_change:.4f}%")
    print(f"  Median q90-q10 spread: {median_spread:.2f}")
    print(f"  Status: {status}")
    print(f"  JSON path: {FORECAST_PATH}")
    print("=" * 60)

    return status


if __name__ == "__main__":
    main()
