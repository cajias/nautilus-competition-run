# Round 0, iter 2 thesis

- prev_gain (on entry): 0.0
- feature_shortlist: ['har_rv_22', 'har_rv_5', 'realized_skew_20', 'vw_momentum_residual_20']
- model_head: lightgbm
- label_horizon_bars: 12

## Rules crystallized for trade-time
```json
{
  "drawdown_cap_pct": 0.15,
  "position_size_cap_pct": 0.3,
  "vol_target_annualized": 0.18,
  "regime_gate": {
    "realized_vol_annualized_max": 2.0
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
    0.5111068186208229,
    0.5252076492176937,
    0.5039598222909021,
    0.5238555147768978,
    0.520185435580452
  ],
  "mean_accuracy": 0.5168630480973537,
  "n_samples": 25885,
  "n_folds": 5
}
```
