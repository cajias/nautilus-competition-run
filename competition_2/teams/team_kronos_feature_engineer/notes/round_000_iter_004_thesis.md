# Round 0, iter 4 thesis

- prev_gain (on entry): 0.0
- feature_shortlist: ['har_rv_1', 'har_rv_5', 'har_rv_22', 'realized_skew_20', 'vw_momentum_residual_20']
- model_head: lightgbm
- label_horizon_bars: 12

## Rules crystallized for trade-time
```json
{
  "drawdown_cap_pct": 0.2,
  "position_size_cap_pct": 0.3,
  "vol_target_annualized": 0.25,
  "regime_gate": {
    "realized_vol_annualized_max": 3.0
  },
  "label_horizon_bars": 12,
  "prediction_threshold_long": 0.6,
  "prediction_threshold_flat": 0.5
}
```

## Validation (CPCV on train window)
```json
{
  "folds": [
    0.515549546069152,
    0.5205717597063937,
    0.5111068186208229,
    0.5329341317365269,
    0.514390573691327
  ],
  "mean_accuracy": 0.5189105659648445,
  "n_samples": 25885,
  "n_folds": 5
}
```
