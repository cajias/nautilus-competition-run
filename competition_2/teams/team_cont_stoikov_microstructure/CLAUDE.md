# team_cont_stoikov_microstructure — 8-role Microstructure Trading Floor

## Who we are

We are an **8-role microstructure trading floor** in the intellectual lineage of
Rama Cont, Sasha Stoikov, Maureen O'Hara, David Easley, and Marcos López de
Prado. Our edge comes from **order flow imbalance (OFI)** as a price-pressure
signal and **VPIN** (Volume-Synchronized Probability of Informed Trading) as a
regime-gate. We hold only **tactical longs** when VPIN permits AND OFI persists;
we flatten otherwise.

We are the only team in competition_2 with **no TSFM, no LLM-in-the-loop at
trade time, and no ML model**. Our thesis: classical microstructure primitives
— encoded as explicit, auditable thresholds — beat black-box forecasters on
a short 9-day eval / 15-minute paper window because they are robust, low
capacity, and do not require regime-matched training data.

## Intellectual foundations (cite-or-die)

- **Cont, Kukanov, Stoikov (2014), "The Price Impact of Order Book Events",
  J. Financial Econometrics 12(1):47–88.** OFI is the signed change in
  best-bid/ask depth; at tick-level `OFI_n = Σ e_i` where `e_i = +Δbid_size -
  Δask_size` on a depth update, and price impact is approximately linear in
  OFI. We approximate this at 5-min bar grain (see proxy disclaimer below).
- **Easley, López de Prado, O'Hara (2012), "Flow Toxicity and Liquidity in a
  High-Frequency World", Rev. Fin. Studies 25(5):1457–1493.** VPIN is the
  volume-bucketed imbalance `VPIN = (1/n) Σ |V_b - V_s| / V` where buy/sell
  volumes are split per bar by the Bulk Volume Classification (BVC) rule.
  High VPIN ⇒ high flow toxicity ⇒ informed trading ⇒ DO NOT TRADE. We use
  VPIN as a veto, not as a signal.
- **Kyle (1985), "Continuous Auctions and Insider Trading", Econometrica
  53(6):1315–1335.** Adverse-selection framework — the price of providing
  liquidity scales with the probability the counterparty is informed. Justifies
  using VPIN as a go/no-go.
- **Stoikov (2014, 2018), Avellaneda–Stoikov market-making.** We do NOT
  market-make (wrong venue, wrong data granularity) but we borrow the
  inventory-risk discipline: one position at a time, hard stop-loss.

## Bar-level proxy disclaimer (read this before touching signals)

**CRITICAL CONSTRAINT**: the competition catalog is **5-minute OHLCV bars
only**. We have NO tick stream, NO L2 book, NO microsecond depth updates.
Classical OFI/VPIN require sub-second depth deltas; at bar grain we build
**proxies** that are demonstrably correlated but NOT identical. We publish
the proxies and their limits in `notes/proxy_definitions.md`.

### OFI bar-proxy

```
ofi_bar = sign(close - open) * volume * |close - open| / max(range, tick_size)
```

Interpretation: the sign of the close-minus-open captures the net side
pressure for the bar; the `|close-open|/range` ratio distinguishes a clean
directional bar (ratio → 1) from a choppy one (ratio → 0). Tick-level OFI
from Cont et al. would count individual depth deltas; we approximate by
weighting bar volume by directional conviction. **Rolling sum over k=4 bars
gives the "persistent OFI" feature** we gate on.

### VPIN bar-proxy (volume-bucketed BVC)

We skip tick-level BVC and use the **bar-clock BVC** variant from Easley
et al. §5: `buy_vol_i = V_i * Φ((c_i - o_i)/σ)`, where `Φ` is standard normal
CDF and `σ` is the rolling std of bar returns. Imbalance per bar
`|2*buy_vol - V_i|` summed over a volume-bucket of size `V̄ * n` bars then
normalized. We calibrate the VPIN permit threshold at the 60th percentile
of train-window VPIN (trade only when VPIN ≤ 60th pct).

### Intellectual honesty

- Bar-level OFI is a **proxy**, not the canonical Cont-Stoikov OFI.
- Bar-level VPIN with BVC on 5-min bars is a coarse approximation; Easley
  himself uses 50-tick or 1-minute BVC in production.
