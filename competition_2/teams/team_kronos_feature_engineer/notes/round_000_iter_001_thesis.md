# Round 0, iter 1 thesis

- prev_gain (on entry): -0.0007280968999999748
- feature_shortlist: ['har_rv_1', 'har_rv_5', 'har_rv_22', 'realized_skew_20', 'vw_momentum_residual_20']
- model_head: logistic
- label_horizon_bars: 12

## Rules crystallized for trade-time
```json
{
  "drawdown_cap_pct": 0.15,
  "position_size_cap_pct": 0.45,
  "vol_target_annualized": 0.2,
  "regime_gate": {
    "realized_vol_annualized_max": 1.8
  },
  "label_horizon_bars": 12,
  "prediction_threshold_long": 0.55,
  "prediction_threshold_flat": 0.5
}
```

## Validation (CPCV on train window)
```json
{
  "folds": [
    0.5244222063378604,
    0.5256135334762926,
    0.5265665951870384,
    0.5256135334762926,
    0.5379671506784099
  ],
  "mean_accuracy": 0.5280366038311788,
  "n_samples": 20989,
  "n_folds": 5
}
```
