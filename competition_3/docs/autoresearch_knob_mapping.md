# /autoresearch knob mapping for the 6 competition_3 teams

**Skill version:** 2.1.2 (cache path) / 2.1.0 (SKILL.md frontmatter version field)
**Skill path:** `/Users/rc/.claude/plugins/cache/autoresearch/autoresearch/2.1.2/skills/autoresearch/SKILL.md`
**Skill type:** BASE `/autoresearch` — autonomous `modify → verify → keep/discard` loop

## Correction notice (2026-06-02)

An earlier version of this document (v1) incorrectly steered the 6 teams onto
`/autoresearch:reason` and `/autoresearch:probe` sub-skills. Those sub-skills
are for qualitative investigation with NO verify function. Competition_3 HAS a
verify function (`gain > 1.0 AND win_rate >= 0.5` on the train-window backtest).
All 6 teams now use the BASE `/autoresearch` skill with per-team preset wording.

## How the base skill works (one-paragraph summary)

`/autoresearch` is an autonomous goal-directed iteration framework. Its core
loop is: **modify → verify → keep/discard**, running against a user-defined
metric for up to N iterations (default 25, opt-in unlimited). Structured
keyword args (`Goal:`, `Scope:`, `Metric:`, `Verify:`, `Iterations:`) define
the optimization problem; universal flags (`--evals`, `--evals-interval N`,
`--chain <targets>`) add checkpointing and pipeline composition. Results land
in `autoresearch/autoresearch-{YYMMDD}-{HHMM}/`.

## Confirmed knobs (real vs. emulated)

The base skill exposes two real runtime knobs and the rest are emulated via
prompt wording (the Scope/Goal/Metric args).

| Knob (our axis) | Real or emulated | Mechanism |
|---|---|---|
| Iteration budget | **Real** | `Iterations: N` (default 25; `Iterations: unlimited` to opt-in) |
| Mid-loop checkpoints | **Real** | `--evals` flag + `--evals-interval N` |
| Modification breadth | **Emulated** | Scope: wording — wide ("any signal logic, any indicator, any parameter") vs. narrow ("only adjust indicator periods") |
| Acceptance strictness | **Emulated** | Metric:/Goal: wording — strict gate ("must exceed threshold by 5%") vs. first-pass ("accept first strategy clearing the gate") |
| Verification depth | **Emulated** | Verify: command — fast smoke test vs. full walk-forward backtest |
| Stop condition | **Emulated** | Iterations: cap + `--evals` plateau detection vs. explicit "stop when no improvement for K rounds" in Goal: |

## Verify command (shared across all 6 teams)

```
Verify: uv run python backtest.py --strategy attempts/<iter>/strategy.py
```

Pass gate: `gain_train > 1.0 AND win_rate_train >= 0.5`
Score: `composite = gain_factor × win_rate`

## Preset invocations

### team_breadth_first

Behavioral intent: explore many different modifications per iteration (wide Scope), accept the first strategy that clears the gate. Low iteration budget because the team expects one of the early broad candidates to pass.

```
/autoresearch
Goal: Explore a wide range of strategy types (momentum, mean-reversion, breakout,
      multi-asset) and accept the first strategy that clears the pass gate.
      Do NOT re-iterate if a passing strategy is found on attempt 1.
Scope: strategy.py — any signal type, any of the 10 catalog symbols, any indicator
       period, any position-sizing scheme. No constraints on approach.
Metric: composite = gain_factor × win_rate; gate: gain_train > 1.0 AND win_rate_train >= 0.5
Verify: uv run python backtest.py --strategy attempts/<iter>/strategy.py
Iterations: 5
```

### team_depth_first

Behavioral intent: commit to one promising approach early, then refine it deeply across many iterations. Narrow Scope (fewer but carefully chosen modifications), full iteration budget.

```
/autoresearch
Goal: Identify the single most promising strategy type from the diagnostics,
      then refine it across as many iterations as the budget allows.
      Prefer deep refinement of one approach over exploring new approaches.
Scope: strategy.py — refine indicator periods, signal thresholds, and position
       sizing for the approach chosen on iteration 1. Do NOT switch strategy type
       mid-run unless the backtester confirms zero chance of passing.
Metric: composite = gain_factor × win_rate; gate: gain_train > 1.0 AND win_rate_train >= 0.5;
        secondary: maximize composite margin above gate (not just barely pass)
Verify: uv run python backtest.py --strategy attempts/<iter>/strategy.py
Iterations: 5
--evals --evals-interval 2
```

### team_adversarial

Behavioral intent: after each accepted change, apply a stricter re-verify gate before committing. Any strategy that passes must also pass a higher bar (e.g., composite > 1.2) before being accepted as the round winner.

```
/autoresearch
Goal: Find a strategy that not only clears the minimum gate (gain > 1.0,
      win_rate >= 0.5) but also achieves composite >= 1.2. Treat the minimum
      gate as necessary but not sufficient. After each candidate clears the
      minimum, run a stricter check: composite must exceed 1.2, else treat
      as a soft fail and continue iterating.
Scope: strategy.py — any modification, but prefer modifications that increase
       composite headroom rather than just barely clearing the gate.
Metric: primary: composite = gain_factor × win_rate; hard gate: gain > 1.0 AND
        win_rate >= 0.5; adversarial gate: composite > 1.2 (soft — loop continues
        if not met, but accept if iteration budget exhausted)
Verify: uv run python backtest.py --strategy attempts/<iter>/strategy.py
Iterations: 5
--evals
```

