# competition_2 — Competition-Level Rules

## Scope

This file is inherited by every team session under `competition_2/teams/*`. It
defines the **rules of the game** that the harness enforces. Per-team strategy
lives in each team's own `CLAUDE.md`; the rules below override nothing there but
are non-negotiable.

## Competition Rules

### Round structure

Each round runs in two phases, in order:

1. **Eval** — `train(ctx)` fits a strategy on the train window, then the harness
   backtests it on the **eval window** (strict OOS).
2. **Paper** — only iterations that **pass the eval gate** advance to paper
   trading (live testnet or simulated paper, per `config.yaml paper.mode`).

A team that never passes the gate in a round produces **zero paper output** for
that round. The round still completes; the team's composite for the round is
`0.0`.

### The eval gate (THE rule)

An iteration advances to paper **iff**:

```
gain_factor > 1.0
```

i.e. final_eval_equity **strictly greater than** starting_eval_equity. This is
the gate at `nautilus_competition/orchestrator.py` (~line 232,
`if ev.gain_factor > 1.0:`).

- Breakeven (`gain_factor == 1.0`) does **NOT** advance.
- A flat strategy that never trades has `gain_factor == 1.0` exactly. It will
  **NOT** advance. "Trade nothing and survive" is not a viable submission.
- The comparison is strict. `1.0000001` advances; `1.0` does not.

### Iteration budget

- Each team gets up to `agent.max_train_iterations` attempts per round (default
  **5** in the active `config.yaml`).
- The **first** iteration that crosses the gate ends the round. Remaining
  iterations are not consumed.
- Iterations are 0-indexed: `ctx.iteration ∈ {0, 1, …, max-1}`.

### Failure mode (expected, not a bug)

If a team exhausts its budget without crossing the gate:

- The harness writes `FAILED.json` with `cause: "max_iterations_exhausted"`.
- The paper directory stays empty for that team.
- The team's round composite is `0.0`.

This is **expected behavior**. It signals: the strategy class is wrong for
this round — change it next round, do not file a bug.

### Implications for teams (actionable)

The harness passes `ctx.prev_gain = last_eval_gain_factor - 1.0` on retries
(`ctx.iteration > 0`). Use it to steer:

| `prev_gain` | Verdict | Required response |
|---|---|---|
| `< 0` | Losing strategy | **Swap paradigm.** Different signal family (momentum→mean-reversion), different feature class (price→volume), different gate (regime-conditional). Do NOT just perturb parameters within a losing family. |
| `[0, 0.05)` | Marginal positive | Tune within the paradigm. Threshold, sizing, regime filter. |
| `≥ 0.05` | Strong positive | Already crossing the gate. Submit and move on. Don't over-fit. |

**Decide early.** If iter 0 returns `gain_factor < 0.95`, swap on iter 1 — do
not burn budget tuning a known loser. The budget is 5 iterations, not 50.

## Cross-references

- **Operator skill** `nautilus-competition-operator` — full operator-side
  semantics (round driver, leaderboard, FAILED.json triage).
- **Team-author skill** `nautilus-competition-team-author` — full
  `prev_gain` / iteration contract from the team side.
- **Source of truth** — `nautilus_competition/orchestrator.py`, the gate at
  `if ev.gain_factor > 1.0:` (~line 232).

## Per-team work

Per-team strategy, persona, roster, and runtime contract live in each team's
own `CLAUDE.md` under `competition_2/teams/<team>/`. The rules above are the
floor every team must respect; what each team does on top of that floor is the
team's own design.
