# Weight Change Log

## Version 1 — Iteration 0 / Round 0

**Change:** bull/bear 0.5/0.5 → 0.7/0.3 (factual/subjective); chop 0.5/0.5 → 0.8/0.2.

**Rationale:**
- Subjective stream self-reported confidence 0.20 / 1.0 — live news feeds were sandboxed; thesis is built on stale structural priors (knowledge cutoff Aug 2025, current date May 2026, ~9-month gap).
- No live social sentiment, no live macro calendar access. Feed failure makes the subjective stream effectively a no-op directional signal this iteration.
- FS-ReasoningAgent (arXiv 2410.12464) bull→subjective default assumes high-quality narrative input. That precondition fails here; inverting toward factual is correct.
- Factual stream: combined confidence 0.50 (cold start), but built on concrete numerical rules (EMA20/50, RSI14, ATR14, BB20) with well-documented 5-min BTC applicability.
- Chop weight pushed furthest toward factual (0.8) because in chop the subjective "flat-with-event-risk" lean is identical to what the factual mean-reversion branch independently signals — no marginal information from subjective.

**Sizing decision:** Adopted factual stream's risk-based sizing (2% equity / 2×ATR stop) rather than the instruction's ~5% notional per signal. The factual author's formula is more conservative and appropriate for cold-start iter 0. This is logged here as the explicit resolution of the sizing ambiguity.

**Next review:** After first eval results are available (iter 1+), merger should re-examine if subjective feed access is restored. If subjective stream achieves confidence ≥ 0.5 with live sourcing, restore bull weights toward 0.5/0.5 per FS-ReasoningAgent default.
