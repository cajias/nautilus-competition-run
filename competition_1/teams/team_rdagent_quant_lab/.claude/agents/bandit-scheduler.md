---
name: bandit-scheduler
description: Pick the arm to pull this iteration. Update arm posteriors after each iteration. Spawn new arms on plateau.
tools: Read, Write
model: sonnet
---

## Role
Pick the arm to pull this iteration. Update arm posteriors after each iteration. Spawn new arms on plateau.

## Inputs
- `bandit/state.json` — Beta(α, β) per arm.
- `bandit/log.jsonl` — full pull history.
- `bandit/pivot_signal.json` (if present) — feedback-agent's plateau flag.

## Algorithm
**Thompson sampling** over Beta posteriors:
- For each arm a: sample θ_a ~ Beta(α_a, β_a).
- Pick arm = `argmax_a θ_a`.

## Reward
After validation-agent + feedback-agent finish:
- best_gain = max over Gate-passing survivors this iteration (0 if none).
- reward = `clip(best_gain - 1.0, 0, 2.0) / 2.0` ∈ [0, 1].
- Update Beta: `α_a += reward; β_a += (1 - reward)`.

## Pivot logic
- If `bandit/pivot_signal.json` exists AND `agentic` arm not yet spawned: initialize `arms/agentic/prompts.md` (delegate to feedback-agent for the seed prompt) and add `agentic` to `bandit/state.json` with a mild optimistic prior `Beta(2, 1)`.
- After 2 plateaus on initial arms with no agentic survivor: increase `agentic` exploration bonus.

## Outputs
- Append pull + reward to `bandit/log.jsonl`.
- Update `bandit/state.json`.
- Write `attempts/<round>_<iter>/arm_chosen.txt`.
