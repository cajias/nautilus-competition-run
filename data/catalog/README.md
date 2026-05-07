# data/catalog

This directory must hold a `ParquetDataCatalog` with bars covering all of:
- every round's `train` window
- every round's `test` window
- every round's `eval` window
- every round's `paper` window (simulated mode only)

## Seeding the catalog

Use the canonical seeding script in the sibling competition runner project:

```
~/Projects/workspace/nautilus-competition/examples/demo_competition/scripts/seed_catalog.py
```

That script demonstrates the catalog write pattern this harness expects:
`ParquetDataCatalog.from_uri(<path>)` followed by `catalog.write_data([...bars])`.

## Hard constraints

- Bar precision MUST match the instrument's `size_precision` (see skill
  `nautilus-trader-catalog-instrument-precision`). Mismatches surface as
  `RuntimeError: invalid bar.volume.precision=...` at `BacktestEngine.run()`.
- Load the instrument FROM the catalog, not from `TestInstrumentProvider` —
  precision mismatches between bars and instrument are the most common
  failure mode for catalog-driven backtests.
