# /autoresearch knob mapping for the 6 competition_3 teams

**Skill version:** 2.1.2 (cache path) / 2.1.0 (SKILL.md frontmatter version field)
**Skill path:** `/Users/rc/.claude/plugins/cache/autoresearch/autoresearch/2.1.2/skills/autoresearch/SKILL.md`
**Skill type:** hybrid — the main `/autoresearch` command takes structured keyword args (Goal:, Scope:, Metric:, Verify:, Iterations:) and universal flags; the sub-skills each have their own typed flags

## How the skill works (one-paragraph summary)

`/autoresearch` is an autonomous goal-directed iteration framework, NOT a web-search synthesizer. Its core loop is: **modify → verify → keep/discard**, running against a user-defined numeric metric for up to N iterations (default 25). Sub-skills extend this into specialized loops: `/autoresearch:reason` runs adversarial debate with blind judge panels until convergence; `/autoresearch:probe` rotates 8 expert personas to interrogate a topic until constraint saturation; `/autoresearch:scenario` generates edge cases across 12 dimensions; `/autoresearch:predict` convenes 5 expert personas before implementation. Because competition_3 uses these skills for trading-research question analysis rather than code optimization, the relevant sub-skills are `:reason` (for adversarial verification + convergence) and `:probe` (for breadth of persona-driven interrogation), with loop depth controlled via `Iterations:` / `--depth` flags.

## Confirmed knobs

| Knob (our axis) | Skill mechanism | Args / wording | Default | Range / valid values |
|------|-----------|-------|---------|----------------------|
| Breadth | Number of active personas in `/autoresearch:probe` | `--personas N` or `Personas: N` | 6 | 3–8 (integers) |
| Depth | Depth preset in `/autoresearch:probe`, or iteration count in `:reason` | `--depth shallow\|standard\|deep` in `:probe`; `Iterations: N` in `:reason` | standard (15 rounds) for `:probe`; 8 for `:reason` | shallow=5 rounds, standard=15, deep=30, or explicit `Iterations: N`; "unlimited" for unbounded |
| Verification | Number of blind judges in `/autoresearch:reason` | `--judges N` or `Judges: N` | 3 | 3 (default), 5 (thorough), 7 (deep) |
| Loop discipline | Convergence condition in `/autoresearch:reason` | `--convergence N` (stop when incumbent wins N consecutive rounds) or `--mode creative` (never auto-stop) | convergent, stop at 3 consecutive wins | `--convergence N` (integer); `--mode creative` for unbounded; `--mode debate` for no synthesis; first-pass = low `--convergence 1` |

## Sub-skills

| Sub-skill | One-line description |
|---|---|
| `/autoresearch:plan` | Convert a free-form goal into a validated Scope, Metric, and Verify config |
| `/autoresearch:debug` | Hunt bugs via hypothesize → test → falsify loop (default 15 iterations) |
| `/autoresearch:fix` | Crush errors one-by-one until zero remain (default 20 iterations) |
| `/autoresearch:security` | STRIDE + OWASP audit with red-team personas (default 15 iterations) |
| `/autoresearch:ship` | Ship through 8 phases: checklist → dry-run → deploy → verify |
| `/autoresearch:scenario` | Generate edge cases across 12 dimensions (default 20 iterations) |
| `/autoresearch:predict` | 5 expert personas debate a decision before implementation |
| `/autoresearch:learn` | Scout codebase, generate docs, validate, and fix in a loop (default 10 iterations) |
| `/autoresearch:reason` | Adversarial debate with blind judge panel until convergence (default 8 rounds) — primary skill for competition_3 research tasks |
| `/autoresearch:probe` | 8 personas interrogate requirements until constraint saturation (default 15 rounds) — primary skill for breadth/depth axes |
| `/autoresearch:evals` | Analyze iteration results for trends, plateaus, and regressions |

## Preset invocations

The primary sub-skill for competition_3 research is `/autoresearch:reason`, which maps most directly to the breadth/depth/verification/loop axes. Breadth (number of angles explored) is emulated via judge count and synthesizer behavior; depth is emulated via `Iterations:` and `--convergence`; verification panel size is `--judges N`; loop discipline is `--mode` + `--convergence`.

A secondary option is `/autoresearch:probe` for open-ended topic interrogation where the team wants persona-driven breadth across 8 expert viewpoints. Each team's researcher can chain them: `:probe` for initial exploration, then `:reason` for adversarial convergence.

