---
description: Scaffold a fresh competition working directory (config.yaml, teams/, data/catalog/).
argument-hint: "[target-path] [--force]"
allowed-tools: Bash
---

<!--
Usage: /nautilus-competition:init <target-path> [--force]
Wraps: compete init <target-path>
Requires: `compete` on PATH (pip install nautilus-competition).
-->

The user invoked `/nautilus-competition:init` with `$ARGUMENTS`. Scaffold a
fresh competition working directory.

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

Step 2 — scaffold the working dir. Forward `$ARGUMENTS` so flags like
`--force` pass through:

!`compete init $ARGUMENTS`

Step 3 — interpret the result:

- On success (exit 0): the CLI prints "Initialized competition folder at
  <path>" plus a numbered next-steps list. Echo those next-steps back to
  the user, and additionally hint that:
    - `/nautilus-competition:init-team <working-dir> <team-name>` scaffolds
      a team folder under the new working dir;
    - `/nautilus-competition:run <working-dir>` runs the competition once
      teams are populated and `data/catalog/` is seeded;
    - the seeded `config.yaml` ships as a template with placeholder
      windows/instrument that the user must edit before running.
- On non-zero exit: surface stderr verbatim. The common failure is the
  target path being non-empty without `--force`; recommend
  `/nautilus-competition:init <path> --force` only if the user confirms
  they're OK overwriting.
