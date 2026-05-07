---
name: nautilus-trader-catalog-instrument-precision
description: |
  Fix for "RuntimeError: invalid bar.volume.precision=N did not match
  instrument.size_precision=M" or similar bar/instrument precision-mismatch
  errors at BacktestEngine.run() time. Use when: (1) bars come from a
  ParquetDataCatalog and the instrument is loaded from somewhere else
  (TestInstrumentProvider, hand-built, hard-coded), (2) eval works but paper
  fails (or vice versa) on the same data, (3) you've seeded a catalog with
  one tool and are running the engine with an instrument from another. The
  fix is to load instruments FROM the catalog so their precisions match the
  bars stored alongside them.
author: Claude Code
version: 1.0.0
date: 2026-05-07
---

# nautilus_trader catalog ↔ instrument precision mismatch

## Problem

`nautilus_trader.persistence.catalog.ParquetDataCatalog` stores bars **and
instruments** together. A `Bar`'s `volume` is a `Quantity` with a precision
field, and the instrument has a `size_precision` field. The engine's
`OrderMatchingEngine.process_bar` validates that the two match — and aborts
the run if they don't:

```
RuntimeError: invalid bar.volume.precision=5 did not match instrument.size_precision=6
```

This bites when you load bars from a catalog but use a *different* source
for the instrument — typically `TestInstrumentProvider.btcusdt_binance()`
(size_precision=6) over bars seeded by a script that derived its precision
from a different instrument (size_precision=5).

The two ends look identical at the symbol level (`BTCUSDT.BINANCE` in both
cases), but they're literally different objects with different precision
metadata. The engine catches this only at `run()`, not at `add_instrument`
or `add_data` — so unit tests that don't actually call `engine.run()` won't
catch it.

## Trigger conditions

Stack trace at `engine.run()` includes:

```
RuntimeError: invalid bar.volume.precision=N did not match instrument.size_precision=M
  in nautilus_trader.backtest.engine.OrderMatchingEngine.process_bar:4645
```

Common N/M pairs we've seen:
- bars=5, instrument=6 (TestInstrumentProvider's BTCUSDT vs catalog-seeded BTCUSDT)

The error is **only at run-time**, not at engine setup. Tests that monkeypatch
`BacktestEngine.run` won't catch it.

## Solution

**Always load instruments from the same source as the bars.** If bars come
from a catalog, load instruments from that same catalog:

```python
from nautilus_trader.persistence.catalog import ParquetDataCatalog

catalog = ParquetDataCatalog(str(catalog_path))
bars = catalog.bars(
    bar_types=[bar_type_str],
    start=window_start,
    end=window_end,
)

# Load instruments FROM the catalog. Their precision matches the bars.
instruments = list(catalog.instruments())
if not instruments:
    raise RuntimeError(f"No instruments in catalog: {catalog_path}")
for instrument in instruments:
    engine.add_instrument(instrument)

engine.add_data(bars)
```

**Do not** mix sources:

```python
# WRONG — bars from catalog, instrument from TestInstrumentProvider
from nautilus_trader.test_kit.providers import TestInstrumentProvider
engine.add_instrument(TestInstrumentProvider.btcusdt_binance())  # precision likely differs
engine.add_data(catalog.bars(...))   # precision encoded by the seed script
```

If your test/demo path needs to seed a catalog from scratch, derive
**every** precision from the same instrument:

```python
# In your seed script:
instrument = _build_my_instrument()    # one canonical instrument
catalog.write_data([instrument])       # write it BEFORE bars

price_prec = instrument.price_precision
size_prec  = instrument.size_precision  # use these for every Bar/Quantity below

bar = Bar(
    bar_type=bar_type,
    open=Price(..., precision=price_prec),
    high=Price(..., precision=price_prec),
    low=Price(..., precision=price_prec),
    close=Price(..., precision=price_prec),
    volume=Quantity(..., precision=size_prec),  # MUST match instrument.size_precision
    ...
)
catalog.write_data([bar, ...])
```

## Verification

1. Read instruments back from the catalog and confirm:

```python
catalog = ParquetDataCatalog(str(catalog_path))
for inst in catalog.instruments():
    print(f"{inst.id}: size_precision={inst.size_precision}, price_precision={inst.price_precision}")
```

2. Read one bar and confirm:

```python
bars = catalog.bars(bar_types=[bar_type_str])
b = bars[0]
print(f"volume.precision={b.volume.precision}")
# Must equal the instrument's size_precision above.
```

3. Run a tiny `engine.run()` end-to-end. If it completes without
   `RuntimeError`, the precisions match.

## Notes

- **Quantity** and **Price** carry their precision in their type system —
  it's not just a display concern. The engine's order-matching code uses it
  to reject inconsistent input.
- `TestInstrumentProvider` returns instruments with **fixed, hardcoded**
  precisions matched to nautilus_trader's own test fixtures. They're great
  for tests that ALSO use nautilus_trader's test bar fixtures, but they're
  the wrong choice when bars come from a user-seeded catalog.
- Different exchanges (Binance vs Coinbase vs Kraken) have different
  conventions for `size_precision` of "the same" symbol. Don't assume.
- This bug **does not** show up in unit tests that monkeypatch `run()` or
  use canned `EvalResult`/`PaperResult` fixtures. Only the e2e or full-run
  path catches it. Add an e2e gate that exercises `engine.run()` against
  real seeded data.

## Example — both eval and paper phases load from catalog

```python
# nautilus_competition/eval_phase.py and paper_phase.py — same pattern
def _build_engine(...):
    catalog = ParquetDataCatalog(str(catalog_path))
    bars = catalog.bars(bar_types=[bar_type], start=..., end=...)

    engine = BacktestEngine(config=...)
    engine.add_venue(venue=Venue("BINANCE"), oms_type=..., account_type=...,
                     starting_balances=[Money.from_str("1000 USDT")])

    # Load instruments from catalog — same source as bars; precisions agree.
    for instrument in catalog.instruments():
        engine.add_instrument(instrument)

    engine.add_data(bars)
    return engine
```

## References

- `nautilus_trader.model.objects.Quantity.precision` — type carries
  precision; the engine validates compatibility.
- `OrderMatchingEngine.process_bar` (`backtest/engine.cpython-*.so:4645`):
  the validation site that raises the `RuntimeError`.
- `ParquetDataCatalog`: stores instruments alongside bars under the same
  root, retrievable via `catalog.instruments()` and `catalog.bars(...)`.
- Related: `TestInstrumentProvider` is a good source for `nautilus_trader`'s
  own test data, NOT for user-seeded catalogs.
