"""Seed competition_3 data catalog with top-10 USDT spot pairs.

Fetches 5-MIN bars from Binance public data-api (data-api.binance.vision —
the same endpoint used by competition_2's seeder; it carries complete
historical spot klines without API key) for the window
2026-03-25..2026-05-30 (padded around the competition windows defined in
config.yaml) and writes them to ``competition_3/data/catalog/`` as a
ParquetDataCatalog.

Per-instrument precision is looked up from the main api.binance.com/api/v3/exchangeInfo
endpoint using ``Decimal.normalize()`` to strip trailing zeros before
computing the decimal exponent. This matches the pattern in competition_1/2
and avoids the ``bar.open.precision=N did not match instrument.price_precision=M``
error at BacktestEngine.run() time (see skill
``nautilus-trader-catalog-instrument-precision``).

Note on MATICUSDT / POLUSDT: Binance renamed MATIC to POL in 2024. The
MATICUSDT trading pair has been delisted from Binance's klines endpoint (no
historical klines available for the 2026 window); POLUSDT is the active
successor and IS available with full kline history. We seed POLUSDT here.
Teams that reference MATICUSDT should use POLUSDT instead.

Run from competition_3 root or workspace root:
    uv run python competition_3/scripts/seed_top10_catalog.py
"""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from nautilus_trader.model.currencies import (
    ADA,
    AVAX,
    BNB,
    BTC,
    DOGE,
    ETH,
    LINK,
    SOL,
    USDT,
    XRP,
)
from nautilus_trader.model.currencies import Currency
from nautilus_trader.model.data import Bar, BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, CurrencyType, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CurrencyPair
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE = Path(__file__).resolve().parents[1]
CATALOG_DIR = WORKSPACE / "data" / "catalog"

# Padded 30-day window covering all competition windows in config.yaml
# (earliest train start = 2026-04-01; latest eval end = 2026-06-03)
START_UTC = datetime(2026, 3, 25, 0, 0, tzinfo=timezone.utc)
END_UTC = datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc)

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    # MATICUSDT was delisted from Binance klines in 2024 when MATIC was renamed to POL.
    # POLUSDT is the active successor with full historical klines for 2026.
    "POLUSDT",
]

INTERVAL = "5m"
PAGE_LIMIT = 1000
THROTTLE_SECONDS = 0.2   # gentle pause between page fetches

BINANCE_KLINES_URL = "https://data-api.binance.vision/api/v3/klines"
BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"

# POL (formerly MATIC) is not in nautilus_trader's built-in currency map; register it here.
# (Avoids ImportError; the Currency object is used only for CurrencyPair.)
_POL = Currency(
    code="POL",
    precision=8,
    iso4217=0,
    name="POL (Polygon, formerly MATIC)",
    currency_type=CurrencyType.CRYPTO,
)

