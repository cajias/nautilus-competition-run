# Round 0, iter 4 thesis

- prev_gain (on entry): -0.0007280968999999748
- feature_shortlist: ['realized_skew_20', 'vw_momentum_residual_20']
- model_head: lightgbm
- label_horizon_bars: 3

## Rules crystallized for trade-time
```json
{
  "drawdown_cap_pct": 0.15,
  "position_size_cap_pct": 0.35,
  "vol_target_annualized": 0.2,
  "regime_gate": {
    "realized_vol_annualized_max": 4.0
  },
  "label_horizon_bars": 3,
  "prediction_threshold_long": 0.55,
  "prediction_threshold_flat": 0.5
}
```

## Validation (CPCV on train window)
```json
{
  "folds": [
    0.5267920933555609,
    0.5241724220052394,
    0.5286973088830674,
    0.5163134079542748,
    0.5364112327463113
  ],
  "mean_accuracy": 0.5264772929888908,
  "n_samples": 20998,
  "n_folds": 5
}
```
