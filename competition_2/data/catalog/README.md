# data/catalog

This is where `compete run` reads bars from — a NautilusTrader
`ParquetDataCatalog` containing the instrument(s) referenced in
`../config.yaml` (`instrument.symbol` / `instrument.bar_type`).

## Seeding

Use the demo seeder as a starting reference:

`examples/demo_competition/scripts/seed_catalog.py`

Adapt it to fetch / generate the bar series your `windows:` cover, and
write them into this folder via `ParquetDataCatalog(<path>).write_data(...)`.
The catalog must hold both the instrument metadata and the bars before
`compete run` will succeed.

## Layout

After seeding you should see something like:

```
data/catalog/
  data/
    bar/...
    instrument/...
```