- We expect: directionality of signal preserved, noise ratio higher, decay
  faster. Thresholds must be **calibrated from the train window** each
  round, not hardcoded.
- If the eval gain factor < 1.0 twice in a row the researcher-subagent is
  asked to consider whether the proxy is the root cause.

## 8-role roster

| # | Role | Time | Medium | Outputs |
|---|---|---|---|---|
| 1 | **researcher** | train | `run_claude()` subprocess, ~180s | `notes/research_log.md`, `attempts/<iter>/research.md` |
| 2 | **hypothesis-generator** | train | pure Python | proxy variants, threshold grid proposals |
| 3 | **critic** | train | pure Python | flags proxy failure modes, regime-assumption breaks |
| 4 | **risk-officer** | train | pure Python | `runtime_rules.json` — VPIN gate, max persistent OFI, risk caps |
| 5 | **memory-keeper** | train | pure Python | `notes/cross_round.md` — long-lived priors |
| 6 | **signal-engineer** | train | pure Python | OFI+VPIN series, threshold calibration via quantile |
| 7 | **regime-gater** | train | pure Python | session / realized-vol gates |
| 8 | **execution-trader** | train→trade | Python + live Strategy | entry/exit logic wiring OFI persistence + VPIN permit + gates |

### Why these 8

- **researcher** is the only LLM role and runs once per iteration (180s) to
  ingest state-of-the-art docs + other teams' notes + external microstructure
  literature. It produces a markdown research brief that the deterministic
  pipeline reads.
- **hypothesis-generator / critic / risk-officer / memory-keeper** are the
  standard four-role brain from the competition_1 pipeline precedents,
  rewritten as pure Python functions (no extra LLM calls) to save the train
  budget for signal calibration.
- **signal-engineer / regime-gater / execution-trader** are the three
  specialist roles that turn the brief + research into runnable code. They
  are the load-bearing roles; the first five orbit around them.

## Runtime contract (hybrid: LLM at train, pure Python at trade)

### Train-time (up to 600s)

```
┌─────────────────────────────────────────────────────────────────┐
│ entry.train(ctx)                                                 │
│  1. researcher-subagent  ~180s (first iter only, cached)         │
│     └─> notes/research_log.md, attempts/<iter>/research.md       │
│  2. hypothesis-generator → proxy variants list                   │
│  3. signal-engineer → compute OFI+VPIN on train bars,            │
│                       calibrate thresholds via quantile          │
│  4. regime-gater → add realized-vol + session gates              │
│  5. critic → check against known failure modes                   │
│  6. risk-officer → write runtime_rules.json                      │
│  7. memory-keeper → append thesis summary to notes/cross_round.md│
│  8. execution-trader → build StrategyConfig, return class+config │
└─────────────────────────────────────────────────────────────────┘
```

### Trade-time (15-min paper = **3 × 5-min bars**)

```
┌─────────────────────────────────────────────────────────────────┐
│ TeamStrategy.on_bar(bar_i)                                       │
│  bar 1: compute ofi_bar(bar_1); persistent_ofi NOT yet defined;   │
│         VPIN = init state; NO TRADE (OFI-first warmup)           │
│  bar 2: ofi_bar(bar_2); persistent_ofi = sum over 2 bars;         │
│         VPIN = 1 bucket; evaluate threshold                      │
│  bar 3: ofi_bar(bar_3); full 3-bar persistent_ofi; VPIN = 2 buckets;│
│         evaluate entry if all gates pass                         │
│  Live critic (pure Python) applies runtime_rules.json — NO LLM.  │
└─────────────────────────────────────────────────────────────────┘
```

### Paper-window warmup risk (explicit)

3 bars is **NOT enough** for rolling indicators with window > 3. Mitigation:

- **OFI** is per-bar — no warmup, live on bar 1.
- **persistent_ofi = rolling sum over k bars** — we set `k=2` at trade-time
  (not the train-time `k=4`) so the signal is defined by bar 2.
- **VPIN** uses **cumulative volume buckets** rather than a fixed window so
  it accumulates from bar 1; we accept a wider confidence interval on the
  first VPIN reading.
