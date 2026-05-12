# team_moskowitz_tsmom_desk — Systematic Time-Series Momentum Desk

> **Persona motto.** "If you can't explain the trade with a paper citation, don't take it."

We are a classical systematic **Time-Series Momentum (TSMOM)** desk built
around a transparent, fully-auditable stack: long-lookback TSMOM sign as
the primary signal, Keltner(20,2) breakout as a confirmation gate, ATR(20)
expansion as the regime filter, and EWMA(64)-based volatility targeting as
the sole position-sizing mechanism. No LLM at trade time. No ML. No TSFM.
Every parameter is pinned to a paper. Every trade is explainable in one
sentence.

## SOTA basis

- **Moskowitz, Ooi, Pedersen (2012)** "Time Series Momentum" — *Journal
  of Financial Economics*, 104(2), 228–250. The canonical TSMOM paper.
  Establishes that past 12-month excess return predicts next-month sign
  across 58 instruments; shows 1 vs 12 month lookback dominance, vol-
  scaling to a target, and the famous "TSMOM is the crisis alpha"
  finding. We port the sign-based rule to intraday crypto — see also
  our project's `docs/state-of-the-art/State of the Art in Quantitative
  Trading and Age.md` paragraph citing "Time-series momentum (Moskowitz
  2012) generalizes to crypto with Sharpe ~0.7 net of costs".
- **Hurst, Ooi, Pedersen (2017)** "A Century of Evidence on
  Trend-Following Investing" — *Journal of Portfolio Management*, 44(1),
  15–29. Establishes the robustness of short + long TSMOM blends across
  a century of data. Motivates our fast/slow pair (5-bar-equivalent
  short TSMOM + 28-bar-equivalent long TSMOM) rather than a single
  lookback.
- **Chester W. Keltner (1960)** "How to Make Money in Commodities" —
  origin of the Keltner channel (SMA ± k×ATR). We use Keltner(20, k=2)
  as a breakout confirmer: TSMOM sign is necessary, channel breach is
  the trigger. This is the classical "don't fade a trend that hasn't
  broken out yet" filter.
- **Wilder (1978) "New Concepts in Technical Trading Systems"** — ATR
  definition we use for the Keltner band and for the ATR-expansion gate
  (current ATR / trailing ATR).
- **`docs/state-of-the-art/Fast Trading on Binance with NautilusTrader:
  A S.md` §5C & §7** — Nautilus `RiskEngine`, bar precision, order
  submission patterns.

Primary scoring dimension: **`total_return`** (0.4 weight in composite).
TSMOM's structural edge is *direction* in trending regimes; Sharpe (0.4)
is secondary but defended by the vol-target; drawdown (0.2) defended by
the mom-reversal exit and the ATR-expansion gate.

## Runtime pattern — **HYBRID train-time agent + deterministic trade-time**

This is a **multi-agent system inside `train(ctx)`**, not a single
persona. The agents are classical desk roles, and only ONE of them
(the researcher) spawns a Claude subprocess. The other seven are
deterministic Python.

**Train-time (budget: 600s total, researcher ~120s of that):**

1. **researcher** — `agent_runner.run_claude(...)`. Reads
   `docs/state-of-the-art/` for momentum sections; reads peer teams'
   `notes/`; externally cites Moskowitz 2012, Hurst/Ooi/Pedersen 2017,
   vol-targeting lit. Writes `notes/research_log.md` (append-only) and
   `attempts/<iter>/research.md` (per-iteration). On a failed
   `prev_gain`, researcher is primed with "last run LOST money — propose
   alternate TSMOM lookback pair OR alternate trend definition". Cached
   on disk; re-read if the round's `research_log.md` already has a
   fresh stanza (cheap skip path).
2. **hypothesis-generator** — deterministic. Proposes a TSMOM lookback
   pair (short, long) in bars, a Keltner channel width `k`, an ATR
   expansion ratio, and a vol-target annualized sigma. First iter
   defaults: short=5 bars, long=28 bars-of-days (= 28×288 = 8064 5-min
   bars) fast-EWMA approximation, channel_k=2.0, atr_ratio=1.2,
   vol_target=0.15 ann. Retries perturb based on `ctx.prev_gain`.
3. **critic** — deterministic. Flags: whipsaw risk if `long/short < 4`;
   overfit lookbacks if short or long is prime-number-cute; cost-
   blindness if expected flip rate > 1/hour (at 5-min bars, >12 flips/day).
4. **risk-officer** — deterministic. Writes `runtime_rules.json`:
   `max_leverage`, `drawdown_circuit_breaker`, `mom_reversal_exit`,
   `per_bar_notional_cap`, plus — critically — the **momentum carry-
   forward state** (see below).
5. **memory-keeper** — deterministic. Appends the round's thesis and
   knobs to `notes/memory.md` (append-only). Reads
   `ctx.prev_round_leaderboard` if present to record relative rank vs
   peers.
6. **momentum-signal-designer** — deterministic. Calibrates the short &
   long TSMOM EWMA spans on the **train window only**, loading bars via
   `ctx.get_train_data()`. Computes the final bar's EWMA state
   (momentum value AND its internal EWMA accumulator) and hands it to
   risk-officer for persistence.
7. **vol-targeter** — deterministic. Calibrates the EWMA(64) realized
   vol span + target-vol level on the train window. Tunes so that
   median position size sits in [0.3, 0.8] of equity.
8. **breakout-confirmer** — deterministic. Calibrates the Keltner
   channel width and ATR expansion ratio on the train window. Measures
   out-of-sample on the test window (single shot; no peeking at eval).

**Total: 8 roles.** All 8 are listed in `entry.py` docstrings.

**Trade-time (pure deterministic Python, NO LLM):**

- The Strategy reads `runtime_rules.json` in `on_start` — this includes
  the **final-train-bar momentum state** (see Gotchas §5).
- `on_bar`: (a) update short & long TSMOM incrementally via EWMA
  recursion (NOT full recomputation — that would need 8k bars of
  lookback but paper only gives 3 bars at 5-min bars × 15min duration);
  (b) update Keltner(20,2) on live bars; (c) update ATR(20) and
  ATR-trailing; (d) evaluate the stacked gate:
  `sign(TSMOM_long) == sign(TSMOM_short)` AND close breaches the
  Keltner band in that direction AND `ATR_now / ATR_trail >= ratio`;
  (e) vol-target position size; (f) submit market order or flat.
- Exit rule: flip when long-TSMOM sign flips (Moskowitz's original
  rule), or when drawdown circuit-breaker trips, whichever first.
- **Live critic**: `runtime_rules.json` carries a `critic_veto` dict
  (e.g. "no new entry if ATR_now < 0.5 * ATR_trail"). Pure Python check;
  no LLM.

## The 8 roles (summary table)

| # | Role | When | Train-time tool | Persists to |
|---|------|------|-----------------|-------------|
| 1 | researcher | train iter 0 (or on prev_gain < 0) | `run_claude(...)` ~120s | `notes/research_log.md`, `attempts/<iter>/research.md` |
| 2 | hypothesis-generator | every train iter | pure Python | in-memory |
| 3 | critic | every train iter | pure Python | `attempts/<iter>/critic.md` |
| 4 | risk-officer | every train iter | pure Python | `runtime_rules.json` |
| 5 | memory-keeper | every train iter | pure Python | `notes/memory.md` |
| 6 | momentum-signal-designer | every train iter | pure Python (pandas/numpy) | → risk-officer |
| 7 | vol-targeter | every train iter | pure Python (pandas/numpy) | → risk-officer |
| 8 | breakout-confirmer | every train iter | pure Python (pandas/numpy) | → risk-officer |

## The momentum-carry-forward problem

**Problem.** Our long TSMOM is a 28-day lookback. On 5-min bars that's
`28 × 24 × 12 = 8064 bars`. But the paper window is only 9 days, and
the live `paper.duration_minutes: 15` means the Strategy will see **3
bars** before the harness ends the trial. A 28-day EWMA cannot warm up
in 3 bars. The eval window (21d) gives 6048 bars — still short of 8064.

**Solution.** At the end of `train()`, `momentum-signal-designer`
computes the **final EWMA state** (value + internal accumulator) over
the train window's 21k+ bars and persists it to `runtime_rules.json`.
The Strategy initializes its EWMA state FROM that file in `on_start`.
This is the crypto equivalent of "load the model weights from disk",
except the "model" is one floating-point number per momentum lookback.
This is legal: the train window is explicitly handed to us by
`ctx.get_train_data()`; we do NOT peek at eval or paper.

**Drift risk.** The eval window starts ~28 days after the train window
ends. The EWMA state we persist is stale by that much. Mitigation:
risk-officer sets `mom_reversal_exit=True` so that if the sign was
wrong at hand-off, we flip within a few bars of eval start.

## Hard rules

- **Strategy API discipline.** `InstrumentId.from_str(...)`,
  `BarType.from_str(...)`, `self.order_factory.market(...)` with
  `self.submit_order(order)`. No `Strategy.buy`. No constructing
  instruments (`self.cache.instrument(...)` only). See gotchas.
- **Logger singleton.** Do not re-init Nautilus logging if the engine
  is instantiated twice in-process (skill:
  `nautilus-trader-logger-singleton`).
- **Catalog-loaded instruments.** The harness loads the instrument from
  the same catalog that holds the bars, so precisions match (skill:
  `nautilus-trader-catalog-instrument-precision`). We fetch via
  `self.cache.instrument(self.config.instrument_id)`.
- **No look-ahead.** `momentum-signal-designer`, `vol-targeter`, and
  `breakout-confirmer` ingest only `ctx.get_train_data()`. The test
  window is used ONCE for a single OOS sanity check to decide whether
  to accept the fit. NEVER eval or paper.
- **Train/test discipline.** If test-window Sharpe on the fit config is
  negative, retry with perturbed knobs (iteration up to
  `config.agent.max_train_iterations = 5`).

## Files this team owns

```
team_moskowitz_tsmom_desk/
├── CLAUDE.md                       # this file
├── entry.py                        # train(ctx) → (Strategy, StrategyConfig)
├── runtime_rules.json              # written each train iter, loaded by Strategy
├── attempts/<iter>/
│   ├── research.md                 # researcher subagent output (iter 0 or on loss)
│   └── critic.md                   # deterministic critic notes
├── notes/
│   ├── research_log.md             # researcher append-only across rounds
│   └── memory.md                   # memory-keeper append-only thesis log
└── incoming/                       # harness-owned: round leaderboards
```

## Scoring interpretation

- **total_return 0.4** — our primary edge. Long-only-or-flat in up-
  trends, short-only-or-flat in down-trends, flat when gate rejects.
- **sharpe 0.4** — defended by vol-target (we size down when realized
  vol rises) and by mom-reversal exit.
- **max_drawdown 0.2** — defended by the ATR-expansion gate (we skip
  choppy low-vol regimes) and the drawdown circuit-breaker.

## Failure modes to watch

1. **Lookback drift** — the 28-day state persisted from train is stale
   by ~28 days when eval starts. Trust the mom-reversal exit.
2. **Whipsaw in range-bound regimes** — Keltner + ATR-expansion gate
   should cut these. If `prev_gain < 0`, critic will suspect the gate
   is too loose.
3. **Vol-target mis-calibration** — median size should land in [0.3,
   0.8] equity on the train window. If not, vol-targeter re-spans.
4. **Precision mismatch at BacktestEngine.run()** — skill:
   `nautilus-trader-catalog-instrument-precision`. We load instrument
   only via `self.cache.instrument(...)`; harness seeds cache from
   catalog.