### team_speed_run

Behavioral intent: minimum iteration budget, accept the very first strategy that clears the gate. No refinement after first pass. Get to paper trading as fast as possible.

```
/autoresearch
Goal: Accept the first strategy that clears the pass gate. Stop immediately
      on first pass — do NOT continue iterating to improve composite.
      Speed over margin.
Scope: strategy.py — pick the highest prior-probability approach (momentum on
       BTC/ETH) and implement it directly. One modification type only.
Metric: gate: gain_train > 1.0 AND win_rate_train >= 0.5; accept on first pass
Verify: uv run python backtest.py --strategy attempts/<iter>/strategy.py
Iterations: 3
```

### team_balanced

Behavioral intent: all defaults — median breadth, median iteration depth, accept first passing strategy. This is the control / baseline configuration.

```
/autoresearch
Goal: Find a reliable strategy that clears the pass gate. Balance exploration
      of different approaches with refinement of promising ones.
Scope: strategy.py — consider 2-3 strategy types on iteration 1, then refine
       the most promising across remaining iterations.
Metric: composite = gain_factor × win_rate; gate: gain_train > 1.0 AND win_rate_train >= 0.5
Verify: uv run python backtest.py --strategy attempts/<iter>/strategy.py
Iterations: 5
```

### team_completeness

Behavioral intent: loop until no improvement for K consecutive iterations (plateau condition). Unbounded iteration within the competition's 3600 s wall clock. Use `--evals` for plateau detection and let the evals system signal when to stop.

```
/autoresearch
Goal: Maximize composite = gain_factor × win_rate. Keep iterating until two
      consecutive iterations produce no composite improvement (plateau). Do NOT
      stop early on first pass — always attempt to improve margin.
Scope: strategy.py — full modification freedom: signal type, asset selection,
       indicator tuning, position sizing, risk rules. Re-evaluate approach
       every 2 iterations based on evals output.
Metric: composite = gain_factor × win_rate; hard gate: gain_train > 1.0 AND
        win_rate_train >= 0.5; loop exit: 2 consecutive iterations with delta(composite) < 0.01
Verify: uv run python backtest.py --strategy attempts/<iter>/strategy.py
Iterations: unlimited
--evals --evals-interval 1
```

## Which knobs are real vs. emulated — summary

| Team | Real knob used | Emulated via prompt |
|---|---|---|
| team_breadth_first | `Iterations: 5` | Wide Scope:, first-pass accept in Goal: |
| team_depth_first | `Iterations: 5`, `--evals` | Narrow Scope:, refine-not-switch in Goal: |
| team_adversarial | `Iterations: 5`, `--evals` | Stricter composite gate in Metric:/Goal: |
| team_speed_run | `Iterations: 3` | Accept-on-first-pass in Goal:, narrow Scope: |
| team_balanced | `Iterations: 5` | Balanced Goal: wording (control) |
| team_completeness | `Iterations: unlimited`, `--evals --evals-interval 1` | Plateau condition in Goal:/Metric: |

## Sub-skills reference (not used in this competition)

| Sub-skill | When to use instead |
|---|---|
| `/autoresearch:plan` | Convert free-form goal into Scope/Metric/Verify before first run |
| `/autoresearch:reason` | Adversarial debate of a CLAIM with no verify function |
| `/autoresearch:probe` | 8-persona topic interrogation with no verify function |
| `/autoresearch:evals` | Analyze completed run results post-hoc |
| `/autoresearch:debug` | Bug hunting (not metric optimization) |

## Limitations / gotchas

- **`Iterations: unlimited` requires explicit opt-in** per the SKILL.md safety invariant: "Bounded by default. Override with `Iterations: unlimited`."
- **Wall-clock cap**: the competition harness enforces `per_train_timeout_seconds = 3600 s`. `Iterations: unlimited` is bounded in practice by that wall clock — not by the skill.
- **Output directories** always land in `autoresearch/autoresearch-{YYMMDD}-{HHMM}/` relative to the working directory.
- **Chain handoff**: use `--chain evals` to run the evals sub-skill automatically after the base loop completes.
- **Prior version of this doc** used `:reason`/`:probe` flags (`--judges N`, `--convergence N`, `--personas N`). Those are WRONG for the base skill — the base skill does not accept those flags.

## Validation

This mapping was verified by: reading `SKILL.md` v2.1.0 (the main skill manifest at the cache path above). All keyword arg names (`Goal:`, `Scope:`, `Metric:`, `Verify:`, `Iterations:`) and universal flags (`--evals`, `--chain`) are drawn directly from the SKILL.md table. The sub-skill flags (`--judges`, `--convergence`, `--personas`) that appeared in v1 of this doc belong to `:reason`/`:probe` sub-skills and have been removed.
