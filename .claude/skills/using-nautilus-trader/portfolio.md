# Portfolio

**Location:** `nautilus_trader.portfolio.portfolio`

**Docs:** https://nautilustrader.io/docs/latest/concepts/portfolio/

Access via `self.portfolio` in strategies/actors.

## Account

```python
venue = Venue("BINANCE")
account = self.portfolio.account(venue)
account.account_type  # CASH, MARGIN
```

## Balances

```python
balances = self.portfolio.balances(venue)
for currency, balance in balances.items():
    balance.total, balance.free, balance.locked

locked = self.portfolio.balances_locked(venue)
```

## Margins

```python
init_margins = self.portfolio.margins_init(venue)
maint_margins = self.portfolio.margins_maint(venue)
```

## Positions

```python
positions = self.portfolio.positions_open()
positions = self.portfolio.positions_open(instrument_id=instrument_id)
positions = self.portfolio.positions_closed()

# Net position (signed quantity)
net_qty = self.portfolio.net_position(instrument_id)

# Boolean checks
self.portfolio.is_net_long(instrument_id)
self.portfolio.is_net_short(instrument_id)
self.portfolio.is_flat(instrument_id)
self.portfolio.is_completely_flat()
```

## Position Details

```python
position.side           # LONG, SHORT, FLAT
position.quantity       # Absolute quantity
position.signed_qty     # Positive=long, negative=short
position.avg_px_open    # Entry price
position.realized_pnl
position.unrealized_pnl(current_price)
position.total_pnl(current_price)
position.return_pct(current_price)
```

## PnL

```python
# Per instrument
unrealized = self.portfolio.unrealized_pnl(instrument_id)
realized = self.portfolio.realized_pnl(instrument_id)

# All instruments at venue
unrealized_all = self.portfolio.unrealized_pnls(venue)
realized_all = self.portfolio.realized_pnls(venue)
```

## Exposure

```python
exposure = self.portfolio.net_exposure(instrument_id)
exposures = self.portfolio.net_exposures(venue)
```

## Position Sizing Pattern

```python
def calculate_size(self, stop_distance: float) -> Quantity:
    account = self.portfolio.account(Venue("BINANCE"))
    balance = account.balance(Currency.from_str("USDT"))
    risk_amount = float(balance.free) * 0.01  # 1% risk
    size = risk_amount / stop_distance
    return Quantity.from_str(str(round(size, 8)))
```
