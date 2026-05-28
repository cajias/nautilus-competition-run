# Round 0, iter 1 thesis

- prev_gain (on entry): -0.004682300529999961
- feature_shortlist: ['realized_skew_20', 'vw_momentum_residual_20', 'har_rv_5']
- model_head: logistic
- label_horizon_bars: 8

## Rules crystallized for trade-time
```json
{
  "drawdown_cap_pct": 0.2,
  "position_size_cap_pct": 0.3,
  "vol_target_annualized": 0.18,
  "regime_gate": {
    "realized_vol_annualized_max": 2.5
  },
  "label_horizon_bars": 8,
  "prediction_threshold_long": 0.6,
  "prediction_threshold_flat": 0.5
}
```

## Validation (CPCV on train window)
```json
{
  "folds": [
    0.49661966389801043,
    0.5153563840061812,
    0.5112999806837937,
    0.525980297469577,
    0.5068519590812585
  ],
  "mean_accuracy": 0.5112216570277641,
  "n_samples": 25889,
  "n_folds": 5
}
```