# Map symbol -> (base_currency, quote_currency) using built-in NautilusTrader types
_CURRENCY_MAP: dict[str, tuple[Currency, Currency]] = {
    "BTCUSDT":  (BTC,   USDT),
    "ETHUSDT":  (ETH,   USDT),
    "SOLUSDT":  (SOL,   USDT),
    "BNBUSDT":  (BNB,   USDT),
    "XRPUSDT":  (XRP,   USDT),
    "ADAUSDT":  (ADA,   USDT),
    "DOGEUSDT": (DOGE,  USDT),
    "AVAXUSDT": (AVAX,  USDT),
    "LINKUSDT": (LINK,  USDT),
    "POLUSDT":  (_POL,  USDT),
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VENUE = Venue("BINANCE")


def _fetch_exchange_info() -> dict[str, dict]:
    """Return exchangeInfo keyed by symbol (from main api.binance.com)."""
    req = urllib.request.Request(BINANCE_EXCHANGE_INFO_URL)
    with urllib.request.urlopen(req, timeout=30) as resp:
        info = json.loads(resp.read().decode())
    return {s["symbol"]: s for s in info["symbols"]}


def _precision_from_filter(sym_info: dict, filter_type: str) -> int:
    """Extract decimal precision from a Binance filter step/tick value.

    Uses ``Decimal.normalize()`` before taking the exponent so that a value
    like ``'0.01000000'`` yields precision 2 (not 8).
    """
    key = "tickSize" if filter_type == "PRICE_FILTER" else "stepSize"
    for f in sym_info["filters"]:
        if f["filterType"] == filter_type:
            raw = f.get(key, "1")
            d = Decimal(raw).normalize()
            exp = d.as_tuple().exponent
            # exp is negative for fractional tick; clamp to 0 for whole-number steps (e.g., DOGE qty)
            return max(0, -int(exp))
    return 8  # safe fallback


def _fetch_klines_paginated(sym: str, start_ms: int, end_ms: int) -> list[list]:
    """Paginate Binance klines from start_ms up to (but not including) end_ms."""
    all_klines: list[list] = []
    cursor = start_ms
    page = 0

    while cursor < end_ms:
        page += 1
        params = (
            f"?symbol={sym}"
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
        # Advance cursor past last open kline by one bar width (5 min)
        cursor = last_open_ms + 5 * 60 * 1000
        time.sleep(THROTTLE_SECONDS)

    return all_klines


def _build_instrument(sym: str, sym_info: dict, p_prec: int, q_prec: int) -> CurrencyPair:
    """Build a CurrencyPair instrument with precision matching the klines."""
    base_currency, quote_currency = _CURRENCY_MAP[sym]
    instrument_id = InstrumentId(Symbol(sym), VENUE)
    price_increment = Price.from_str(f"{10 ** -p_prec:.{p_prec}f}")
    # q_prec=0 means whole units (e.g., DOGE volume) — use "1"
    size_str = f"{10 ** -q_prec:.{q_prec}f}" if q_prec > 0 else "1"
    size_increment = Quantity.from_str(size_str)
    # min_quantity from LOT_SIZE filter
    min_qty_str: str | None = None
    for f in sym_info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            raw_min = f.get("minQty", "0")
            # Format to q_prec decimal places
            min_qty_str = f"{float(raw_min):.{q_prec}f}"
            break
    min_quantity = Quantity.from_str(min_qty_str) if min_qty_str else None

    return CurrencyPair(
        instrument_id=instrument_id,
        raw_symbol=Symbol(sym),
        base_currency=base_currency,
        quote_currency=quote_currency,
        price_precision=p_prec,
        size_precision=q_prec,
        price_increment=price_increment,
        size_increment=size_increment,
        lot_size=None,
        max_quantity=None,
        min_quantity=min_quantity,
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


def _build_bars(instrument: CurrencyPair, klines: list[list]) -> list[Bar]:
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
    pp = instrument.price_precision
    sp = instrument.size_precision
    bars: list[Bar] = []
    for k in klines:
        # Binance kline: [open_ms, open, high, low, close, volume, close_ms, ...]
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
    return bars


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(CATALOG_DIR))

    print(f"Catalog dir : {CATALOG_DIR}")
    print(f"Window      : {START_UTC.isoformat()} .. {END_UTC.isoformat()}")
    print(f"Symbols     : {SYMBOLS}")
    print()

    print("Fetching exchangeInfo from api.binance.com ...")
    exchange_info = _fetch_exchange_info()

    start_ms = int(START_UTC.timestamp() * 1000)
    end_ms = int(END_UTC.timestamp() * 1000)

    for sym in SYMBOLS:
        sym_info = exchange_info.get(sym)
        if sym_info is None:
            print(f"[skip] {sym}: not found in exchangeInfo")
            continue

        p_prec = _precision_from_filter(sym_info, "PRICE_FILTER")
        q_prec = _precision_from_filter(sym_info, "LOT_SIZE")

        try:
            instrument = _build_instrument(sym, sym_info, p_prec, q_prec)
        except Exception as exc:
            print(f"[skip] {sym}: instrument build failed — {exc}")
            continue

        print(f"Fetching {sym} klines (p_prec={p_prec} q_prec={q_prec}) ...")
        try:
            klines = _fetch_klines_paginated(sym, start_ms, end_ms)
        except Exception as exc:
            print(f"[skip] {sym}: klines fetch failed — {exc}")
            continue

        if not klines:
            print(f"[skip] {sym}: no klines returned")
            continue

        bars = _build_bars(instrument, klines)
        if not bars:
            print(f"[skip] {sym}: produced 0 bars")
            continue

        catalog.write_data([instrument])
        catalog.write_data(bars)

        first_dt = datetime.fromtimestamp(bars[0].ts_event / 1e9, tz=timezone.utc).isoformat()
        last_dt = datetime.fromtimestamp(bars[-1].ts_event / 1e9, tz=timezone.utc).isoformat()
        print(f"[ok]  {sym}: {len(bars)} bars  (p_prec={p_prec} q_prec={q_prec})  {first_dt} .. {last_dt}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
