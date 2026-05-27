"""Seed the competition_2 catalog with real Binance BTCUSDT 5-minute klines.

Fetches a 253-day window via Binance's public ``/api/v3/klines`` endpoint
(no API key needed), builds a NautilusTrader BarType matching
``BTCUSDT.BINANCE-5-MINUTE-LAST-EXTERNAL``, and persists ~72,864 bars + the
``BTCUSDT.BINANCE`` ``CurrencyPair`` instrument into
``<working-dir>/data/catalog/`` as a ParquetDataCatalog.

Window: 2025-09-01 00:00 UTC .. 2026-05-12 00:00 UTC (253 days, spans
train+test+eval+paper per config.yaml with extended history for window
optimization). ~72,864 5-minute bars.

Pattern derived from
``~/Projects/workspace/nautilus-trading/tests/fixtures/crypto/build_catalog.py``
(switched HOUR -> 5-MINUTE; added pagination; instrument precision matched
to bars per skill ``nautilus-trader-catalog-instrument-precision``).

Run from the workspace root:
    uv run python scripts/seed_real_catalog.py
"""

from __future__ import annotations

import json
import shutil
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from nautilus_trader.model.currencies import BTC, USDT
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog


WORKSPACE = Path(__file__).resolve().parents[1]
CATALOG_DIR = WORKSPACE / "data" / "catalog"

SYMBOL = "BTCUSDT"
INTERVAL = "5m"  # Binance API string
START_UTC = datetime(2025, 9, 1, 0, 0, tzinfo=timezone.utc)
END_UTC = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)  # exclusive on the API; 253-day window

BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
PAGE_LIMIT = 1000          # Binance max per request
THROTTLE_SECONDS = 0.12    # gentle pause between pages
EXPECTED_BARS = (END_UTC - START_UTC).days * 24 * 12  # 253 days × 288 5-min bars/day = 72,864


def fetch_klines_paginated() -> list[list]:
    """Fetch all klines for the window, paginating ``startTime`` forward."""
    start_ms = int(START_UTC.timestamp() * 1000)
    end_ms = int(END_UTC.timestamp() * 1000)
    all_klines: list[list] = []
    cursor = start_ms
    page = 0

    while cursor < end_ms:
        page += 1
        params = (
            f"?symbol={SYMBOL}"
            f"&interval={INTERVAL}"
            f"&startTime={cursor}"
            f"&endTime={end_ms}"
            f"&limit={PAGE_LIMIT}"
        )
        req = urllib.request.Request(BINANCE_KLINES_URL + params)
        with urllib.request.urlopen(req, timeout=30) as resp:
            chunk = json.loads(resp.read().decode())
        if not chunk:
            break
        all_klines.extend(chunk)
        last_open_ms = chunk[-1][0]
        # Step cursor past the last open we received; klines are 5min so add 5*60*1000ms.
        cursor = last_open_ms + 5 * 60 * 1000
        print(f"  page {page}: {len(chunk)} klines (cumulative {len(all_klines)})")
        time.sleep(THROTTLE_SECONDS)

    if len(all_klines) < EXPECTED_BARS - 10:
        raise RuntimeError(
            f"expected ~{EXPECTED_BARS} klines, got {len(all_klines)} — "
            f"window may be partial or API throttled"
        )
    return all_klines