### team_breadth_first

```
/autoresearch:probe Topic: <the question the team investigates> --depth shallow --personas 8 --mode autonomous Iterations: 5
```

Behavioral intent: Activate all 8 personas for maximum breadth, but run only 5 shallow rounds (the `shallow` depth preset). Light verification — no `:reason` follow-up unless explicitly chained. Single pass through the persona rotation.

### team_depth_first

```
/autoresearch:reason Task: <the question the team investigates> Domain: research --judges 3 --convergence 4 Iterations: 12
```

Behavioral intent: Fewer parallel angles (3 judges, no wide probe) but deep iterative refinement — 12 rounds with a convergence threshold of 4 consecutive wins before stopping. Medium verification via 3-judge panel.

### team_adversarial

```
/autoresearch:reason Task: <the question the team investigates> Domain: research --judges 5 --mode convergent --convergence 3 Iterations: 8
```

Behavioral intent: Full 5-judge adversarial panel (the "thorough" setting), medium depth (default 8 rounds), convergent mode. Single pass — stops when a candidate wins 3 consecutive rounds.

### team_speed_run

```
/autoresearch:reason Task: <the question the team investigates> Domain: research --judges 1 --convergence 1 Iterations: 3 --no-synthesis
```

Behavioral intent: Minimal verification — 1 judge, lowest convergence threshold (1 win = done), maximum 3 iterations, synthesis skipped. Fastest possible single pass through the adversarial loop.

### team_balanced

```
/autoresearch:reason Task: <the question the team investigates> Domain: research --judges 3 --convergence 3 Iterations: 8
```

Behavioral intent: All defaults — 3-judge panel, convergence after 3 consecutive wins, 8-iteration cap. This is the control / baseline configuration representing the skill's out-of-the-box behavior.

### team_completeness

```
/autoresearch:reason Task: <the question the team investigates> Domain: research --judges 3 --mode convergent --convergence 3 Iterations: unlimited --evals
```

Behavioral intent: Unbounded iterations (`Iterations: unlimited`) with convergence requiring 3 consecutive wins — meaning the loop continues until the answer truly stabilizes. The `--evals` flag adds mid-loop checkpoints. After two consecutive checkpoints with no improvement (plateau detection), the evals system recommends stopping — emulating "2 dry rounds" of the loop-until-dry preset.

## Limitations / gotchas

- **`/autoresearch` (the base command) is a code-metric optimizer**, not a research synthesizer. The competition should use `/autoresearch:reason` and `/autoresearch:probe` as the primary invocations for question-answer research tasks.
- **`--judges 1` is inferred behavior for team_speed_run**: the `:reason` command documents `--judges N` with values 3, 5, 7. Using `--judges 1` pushes below the documented minimum. If the skill rejects it, substitute `--judges 3 --convergence 1 Iterations: 2 --no-synthesis` as the minimal-verify equivalent.
- **`Iterations: unlimited` requires explicit opt-in** per the SKILL.md safety invariant: "Bounded by default. Override with `Iterations: unlimited`."
- **Convergence threshold `--convergence N`**: defaults to 3. Lowering it accelerates termination; raising it demands more stability before stopping.
- **`--mode creative`** never auto-stops — use only if the team explicitly wants unbounded divergent exploration.
- **`--adversarial` flag in `:probe`** rotates Skeptic, Contradiction Finder, and Edge-Case Hunter to the front of the persona rotation — useful for team_adversarial if they use `:probe` as a preprocessing step.
- **Output directories** are always written to `autoresearch/{subcommand}-{YYMMDD}-{HHMM}/` relative to the working directory. Plan Task 9 should note this when configuring researcher working directories.
- **Chain handoff**: all sub-skills write `handoff.json` and support `--chain <targets>` for sequential pipeline composition (e.g., `--chain reason` after `:probe`).

## Validation

This mapping was verified by: reading `SKILL.md` (the main skill manifest), `commands/autoresearch.md` (the base loop command spec), `commands/autoresearch/reason.md` (the adversarial debate sub-skill with full flag documentation), and `commands/autoresearch/probe.md` (the persona interrogation sub-skill). All flag names, defaults, and valid values are drawn directly from the `argument-hint` frontmatter and `Parse Arguments` sections of those files. Did NOT actually invoke `/autoresearch` (no live Claude session required for this scaffolding task).