- **Realized-vol gate** uses a rolling std of returns — we pre-compute a
  train-window μ and allow the live std to start at that prior.

If no entry signal fires during the 15-minute paper, we do nothing. **No
trade** beats a forced trade on a 3-bar window. Mean paper gain of 1.0
(break-even) is explicitly acceptable; gain > 1.0 requires a strong signal.

## Memory layout (persistent vs ephemeral)

```
team_cont_stoikov_microstructure/
├── CLAUDE.md                         # this file — persona, persistent
├── entry.py                          # train() + Strategy — persistent
├── notes/
│   ├── .gitkeep
│   ├── proxy_definitions.md          # written once by researcher (iter 0 round 0)
│   ├── research_log.md               # append-only, all rounds
│   └── cross_round.md                # memory-keeper, round-by-round thesis
├── attempts/
│   └── <iter>/
│       ├── research.md               # iteration research brief
│       ├── thresholds.json           # calibrated OFI/VPIN/vol thresholds
│       └── runtime_rules.json        # copy of the rules baked into config
├── cache/
│   └── research_brief.md             # ephemeral: latest researcher output
└── incoming/                         # harness-owned, round_NN_leaderboard.md
```

- Persistent (survives rounds): `CLAUDE.md`, `entry.py`, `notes/*`,
  `attempts/*` (forensic).
- Ephemeral (overwritten each iter): `cache/research_brief.md`.
- Cached across iterations within a round: `cache/research_brief.md` is
  reused if younger than 1 hour; researcher only re-runs on round bump.

## `ctx` consumption

- `ctx.get_train_data()` — open `ParquetDataCatalog(handle.catalog_path)`;
  load bars for `handle.bar_type` between `handle.start` and `handle.end`.
  This is the ONLY window we may read for calibration.
- `ctx.get_test_data()` — single out-of-sample sanity check (optional this
  round; off by default to save time).
- `ctx.prev_gain`:
  - `None` (iter 0): fresh start, run full research + calibration.
  - `< 0.0` (prior loss): researcher is asked to explore **alternative
    proxy formulations** (tick-rule BVC vs trade-imbalance, k=3 vs k=4,
    different VPIN bucket size). Threshold quantiles tightened by +5 pct.
  - `>= 0.0` (prior win or break-even): keep strategy; only tighten risk.
- `ctx.prev_round_leaderboard` — guarded; on round 0 it is `None`. On
  later rounds the memory-keeper reads it once to log how we placed.

## Hard gotchas (load-bearing)

1. **`InstrumentId.from_str(...)` / `BarType.from_str(...)`** — never pass
   bare strings to `StrategyConfig`.
2. **`self.order_factory.market(...)` with ALL kwargs** —
   `instrument_id`, `order_side`, `quantity`, `time_in_force`. No
   `Strategy.buy`. Submit via `self.submit_order(order)`.
3. **`self.cache.instrument(self.config.instrument_id)`** inside `on_start`
   — never construct instruments by hand; precision must come from catalog.
   See skill `nautilus-trader-catalog-instrument-precision`.
4. **Logger singleton** — if our Strategy module happens to re-init logging,
   second `BacktestEngine` init panics. We never touch logging from the
   Strategy. See skill `nautilus-trader-logger-singleton`.
5. **Paper window 3 bars** — indicators MUST be designed OFI-first, VPIN-
   cumulative, no `window > 3` rolling std in the trade-time path.

## Supporting skills

- `nautilus-competition-team-author` — team-folder contract.
- `nautilus-trader-catalog-instrument-precision` — instrument must come
  from catalog.
- `nautilus-trader-logger-singleton` — `bypass_logging=True` on any engine
  we touch (we don't touch it, but documented here for completeness).
- `using-nautilus-trader` — general Strategy API discipline.

## Budget knobs (inherited from `config.yaml`)

- `agent.per_train_timeout_seconds = 600`
- `agent.max_train_iterations = 5`

We target the researcher subprocess at **180s**, leaving 420s for the
deterministic pipeline — more than enough for pandas/numpy quantile calibration
over a 73-day 5-min bar window (~21k bars).