def build_instrument() -> CurrencyPair:
    """BTCUSDT.BINANCE CurrencyPair with precision matching kline bars.

    Binance kline price strings like '67891.23' have 2-decimal precision;
    quantity strings like '0.012345' have 6-decimal precision. These match
    Binance's actual exchangeInfo for BTCUSDT spot. Aligning size_precision=6
    with the kline volume strings avoids the
    `nautilus-trader-catalog-instrument-precision` mismatch at
    BacktestEngine.run() time.
    """
    instrument_id = InstrumentId(Symbol(SYMBOL), Venue("BINANCE"))
    return CurrencyPair(
        instrument_id=instrument_id,
        raw_symbol=Symbol(SYMBOL),
        base_currency=BTC,
        quote_currency=USDT,
        price_precision=2,
        size_precision=6,
        price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_str("0.000001"),
        lot_size=None,
        max_quantity=None,
        min_quantity=Quantity.from_str("0.00001"),
        max_notional=None,
        min_notional=None,
        max_price=None,
        min_price=None,
        margin_init=Decimal("0"),
        margin_maint=Decimal("0"),
        maker_fee=Decimal("0.001"),
        taker_fee=Decimal("0.001"),
        ts_event=0,
        ts_init=0,
    )


def build_bars(instrument: CurrencyPair, klines: list[list]) -> list[Bar]:
    """Convert Binance klines to NautilusTrader Bars (5-MINUTE-LAST-EXTERNAL)."""
    bar_spec = BarSpecification(
        step=5,
        aggregation=BarAggregation.MINUTE,
        price_type=PriceType.LAST,
    )
    bar_type = BarType(
        instrument_id=instrument.id,
        bar_spec=bar_spec,
        aggregation_source=AggregationSource.EXTERNAL,
    )
    # Match instrument precision exactly — Binance returns kline strings with
    # 8-decimal padding ("67891.23000000"); leaving them as-is gives a Price
    # with precision=8, which trips BacktestEngine's
    # `bar.open.precision=8 did not match instrument.price_precision=2` check.
    # See skill `nautilus-trader-catalog-instrument-precision`.
    pp = instrument.price_precision   # 2
    sp = instrument.size_precision    # 6
    bars: list[Bar] = []
    for k in klines:
        # Binance kline format: [open_ms, open, high, low, close, volume, close_ms, ...]
        _open_ms, o, h, low, c, v, close_ms = k[0], k[1], k[2], k[3], k[4], k[5], k[6]
        ts_event_ns = int(close_ms) * 1_000_000
        bars.append(
            Bar(
                bar_type=bar_type,
                open=Price.from_str(f"{float(o):.{pp}f}"),
                high=Price.from_str(f"{float(h):.{pp}f}"),
                low=Price.from_str(f"{float(low):.{pp}f}"),
                close=Price.from_str(f"{float(c):.{pp}f}"),
                volume=Quantity.from_str(f"{float(v):.{sp}f}"),
                ts_event=ts_event_ns,
                ts_init=ts_event_ns,
            )
        )
    if not bars:
        raise RuntimeError("produced 0 bars from Binance response")
    return bars


def main() -> None:
    print(f"Workspace: {WORKSPACE}")
    print(f"Catalog dir: {CATALOG_DIR}")
    print(f"Window: {START_UTC.isoformat()} .. {END_UTC.isoformat()}")
    print(f"Expected bars: {EXPECTED_BARS}")

    if CATALOG_DIR.exists() and any(CATALOG_DIR.iterdir()):
        # Preserve .gitkeep + README.md but wipe existing parquet data.
        for entry in CATALOG_DIR.iterdir():
            if entry.name in {".gitkeep", "README.md"}:
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching {SYMBOL} {INTERVAL} klines from Binance public API...")
    klines = fetch_klines_paginated()
    print(f"Fetched {len(klines)} klines total")

    instrument = build_instrument()
    bars = build_bars(instrument, klines)

    catalog = ParquetDataCatalog(str(CATALOG_DIR))
    catalog.write_data([instrument])
    catalog.write_data(bars)

    print(f"\nCatalog seeded:")
    print(f"  Instrument: {instrument.id}")
    print(f"  Bars: {len(bars)}")
    first_ts = bars[0].ts_event
    last_ts = bars[-1].ts_event
    print(f"  First bar ts_event: {datetime.fromtimestamp(first_ts / 1e9, tz=timezone.utc).isoformat()}")
    print(f"  Last bar ts_event:  {datetime.fromtimestamp(last_ts / 1e9, tz=timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
