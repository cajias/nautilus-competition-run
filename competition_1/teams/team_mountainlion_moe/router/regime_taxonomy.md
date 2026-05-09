# router/regime_taxonomy.md

**Version: 1**

Initial 3-regime taxonomy. The gating-router classifies each iteration into one of these labels. Edit + version-bump when RAG disagreement > 40% on the current taxonomy.

## Regimes

### `trending`
- Realized volatility in mid-tercile.
- |slope of SMA(50)| > some threshold (router calibrates).
- Volume z-score > 0 on breakout bars.
- Recommended expert: `momentum-expert`.

### `ranging`
- Realized volatility in low-tercile.
- SMA(20) and SMA(50) flat (slope ≈ 0).
- Price oscillating around mean (Bollinger band-bounded).
- Recommended expert: `mean-reversion-expert`.

### `volatile`
- Realized volatility in high-tercile or jump-detected.
- ATR(14) > 2× rolling median.
- Order-flow imbalance present (when L2 is available).
- Recommended expert: `microstructure-expert` (only for tier 2A/2B; on tier 2C, fall back to `mean-reversion-expert` with halved size).
