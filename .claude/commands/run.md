---
description: Run a multi-team competition end-to-end. Wraps `compete run <working-dir>`.
argument-hint: "[working-dir] [--run-id <id>] [--paper-duration-minutes <n>] [--rounds <n>]"
allowed-tools: Bash
---

<!--
Usage: /nautilus-competition:run <working-dir> [extra compete-run flags]
Wraps: compete run <working-dir>
Requires: `compete` on PATH (pip install nautilus-competition).
Optional: COMPETE_METRICS_ENDPOINT exported for live Grafana dashboard.
-->

The user invoked `/nautilus-competition:run` with `$ARGUMENTS`. Drive a
multi-team competition end-to-end via the `compete` CLI.

Step 1 — verify the binary is installed:

!`command -v compete >/dev/null 2>&1 && echo COMPETE_OK || echo COMPETE_MISSING`

If the check above prints `COMPETE_MISSING`, **stop** and surface this
install hint to the user verbatim, then exit:

```
The `compete` CLI is not on PATH. This plugin's slash commands delegate
to the locally-installed `compete` binary, which ships via pip:

    pip install nautilus-competition
    # or, until published to PyPI:
    pip install -e <path-to-checkout-of-nautilus-competition>

See plugins/nautilus-competition/README.md "Install" section for the
two-channel install model (APM for the plugin, pip for the CLI).
```

Step 2 — observability nudge. If `COMPETE_METRICS_ENDPOINT` is unset, tell
the user (one short line) that they can `export
COMPETE_METRICS_ENDPOINT=http://localhost:9091` for live Grafana metrics
(see `/nautilus-competition:observability` to bring the stack up). Don't
block on this; it's optional.

Current value: !`echo "COMPETE_METRICS_ENDPOINT=${COMPETE_METRICS_ENDPOINT:-<unset>}"`

Step 3 — run the competition. Forward `$ARGUMENTS` through to `compete run`
verbatim (the first positional is the working-dir; remaining tokens are
flags like `--run-id`, `--paper-duration-minutes`, `--rounds`,
`--metrics-endpoint`):

!`compete run $ARGUMENTS`

Step 4 — interpret the result:

- On success (exit 0): the run wrote to `<working-dir>/runs/<run_id>/`.
  Surface the run_id from stdout (the orchestrator logs it) and point the
  user at `<working-dir>/runs/<run_id>/final_leaderboard.md` for the
  per-round + final standings, plus
  `<working-dir>/runs/<run_id>/round_NN/leaderboard.md` for per-round
  detail. If `COMPETE_METRICS_ENDPOINT` was set, also remind them to open
  http://localhost:3000/d/competition.
- On non-zero exit: surface stderr verbatim. The most common failures are
  (a) "Not a competition folder" — direct user to
  `/nautilus-competition:init`; (b) catalog/instrument precision mismatch —
  refer to the `nautilus-trader-catalog-instrument-precision` skill; (c)
  logger panic on second `BacktestEngine` init — refer to the
  `nautilus-trader-logger-singleton` skill.
