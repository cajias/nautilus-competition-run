---
description: Scaffold a new team folder inside an existing competition working directory.
argument-hint: "[working-dir] [team-name] [--force]"
allowed-tools: Bash
---

<!--
Usage: /nautilus-competition:init-team <working-dir> <team-name> [--force]
Wraps: compete init-team <working-dir> <team-name>
Requires: `compete` on PATH (pip install nautilus-competition).
Working-dir must already be a competition folder (contains config.yaml + teams/).
-->

The user invoked `/nautilus-competition:init-team` with `$ARGUMENTS`. Scaffold
a new team folder inside an existing competition.

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

Step 2 — scaffold the team folder. The CLI takes two positionals
(`<working-dir> <team-name>`) plus an optional `--force` flag; forward
`$ARGUMENTS` verbatim:

!`compete init-team $ARGUMENTS`

Step 3 — interpret the result:

- On success (exit 0): the CLI prints "Created team folder at
  <working-dir>/teams/<team-name>" plus a hint about the two seeded files
  (`CLAUDE.md` and `entry.py`). Echo that back, then add:
    - The team's `CLAUDE.md` is a persona placeholder; the user should
      replace the TODOs with the team's actual strategy thesis.
    - The seeded `entry.py` is a buy-and-hold placeholder; the
      `nautilus-competition-team-author` skill (auto-loaded when authoring
      a team) covers the full `train(ctx) -> (Strategy, StrategyConfig)`
      contract.
    - Once the team is customized, `/nautilus-competition:run
      <working-dir>` will pick it up automatically.
- On non-zero exit: surface stderr verbatim. The common failures are (a)
  "Not a competition folder" — recommend
  `/nautilus-competition:init <working-dir>` first; (b) the team folder
  already exists non-empty — recommend `--force` only if the user confirms
  they're OK overwriting.
