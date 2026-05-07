# arms/model_search/prompts.md

**Seed prompt for the synthesis-agent when the bandit pulls the `model-search` arm.**

Generate k=8-16 (architecture, hyperparameter) tuples to train an ML model on the fixed feature bundle (Qlib `Alpha158` features).

Available architectures:
- LightGBM (gradient-boosted trees)
- TabNet (attentive transformer for tabular)
- TFT (Temporal Fusion Transformer)
- TRA (Temporal Routing Adaptor — RD-Agent's reference baseline)
- LSTM (lightweight 1-2 layer)
- LinearRidge (baseline; submit if all complex models overfit)

Hyperparameter axes per architecture (suggested ranges):
- LightGBM: `num_leaves [15, 63]`, `max_depth [3, 8]`, `learning_rate [0.01, 0.1]`, `n_estimators [100, 1000]`
- TabNet: `n_d [8, 64]`, `n_steps [3, 10]`, `gamma [1.0, 2.0]`
- TFT: `hidden_size [16, 64]`, `num_heads [1, 4]`, `dropout [0.1, 0.3]`
- TRA: per RD-Agent paper defaults
- LSTM: `hidden [32, 128]`, `num_layers [1, 2]`, `dropout [0.1, 0.3]`

Constraints:
- All models trained on training window only; CPCV with embargo for IS evaluation.
- Predict next-bar return (regression) or next-bar return-sign (classification, then map back to size).
- Strategy translates prediction into position via fixed sizing rule.

Output format (per `synthesis-agent.md`): k entries, each with `hypothesis_text` (architecture + hyperparams as YAML), `parent_id`, `rationale`, `predicted_failure_mode`.
