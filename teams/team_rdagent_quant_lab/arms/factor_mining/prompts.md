# arms/factor_mining/prompts.md

**Seed prompt for the synthesis-agent when the bandit pulls the `factor-mining` arm.**

Generate k=8-16 alpha factor expressions in the WorldQuant-101 / Qlib `Alpha158` operator grammar.

Available operators (canonical Alpha158 set; cite `State of the Art… §A`):
- Time-series: `ts_rank`, `ts_max`, `ts_min`, `ts_argmax`, `ts_argmin`, `delta`, `decay_linear`, `correlation`, `ts_cov`, `ts_std`, `ts_sum`
- Cross-sectional: `rank`, `scale`
- Arithmetic: `+`, `-`, `*`, `/`, `abs`, `log`, `sign`
- Conditional: `where`, `if_else`

Inputs available: `open`, `high`, `low`, `close`, `volume`, `vwap` (and any pre-computed Alpha158 features per `notes/alpha158_operators.md`).

Constraints:
- No look-ahead: every operand must reference bar `t` or earlier.
- Mutate accepted ancestors (per forest summary in `attempts/<round>_<iter>/spec.md`) by single-operator substitution where possible — preserves lineage.
- Anti-redundancy: if you generate a factor whose IC correlation with an existing accepted factor exceeds 0.8 on training data, mark it `parent_id=<that-factor-id>` and call it a refinement rather than a new node.

Output format (per `synthesis-agent.md`): k entries, each with `hypothesis_text` (the factor expression as a string), `parent_id`, `rationale`, `predicted_failure_mode`.
