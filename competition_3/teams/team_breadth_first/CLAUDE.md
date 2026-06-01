# Team: team_breadth_first

## Your /autoresearch preset

Wide net of ideas, take the best surface-level signal.

Full invocation lives in `.claude/agents/researcher.md`.

## Inner refinement loop (run inside this Claude session)

Cap: 5 attempts OR competition harness's `per_train_timeout_seconds` (3600 s).

For each attempt `<iter>`:

1. Dispatch the **researcher** agent. It runs the autoresearch invocation and writes `_inbox/research_brief.md`.
2. Dispatch the **strategist** agent. It reads the brief, writes `attempts/<iter>/strategy.py` + `attempts/<iter>/runtime_rules.json`.
3. Dispatch the **risk-officer** agent. It audits both files.
   - FAIL → strategist revises, then risk-officer re-audits. If still FAIL after 2 risk passes, abandon this attempt and start the next.
4. Dispatch the **backtester** agent. It runs train-backtest, writes `attempts/<iter>/backtest_result.json` + `diagnostics.md`.
5. Read `backtest_result.json`:
   - If `pass: true` → COPY this iteration's `strategy.py` to `attempts/<round_iter>/strategy.py` where `<round_iter>` matches the harness iteration index, then EXIT the loop.
   - Else → loop to step 1 with the diagnostics in context for the researcher.

When exiting the loop (pass OR forfeit), write the number of attempts taken to `attempts/<round_iter>/inner_iterations.txt`.

If 5 attempts pass without a passing strategy:
- Write a "hold cash, no orders" strategy.py to `attempts/<round_iter>/strategy.py`.
- Exit with a note that no passing strategy was found this round.

## Don't

- Don't run the autoresearch invocation with different flags than the one in researcher.md — that breaks the ablation.
- Don't write strategy.py outside `attempts/<iter>/` — the harness imports from a specific path.
- Don't touch test or paper windows.
