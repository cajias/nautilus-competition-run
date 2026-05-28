# Round 0, iter 3 thesis

- prev_gain (on entry): -0.0040888787199999665
- feature_shortlist: ['vw_momentum_residual_20', 'realized_skew_20', 'har_rv_5']
- model_head: logistic
- label_horizon_bars: 6

## Rules crystallized for trade-time
```json
{
  "drawdown_cap_pct": 0.2,
  "position_size_cap_pct": 0.3,
  "vol_target_annualized": 0.25,
  "regime_gate": {
    "realized_vol_annualized_max": 2.5
  },
  "label_horizon_bars": 6,
  "prediction_threshold_long": 0.6,
  "prediction_threshold_flat": 0.5
}
```

## Validation (CPCV on train window)
```json
{
  "folds": [
    0.48725376593279257,
    0.5133256083429896,
    0.5102356122054847,
    0.5106218617226729,
    0.5155435412241746
  ],
  "mean_accuracy": 0.5073960778856229,
  "n_samples": 25891,
  "n_folds": 5
}
```
